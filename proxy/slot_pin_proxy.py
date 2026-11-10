#!/usr/bin/env python3
"""
slot-pin-proxy: sits between an OpenAI-compatible client (openclaw) and
llama-server, and forces every completion request onto one fixed
llama-server slot via the native `id_slot` param.

Why: llama-server's own prompt cache (`--cache-prompt`, on by default)
reuses the common prefix between a request and whatever a slot already
holds, but only if the request lands on the *same* slot as last time.
The OpenAI-compatible endpoint has no client-facing way to request a
specific slot, and the automatic prompt-similarity picker can bounce a
single ongoing conversation across different slots (observed directly:
task 273/287 on slot 2, 814/829 on slot 1, 1395/1408 on slot 0 -- same
logical openclaw session, three different slots), throwing away cache
that would otherwise apply. Pinning to one slot makes that reuse
guaranteed instead of lucky.

Today openclaw only has one real conversation identity (the "main"
agent; heartbeats run inside that same session -- see openclaw.json),
so a single preferred slot for everything is the correct-sized fix. If
a second identity shows up later (e.g. a separate agent), extend
`pick_slot()` to map identities to distinct slot numbers instead of
rewriting this.

2026-09-06 update: pinning was originally unconditional (always
id_slot=PINNED_SLOT), which is fine for one request at a time but
actively harmful when two calls for the same session overlap (e.g. a
heartbeat firing while a manual/CLI turn is still mid-flight on slow
hardware): the second request grabbing the same busy slot forces
llama-server to cancel whatever the first one was doing. Now `pick_slot`
checks `/slots` first and only pins to PINNED_SLOT if it's actually
idle; otherwise it hands the request to any other idle slot so two
overlapping calls don't fight over one. Falls back to PINNED_SLOT
(old behavior) only if every slot is busy or the `/slots` check itself
fails -- no worse than before in that case, just no better.

2026-09-06 update #2: that fix stopped collisions, but surfaced a
different cost -- two *different* sessions (e.g. the heartbeat's session
and an interactive one) landing on two different idle slots and actually
running concurrently. llama-server's RPC-sharded backend doesn't give
each concurrent job its own throughput; they visibly split it (watched
one job's speed drop from ~94 tok/s to ~62 tok/s as a second and third
started). A FIFO_LOCK below serializes completion requests through the
proxy -- only one is ever in flight to llama-server at a time, others
wait in strict arrival order -- so nothing loses throughput to a
concurrent neighbor. This does NOT reintroduce the cache-thrashing
problem `pick_slot` above was built to avoid: cache lives on the slot,
not on request timing, and slots stay assigned to whichever session last
used them regardless of serialization -- see docs/LOG.md.

2026-09-06 update #3: "whichever session last used them" turned out to
be the weak point -- there was only ever one shared PINNED_SLOT for
*every* session, so any two distinct sessions (e.g. the heartbeat's
`agent:main:main` and an interactive `scratch-test`) still evicted each
other's cache whenever they happened to both want slot 0, exactly the
thrashing the pinning design was meant to prevent. Confirmed live: a
`main` turn came in right after `scratch-test` retries had evicted its
cache, forcing a full ~40K-token cold reprocess that then blew through
the 900s timeout waiting in the FIFO queue behind other traffic. Fixed
by making the preferred slot per-session instead of global --
`SessionSlotAssigner` derives a stable fingerprint per session (hash of
its first non-system message, fixed for that session's life, no
cooperation needed from openclaw) and assigns it its own slot,
round-robin, on first sight. Distinct sessions now get distinct slots and
can't evict each other at all, up to N_SLOTS concurrently-active sessions
-- beyond that hard ceiling something has to give, which is a real
resource limit (each slot reserves its own chunk of context memory), not
a bug to chase further. See docs/LOG.md.

2026-09-06 update #4: none of the above stopped a request from running
to completion server-side after its client had already given up
(openclaw's own timeout, or a person closing the TUI) -- confirmed
directly tonight, a request kept processing for minutes after openclaw
had already logged it as a terminal error, still holding both an
llama-server slot and the FIFO gate the whole time, delaying every real
request queued behind it. `ProxyHandler._client_gone()` now polls the
client connection (non-blocking peek, no data consumed) while waiting on
a slow upstream and while streaming; the moment the client's gone, the
proxy shuts down its own connection to llama-server, which triggers
llama-server's own existing cancel-on-disconnect handling (the same
"stop: cancel task" path already seen tonight whenever the proxy itself
restarted mid-request) -- so an abandoned request now actually frees the
slot and the queue instead of grinding on for nobody.

2026-10-30 update: disk KV slot files (one ~1 GB .bin per session
fingerprint, see "Disk-persisted slot cache" below) were never cleaned
up -- node-a accumulated ~154 GB of them. slot_cleanup.py now removes (or
archives) files not written for N days (default 30), once at startup and
every few hours (default 6) on a background thread, holding the FIFO gate
while it removes so it can't race a save/restore, and forgets those
sessions' slot assignments. Configure with --slot-cleanup /
--slot-max-age-days / --slot-archive-dir / --slot-cleanup-interval-hours
or the matching CARAVAN_SLOT_* env vars; see slot_cleanup.py.
v2 (2026-10-31): the same pass also holds the Mini to a cap on saved
chats, llama.cpp + MLX together (--slot-max-count 200 / --slot-max-gb 50,
least recently used first). Sessions in a slot, with unsaved turns, or
with a turn in the last --slot-protect-minutes (30) are never evicted
(_active_sessions).

2026-10-30 performance pass (see docs/LOG.md for the full list):
  * new sessions get the least-recently-used slot, not round-robin
    (SessionSlotAssigner);
  * disk saves are skipped when a slot hasn't grown, can be thinned to
    every N turns, or moved off the response path entirely by an
    optional idle saver (save_slot / SaveTracker / start_idle_saver);
  * no disk restore over a slot llama-server already holds warm;
  * streaming uses read1() so SSE tokens aren't held back in 4 KB
    batches, and responses without Content-Length are re-chunked
    instead of being sent unframed on a keep-alive connection;
  * prompt-style calls are fingerprinted by a stable prompt prefix
    (short prompts are unpinned one-shots, never saved to disk);
  * the per-request /slots idle check and the TEMP prompt-logging debug
    block are gone.
Settings: --n-slots, --slot-save-every, --slot-idle-save-seconds,
--prompt-fingerprint-chars (or CARAVAN_N_SLOTS, CARAVAN_SLOT_SAVE_EVERY,
CARAVAN_SLOT_IDLE_SAVE_SECONDS, CARAVAN_PROMPT_FINGERPRINT_CHARS, or
~/.caravan/config.json) -- see main().

2026-10-30 MLX step (a): completions are now routed by their `model`
field (backends.py). GGUF models go to llama-server exactly as before;
MLX models (an "mlx-community/" id prefix, or an explicit "mlx.models"
entry in the config) go to an mlx_lm.server on this Mini (default
127.0.0.1:8092). MLX requests still go through the FIFO and get a
session fingerprint, but there's no id_slot and no disk save/restore yet
-- logged as "cache=mlx-noop". Settings: --mlx-host / --mlx-port /
--mlx-prefixes / --no-mlx, CARAVAN_MLX_* env vars, or the "mlx" object
in ~/.caravan/config.json.

2026-10-31 MLX step (b): the MLX upstream is the Caravan MLX worker
(agent/mlx_worker.py). The proxy sends the session fingerprint as
X-Caravan-Session, asks the worker to restore a session's cache from disk
before its first turn, and to save it after replies (every
save_every_n_turns); slot_cleanup ages out the .safetensors files too.
"""
import argparse
import contextlib
import hashlib
import http.client
import json
import os
import re
import select
import socket
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import NamedTuple

try:
    import slot_cleanup  # run as a script: proxy/ is sys.path[0]
    import backends
except ImportError:  # imported as proxy.slot_pin_proxy from the repo root
    from proxy import slot_cleanup
    from proxy import backends

UPSTREAM_HOST = os.environ.get("CARAVAN_UPSTREAM_HOST", "127.0.0.1")
UPSTREAM_PORT = int(os.environ.get("CARAVAN_UPSTREAM_PORT", "8080"))
LISTEN_PORT = int(os.environ.get("CARAVAN_PROXY_PORT", "8090"))

# Paths that take a JSON completion-shaped body and accept `id_slot`.
COMPLETION_PATHS = {"/v1/chat/completions", "/v1/completions", "/completion"}


# --- Settings (2026-10-30) -------------------------------------------------
# Precedence everywhere: CLI flag > env var > ~/.caravan/config.json
# ($CARAVAN_CONFIG) > default. n_slots lives under "llama_server" in the
# config file because llama-server's --parallel must match it; the rest
# under "proxy".
class ProxySettings(NamedTuple):
    n_slots: int                  # must equal llama-server --parallel
    save_every_n_turns: int       # inline disk save every N completed turns per session
    idle_save_seconds: float      # >0: save after a session's slot is idle this long, instead of inline
    prompt_fingerprint_chars: int  # prompt-style calls: prefix length that identifies a session
    mlx_save_min_turns: int = 1   # MLX: no disk save until a session has this many turns (2 = skip one-shots)


PROXY_SETTING_SOURCES = {
    # key: (env var, config section, config key, default, cast, minimum)
    "n_slots": ("CARAVAN_N_SLOTS", "llama_server", "n_slots", 4, int, 1),
    "save_every_n_turns": ("CARAVAN_SLOT_SAVE_EVERY", "proxy", "slot_save_every", 1, int, 1),
    "idle_save_seconds": ("CARAVAN_SLOT_IDLE_SAVE_SECONDS", "proxy", "slot_idle_save_seconds", 0.0, float, 0),
    "prompt_fingerprint_chars": ("CARAVAN_PROMPT_FINGERPRINT_CHARS", "proxy",
                                 "prompt_fingerprint_chars", 2048, int, 64),
    # v2.1: a one-message request (turn 1) is often a one-shot that never
    # comes back; 2 defers the first MLX save to the session's 2nd turn
    # (which then saves everything). Trade-off: a restart right after a
    # session's first turn re-reads that prompt.
    "mlx_save_min_turns": ("CARAVAN_MLX_SAVE_MIN_TURNS", "proxy", "mlx_save_min_turns", 1, int, 1),
}


def _config_file_path() -> Path:
    return Path(os.environ.get(
        "CARAVAN_CONFIG", str(Path.home() / ".caravan" / "config.json")
    )).expanduser()


def _load_config_file(path: "Path | None" = None) -> dict:
    path = path or _config_file_path()
    try:
        data = json.loads(Path(path).read_text())
    except FileNotFoundError:
        return {}
    except (OSError, ValueError) as e:
        sys.stderr.write(f"[slot-pin-proxy] ignoring unreadable config {path}: {e}\n")
        return {}
    return data if isinstance(data, dict) else {}


def resolve_proxy_settings(overrides: "dict | None" = None,
                           config_path: "Path | None" = None) -> ProxySettings:
    overrides = {k: v for k, v in (overrides or {}).items() if v is not None}
    cfg = _load_config_file(config_path)
    out = {}
    for key, (env, section, ckey, default, cast, minimum) in PROXY_SETTING_SOURCES.items():
        sec = cfg.get(section)
        file_val = sec.get(ckey) if isinstance(sec, dict) else None
        if key in overrides:
            raw = overrides[key]
        elif os.environ.get(env, "").strip():
            raw = os.environ[env].strip()
        elif file_val not in (None, ""):
            raw = file_val
        else:
            raw = default
        try:
            val = cast(raw)
        except (TypeError, ValueError):
            raise ValueError(f"{key} must be a number, got {raw!r}")
        if val < minimum:
            raise ValueError(f"{key} must be >= {minimum}, got {val}")
        out[key] = val
    return ProxySettings(**out)


try:
    SETTINGS = resolve_proxy_settings()
except ValueError as _e:  # never crash-loop a KeepAlive'd proxy over a bad setting
    sys.stderr.write(f"[slot-pin-proxy] invalid setting ({_e}); using defaults\n")
    SETTINGS = ProxySettings(**{k: v[3] for k, v in PROXY_SETTING_SOURCES.items()})
N_SLOTS = SETTINGS.n_slots

try:
    MLX_SETTINGS = backends.resolve_mlx_settings(_load_config_file())
except ValueError as _e:
    sys.stderr.write(f"[slot-pin-proxy] invalid mlx setting ({_e}); MLX routing off\n")
    MLX_SETTINGS = backends.resolve_mlx_settings({}, {"enabled": False, "port": backends.DEFAULT_MLX_PORT})
# host/port read lazily so UPSTREAM_HOST/PORT stay the one source of truth.
ROUTER = backends.Router(
    backends.LlamaBackend(lambda: UPSTREAM_HOST, lambda: UPSTREAM_PORT), MLX_SETTINGS)


class MlxSessionTracker:
    """MLX has no slots: this only remembers which session fingerprints
    were seen this run (and turn counts) so the log shows pinning is
    still per-session, and so step (b) has the hook it needs."""

    def __init__(self, clock=time.monotonic):
        self._lock = threading.Lock()
        self._clock = clock
        self.turns: dict = {}
        self.last_turn: dict = {}

    def seen(self, fingerprint) -> bool:
        with self._lock:
            return fingerprint in self.turns

    def turn(self, fingerprint) -> int:
        with self._lock:
            self.turns[fingerprint] = self.turns.get(fingerprint, 0) + 1
            self.last_turn[fingerprint] = self._clock()
            return self.turns[fingerprint]

    def recent(self, seconds: float) -> list:
        """Sessions with an MLX turn in the last `seconds` (slot cap: active)."""
        now = self._clock()
        with self._lock:
            return [fp for fp, t in self.last_turn.items() if now - t < seconds]

    def forget(self, fingerprints) -> None:
        with self._lock:
            for fp in fingerprints:
                self.turns.pop(fp, None)
                self.last_turn.pop(fp, None)


mlx_sessions = MlxSessionTracker()


class FifoGate:
    """Strict first-in-first-out mutual exclusion.

    A plain threading.Lock doesn't guarantee waiters are woken in arrival
    order -- this does, via an explicit ticket queue: each waiter takes a
    ticket, and only the ticket at the front of the line is ever allowed
    through. See module docstring, "2026-09-06 update #2".
    """

    def __init__(self):
        self._cv = threading.Condition()
        self._queue = []
        self._next_ticket = 0

    def acquire(self) -> tuple[int, int, float]:
        """Blocks until it's this caller's turn. Returns
        (ticket, queue_depth_ahead, waited_seconds) for logging."""
        start = time.monotonic()
        with self._cv:
            ticket = self._next_ticket
            self._next_ticket += 1
            self._queue.append(ticket)
            ahead = len(self._queue) - 1
            while self._queue[0] != ticket:
                self._cv.wait()
        return ticket, ahead, time.monotonic() - start

    def status(self):
        with self._cv:
            return {"active": bool(self._queue), "waiting": max(0, len(self._queue) - 1)}

    def release(self, ticket: int) -> None:
        with self._cv:
            self._queue.remove(ticket)
            self._cv.notify_all()


completion_fifo = FifoGate()


class SessionSlotAssigner:
    """Tracks which session (fingerprint) currently occupies each
    llama-server slot, and when each slot was last used.

    A session that's still sitting in a slot gets that slot back (warm,
    llama-server's prompt cache reuses the shared prefix). A session that
    isn't in any slot -- new, or evicted since -- gets the least-recently-
    used slot (empty slots first), so the slot given up is always the
    coldest one rather than whichever came next round-robin.

    History: 2026-09-06 update #3 introduced per-session slots (assigned
    round-robin on first sight, persisted to STATE_FILE so a proxy-only
    restart doesn't forget them -- the KV cache itself is issue #4, see
    below). 2026-10-30: round-robin -> LRU (#7 in the perf review), and
    the state is now "occupant + last-used per slot" rather than an
    ever-growing fingerprint->slot map (so session_slots.json is bounded
    by N_SLOTS). The legacy {"assignments": {...}} format is still read.
    """

    def __init__(self, n_slots: int, state_file: "Path | None" = None,
                 clock=time.time):
        self._n_slots = n_slots
        self._lock = threading.RLock()
        self._occupant: list = [None] * n_slots
        self._last_used: list = [0.0] * n_slots
        self._state_file = state_file
        self._clock = clock
        self._load()

    def _load(self) -> None:
        if self._state_file is None or not self._state_file.exists():
            return
        try:
            data = json.loads(self._state_file.read_text())
            slots = data.get("slots")
            if isinstance(slots, list):
                for i, entry in enumerate(slots[: self._n_slots]):
                    if not isinstance(entry, dict):
                        continue
                    fp = entry.get("fingerprint")
                    self._occupant[i] = fp if isinstance(fp, str) else None
                    try:
                        self._last_used[i] = float(entry.get("last_used", 0.0))
                    except (TypeError, ValueError):
                        pass
            else:
                # Legacy format: fingerprint -> slot, insertion-ordered by
                # first sight, so the last fingerprint mapped to a slot is
                # the one most likely still in it.
                for fp, slot in data.get("assignments", {}).items():
                    if isinstance(slot, int) and 0 <= slot < self._n_slots:
                        self._occupant[slot] = fp
            sys.stderr.write(
                f"[slot-pin-proxy] restored slot occupancy for "
                f"{sum(1 for o in self._occupant if o)} slot(s) from {self._state_file}\n"
            )
        except (OSError, ValueError, AttributeError, json.JSONDecodeError) as e:
            # Corrupt or unreadable -- fine, just start fresh rather than
            # crash the proxy over a cache of a cache.
            sys.stderr.write(f"[slot-pin-proxy] could not restore slot assignments: {e}\n")

    def _save(self) -> None:
        if self._state_file is None:
            return
        try:
            self._state_file.parent.mkdir(parents=True, exist_ok=True)
            tmp = self._state_file.with_suffix(".tmp")
            tmp.write_text(json.dumps({
                "version": 2,
                "slots": [
                    {"fingerprint": fp, "last_used": t}
                    for fp, t in zip(self._occupant, self._last_used)
                ],
                # Kept for anything that reads the old shape (and for
                # slot_cleanup.prune_state_file).
                "assignments": {fp: i for i, fp in enumerate(self._occupant) if fp},
            }))
            tmp.replace(self._state_file)  # atomic on the same filesystem
        except OSError as e:
            sys.stderr.write(f"[slot-pin-proxy] could not persist slot assignments: {e}\n")

    def lookup(self, fingerprint: str) -> "int | None":
        with self._lock:
            for i, fp in enumerate(self._occupant):
                if fp == fingerprint:
                    return i
            return None

    def occupant(self, slot: int) -> "str | None":
        with self._lock:
            return self._occupant[slot]

    def lru_slot(self) -> int:
        """Empty slots first (lowest last-used, then lowest id), then the
        least recently used occupied slot."""
        with self._lock:
            return min(
                range(self._n_slots),
                key=lambda i: (self._occupant[i] is not None, self._last_used[i], i),
            )

    def slot_for(self, fingerprint: str) -> tuple:
        """(slot, already_there, evicted_fingerprint). Doesn't change any
        state -- call mark_used() once the request is committed to it."""
        with self._lock:
            slot = self.lookup(fingerprint)
            if slot is not None:
                return slot, True, None
            slot = self.lru_slot()
            return slot, False, self._occupant[slot]

    def mark_used(self, slot: int, fingerprint: "str | None") -> None:
        """Records that `slot` now holds `fingerprint`'s context (None for
        an ephemeral, unpinned request -- the slot's content is then
        nobody's, and it's the first to be reused)."""
        with self._lock:
            if fingerprint is not None:
                for i, fp in enumerate(self._occupant):
                    if fp == fingerprint and i != slot:
                        self._occupant[i] = None
            self._occupant[slot] = fingerprint
            self._last_used[slot] = self._clock()
            self._save()

    def occupants(self) -> list:
        """Fingerprints currently held in a llama.cpp slot."""
        with self._lock:
            return [fp for fp in self._occupant if fp]

    def forget(self, fingerprints) -> list:
        """Drops sessions whose disk cache was cleaned up (slot_cleanup):
        their slots become free for the next new session. Done here, on
        the live state, rather than by editing the JSON file -- otherwise
        the next _save() would write them straight back."""
        with self._lock:
            wanted = set(fingerprints)
            dropped = []
            for i, fp in enumerate(self._occupant):
                if fp is not None and fp in wanted:
                    self._occupant[i] = None
                    dropped.append(fp)
            if dropped:
                self._save()
            return dropped


STATE_FILE = Path(os.environ.get(
    "CARAVAN_PROXY_STATE_FILE",
    str(Path.home() / ".caravan" / "proxy" / "session_slots.json"),
))
session_slots = SessionSlotAssigner(N_SLOTS, STATE_FILE)


# openclaw injects a synthetic marker as the first non-system message on
# every single call, e.g. "[Sun 2026-09-06 10:34 CDT] (session bootstrap)"
# -- timestamped to the current minute, not the session's real history.
# Root-caused 2026-09-06: this is why the naive "hash the first
# non-system message" approach fingerprinted the same real session
# differently on every call (confirmed live -- three requests, three
# different fingerprints, three different slots). Skip it and keep
# looking for the first message that isn't this synthetic wrapper.
_BOOTSTRAP_MARKER_RE = re.compile(r"^\[.*?\]\s*\(session bootstrap\)\s*$")


def session_fingerprint(body: dict) -> "str | None":
    """Stable per-session key, or None for a request that shouldn't get a
    persistent slot or a disk save ("ephemeral").

    Chat-style (`messages`): hash of the first *real* non-system,
    non-bootstrap-marker message -- fixed for a session's lifetime (that
    message never changes once sent), distinct across sessions, with no
    cooperation needed from openclaw (no session id is present in the
    OpenAI-compatible wire format).

    Prompt-style (`prompt`, /completion and /v1/completions; 2026-10-30):
    a raw prompt grows by appending, so its first
    SETTINGS.prompt_fingerprint_chars characters stay fixed for a
    continuing conversation -- hash that prefix. Prompts no longer than
    that are treated as ephemeral one-shots: previously the whole-body
    fallback hash gave every such call its own fingerprint, its own slot
    and its own ~1 GB disk save, none of which could ever be reused.
    Batched prompts (a list of strings) are ephemeral too.

    Anything else (no usable message/prompt) is ephemeral -- same
    reasoning.

    2026-10-30: the TEMP sys-debug/fp-debug logging (system-prompt hash
    and message previews on every request) was removed -- it wrote the
    start of every prompt into the proxy log.
    """
    messages = body.get("messages")
    if isinstance(messages, list):
        for m in messages:
            if not isinstance(m, dict) or m.get("role") == "system":
                continue
            content = m.get("content", "")
            if not isinstance(content, str):
                content = json.dumps(content, sort_keys=True)
            if _BOOTSTRAP_MARKER_RE.match(content.strip()):
                continue
            return hashlib.sha256(content.encode("utf-8")).hexdigest()[:16]
        return None

    prompt = body.get("prompt")
    if isinstance(prompt, list) and prompt and all(isinstance(t, int) for t in prompt):
        text = json.dumps(prompt)  # token ids: appending keeps the prefix stable
    elif isinstance(prompt, str):
        text = prompt
    else:
        return None
    n = SETTINGS.prompt_fingerprint_chars
    if len(text) <= n:
        return None
    return hashlib.sha256(("prompt:" + text[:n]).encode("utf-8")).hexdigest()[:16]


# 2026-10-30: pick_slot()'s per-request GET /slots "is the preferred slot
# idle?" check is gone (#12 in the perf review). Every completion already
# goes through completion_fifo one at a time, so the target slot is idle
# by construction; the one exception (a just-cancelled request still
# winding down) is handled by llama-server itself, which defers a task
# aimed at a busy id_slot until that slot frees up rather than clobbering
# it. The extra round trip on every request bought nothing.


def mlx_session_fingerprint(body: dict):
    """Keep auxiliary (e.g. Hermes title) calls out of a chat's KV cache.

    The first user message alone is identical in a title request and its chat.
    Namespace by the actual template inputs, not growing conversation history.
    Never log prompt text. llama.cpp keeps its existing slot identity.
    """
    base = session_fingerprint(body)
    if base is None or not isinstance(body.get("messages"), list):
        return base
    scope = {"session": base, "model": body.get("model"),
             "system": [m for m in body["messages"] if m.get("role") in ("system", "developer")],
             "tools": body.get("tools") or [],
             "template": body.get("chat_template_kwargs") or {},
             "thinking": body.get("thinking"), "reasoning_effort": body.get("reasoning_effort")}
    return hashlib.sha256(json.dumps(scope, sort_keys=True, ensure_ascii=False,
                                     separators=(",", ":")).encode()).hexdigest()[:16]


# --- Disk-persisted slot cache (issue #4) ---------------------------------
# Requires llama-server to be started with --slot-save-path (see
# ../launchd/com.caravan.llama-server.plist). Saves a slot's actual KV
# cache to disk and restores it on first use after a restart -- unlike
# SessionSlotAssigner's persistence above (which only remembers *which*
# slot a session is in), this persists the cache *content* itself, so it
# survives an llama-server restart, not just a proxy restart. See
# docs/LOG.md and GitHub issue #4.
#
# 2026-10-30 (perf review #1 and #8):
#  * A save (up to ~1 GB, blocking, under the FIFO gate so the next
#    request waits) is skipped when the slot's token count hasn't grown
#    since the last save/restore of that session, and can be thinned to
#    every N turns (SETTINGS.save_every_n_turns, default 1 = every turn).
#  * Optional idle saver (SETTINGS.idle_save_seconds > 0, off by
#    default): no inline saves at all; a background thread saves a
#    session once its slot has been idle that long, taking the FIFO gate
#    like a request so it can't race a restore or a completion.
#  * A session with unsaved turns is always saved before its slot is
#    handed to a different session (otherwise those turns would be lost).
#  * A restore is skipped when llama-server already holds that session
#    warm in that slot (checked via GET /slots, once per session per
#    proxy run) -- e.g. after a proxy-only restart, which used to
#    overwrite a warm slot with an older disk copy.
SLOT_SAVE_DIR = Path(os.environ.get(
    "CARAVAN_SLOT_SAVE_DIR",
    str(Path.home() / ".caravan" / "llama-server" / "slots"),
))


def _slot_save_filename(fingerprint: str) -> str:
    return f"{fingerprint}.bin"


def _post_json_to_upstream(path: str, body: dict, timeout: float):
    """POST JSON straight to llama-server (not through the FIFO -- this
    runs from inside a request that already holds the gate) and return
    the parsed response, or None on any failure. Best-effort by design:
    every caller treats a failure here as "carry on cold", never as a
    reason to fail the real request."""
    try:
        conn = http.client.HTTPConnection(UPSTREAM_HOST, UPSTREAM_PORT, timeout=timeout)
        data = json.dumps(body).encode("utf-8")
        conn.request("POST", path, body=data, headers={"Content-Type": "application/json"})
        resp = conn.getresponse()
        raw = resp.read()
        conn.close()
        if resp.status != 200:
            return None
        return json.loads(raw)
    except Exception:
        return None


def get_slot_info(slot_id: int) -> "dict | None":
    """llama-server's GET /slots entry for one slot (metrics-only view:
    id, n_ctx, is_processing, and n_prompt_tokens -- tokens currently
    held, prompt + generated -- once the slot has run a task), or None."""
    try:
        conn = http.client.HTTPConnection(UPSTREAM_HOST, UPSTREAM_PORT, timeout=5)
        conn.request("GET", "/slots")
        resp = conn.getresponse()
        raw = resp.read()
        conn.close()
        if resp.status != 200:
            return None
        for s in json.loads(raw):
            if isinstance(s, dict) and s.get("id") == slot_id:
                return s
    except Exception:
        return None
    return None


class SaveTracker:
    """Per-session bookkeeping for when a disk save is actually needed."""

    def __init__(self, clock=time.monotonic):
        self._lock = threading.Lock()
        self._clock = clock
        self._turns_unsaved: dict = {}
        self._saved_tokens: dict = {}
        self._last_activity: dict = {}
        self._slot: dict = {}

    def on_turn_complete(self, fingerprint: str, slot: int, save_every: int,
                         idle_mode: bool) -> bool:
        """Records a completed turn; True if an inline save is due now."""
        with self._lock:
            n = self._turns_unsaved.get(fingerprint, 0) + 1
            self._turns_unsaved[fingerprint] = n
            self._last_activity[fingerprint] = self._clock()
            self._slot[fingerprint] = slot
            return (not idle_mode) and n >= save_every

    def on_saved(self, fingerprint: str, n_tokens: "int | None") -> None:
        with self._lock:
            self._turns_unsaved[fingerprint] = 0
            if n_tokens is not None:
                self._saved_tokens[fingerprint] = n_tokens

    on_restored = on_saved

    def saved_tokens(self, fingerprint: str) -> "int | None":
        with self._lock:
            return self._saved_tokens.get(fingerprint)

    def dirty(self, fingerprint: str) -> bool:
        with self._lock:
            return self._turns_unsaved.get(fingerprint, 0) > 0

    def idle_dirty(self, idle_seconds: float) -> list:
        """[(fingerprint, slot)] with unsaved turns, idle >= idle_seconds."""
        now = self._clock()
        with self._lock:
            return [
                (fp, self._slot[fp]) for fp, n in self._turns_unsaved.items()
                if n > 0 and now - self._last_activity.get(fp, now) >= idle_seconds
            ]

    def active(self, seconds: float) -> list:
        """Sessions with unsaved turns, or a turn in the last `seconds`."""
        now = self._clock()
        with self._lock:
            return [fp for fp, t in self._last_activity.items()
                    if self._turns_unsaved.get(fp, 0) > 0 or now - t < seconds]

    def forget(self, fingerprints) -> None:
        with self._lock:
            for fp in fingerprints:
                for d in (self._turns_unsaved, self._saved_tokens,
                          self._last_activity, self._slot):
                    d.pop(fp, None)


save_tracker = SaveTracker()

# Sessions seen warm (completed a turn, or verified via /slots) in their
# current slot during this proxy run -- skips the /slots warm check.
# Cleared when llama-server looks like it went away (upstream
# unreachable), since a restarted llama-server comes back with empty slots.
_warm_this_run: set = set()
_restore_failed: set = set()
_restore_lock = threading.Lock()


def maybe_restore_slot(slot_id: int, fingerprint: str, already_there: bool) -> str:
    """Restores `fingerprint`'s saved KV cache into slot_id if it has one
    and the slot isn't already holding it warm. Returns what happened:
    "no-file", "warm", "failed-before", "restored" or "failed".

    History: a 2026-09-06 "seed a new session from the most recently
    saved other session" fallback was disabled the same day (restoring a
    big seed could exhaust the then-unified KV pool: "Unable to restore
    slot: No available space in KV cache") and its dead code was removed
    2026-10-30. See docs/LOG.md before ever reviving it.
    """
    path = SLOT_SAVE_DIR / _slot_save_filename(fingerprint)
    with _restore_lock:
        if already_there and fingerprint in _warm_this_run:
            return "warm"
        if fingerprint in _restore_failed:
            return "failed-before"
    if not path.exists():
        return "no-file"
    if already_there:
        info = get_slot_info(slot_id)
        if info is None or int(info.get("n_prompt_tokens") or 0) > 0:
            # Either llama-server still holds this session's context (a
            # proxy-only restart), or /slots isn't answering -- in which
            # case a restore wouldn't work either. Don't clobber the slot.
            with _restore_lock:
                _warm_this_run.add(fingerprint)
            return "warm"

    result = _post_json_to_upstream(
        f"/slots/{slot_id}?action=restore",
        {"filename": path.name},
        timeout=120.0,
    )
    if result is not None:
        n = result.get("n_restored")
        save_tracker.on_restored(fingerprint, n if isinstance(n, int) else None)
        sys.stderr.write(
            f"[slot-pin-proxy] restored slot {slot_id} from disk for fingerprint "
            f"{fingerprint} ({n} tokens)\n"
        )
        return "restored"
    with _restore_lock:
        _restore_failed.add(fingerprint)
    sys.stderr.write(
        f"[slot-pin-proxy] restore failed for slot {slot_id}, fingerprint {fingerprint} "
        "-- continuing cold (won't retry this run)\n"
    )
    return "failed"


def save_slot(slot_id: int, fingerprint: str) -> str:
    """Saves slot_id's KV cache to disk as `fingerprint`'s file, unless its
    token count hasn't grown since the last save/restore. Must be called
    while holding completion_fifo. Returns "saved", "unchanged",
    "not-occupant" or "failed"."""
    if session_slots.occupant(slot_id) != fingerprint:
        return "not-occupant"
    info = get_slot_info(slot_id)
    n_tokens = None
    if info is not None and isinstance(info.get("n_prompt_tokens"), int):
        n_tokens = info["n_prompt_tokens"]
        last = save_tracker.saved_tokens(fingerprint)
        if last is not None and n_tokens == last:
            save_tracker.on_saved(fingerprint, last)
            sys.stderr.write(
                f"[slot-pin-proxy] skip save: slot {slot_id} unchanged since last save "
                f"({n_tokens} tokens), fingerprint {fingerprint}\n"
            )
            return "unchanged"
    result = _post_json_to_upstream(
        f"/slots/{slot_id}?action=save",
        {"filename": _slot_save_filename(fingerprint)},
        timeout=120.0,
    )
    if result is None:
        sys.stderr.write(f"[slot-pin-proxy] save failed for slot {slot_id}, fingerprint {fingerprint}\n")
        return "failed"
    saved = result.get("n_saved")
    save_tracker.on_saved(fingerprint, saved if isinstance(saved, int) else n_tokens)
    sys.stderr.write(f"[slot-pin-proxy] saved slot {slot_id} to disk for fingerprint {fingerprint}\n")
    return "saved"


def flush_if_dirty(fingerprint: "str | None", slot_id: int) -> "str | None":
    """Before slot_id is handed to another session: save its current
    occupant if it has unsaved turns. Caller holds completion_fifo."""
    if fingerprint is None or not save_tracker.dirty(fingerprint):
        return None
    return save_slot(slot_id, fingerprint)


def start_idle_saver(idle_seconds: float, gate=None, poll_seconds: "float | None" = None):
    """Background saver (SETTINGS.idle_save_seconds > 0): saves sessions
    with unsaved turns once they've been idle `idle_seconds`, taking the
    FIFO gate (a context-manager factory, default _exclusive_slot_io) so
    it never overlaps a request, restore or cleanup."""
    if idle_seconds <= 0:
        return None
    gate = gate or _exclusive_slot_io
    poll = poll_seconds if poll_seconds is not None else max(1.0, min(15.0, idle_seconds / 4))

    def _loop():
        while True:
            time.sleep(poll)
            try:
                for fp, slot in save_tracker.idle_dirty(idle_seconds):
                    with gate():
                        # Re-check under the gate: a request may have run
                        # (or moved the session) while we waited.
                        if (fp, slot) in save_tracker.idle_dirty(idle_seconds) \
                                and session_slots.occupant(slot) == fp:
                            save_slot(slot, fp)
            except Exception as e:  # never let the saver kill the proxy
                sys.stderr.write(f"[slot-pin-proxy] idle saver error: {e!r}\n")

    sys.stderr.write(f"[slot-pin-proxy] idle saver on: save after {idle_seconds:g}s idle "
                     "(inline saves disabled)\n")
    t = threading.Thread(target=_loop, name="idle-slot-saver", daemon=True)
    t.start()
    return t


@contextlib.contextmanager
def _exclusive_slot_io():
    """Holds the completion FIFO gate -- every slot save/restore happens
    while it's held, so while cleanup (or the idle saver) holds it nothing
    else can be mid save/restore. Waits its turn behind queued requests
    like any other caller."""
    ticket, _, _ = completion_fifo.acquire()
    try:
        yield
    finally:
        completion_fifo.release(ticket)


def prepare_completion(data: dict) -> tuple:
    """Assigns a slot to a parsed completion body and restores its disk
    cache if needed. Caller holds completion_fifo. Returns
    (slot, fingerprint_or_None, note-for-the-log)."""
    fingerprint = session_fingerprint(data)
    if fingerprint is None:
        slot = session_slots.lru_slot()
        flush_if_dirty(session_slots.occupant(slot), slot)
        session_slots.mark_used(slot, None)
        return slot, None, f" id_slot={slot} ephemeral"
    slot, already_there, evicted = session_slots.slot_for(fingerprint)
    if evicted is not None and evicted != fingerprint:
        flush_if_dirty(evicted, slot)
        with _restore_lock:
            _warm_this_run.discard(evicted)
    restore = maybe_restore_slot(slot, fingerprint, already_there)
    session_slots.mark_used(slot, fingerprint)
    return slot, fingerprint, f" id_slot={slot} fp={fingerprint} cache={restore}"


def finish_completion(slot: int, fingerprint: "str | None") -> "str | None":
    """After a complete 200 response: record the turn and save inline if
    due. Caller holds completion_fifo -- so the next queued request waits
    for the save, the latency cost accepted for surviving restarts (see
    docs/LOG.md, issue #4)."""
    if fingerprint is None:
        return None
    with _restore_lock:
        _warm_this_run.add(fingerprint)
    due = save_tracker.on_turn_complete(
        fingerprint, slot, SETTINGS.save_every_n_turns, SETTINGS.idle_save_seconds > 0)
    return save_slot(slot, fingerprint) if due else None


def note_upstream_down() -> None:
    """llama-server unreachable: it may be restarting, and will come back
    with empty slots -- forget what we believed was warm."""
    with _restore_lock:
        _warm_this_run.clear()
        _restore_failed.clear()


def discover_models():
    """Only models advertised by live backends; discovery never queues inference."""
    rows={};reachable=False
    targets=[ROUTER.llama]
    if MLX_SETTINGS.enabled:targets.insert(0,ROUTER.mlx)
    for backend in targets:
        conn=None
        try:
            conn=http.client.HTTPConnection(*backend.address(),timeout=2)
            conn.request("GET","/v1/models")
            response=conn.getresponse()
            if response.status!=200:continue
            data=json.loads(response.read(1024*1024))
            if not isinstance(data.get("data"),list):continue
            reachable=True
            for item in data["data"]:
                if not isinstance(item,dict) or not isinstance(item.get("id"),str):continue
                item=dict(item);mid=item["id"]
                if backend.name=="mlx" and mid.startswith("/"):
                    mid=Path(mid).name.replace("--","/",1)
                item["id"]=mid;rows.setdefault(mid,item)
        except (OSError,ValueError,http.client.HTTPException):pass
        finally:
            if conn is not None:conn.close()
    return reachable,{"object":"list","data":list(rows.values())}


class ProxyHandler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    # How often to check whether the client (openclaw) is still there while
    # we're blocked waiting on a slow upstream. See _client_gone().
    DISCONNECT_POLL_INTERVAL = 0.5

    def log_message(self, fmt, *args):
        sys.stderr.write("[slot-pin-proxy] " + (fmt % args) + "\n")

    def handle_one_request(self):
        try:
            super().handle_one_request()
        except (BrokenPipeError, ConnectionResetError, http.client.HTTPException):
            # Harmless: client closed a keep-alive connection between
            # requests instead of sending another one.
            self.close_connection = True

    def _client_gone(self) -> bool:
        """Non-blocking check for whether the client has closed its side
        of the connection -- used so a slow cold-start (minutes of prompt
        processing with no bytes sent yet) doesn't keep grinding away
        after openclaw has already given up and moved on (its own
        timeout, or the user killing the TUI). Peeks without consuming:
        a client that's just quietly waiting for our response shows up
        as "not readable" and is left alone; only an actual FIN/RST
        (readable, zero bytes, or a read error) counts as gone. See
        module docstring, "keep the LLM working only on requests someone
        is still waiting on" -- 2026-09-06."""
        try:
            ready, _, _ = select.select([self.connection], [], [], 0)
            if not ready:
                return False
            return self.connection.recv(1, socket.MSG_PEEK) == b""
        except OSError:
            return True

    def _forward(self, method: str):
        raw_len = int(self.headers.get("Content-Length", 0) or 0)
        raw_body = self.rfile.read(raw_len) if raw_len else b""

        is_completion = self.path in COMPLETION_PATHS and bool(raw_body)
        ticket = None
        if is_completion:
            ticket, ahead, waited = completion_fifo.acquire()
            if ahead > 0 or waited > 0.05:
                self.log_message(
                    "%s %s -- waited %.1fs behind %d queued request(s)",
                    method, self.path, waited, ahead,
                )
        try:
            self._forward_locked(method, raw_body, is_completion)
        finally:
            if ticket is not None:
                completion_fifo.release(ticket)

    def _forward_locked(self, method: str, raw_body: bytes, is_completion: bool):
        slot_note = ""
        slot_for_save = None
        fingerprint_for_save = None
        backend = ROUTER.llama
        mlx_fingerprint = None
        if is_completion:
            try:
                data = json.loads(raw_body)
            except ValueError:
                data = None
            if isinstance(data, dict):
                backend = ROUTER.for_model(data.get("model"))
            if isinstance(data, dict) and backend.supports_slots:
                slot, fingerprint, slot_note = prepare_completion(data)
                data["id_slot"] = slot
                raw_body = json.dumps(data).encode("utf-8")
                slot_for_save = slot
                fingerprint_for_save = fingerprint
            elif isinstance(data, dict):
                # MLX (step b, 2026-10-31): same session identity, no slot.
                # The fingerprint goes to Caravan's MLX worker as
                # X-Caravan-Session -> one prompt cache per session, saved to
                # <fp>.safetensors and loaded back after a restart. A plain
                # mlx_lm.server ignores the header and 404s the cache calls
                # ("mlx-noop").
                mlx_fingerprint = mlx_session_fingerprint(data)
                restore = backend.restore(mlx_fingerprint) if mlx_fingerprint else "ephemeral"
                warm = "warm" if mlx_fingerprint and mlx_sessions.seen(mlx_fingerprint) else "cold"
                how = ("per-session MLX prompt cache" if restore != "mlx-noop"
                       else "no MLX cache endpoints upstream")
                slot_note = (f" backend=mlx model={data.get('model')} fp={mlx_fingerprint} "
                             f"cache={restore} ({warm}; {how})")
                raw_body = json.dumps(backend.prepare_body(data)).encode("utf-8")
        upstream_host, upstream_port = backend.address()

        headers = {
            k: v
            for k, v in self.headers.items()
            if k.lower() not in ("host", "content-length")
        }
        headers["Content-Length"] = str(len(raw_body))
        headers["Host"] = f"{upstream_host}:{upstream_port}"
        if mlx_fingerprint is not None:
            headers.update(backend.session_headers(mlx_fingerprint))

        conn = http.client.HTTPConnection(upstream_host, upstream_port)
        try:
            # conn.getresponse() blocks with no timeout -- during a cold
            # prompt-processing run that can be many minutes with zero
            # bytes sent yet, so it happens on a background thread while
            # the main thread polls _client_gone(). If the client leaves,
            # shutting down conn's socket unblocks the thread immediately
            # and tells llama-server its client (us) disconnected, which
            # triggers its own existing cancel-on-disconnect handling --
            # same path already observed tonight when the proxy itself
            # was restarted mid-request. This is what actually frees the
            # slot and the FIFO gate instead of both sitting on a
            # request nobody is waiting for.
            response_box: dict = {}

            def _do_upstream_request():
                try:
                    conn.request(method, self.path, body=raw_body, headers=headers)
                    response_box["resp"] = conn.getresponse()
                except Exception as e:
                    response_box["exc"] = e

            req_thread = threading.Thread(target=_do_upstream_request, daemon=True)
            req_thread.start()
            while req_thread.is_alive():
                if self._client_gone():
                    self.log_message(
                        "%s %s -- client gone, cancelling upstream (was waiting on response)",
                        method, self.path,
                    )
                    self.close_connection = True
                    if conn.sock is not None:
                        try:
                            conn.sock.shutdown(socket.SHUT_RDWR)
                        except OSError:
                            pass
                    req_thread.join(timeout=2)
                    return
                req_thread.join(timeout=self.DISCONNECT_POLL_INTERVAL)

            if "exc" in response_box:
                exc = response_box["exc"]
                if not isinstance(exc, OSError):
                    raise exc
                # llama-server isn't up yet/crashed -- common right after
                # a launchd (re)start race, not worth a traceback.
                if backend.supports_slots:
                    note_upstream_down()
                self.log_message("%s %s -> %s upstream unreachable (%s)",
                                 method, self.path, backend.name, exc)
                body = (b"mlx_lm.server upstream unreachable\n" if backend.name == "mlx"
                        else b"llama-server upstream unreachable\n")
                self.send_response(502)
                self.send_header("Content-Type", "text/plain")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
                return

            upstream_resp = response_box["resp"]
            self.log_message(
                "%s %s -> %s%s", method, self.path, upstream_resp.status, slot_note
            )

            # Response framing (2026-10-30, perf review #2). http.client
            # has already de-chunked upstream's body, so the original
            # Transfer-Encoding can't be passed through -- and dropping it
            # while keeping the connection alive (as before) left a
            # streaming response with neither Content-Length nor chunked
            # framing, i.e. no way for the client to tell where it ends
            # short of the connection closing. Now:
            #   * upstream sent Content-Length -> pass it through, stream as-is;
            #   * no length, HTTP/1.1 client -> re-chunk (keeps keep-alive,
            #     which openclaw uses, and is exactly what upstream did);
            #   * no length, HTTP/1.0 client -> Connection: close (chunked
            #     isn't allowed for 1.0).
            status = upstream_resp.status
            has_length = upstream_resp.getheader("Content-Length") is not None
            no_body = method == "HEAD" or status in (204, 304) or 100 <= status < 200
            chunked = not no_body and not has_length and self.request_version == "HTTP/1.1"
            if not no_body and not has_length and not chunked:
                self.close_connection = True

            self.send_response(status)
            for k, v in upstream_resp.getheaders():
                if k.lower() in ("transfer-encoding", "connection"):
                    continue
                self.send_header(k, v)
            if chunked:
                self.send_header("Transfer-Encoding", "chunked")
            elif self.close_connection:
                self.send_header("Connection", "close")
            self.end_headers()

            # Stream the response back as it arrives -- required for SSE
            # (stream: true) so tokens still show up incrementally. read1()
            # (not read(4096), which blocks until 4096 bytes have arrived
            # and made SSE token streams bursty) returns whatever upstream
            # has sent so far. Also watched for disconnect here:
            # generation alone can run minutes at this hardware's
            # ~4 tok/s, same reasoning as above.
            while not no_body:
                if self._client_gone():
                    self.log_message(
                        "%s %s -- client gone, cancelling upstream (was streaming)",
                        method, self.path,
                    )
                    self.close_connection = True
                    return
                chunk = upstream_resp.read1(65536)
                if not chunk:
                    break
                if chunked:
                    self.wfile.write(b"%x\r\n%s\r\n" % (len(chunk), chunk))
                else:
                    self.wfile.write(chunk)
                self.wfile.flush()
            if chunked:
                self.wfile.write(b"0\r\n\r\n")
                self.wfile.flush()

            # Reached only on a genuinely complete response (loop above
            # exited via the normal "no more chunks" path, not an early
            # return) -- record the turn, and save this slot's cache now if
            # it's due (see finish_completion / save_slot). Runs while
            # still holding the FIFO gate.
            if status == 200 and slot_for_save is not None:
                finish_completion(slot_for_save, fingerprint_for_save)
            elif status == 200 and mlx_fingerprint is not None:
                n = mlx_sessions.turn(mlx_fingerprint)
                every = max(1, int(SETTINGS.save_every_n_turns or 1))
                min_turns = max(1, int(SETTINGS.mlx_save_min_turns or 1))
                if n < min_turns:
                    saved = f"skipped (turn {n} < min {min_turns})"
                elif n % every == 0:
                    saved = ROUTER.mlx.save(mlx_fingerprint)
                else:
                    saved = f"skipped (every {every})"
                sys.stderr.write(
                    f"[slot-pin-proxy] mlx fp={mlx_fingerprint} turn {n}: slot save {saved}\n")
        except (BrokenPipeError, ConnectionResetError, http.client.HTTPException):
            # http.client.HTTPException (e.g. IncompleteRead) added
            # 2026-09-06: caught live during the --slot-save-path restart
            # test -- llama-server can accept a TCP connection and send a
            # malformed/truncated chunked response in the brief window
            # before it's actually ready, which isn't a BrokenPipeError or
            # ConnectionResetError and was escaping uncaught, crashing
            # that request's thread with a raw traceback in the log. Not
            # fatal (each request is its own thread, and openclaw's own
            # retry recovered), but noisy and worth treating the same as
            # any other "upstream connection didn't behave" case.
            # The response may be half-written: never reuse this
            # connection (a missing terminal chunk must look like an error).
            self.close_connection = True
        finally:
            conn.close()

    def do_GET(self):
        if self.path.split("?")[0] == "/v1/models":
            reachable,data=discover_models()
            body=json.dumps(data if reachable else {"error":"No model backend is reachable"}).encode()
            self.send_response(200 if reachable else 503)
            self.send_header("Content-Type","application/json")
            self.send_header("Content-Length",str(len(body)))
            self.end_headers();self.wfile.write(body)
            return
        if self.path.split("?")[0] == "/caravan/proxy/status":
            body = json.dumps(completion_fifo.status()).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        self._forward("GET")

    def do_POST(self):
        self._forward("POST")

    def do_PUT(self):
        self._forward("PUT")

    def do_DELETE(self):
        self._forward("DELETE")


def _forget_cleaned_sessions(fingerprints) -> list:
    fingerprints = list(fingerprints)
    save_tracker.forget(fingerprints)
    mlx_sessions.forget(fingerprints)
    with _restore_lock:
        for fp in fingerprints:
            _warm_this_run.discard(fp)
            _restore_failed.discard(fp)
    return session_slots.forget(fingerprints)


def _active_sessions(protect_seconds: float = 1800.0) -> list:
    """Sessions the per-Mini slot cap must never evict: in a llama.cpp
    slot right now, unsaved turns, or a turn (llama.cpp or MLX) in the
    last protect_seconds."""
    return sorted(set(session_slots.occupants())
                  | set(save_tracker.active(protect_seconds))
                  | set(mlx_sessions.recent(protect_seconds)))


def start_slot_cleanup(overrides: "dict | None" = None):
    """Starts the automatic stale-slot cleanup thread. A bad setting
    disables cleanup with a log line rather than crash-looping a
    KeepAlive'd proxy."""
    overrides = {k: v for k, v in (overrides or {}).items() if v is not None}
    overrides.setdefault("slot_dir", str(SLOT_SAVE_DIR))
    overrides.setdefault("state_file", str(STATE_FILE))
    if MLX_SETTINGS.enabled:
        overrides.setdefault("mlx_dir", MLX_SETTINGS.cache_dir)
    try:
        settings = slot_cleanup.resolve_settings(overrides)
    except ValueError as e:
        sys.stderr.write(f"[slot-pin-proxy] slot cleanup disabled, bad setting: {e}\n")
        return None
    return slot_cleanup.start_background(
        settings, gate=_exclusive_slot_io, forget=_forget_cleaned_sessions,
        drop=lambda fps: ROUTER.mlx.drop(fps),
        active=lambda: _active_sessions(settings.protect_minutes * 60.0),
    )


def configure_mlx(overrides: "dict | None" = None) -> None:
    """Re-resolves MLX routing with CLI overrides (main(); tests)."""
    global MLX_SETTINGS
    MLX_SETTINGS = backends.resolve_mlx_settings(_load_config_file(), overrides)
    ROUTER.mlx = backends.MlxBackend(MLX_SETTINGS)


def configure(settings: ProxySettings) -> None:
    """Applies resolved settings (main() after parsing flags; tests)."""
    global SETTINGS, N_SLOTS, session_slots
    if settings.n_slots != N_SLOTS:
        session_slots = SessionSlotAssigner(settings.n_slots, STATE_FILE)
    SETTINGS = settings
    N_SLOTS = settings.n_slots


def main(argv=None):
    parser = argparse.ArgumentParser(
        description="Caravan slot-pin proxy (ports/upstream via CARAVAN_* env vars). "
                    "Settings: flag > env > ~/.caravan/config.json > default.")
    parser.add_argument("--n-slots", type=int, default=None,
                        help="llama-server slot count, must match its --parallel "
                             "(env CARAVAN_N_SLOTS, config llama_server.n_slots, default 4)")
    parser.add_argument("--slot-save-every", dest="save_every_n_turns", type=int, default=None,
                        help="save a session's KV cache to disk every N completed turns "
                             "(env CARAVAN_SLOT_SAVE_EVERY, config proxy.slot_save_every, default 1)")
    parser.add_argument("--slot-idle-save-seconds", dest="idle_save_seconds", type=float, default=None,
                        help="if >0, no inline saves: save once a session has been idle this long "
                             "(env CARAVAN_SLOT_IDLE_SAVE_SECONDS, config proxy.slot_idle_save_seconds, "
                             "default 0 = off)")
    parser.add_argument("--prompt-fingerprint-chars", dest="prompt_fingerprint_chars", type=int,
                        default=None,
                        help="prompt-style calls: prefix length identifying a session; shorter "
                             "prompts are unpinned one-shots (env CARAVAN_PROMPT_FINGERPRINT_CHARS, "
                             "config proxy.prompt_fingerprint_chars, default 2048)")
    parser.add_argument("--mlx-save-min-turns", dest="mlx_save_min_turns", type=int, default=None,
                        help="MLX sessions: no disk save before this many turns; 2 skips saving "
                             "one-message requests (env CARAVAN_MLX_SAVE_MIN_TURNS, config "
                             "proxy.mlx_save_min_turns, default 1 = save from the first turn)")
    g = parser.add_argument_group("MLX backend (flag > env > config \"mlx\" > default)")
    g.add_argument("--mlx-host", default=None, help="mlx_lm.server host (env CARAVAN_MLX_HOST, default 127.0.0.1)")
    g.add_argument("--mlx-port", type=int, default=None,
                   help=f"mlx_lm.server port (env CARAVAN_MLX_PORT, default {backends.DEFAULT_MLX_PORT})")
    g.add_argument("--mlx-prefixes", default=None,
                   help="comma list of model-id prefixes routed to MLX (env CARAVAN_MLX_PREFIXES, "
                        "default mlx-community/)")
    g.add_argument("--no-mlx", action="store_true", help="never route to MLX (env CARAVAN_MLX_ENABLED=0)")
    slot_cleanup.add_cli_args(parser, proxy=True)
    args = parser.parse_args(argv)
    try:
        configure(resolve_proxy_settings({k: getattr(args, k) for k in ProxySettings._fields}))
        configure_mlx({"host": args.mlx_host, "port": args.mlx_port,
                       "model_prefixes": args.mlx_prefixes,
                       "enabled": False if args.no_mlx else None})
    except ValueError as e:
        parser.error(str(e))

    server = ThreadingHTTPServer(("127.0.0.1", LISTEN_PORT), ProxyHandler)
    print(
        f"[slot-pin-proxy] listening on 127.0.0.1:{LISTEN_PORT}, "
        f"forwarding to {UPSTREAM_HOST}:{UPSTREAM_PORT}, "
        f"pinning completions per-session across {N_SLOTS} slot(s) (LRU), FIFO-serialized; "
        f"disk save every {SETTINGS.save_every_n_turns} turn(s)"
        + (f", idle saver {SETTINGS.idle_save_seconds:g}s" if SETTINGS.idle_save_seconds > 0 else ""),
        flush=True,
    )
    if MLX_SETTINGS.enabled:
        print(f"[slot-pin-proxy] MLX routing on: models matching {list(MLX_SETTINGS.model_prefixes)} "
              f"or {sorted(MLX_SETTINGS.models)} -> mlx_lm.server {MLX_SETTINGS.host}:{MLX_SETTINGS.port} "
              f"(per-session prompt cache in {MLX_SETTINGS.cache_dir} when the upstream is Caravan's MLX worker)", flush=True)
    else:
        print("[slot-pin-proxy] MLX routing off", flush=True)
    start_slot_cleanup(slot_cleanup.overrides_from_args(args))
    start_idle_saver(SETTINGS.idle_save_seconds)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
