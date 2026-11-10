#!/usr/bin/env python3
"""Caravan MLX worker (2026-10-31, MLX step b): an OpenAI-compatible
server for one MLX model with per-session prompt caches that survive
between messages *and* across restarts.

Why not plain mlx_lm.server (v1, step a)? Measured 2026-10-30 with
mlx-lm 0.32.2 (still the latest release on 2026-10-31):
  * Gemma 4 and GPT-OSS reused nothing between messages. mlx_lm.server
    stores a conversation's cache *after* generation, keyed by prompt +
    generated tokens. The next request's prompt re-renders the reply
    through the chat template (thinking / analysis channel dropped), so it
    diverges right after the old prompt, and the only way back is to trim
    the stored cache -- which a RotatingKVCache (sliding-window layers:
    25 of Gemma 4's 30, 12 of GPT-OSS's 24) refuses once it has wrapped
    (is_trimmable() == offset < max_size). Result: a cold re-read every
    turn. Qwen3 (plain KVCache, always trimmable) reused fine.
  * Every cache hit was a copy.deepcopy of the stored cache, which is
    what pushed Qwen3 30B over the GPU limit unless the cache was capped.
  * No disk persistence at all.

What this worker does instead (same idea as llama.cpp's context
checkpoints, upstream PR #26004):
  * One live cache per session (keyed by the proxy's session fingerprint,
    sent as the X-Caravan-Session header). No copies.
  * The worker runs the prompt prefill itself, up to the last prompt
    token, and snapshots the layers that can't be trimmed (rotating /
    sliding-window, or any non-KVCache layer) at that point: the
    "checkpoint". Generation then runs from the last token.
  * After the reply, the session is rewound to the checkpoint: trimmable
    layers are trimmed back, the others restored from the snapshot. The
    next turn's prompt starts with exactly those tokens, so only the new
    part (previous reply as re-rendered + new message) is read.
  * The checkpoint is what gets saved to disk
    (<cache-dir>/<fingerprint>.safetensors via mlx_lm's save_prompt_cache)
    when the proxy asks (POST /caravan/cache/save), and loaded on the first
    request after a restart (POST /caravan/cache/restore, or lazily on a
    miss). Metadata records model path, tokenizer hash and cache layout;
    any mismatch means "cold", never a crash.
  * Memory: at most --prompt-cache-size sessions in memory and
    --prompt-cache-bytes for all of them, except the session in use is
    never evicted (it's the live cache -- keeping it costs nothing extra).
    Evicted sessions with unsaved turns are saved first.

Same flag names as mlx_lm.server where they mean the same thing, so the
"mlx.extra_args" config keeps working:
    python agent/mlx_worker.py --model DIR --port 8092 \
        [--prompt-cache-size 4] [--prompt-cache-bytes N] [--prefill-step-size 2048] \
        [--cache-dir ~/.caravan/mlx/prompt-cache] [--no-persist] [--cache-limit-gb G] \
        [--kv-bits 8]   # quantized cache for full-attention layers (Qwen3 at 16k)

The pure cache bookkeeping (SessionStore) doesn't import mlx, so it's
unit-tested with fake cache layers (tests/test_mlx_worker.py).
"""
import argparse
import hashlib
import json
import os
import re
import signal
import sys
import threading
import time
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import guess_ahead
import adaptive_pl
import shared_prefix
from typing import Optional

FORMAT = "caravan-mlx-cache-1"
KEY_RE = re.compile(r"^[A-Za-z0-9_-]{1,64}$")
ANON = "_anon"   # requests without a session key share one in-memory, never-saved session
# Cache classes whose trim() always works (no snapshot needed to rewind).
ALWAYS_TRIMMABLE = ("KVCache", "QuantizedKVCache", "ConcatenateKVCache")
DEFAULT_CACHE_DIR = "~/.caravan/mlx/prompt-cache"


def log(msg: str) -> None:
    sys.stderr.write(f"{time.strftime('%H:%M:%S')} [mlx-worker] {msg}\n")
    sys.stderr.flush()


def enable_stack_dumps():
    """SIGUSR1 dumps Python thread stacks to this worker's own stderr, no locals.

    Useful for socket/scheduler stalls without privileged debugger attachment.
    No periodic sampling or decode-path overhead; unsupported hosts fail soft.
    """
    import faulthandler
    sig = getattr(signal, "SIGUSR1", None)
    if sig is None:
        return False
    try:
        faulthandler.register(sig, file=sys.stderr, all_threads=True)
    except (OSError, RuntimeError, ValueError):
        return False
    return True


def common_prefix(a, b) -> int:
    n = min(len(a), len(b))
    i = 0
    while i < n and a[i] == b[i]:
        i += 1
    return i


def valid_key(key) -> bool:
    return isinstance(key, str) and bool(KEY_RE.match(key)) and key != ANON


class Session:
    def __init__(self, key, cache):
        self.key = key
        self.cache = cache          # list of layer caches (live)
        self.tokens = []            # tokens the cache holds (== checkpoint after rewind)
        self.snaps = None           # {layer index: snapshot} at len(tokens), or None
        self.dirty = False          # turns not yet on disk
        self.last_used = time.monotonic()
        self.turns = 0


class SessionStore:
    """Per-session caches. `ops` hides every mlx call (see MlxOps):
    new_cache(), always_trimmable(layer), trim(layer, n), offset(layer),
    snapshot(layer), from_snapshot(snap), nbytes(cache), snap_nbytes(snaps),
    save(path, cache, metadata), load(path) -> (cache, metadata),
    classes(cache), release()."""

    def __init__(self, ops, cache_dir, ident: dict, max_sessions=4, max_bytes=None,
                 persist=True, clock=time.monotonic):
        self.ops = ops
        self.cache_dir = Path(cache_dir).expanduser() if cache_dir else None
        self.ident = dict(ident)
        self.max_sessions = max(1, int(max_sessions))
        self.max_bytes = max_bytes
        self.persist = bool(persist and self.cache_dir is not None)
        self.clock = clock
        self.sessions = {}
        self.stats = {"hit_tokens": 0, "read_tokens": 0}
        self.on_evict = None        # v3 split: callback(keys) so the other stage drops them too

    # --- paths / metadata -------------------------------------------------
    def path(self, key) -> Path:
        return self.cache_dir / f"{key}.safetensors"

    def _metadata(self, s: Session) -> dict:
        md = {"format": FORMAT, "key": s.key, "tokens": json.dumps(s.tokens),
              "classes": ",".join(self.ops.classes(s.cache)), "saved_at": str(time.time())}
        md.update({k: str(v) for k, v in self.ident.items()})
        return md

    def check_metadata(self, md: dict, cache) -> "str | None":
        """None if a loaded file fits this worker, else why not."""
        if not isinstance(md, dict) or md.get("format") != FORMAT:
            return "not a caravan cache file"
        for k, v in self.ident.items():
            if md.get(k) != str(v):
                return f"{k} differs"
        if md.get("classes") != ",".join(self.ops.classes(self.ops.new_cache())):
            return "cache layout differs"
        if ",".join(self.ops.classes(cache)) != md.get("classes"):
            return "cache layout differs"
        try:
            toks = json.loads(md.get("tokens", ""))
        except ValueError:
            return "bad token list"
        if not isinstance(toks, list) or not all(isinstance(t, int) for t in toks) or not toks:
            return "bad token list"
        for layer in cache:
            if self.ops.always_trimmable(layer) and self.ops.offset(layer) != len(toks):
                return "token count doesn't match the cache"
        return None

    # --- memory -----------------------------------------------------------
    def session_bytes(self, s: Session) -> int:
        return self.ops.nbytes(s.cache) + (self.ops.snap_nbytes(s.snaps) if s.snaps else 0)

    def total_bytes(self) -> int:
        return sum(self.session_bytes(s) for s in self.sessions.values())

    def enforce_limits(self, keep=None) -> list:
        """Evicts least-recently-used sessions (never `keep`), saving dirty
        ones first. Returns evicted keys."""
        evicted = []
        while len(self.sessions) > 1:
            over_n = len(self.sessions) > self.max_sessions
            over_b = self.max_bytes is not None and self.total_bytes() > self.max_bytes
            if not (over_n or over_b):
                break
            victims = sorted((s for k, s in self.sessions.items() if k != keep),
                             key=lambda s: s.last_used)
            if not victims:
                break
            v = victims[0]
            if v.dirty and self.persist and v.key != ANON:
                self.save(v.key)
            del self.sessions[v.key]
            evicted.append(v.key)
        if evicted:
            self.ops.release()
            log(f"evicted {len(evicted)} session(s) from memory: {', '.join(evicted)}")
            if self.on_evict:
                self.on_evict(evicted)
        return evicted

    # --- disk -------------------------------------------------------------
    def save(self, key) -> str:
        s = self.sessions.get(key)
        if s is None:
            return "absent"
        if not self.persist or key == ANON:
            return "off"
        if not s.dirty:
            return "unchanged"
        if not s.tokens or s.snaps is None:
            return "empty"
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        final = self.path(key)
        tmp = final.with_name(f"{key}.tmp-{os.getpid()}.safetensors")
        t0 = time.time()
        try:
            self.ops.save(str(tmp), s.cache, self._metadata(s))
            os.replace(tmp, final)
        except Exception as e:
            try:
                tmp.unlink()
            except OSError:
                pass
            log(f"save failed for {key}: {e!r}")
            return "failed"
        s.dirty = False
        size = final.stat().st_size
        log(f"saved {key}: {len(s.tokens)} tokens, {size / 1e6:.0f} MB in {time.time() - t0:.2f}s")
        return "saved"

    def _load(self, key) -> "tuple[Optional[Session], str]":
        if not self.persist or not valid_key(key):
            return None, "miss"
        p = self.path(key)
        if not p.is_file():
            return None, "miss"
        t0 = time.time()
        try:
            cache, md = self.ops.load(str(p))
        except Exception as e:
            log(f"could not read {p.name} ({e!r}) -- starting cold")
            return None, "rejected"
        why = self.check_metadata(md, cache)
        if why:
            log(f"ignoring {p.name}: {why} -- starting cold")
            return None, "rejected"
        s = Session(key, cache)
        s.tokens = json.loads(md["tokens"])
        s.snaps = {i: self.ops.snapshot(c) for i, c in enumerate(cache)
                   if not self.ops.always_trimmable(c)}
        s.last_used = self.clock()
        self.sessions[key] = s
        log(f"restored {key} from disk: {len(s.tokens)} tokens in {time.time() - t0:.2f}s")
        return s, "restored"

    def restore(self, key) -> str:
        """Prefetch a session (proxy: first request for it this run)."""
        if key in self.sessions:
            return "warm"
        s, how = self._load(key)
        if s is not None:
            self.enforce_limits(keep=key)
        return how

    def drop(self, keys) -> list:
        out = [k for k in keys if self.sessions.pop(k, None) is not None]
        if out:
            self.ops.release()
        return out

    def flush(self) -> int:
        n = 0
        for k in list(self.sessions):
            if self.save(k) == "saved":
                n += 1
        return n

    # --- per request ------------------------------------------------------
    def prepare(self, key, prompt, allow_load=True) -> "tuple[Session, int, str]":
        """Session for `key` with its cache positioned at the longest
        reusable prefix of `prompt` (always leaving >= 1 token to read).
        Returns (session, n_reused, how). allow_load=False (v3 split): never
        read the disk here -- the head restores both halves together first."""
        key = key if valid_key(key) else ANON
        how = "memory"
        s = self.sessions.get(key)
        if s is None and not allow_load:
            how = "new"
        elif s is None:
            s, how = self._load(key)
            how = "disk" if s is not None else ("rejected" if how == "rejected" else "new")
        if s is None:
            s = Session(key, self.ops.new_cache())
            self.sessions[key] = s
        s.last_used = self.clock()
        limit = len(prompt) - 1
        n = common_prefix(s.tokens, prompt)
        if s.tokens and n >= len(s.tokens) and len(s.tokens) <= limit:
            return s, len(s.tokens), f"hit-{how}"
        if not s.tokens:
            return s, 0, "cold"
        target = max(0, min(n, limit))
        if all(self.ops.always_trimmable(c) or c_trimmable(self.ops, c) for c in s.cache):
            drop = len(s.tokens) - target
            for c in s.cache:
                self.ops.trim(c, drop)
            s.tokens = s.tokens[:target]
            s.snaps = None
            return s, target, f"trimmed-{how}"
        log(f"session {key}: prompt diverges at token {n} of {len(s.tokens)} cached and "
            "sliding-window layers can't rewind -- re-reading from scratch")
        s.cache = self.ops.new_cache()
        s.tokens, s.snaps = [], None
        self.ops.release()
        return s, 0, f"diverged-{how}"

    def checkpoint(self, s: Session, tokens) -> None:
        """Cache now holds exactly `tokens` (prefill done, nothing generated)."""
        s.tokens = list(tokens)
        s.snaps = {i: self.ops.snapshot(c) for i, c in enumerate(s.cache)
                   if not self.ops.always_trimmable(c)}

    def rewind(self, s: Session, completed=True) -> None:
        """After generation: back to the checkpoint so the next turn's
        prompt (which re-renders this reply) can reuse everything before it."""
        if s.snaps is None:
            self.reset(s)
            return
        p = len(s.tokens)
        for i, c in enumerate(s.cache):
            if i in s.snaps:
                s.cache[i] = self.ops.from_snapshot(s.snaps[i])
            else:
                self.ops.trim(c, max(0, self.ops.offset(c) - p))
        if completed:
            s.turns += 1
            s.dirty = True
        s.last_used = self.clock()
        self.enforce_limits(keep=s.key)

    def reset(self, s: Session) -> None:
        s.cache = self.ops.new_cache()
        s.tokens, s.snaps = [], None
        self.ops.release()

    def describe(self) -> list:
        return [{"key": s.key, "tokens": len(s.tokens), "bytes": self.session_bytes(s),
                 "dirty": s.dirty, "turns": s.turns,
                 "on_disk": bool(self.persist and s.key != ANON and self.path(s.key).is_file())}
                for s in sorted(self.sessions.values(), key=lambda s: -s.last_used)]


def c_trimmable(ops, layer) -> bool:
    try:
        return bool(layer.is_trimmable())
    except Exception:
        return False


class HarmonySplitter:
    """gpt-oss replies come back from mlx-lm 0.32.2 as raw harmony text
    (<|channel|>analysis<|message|>...<|end|><|start|>assistant<|channel|>final<|message|>...).
    Splits a stream of text pieces into ("reasoning", t) / ("normal", t)
    and drops the markup, so clients get a clean answer, the way
    llama.cpp's harmony parser fills content / reasoning_content.

    A small state machine over <|...|> markers: <|start|> and <|channel|>
    open a header (role / channel name) that runs to <|message|>; the body
    after it is reasoning for analysis/commentary and content for final.
    Text before any channel header is content (a reply without channels)."""
    MARK = "<|channel|>final<|message|>"
    REASONING_CHANNELS = ("analysis", "commentary")

    def __init__(self):
        self.buf = ""
        self.mode = "body"      # "body" | "header"
        self.header = ""
        self.kind = "normal"
        self.final = False

    def _marker(self, m):
        if m in ("<|start|>", "<|channel|>"):
            if self.mode != "header":
                self.mode, self.header = "header", ""
            if m == "<|channel|>":
                self.header = ""
        elif m == "<|message|>":
            chan = self.header.strip().split(" ")[0] if self.header.strip() else ""
            if chan.startswith("final"):
                self.kind, self.final = "normal", True
            elif chan in self.REASONING_CHANNELS or chan.startswith(self.REASONING_CHANNELS):
                self.kind = "reasoning"
            elif chan.startswith("assistant") or not chan:
                pass
            else:
                self.kind = "reasoning"
            self.mode, self.header = "body", ""
        # <|end|>, <|return|>, <|call|>, <|constrain|> ...: markup only

    def feed(self, text):
        self.buf += text
        out = []
        while self.buf:
            j = self.buf.find("<|")
            if j < 0:
                keep = 1 if self.buf.endswith("<") else 0
                piece, self.buf = self.buf[:len(self.buf) - keep], self.buf[len(self.buf) - keep:]
                self._text(piece, out)
                break
            if j > 0:
                self._text(self.buf[:j], out)
                self.buf = self.buf[j:]
            k = self.buf.find("|>", 2)
            if k < 0:
                break          # incomplete marker: wait for more
            self._marker(self.buf[:k + 2])
            self.buf = self.buf[k + 2:]
        merged = []
        for kind, t in out:
            if merged and merged[-1][0] == kind:
                merged[-1] = (kind, merged[-1][1] + t)
            else:
                merged.append((kind, t))
        return [(k, t) for k, t in merged if t]

    def _text(self, t, out):
        if not t:
            return
        if self.mode == "header":
            self.header += t
        else:
            out.append((self.kind, t))

    def flush(self):
        t, self.buf = self.buf, ""
        if t and self.mode == "body":
            return [(self.kind, t)]
        return []


def tokenizer_hash(model_dir: Path) -> str:
    h = hashlib.sha256()
    for name in ("tokenizer.json", "tokenizer_config.json", "chat_template.jinja", "config.json"):
        p = model_dir / name
        if p.is_file():
            h.update(name.encode())
            h.update(p.read_bytes())
    return h.hexdigest()[:16]


class MlxOps:
    """The mlx side of SessionStore."""

    def __init__(self, model, kv_bits=None, kv_group_size=64):
        import mlx.core as mx
        from mlx_lm.models import cache as C
        self.mx, self.C, self.model = mx, C, model
        self.kv_bits, self.kv_group_size = kv_bits, kv_group_size

    def new_cache(self):
        cache = self.C.make_prompt_cache(self.model)
        if self.kv_bits:
            # Full-attention layers only (sliding-window ones are already
            # bounded); quantized from the first token, so prefill, the
            # checkpoint and the file all use the same layout.
            cache = [self.C.QuantizedKVCache(group_size=self.kv_group_size, bits=self.kv_bits)
                     if type(c).__name__ == "KVCache" else c for c in cache]
        return cache

    def always_trimmable(self, layer):
        return type(layer).__name__ in ALWAYS_TRIMMABLE

    def trim(self, layer, n):
        if n > 0:
            layer.trim(n)

    def offset(self, layer):
        return int(getattr(layer, "offset", 0) or 0)

    def _fresh(self, x):
        mx = self.mx
        if isinstance(x, mx.array):
            return mx.array(x)
        if isinstance(x, (list, tuple)):
            return type(x)(self._fresh(y) for y in x)
        return x

    def snapshot(self, layer):
        mx = self.mx
        st = layer.state
        if type(layer).__name__ == "RotatingKVCache":
            keys, values, offset, keep, max_size, idx = st
            # Compact to the last max_size tokens when the buffer is in
            # temporal order (after a multi-token update it always is):
            # equivalent for every later update, and smaller on disk.
            if keys is not None and keep == 0 and idx == keys.shape[2] and keys.shape[2] > max_size:
                keys = mx.contiguous(keys[..., -max_size:, :])
                values = mx.contiguous(values[..., -max_size:, :])
                idx = max_size
            st = (keys, values, offset, keep, max_size, idx)
        snap = (type(layer), self._fresh(st))
        mx.eval([a for a in _arrays(snap[1], mx)])
        return snap

    def from_snapshot(self, snap):
        cls, st = snap
        return cls.from_state(self._fresh(st))

    def nbytes(self, cache):
        n = 0
        for c in cache:
            try:
                n += int(c.nbytes)
            except Exception:
                pass
        return n

    def snap_nbytes(self, snaps):
        return sum(a.nbytes for s in snaps.values() for a in _arrays(s[1], self.mx))

    def classes(self, cache):
        return [type(c).__name__ for c in cache]

    def save(self, path, cache, metadata):
        out = []
        for c in cache:
            if type(c).__name__ == "KVCache" and c.keys is not None:
                o = c.offset
                out.append(self.C.KVCache.from_state((c.keys[..., :o, :], c.values[..., :o, :], o)))
            elif type(c).__name__ == "QuantizedKVCache" and c.keys is not None:
                o = c.offset
                q = self.C.QuantizedKVCache(group_size=c.group_size, bits=c.bits)
                q.state = (tuple(x[..., :o, :] for x in c.keys), tuple(x[..., :o, :] for x in c.values),
                           o, c.group_size, c.bits)
                out.append(q)
            else:
                out.append(c)
        self.C.save_prompt_cache(path, out, metadata)

    def load(self, path):
        return self.C.load_prompt_cache(path, return_metadata=True)

    def release(self):
        self.mx.clear_cache()


def _arrays(x, mx):
    if isinstance(x, mx.array):
        yield x
    elif isinstance(x, (list, tuple)):
        for y in x:
            yield from _arrays(y, mx)


def _text_of(content):
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "".join(p.get("text", "") for p in content if isinstance(p, dict) and p.get("type") in ("text", None))
    return "" if content is None else str(content)


def apply_startup_wiring(mode, mx, set_recommended):
    """--wired-limit startup (default, like mlx_lm.server): raise the Metal
    wired limit to the recommended working set once, after load, and keep
    it there for the life of the process so the weights stay resident.
    Returns (old_limit, new_limit) or None when not applied."""
    if mode != "startup":
        return None
    old = set_recommended()
    if old is None:
        return None
    return old, mx.device_info().get("max_recommended_working_set_size")


def request_wiring(mode, G, model, stream):
    """Context for one request's prompt reading. v2 behaviour
    ("per-request") wrapped it in mlx_lm's wired_limit(), which raises the
    limit on entry and drops it back on exit -- so with no startup limit
    the limit went up and down (twice, with stream_generate's own wrapper)
    on every request. In "startup"/"off" mode this is a no-op."""
    import contextlib
    if mode == "per-request":
        return G.wired_limit(model, [stream])
    return contextlib.nullcontext()


class Engine:
    """Model + tokenizer + the session store. MLX streams are per-thread,
    so everything that touches mlx (load, prefill, generation, cache
    save/load) runs on one dedicated thread; HTTP handler threads hand it
    jobs and read results from a queue -- one generation at a time, like
    mlx_lm.server's generation thread."""

    def __init__(self, args):
        import queue
        self.args = args
        self.jobs = queue.Queue()
        self._queue_mod = queue
        # Idea 1: max concurrent split chats. None = resolve in _setup (ROADMAP #13a).
        raw_pipe = getattr(args, "split_pipeline_chats", None)
        self._pipeline_chats_explicit = raw_pipe is not None
        if raw_pipe is None:
            self.pipeline_chats = None
        else:
            self.pipeline_chats = max(1, int(raw_pipe))
        self.native_mtp = None
        self.draft_model = None
        self.draft_tokenizer = None
        self.speculate_k = int(getattr(args, "split_speculate_k", 4) or 4)
        if self.speculate_k < 1:
            self.speculate_k = 1
        # Idea 3 draft-free: prompt-lookup / n-gram from context (0 = off).
        self.prompt_lookup_n = int(getattr(args, "split_prompt_lookup", 0) or 0)
        if self.prompt_lookup_n < 0:
            self.prompt_lookup_n = 0
        self.prompt_lookup_adaptive = bool(getattr(args, "split_prompt_lookup_adaptive", False))
        self._adaptive_pl_gate = None
        if self.prompt_lookup_adaptive and self.prompt_lookup_n > 0:
            self._adaptive_pl_gate = adaptive_pl.AdaptivePLGate(ngram_n=self.prompt_lookup_n)
        # Day 12/13: flag/env pins on; otherwise learn may flip live (default off).
        self._learn_spc_explicit = bool(getattr(args, "split_shared_prefix_cache", False))
        self.shared_prefix_enabled = self._learn_spc_explicit
        self.shared_prefix_cache = (
            shared_prefix.SharedPrefixCache() if self.shared_prefix_enabled else None
        )
        self._learn_spc_override = None  # None=follow enabled/winner; True/False force
        if self.shared_prefix_enabled:
            log("split shared-prefix cache: on (flag/env)")
        # Idea 3 auto-pair / remap / shut-off (populated in _setup when lead).
        self.draft_remap_d2t = {}
        self.draft_remap_t2d = {}
        self.draft_path = None
        self.guess_pairing = None
        self.break_even_frac = 0.35
        self._chat_shutoffs = {}
        self._speculate_k_explicit = bool(getattr(args, "split_speculate_k_explicit", False))
        # ROADMAP #13b learn-from-chats state (filled in _setup / _learn_apply_startup).
        self._learn_enabled = not bool(getattr(args, "no_learn", False))
        # Day 15: reload options (kv_bits, fuse_kernels, keepalive) the web
        # launcher left on Auto. Empty = old behavior (not learned).
        self._learn_reload_auto = [
            n.strip() for n in str(getattr(args, "learn_reload_auto", "") or "").split(",")
            if n.strip() in ("kv_bits", "fuse_kernels", "keepalive")]
        self._learn_path = getattr(args, "tuned_settings", None)
        self._learn_store = None
        self._learn_entry = None
        self._learn_key = None
        self._learn_explicit = {}
        self._learn_guess_override = None  # None = follow draft_model; True/False force
        self._learn_n_layers = None
        self._learn_lock = threading.Lock()
        self._sweep_pause = bool(getattr(args, "sweep_paused", False))
        self._sweep_restore = None
        self._learn_trial = None
        self._learn_conc_window = []
        self.model_dir = Path(args.model).expanduser().resolve()
        ready = queue.Queue()
        self.thread = threading.Thread(target=self._main, args=(ready,), name="mlx", daemon=True)
        self.thread.start()
        err = ready.get()
        if err is not None:
            raise err

    def _setup(self):
        import importlib
        import mlx.core as mx
        # ROADMAP #17: fuse patches must run before mlx_lm model imports bind SDPA.
        try:
            import fuse_kernels as FK
            self._fuse_mode = FK.resolve_mode(getattr(self.args, "fuse_kernels", None))
            FK.apply_fuse_kernels(self._fuse_mode, log=log)
        except Exception as e:
            self._fuse_mode = "off"
            log(f"fuse kernels: skipped ({type(e).__name__}: {e})")
        # Caravan remaps (e.g. qwen3_5_text → qwen3_5) before any mlx_lm load.
        try:
            import os as _os, sys as _sys
            _proxy = _os.path.join(_os.path.dirname(_os.path.dirname(_os.path.abspath(__file__))), "proxy")
            if _proxy not in _sys.path:
                _sys.path.insert(0, _proxy)
            from mlx_arch import apply_mlx_lm_remaps
            apply_mlx_lm_remaps(log=log)
        except Exception as _e:
            log(f"model_type remap skipped: {_e!r}")
        from mlx_lm import load
        from mlx_lm.sample_utils import make_sampler, make_logits_processors
        G = importlib.import_module("mlx_lm.generate")
        args = self.args
        self.mx, self.G = mx, G
        self.make_sampler, self.make_logits_processors = make_sampler, make_logits_processors
        self.stream = mx.new_stream(mx.default_device())
        t0 = time.time()
        self.split = None           # v3: SplitSessions when this is the lead of a two-Mini split
                                    # (internally the lead is still role "head", Packer 1 "front")
        self.client = None
        role = getattr(args, "split_role", "none") or "none"
        if role == "head":
            import mlx_split as S
            from mlx_lm.utils import load_tokenizer
            cfg0 = json.loads((self.model_dir / "config.json").read_text())
            self.client = S.FrontClient(args.split_peer)
            if getattr(args, "split_keepalive", True):
                self.client.enable_gpu_keepalive(mx)
                log("lead GPU keepalive on (warms Metal while waiting for packer 1)")
            # ROADMAP #13a: auto packer layers when --split-packer-layers omitted.
            counts = S.parse_counts(getattr(args, "split_counts", None))
            if counts:
                S.plan_ranges(S.read_n_layers(self.model_dir), counts)
                args.split_front_layers = sum(counts[:-1])
            self._learn_packer_was_explicit = args.split_front_layers is not None
            if args.split_front_layers is None:
                hello0 = self.client.call("hello", proto=S.PROTO)[0]
                lead_total, lead_avail = S.host_memory_gb()
                pack_total = float(hello0.get("mem_total_gb") or lead_total)
                n_layers = int(hello0.get("n_layers") or S.read_n_layers(self.model_dir))
                mt = str(cfg0.get("model_type") or hello0.get("model_type") or "")
                k, reason = S.choose_packer_layers(n_layers, lead_total, pack_total, mt)
                pack_k = int((hello0.get("range") or [0, 0])[1] or 0)
                if pack_k and pack_k != k:
                    raise RuntimeError(
                        f"auto split wants packer_layers={k} ({reason}), but packer loaded K={pack_k}. "
                        f"Restart the packer without --split-packer-layers (or pass "
                        f"--split-packer-layers {k} on both).")
                args.split_front_layers = k
                log(f"auto split: packer_layers={k} ({reason})")
            # ROADMAP #13b: overlay saved/pending packer_layers BEFORE weights load.
            if self._learn_enabled and not self._learn_packer_was_explicit:
                try:
                    import tuned_settings as TS
                except ImportError:
                    import importlib
                    TS = importlib.import_module("tuned_settings")
                tpath = Path(self._learn_path).expanduser() if self._learn_path else None
                st = TS.load_store(tpath)
                key = TS.entry_key(self.model_dir, spanned=True)
                entry = (st.get("models") or {}).get(key) or {}
                winner_k = (entry.get("winner") or {}).get("packer_layers")
                pending = dict(entry.get("pending_reload") or {})
                pending_k = pending.get("packer_layers")
                chosen, why = None, None
                if pending_k is not None:
                    chosen, why = int(pending_k), "queued from last run"
                elif winner_k is not None:
                    chosen, why = int(winner_k), "saved winner for spanned"
                if chosen is not None and int(args.split_front_layers) != chosen:
                    hello_chk = self.client.call("hello", proto=S.PROTO)[0]
                    pack_k = int((hello_chk.get("range") or [0, 0])[1] or 0)
                    if pack_k and pack_k != chosen:
                        log(f"learn: want packer_layers={chosen} ({why}), packer has K={pack_k}; "
                            f"keeping loaded K={args.split_front_layers} "
                            f"(restart packer without --split-packer-layers to try {chosen})")
                    else:
                        log(f"learned split: packer_layers={chosen} ({why})")
                        args.split_front_layers = chosen
                        if pending_k is not None and key in (st.get("models") or {}):
                            # Consume pending so next load doesn't re-try forever.
                            st["models"][key].setdefault("pending_reload", {}).pop("packer_layers", None)
                            try:
                                TS.save_store(st, tpath)
                            except OSError:
                                pass
            self.stage = S.Stage(self.model_dir, "head", args.split_front_layers, counts, len(counts) - 1 if counts else None)
            self.model = S.SplitModel(self.stage, self.client)
            self.tokenizer = load_tokenizer(self.model_dir, eos_token_ids=cfg0.get("eos_token_id"))
            add_turn_end_stops(self.tokenizer, log=log)
            hello = self.client.call("hello", proto=S.PROTO)[0]
            expected = S.plan_ranges(self.stage.n_layers, counts)[:-1] if counts else None
            actual = [tuple(x["range"]) for x in hello.get("stages", [hello])]
            if ((expected is not None and actual != expected)
                    or hello.get("range") != [0, self.stage.range[0]]
                    or hello.get("n_layers") != self.stage.n_layers):
                raise RuntimeError(f"Packer 1 ({S.title_from_label(hello.get('stage'))}) doesn't match the lead "
                                   f"({S.stage_title('head', self.stage.range, self.stage.n_layers)})")
            log(f"split lead: {S.stage_title('head', self.stage.range, self.stage.n_layers)} here, "
                f"{S.title_from_label(hello.get('stage'))} at {args.split_peer}")
            # ROADMAP #13a: auto pipeline chat count when flag/env omitted.
            if self.pipeline_chats is None:
                total_gb, avail_gb = S.host_memory_gb()
                weights_gb = self.stage.nbytes() / 1e9
                n, reason = S.choose_pipeline_chats(
                    total_gb=total_gb, weights_gb=weights_gb, available_gb=avail_gb)
                self.pipeline_chats = n
                log(f"auto pipeline: chats={n} ({reason})")
            no_draft = bool(getattr(args, "no_split_draft", False))
            draft = getattr(args, "split_draft_model", None)
            if no_draft:
                draft = None
                log("split speculate: --no-split-draft; auto-pair off")
            dpath = None
            pairing = None
            if draft:
                dpath = Path(draft).expanduser().resolve()
                if not dpath.is_dir():
                    raise FileNotFoundError(f"split draft model not found: {dpath}")
                pairing = guess_ahead.find_pairing(self.model_dir)
                if pairing and pairing.get("skip"):
                    pairing = None
            elif not no_draft:
                pairing = guess_ahead.find_pairing(self.model_dir)
                if pairing and pairing.get("skip"):
                    log(f"split speculate: no pairing ({pairing.get('reason')})")
                    pairing = None
                elif pairing:
                    cand = guess_ahead.drafts_dir() / pairing["draft"]["name"]
                    if cand.is_dir() and (cand / "config.json").is_file():
                        dpath = cand.resolve()
                        log(f"split speculate: auto-pair {pairing['id']} -> {dpath.name}")
                    else:
                        auto = bool(getattr(args, "split_draft_auto_download", False))
                        if guess_ahead.ask_download(pairing, auto=auto, model_label=self.model_dir.name):
                            dpath = guess_ahead.download_draft(pairing).resolve()
                            log(f"split speculate: downloaded helper {dpath.name}")
                        else:
                            log("split speculate: helper download declined; baseline")
                            pairing = None
            if dpath is not None:
                vocab = guess_ahead.build_vocab_maps(self.model_dir, dpath)
                if not vocab.get("ok"):
                    log(f"split speculate: vocab mismatch ({vocab.get('reason')}); skipping draft")
                    dpath = None
                    pairing = None
                else:
                    self.draft_model, self.draft_tokenizer = load(str(dpath))
                    self.draft_path = dpath
                    self.draft_remap_d2t = {int(k): int(v) for k, v in (vocab.get("remap_draft_to_target") or {}).items()}
                    self.draft_remap_t2d = {int(k): int(v) for k, v in (vocab.get("remap_target_to_draft") or {}).items()}
                    self.guess_pairing = pairing
                    if pairing and not self._speculate_k_explicit:
                        self.speculate_k = int(pairing["draft"].get("k") or self.speculate_k)
                    log(f"split speculate: draft {dpath.name}, k={self.speculate_k}, "
                        f"vocab={vocab.get('mode')} remap={vocab.get('n_remap', 0)} "
                        f"(idea 3 guess-ahead)")
            if self.prompt_lookup_n:
                log(f"split speculate: prompt-lookup n={self.prompt_lookup_n}, "
                    f"k={self.speculate_k} (idea 3 draft-free)")
            if self.prompt_lookup_adaptive and self.prompt_lookup_n:
                log(f"split speculate: prompt-lookup adaptive on (n={self.prompt_lookup_n})")
        else:
            self._learn_packer_was_explicit = getattr(args, "split_front_layers", None) is not None
            self.model, self.tokenizer = load(str(self.model_dir))
            try:
                from mlx_arch import fix_rope_scaling
                import json as _json
                fix_rope_scaling(self.model, _json.loads((self.model_dir / "config.json").read_text()), log=log)
            except Exception as _e:
                log(f"rope scaling patch skipped: {_e!r}")
            add_turn_end_stops(self.tokenizer, log=log)
        if getattr(args, "native_mtp", False):
            if getattr(args, "kv_bits", None):
                raise ValueError("native MTP experiment uses uncompressed caches only")
            if self.client is not None:
                raise ValueError("native MTP experiment is single-Mini only")
            from native_mtp import load_head
            self.native_mtp = load_head(self.model_dir, self.model)
            log("native MTP: matching Qwen3.5 head loaded (experimental, greedy only)")
        cfg = json.loads((self.model_dir / "config.json").read_text())
        self.model_type = cfg.get("model_type", "")
        self.wired_mode = getattr(args, "wired_limit", "startup")
        from mlx_lm.utils import maybe_set_recommended_wired_limit
        self.wired = apply_startup_wiring(self.wired_mode, mx, maybe_set_recommended_wired_limit)
        if self.wired:
            log(f"wired limit {self.wired[0]} -> {self.wired[1]} bytes (held for process lifetime)")
        else:
            log(f"wired limit mode {self.wired_mode}: not set at startup")
        if args.cache_limit_gb is not None and args.cache_limit_gb > 0:
            mx.set_cache_limit(int(args.cache_limit_gb * (1 << 30)))
            log(f"mlx cache_limit {args.cache_limit_gb} GB")
        if getattr(args, "memory_limit_gb", None):
            try:
                mx.set_memory_limit(int(float(args.memory_limit_gb) * (1 << 30)))
                log(f"mlx memory_limit {args.memory_limit_gb} GB")
            except Exception as e:
                log(f"mlx memory_limit skipped: {e!r}")
        self.memory_safety_gb = float(getattr(args, "memory_safety_gb", 1.75) if getattr(args, "memory_safety_gb", None) is not None else 1.75)
        import memory_notes as _MN
        self.memory_dir = Path(getattr(args, "memory_dir", None) or _MN.default_memory_dir()).expanduser()
        self.model_cfg = cfg
        self.prefill_step = int(args.prefill_step_size)
        self.default_max_tokens = int(args.max_tokens)
        ident = {"model": str(self.model_dir), "tokenizer": tokenizer_hash(self.model_dir),
                 "mlx_lm": _version("mlx_lm"), "model_type": self.model_type,
                 "kv_bits": args.kv_bits or 0}
        if self.client is not None:
            import mlx_split as S
            ident["stage"] = S.stage_label("head", self.stage.range, self.stage.n_layers)
        self.store = SessionStore(MlxOps(self.model, args.kv_bits, args.kv_group_size), args.cache_dir, ident,
                                  max_sessions=args.prompt_cache_size,
                                  max_bytes=args.prompt_cache_bytes,
                                  persist=not args.no_persist)
        if self.client is not None:
            self.split = S.SplitSessions(self.store, self.client, log=log)
        # Warm-up: the first forward pass in a fresh process pays one-off
        # kernel/weight-paging costs (~1-2.5 s here); pay them at startup
        # instead of on the first resumed turn.
        tw = time.time()
        if self.split:
            self.model.begin_scratch()
        with mx.stream(self.stream):
            c = self.store.ops.new_cache()
            self.model(mx.array([[int(self.tokenizer.encode("Hi")[-1])] * 16]), cache=c)
            mx.eval([x.state for x in c])
            del c
            mx.clear_cache()
        if self.split:
            self.model.end_scratch()
        self.warmup_s = time.time() - tw
        log(f"warm-up {self.warmup_s:.2f}s")
        if (self.draft_model is not None and self.draft_path is not None
                and not bool(getattr(args, "split_draft_skip_first_load", False))):
            self._first_load_gate(self.draft_path, self.guess_pairing)
        log(f"loaded {self.model_dir.name} ({self.model_type}) in {time.time() - t0:.1f}s; "
            f"sessions<= {self.store.max_sessions}, bytes<= {args.prompt_cache_bytes}, "
            f"prefill step {self.prefill_step}, kv bits {args.kv_bits or 16}, persist="
            + (f"on {self.store.cache_dir}" if self.store.persist else "off"))
        # Non-split (or unresolved) auto → serial one chat.
        # Must run before learn startup so single-Mini seeds winner pipeline_chats=1.
        if self.pipeline_chats is None:
            self.pipeline_chats = 1
        # ROADMAP #13b: overlay saved per-model winners (flags still win).
        self._learn_apply_startup()
        try:
            log("active settings: " + json.dumps(self.active_settings(), sort_keys=True))
        except Exception as e:
            log(f"active settings: unavailable ({e!r})")


    def _shared_prefix_on(self) -> bool:
        if self._learn_spc_override is not None:
            return bool(self._learn_spc_override)
        return bool(getattr(self, "shared_prefix_enabled", False))

    def _set_shared_prefix(self, enabled: bool, *, reason: str = "") -> None:
        """Flip shared-prefix cache on/off live (Day 13 learn)."""
        want = bool(enabled)
        cur = bool(getattr(self, "shared_prefix_enabled", False))
        self._learn_spc_override = want
        self.shared_prefix_enabled = want
        if want and self.shared_prefix_cache is None:
            self.shared_prefix_cache = shared_prefix.SharedPrefixCache()
        if want != cur:
            log(f"learn: shared-prefix {'on' if want else 'off'}"
                + (f" ({reason})" if reason else ""))

    def _learn_apply_startup(self):
        """ROADMAP #13b: start from saved winners when flags didn't pin a value."""
        if not self._learn_enabled:
            return
        try:
            import tuned_settings as TS
        except ImportError:
            import importlib
            TS = importlib.import_module("tuned_settings")
        spanned = self.client is not None
        explicit = {}
        if self._pipeline_chats_explicit:
            explicit["pipeline_chats"] = self.pipeline_chats
        # Packer layers already applied (or kept) before weight load; treat as pinned
        # for this process so resolve_startup only handles live settings here.
        # Only pin packer_layers when the user passed the flag — Day 9 auto
        # also writes args.split_front_layers, and that must stay learnable.
        if getattr(self, "_learn_packer_was_explicit", False) and not getattr(self.args, "sweep_paused", False):
            explicit["packer_layers"] = int(self.args.split_front_layers)
        if bool(getattr(self.args, "no_split_draft", False)):
            explicit["guess_ahead"] = False
        if getattr(self, "_learn_spc_explicit", False):
            explicit["shared_prefix"] = True
        if bool(getattr(self.args, "no_split_shared_prefix_cache", False)):
            explicit["shared_prefix"] = False
        if bool(getattr(self.args, "pin_guess_ahead", False)) and self.draft_model is not None:
            explicit["guess_ahead"] = True
            self._learn_guess_override = True
        day9_k = getattr(self.args, "split_front_layers", None)
        day9_n = self.pipeline_chats
        day9_g = True if self.draft_model is not None else (
            False if bool(getattr(self.args, "no_split_draft", False)) else None)
        n_layers = None
        if hasattr(self, "stage") and self.stage is not None:
            n_layers = getattr(self.stage, "n_layers", None)
            self._learn_n_layers = n_layers
        # Detect whether packer layers came from CLI: args keep the value either way.
        # We stash before auto in _setup; if missing, treat as not explicit.
        if not hasattr(self, "_learn_packer_was_explicit"):
            # Reconstruct: AutoTune only runs when initially None; we set a marker there.
            self._learn_packer_was_explicit = False
        path = Path(self._learn_path).expanduser() if self._learn_path else None
        r = TS.resolve_startup(
            model_dir=self.model_dir, spanned=spanned,
            day9_packer_layers=int(day9_k) if day9_k is not None else None,
            day9_pipeline_chats=int(day9_n) if day9_n is not None else None,
            day9_guess_ahead=day9_g,
            day9_shared_prefix=False,
            explicit=explicit,
            path=path,
            n_layers=n_layers,
        )
        self._learn_store = r["store"]
        self._learn_entry = r["entry"]
        self._learn_key = r["key"]
        self._learn_explicit = dict(explicit)
        # Single Mini: only width 1 exists; don't explore 2.
        if not spanned and "pipeline_chats" not in self._learn_explicit:
            self._learn_explicit["pipeline_chats"] = 1
            self.pipeline_chats = 1
            w = (self._learn_entry.setdefault("winner", {}))
            w["pipeline_chats"] = 1
        # Apply pipeline chats from learned winner when not flagged.
        if "pipeline_chats" not in explicit and r["pipeline_chats"] is not None:
            if self.pipeline_chats != int(r["pipeline_chats"]):
                self.pipeline_chats = int(r["pipeline_chats"])
        # Guess-ahead: only force-off/on when we have a draft available or an explicit off.
        if "guess_ahead" not in explicit and r["guess_ahead"] is not None:
            want = bool(r["guess_ahead"])
            if not want and self.draft_model is not None:
                self._learn_guess_override = False
            elif want:
                self._learn_guess_override = True
        # Shared-prefix: apply learned winner (or stay off) unless flag pinned it.
        if "shared_prefix" not in explicit and r.get("shared_prefix") is not None:
            self._set_shared_prefix(bool(r["shared_prefix"]), reason="startup winner")
        for line in r["reasons"]:
            if line.startswith("learned") or line.startswith("try split") or line.startswith("flag"):
                log(line)
            elif "saved winner" in line or "queued" in line:
                log(line)
        # Persist seeded winner so a crash still remembers the Day 9 starting point.
        try:
            TS.save_store(self._learn_store, path)
        except OSError as e:
            log(f"learn: could not save tuned settings ({e!r})")

    def active_settings(self, info=None) -> dict:
        """Day 15: what was actually in effect (per reply when info is given)."""
        a = self.args
        try:
            import fuse_kernels as FK
            fuse = FK.resolve_mode(getattr(a, "fuse_kernels", None))
        except Exception:
            fuse = str(getattr(a, "fuse_kernels", None) or "off")
        spec = (info or {}).get("speculate")
        out = {
            "guess_ahead": (bool(spec) if info is not None
                            else (self.native_mtp is not None or (self.client is not None and self.draft_model is not None
                                  and self._learn_guess_override is not False))),
            "guess_ahead_loaded": self.draft_model is not None or self.native_mtp is not None,
            "native_mtp_available": self.native_mtp is not None,
            "guess_ahead_mode": "native_mtp" if self.native_mtp is not None else "helper",
            "prompt_lookup": {"enabled": bool(self.prompt_lookup_n),
                              "adaptive": bool(self.prompt_lookup_adaptive), "overlap_on": 0.50},
            "multi_token_verify": "experimental · split draft blocks; Qwen N2 tested, helper slower",
            "two_chats_available": self.client is not None,
            "self_tune": bool(self._learn_enabled),
            "shared_start": bool(self._shared_prefix_on()),
            "pipeline_chats": self.pipeline_chats,
            "fuse_kernels": fuse,
            "kv_bits": int(getattr(a, "kv_bits", None) or 16),
            "keepalive": bool(getattr(a, "split_keepalive", False)) if self.client is not None else None,
            "pinned": sorted(k for k in (self._learn_explicit or {})
                             if k in ("guess_ahead", "shared_prefix", "pipeline_chats")),
            "sweep_paused": bool(getattr(self, "_sweep_pause", False)),
            "packer_layers": getattr(a, "split_front_layers", None),
            "n_layers": getattr(self, "_learn_n_layers", None),
            "reload_auto": list(self._learn_reload_auto or []),
            "reload_trial": dict((self._learn_entry or {}).get("reload_trial") or {}) or None,
        }
        if spec:
            out["guess_ahead_from_draft"] = spec.get("from_draft")
        return out

    def _learn_guess_ahead_on(self):
        if self._learn_guess_override is not None:
            return bool(self._learn_guess_override)
        return self.draft_model is not None

    def _learn_observe(self, info: dict):
        """Record one finished reply; maybe promote a winner or explore next.

        pipeline_chats is NOT scored from single-chat decode tok/s (N=1 and N=2
        look the same alone). Concurrent completions feed record_pipeline_probe()
        with aggregate tok/s; near-back-to-back serial completions (N=1) do too.
        Explore trials are temporary: after trial_replies we restore the winner.
        """
        if getattr(self, "_sweep_pause", False):
            return
        if not self._learn_enabled or self._learn_entry is None or not info:
            return
        try:
            import tuned_settings as TS
        except ImportError:
            import importlib
            TS = importlib.import_module("tuned_settings")
        settings_used = {
            "pipeline_chats": self.pipeline_chats,
            "guess_ahead": self._learn_guess_ahead_on() if self.client is not None else None,
            "packer_layers": getattr(self.args, "split_front_layers", None),
            "shared_prefix": self._shared_prefix_on() if self.client is not None else None,
        }
        with self._learn_lock:
            if getattr(self, "_sweep_pause", False):
                return
            out = TS.observe_reply(
                self._learn_entry,
                settings_used=settings_used,
                completion_tokens=int(info.get("completion_tokens") or 0),
                total_s=float(info.get("total_s") or 0.0),
                prefill_s=float(info.get("prefill_s") or 0.0),
                prompt_tokens=int(info.get("prompt_tokens") or 0),
                explicit=self._learn_explicit,
                n_layers=self._learn_n_layers,
            )
            # Day 15: score reload options and finish / queue reload trials.
            rl_out = None
            if self._learn_reload_auto:
                try:
                    fuse_on = str(getattr(self, "_fuse_mode", "off") or "off") != "off"
                    rl_out = TS.observe_reload(
                        self._learn_entry,
                        settings_used={
                            "kv_bits": int(getattr(self.args, "kv_bits", None) or 16),
                            "fuse_kernels": "on" if fuse_on else "off",
                            "keepalive": bool(getattr(self.args, "split_keepalive", False)),
                        },
                        norm_tps=out["norm_tps"], auto_names=self._learn_reload_auto)
                    for reason in rl_out.get("reasons") or []:
                        log(f"learn: {reason}")
                except Exception as e:  # never break a reply over learning
                    log(f"learn: reload scoring skipped ({type(e).__name__}: {e})")
            # Day 13: score shared-prefix by TTFT on long new chats (not decode tok/s).
            sp_out = None
            if (self.client is not None
                    and "shared_prefix" not in (self._learn_explicit or {})
                    and settings_used.get("shared_prefix") is not None):
                sp_out = TS.record_shared_prefix_probe(
                    self._learn_entry,
                    enabled=bool(settings_used["shared_prefix"]),
                    ttft_s=float(info.get("ttft_s") or 0.0),
                    how=str(info.get("how") or ""),
                    prompt_tokens=int(info.get("prompt_tokens") or 0),
                    cached_tokens=int(info.get("cached_tokens") or 0),
                )
                for name, val, reason in sp_out.get("promotions") or []:
                    log(f"learn: {reason}")
                    if name == "shared_prefix":
                        self._set_shared_prefix(bool(val), reason="promoted")
                for reason in (sp_out.get("keep_reasons") or [])[:1]:
                    log(f"learn: {reason}")
            # Single Mini: no concurrent pipe. Still record decode tok/s under
            # pipeline_chats=1 even though width is pinned (explicit would skip).
            if self.client is None and "pipeline_chats" not in (self._learn_explicit or {}):
                pass  # observe_reply already recorded if not pinned
            elif self.client is None:
                TS.record_sample(self._learn_entry, "pipeline_chats", 1, out["norm_tps"])
            # Window of recent replies for pipeline_chats scoring.
            now = time.time()
            total_s = float(info.get("total_s") or 0.0)
            start = float(info["t0"]) if info.get("t0") is not None else (now - total_s)
            end = start + total_s if info.get("t0") is not None else now
            if end > now + 0.05:
                end = now
            if not hasattr(self, "_learn_conc_window"):
                self._learn_conc_window = []
            self._learn_conc_window = [
                w for w in self._learn_conc_window if now - w["end"] < 4.0
            ]
            self._learn_conc_window.append({
                "start": start,
                "end": end,
                "ct": int(info.get("completion_tokens") or 0),
                "total_s": total_s,
                "n": int(self.pipeline_chats or 1),
            })
            pipe_out = None
            agg = None
            n_used = None
            if ("pipeline_chats" not in self._learn_explicit
                    and self.client is not None
                    and len(self._learn_conc_window) >= 2):
                # Prefer true overlaps (concurrent N>=2). Else score a serial
                # pair (typical when exploring pipeline_chats=1).
                overlapped = []
                for w in self._learn_conc_window:
                    if any(w["start"] < o["end"] and o["start"] < w["end"] and w is not o
                           for o in self._learn_conc_window):
                        overlapped.append(w)
                same = []
                if len(overlapped) >= 2:
                    n_used = int(overlapped[-1]["n"])
                    same = [w for w in overlapped if int(w["n"]) == n_used]
                if len(same) < 2:
                    # Serial burst only scores pipeline_chats=1 (two requests
                    # that had to wait on each other). Never treat sequential
                    # singles at N>=2 as a concurrent probe — that would fake
                    # samples for the Day 9 guess without exercising the pipe.
                    a, b = self._learn_conc_window[-2], self._learn_conc_window[-1]
                    if (int(a["n"]) == int(b["n"]) == 1
                            and not (a["start"] < b["end"] and b["start"] < a["end"])
                            and b["start"] - a["end"] < 1.5):
                        n_used = 1
                        same = [a, b]
                if len(same) >= 2 and n_used is not None:
                    wall0 = min(w["start"] for w in same)
                    wall1 = max(w["end"] for w in same)
                    wall = max(0.001, wall1 - wall0)
                    toks = sum(w["ct"] for w in same)
                    agg = toks / wall
                    pipe_out = TS.record_pipeline_probe(
                        self._learn_entry, n_chats=n_used, aggregate_tps=agg,
                        explicit=self._learn_explicit)
                    for name, val, reason in pipe_out.get("promotions") or []:
                        log(f"learn: {reason}")
                        if name == "pipeline_chats":
                            self.pipeline_chats = max(1, int(val))
                    for reason in (pipe_out.get("keep_reasons") or [])[:1]:
                        log(f"learn: {reason}")
                    self._learn_conc_window = [
                        w for w in self._learn_conc_window if w not in same
                    ]

            for name, val, reason in out.get("promotions") or []:
                log(f"learn: {reason}")
                if name == "pipeline_chats":
                    self.pipeline_chats = max(1, int(val))
            for reason in (out.get("keep_reasons") or [])[:1]:
                log(f"learn: {reason}")

            # Tick down an explore trial; restore the winner when it ends so we
            # don't get stuck on a challenger that never earned promotion.
            trial = getattr(self, "_learn_trial", None)
            if trial:
                trial["remaining"] = int(trial.get("remaining") or 0) - 1
                if trial["remaining"] <= 0:
                    w = dict((self._learn_entry or {}).get("winner") or {})
                    if trial.get("name") == "pipeline_chats" and "pipeline_chats" in w:
                        self.pipeline_chats = max(1, int(w["pipeline_chats"]))
                        log(f"learn: end trial pipeline_chats={trial.get('value')}; "
                            f"back to winner pipeline_chats={self.pipeline_chats}")
                    elif trial.get("name") == "guess_ahead" and "guess_ahead" in w:
                        self._learn_guess_override = bool(w["guess_ahead"])
                        log(f"learn: end trial guess_ahead; back to winner "
                            f"guess_ahead={self._learn_guess_override}")
                    elif trial.get("name") == "shared_prefix" and "shared_prefix" in w:
                        self._set_shared_prefix(bool(w["shared_prefix"]),
                                               reason="end trial; back to winner")
                    self._learn_trial = None

            explore = out.get("explore")
            if explore and not getattr(self, "_learn_trial", None):
                name, val = explore["name"], explore["value"]
                log(f"learn: {explore['reason']}")
                if not explore.get("deferred"):
                    if name == "pipeline_chats" and "pipeline_chats" not in self._learn_explicit:
                        self.pipeline_chats = max(1, int(val))
                        self._learn_trial = {
                            "name": name, "value": val,
                            "remaining": int(explore.get("trial_replies") or TS.MIN_SAMPLES),
                        }
                    elif name == "guess_ahead" and "guess_ahead" not in self._learn_explicit:
                        self._learn_guess_override = bool(val)
                        self._learn_trial = {
                            "name": name, "value": val,
                            "remaining": int(explore.get("trial_replies") or TS.MIN_SAMPLES),
                        }
                    elif name == "shared_prefix" and "shared_prefix" not in self._learn_explicit:
                        self._set_shared_prefix(bool(val), reason=explore.get("reason") or "trial")
                        self._learn_trial = {
                            "name": name, "value": val,
                            "remaining": int(explore.get("trial_replies")
                                             or TS.SHARED_PREFIX_TRIAL_REPLIES),
                        }
            path = Path(self._learn_path).expanduser() if self._learn_path else None
            try:
                TS.save_store(self._learn_store, path)
            except OSError as e:
                log(f"learn: save failed ({e!r})")
            winner = dict((pipe_out or {}).get("winner") or out.get("winner") or {})
            if sp_out and sp_out.get("winner"):
                winner.update(sp_out["winner"])
            self._last_learn = {
                "norm_tps": round(out["norm_tps"], 3),
                "winner": winner,
                "explore": ({"name": explore["name"], "value": explore["value"]}
                            if explore else None),
                "pipeline_probe": (
                    {"aggregate_tps": round(agg, 3), "n": n_used}
                    if pipe_out is not None else None),
                "shared_prefix_probe": (
                    {"recorded": sp_out.get("recorded"), "kind": sp_out.get("kind")}
                    if sp_out is not None else None),
                "trial": (dict(self._learn_trial) if getattr(self, "_learn_trial", None) else None),
            }

    def _main(self, ready):
        try:
            self._setup()
        except BaseException as e:
            ready.put(e)
            return
        ready.put(None)
        # Single-Mini (no client) stays serial (_run).
        # Spanned: N=1 uses _run so guess-ahead/PL work (pipeline decode is
        # single-token). N>=2 uses the pipeline loop; Day 12 wires speculate
        # into _pipe_lead_sample when a draft/PL is loaded.
        if self.pipeline_chats is None or int(self.pipeline_chats) < 1:
            self.pipeline_chats = 1
        use_pipeline = self.client is not None and int(self.pipeline_chats) >= 2
        if not use_pipeline:
            if self.client is not None:
                log(f"split pipeline chats=1 (serial _run; guess-ahead/PL enabled)")
            while True:
                job = self.jobs.get()
                if job is None:
                    return
                kind, payload, out = job
                if kind in ("call", "read"):
                    try:
                        out.put(("ok", payload()))
                    except BaseException as e:
                        out.put(("err", e))
                else:
                    key, prompt, body, cancel = payload
                    try:
                        for ev in self._run(key, prompt, body, cancel):
                            out.put(ev)
                    except BaseException as e:
                        out.put(("error", e))
                    out.put(None)
        else:
            log(f"split pipeline chats={self.pipeline_chats} (idea 1; overlap packer/lead across sessions)")
            self._main_pipeline()


    def _spc_reserved_key(self, pkey: str) -> str:
        # Fits KEY_RE: A-Za-z0-9_- {1,64}
        k = f"spc_{pkey}"
        return k[:64]

    def _clone_lead_session(self, src_key: str, dst_key: str):
        src = self.store.sessions.get(src_key)
        if src is None:
            raise RuntimeError(f"shared-prefix: missing lead src {src_key}")
        ops = self.store.ops
        new_cache = [ops.from_snapshot(ops.snapshot(c)) for c in src.cache]
        dst = self.store.sessions.get(dst_key)
        if dst is None:
            dst = Session(dst_key, new_cache)
            self.store.sessions[dst_key] = dst
        else:
            dst.cache = new_cache
        self.store.checkpoint(dst, src.tokens)
        dst.dirty = True
        return dst

    def _prepare_with_shared_prefix(self, key, prompt):
        """Like s_prepare, but seed from shared-prefix library on cold start."""
        spc = getattr(self, "shared_prefix_cache", None)
        if spc is None or not getattr(self, "shared_prefix_enabled", False):
            return self.s_prepare(key, prompt)
        # Only help brand-new sessions (not mid-chat continuation).
        store = self.store
        existing = store.sessions.get(key)
        if existing is not None and existing.tokens:
            return self.s_prepare(key, prompt)
        n, ent = spc.lookup(prompt)
        if not ent or n <= 0:
            return self.s_prepare(key, prompt)
        reserved = self._spc_reserved_key(ent.key)
        src = store.sessions.get(reserved)
        if src is None or len(src.tokens) != int(ent.n_tokens):
            spc.misses += 1  # library entry stale / lead half missing
            return self.s_prepare(key, prompt)
        try:
            # Day 13: require packer reserved length to match before seeding,
            # otherwise SplitSessions.prepare would split-resync to cold.
            if self.client is not None:
                fr = self.client.call("prepare", key=reserved,
                                      prompt=list(src.tokens) + [0])[0]
                pn = int(fr.get("n") or -1) if not fr.get("error") else -1
                if pn != int(ent.n_tokens):
                    log(f"shared-prefix packer reserved n={pn} want={ent.n_tokens}; cold")
                    spc.misses += 1
                    return self.s_prepare(key, prompt)
            self._clone_lead_session(reserved, key)
            if self.client is not None:
                fr = self.client.call("clone_to", src=reserved, dst=key)[0]
                if fr.get("error"):
                    log(f"shared-prefix packer clone failed: {fr.get('error')}")
                    store.drop([key])
                    return self.s_prepare(key, prompt)
            s, n2, how = self.s_prepare(key, prompt)
            how = f"shared-prefix-{how}"
            log(f"shared-prefix hit n={n2} key={reserved} -> {key}")
            return s, n2, how
        except Exception as e:
            log(f"shared-prefix seed failed: {type(e).__name__}: {e}")
            return self.s_prepare(key, prompt)

    def _agent_prefix_key(self, prompt, body):
        n = int(body.get("_caravan_agent_prefix") or 0)
        if not 1024 <= n < len(prompt):
            return None, 0
        return "agent_" + shared_prefix.prefix_key(prompt, n), n

    def _prepare_agent_prefix(self, key, prompt, body):
        """Reuse an exact pre-user checkpoint, including recurrent state.

        No arbitrary rewind of hybrid/recurrent layers. The prefix is captured
        DURING prefill; each stage keeps its own copy and disk file. Existing
        per-conversation LCP reuse takes precedence when it is longer.
        """
        key = key if valid_key(key) else ANON
        s, reused, how = self._prepare_with_shared_prefix(key, prompt)
        reserved, n = self._agent_prefix_key(prompt, body)
        if reserved is None or reused >= n or key == reserved:
            return s, reused, how
        try:
            owner = self.split or self.store
            owner.restore(reserved)  # digest-paired restore across the entire chain
            src = self.store.sessions.get(reserved)
            if src is None or src.tokens != list(prompt[:n]):
                return self.s_prepare(key, prompt)
            if self.client is not None:
                fr = self.client.call("clone_to", src=reserved, dst=key)[0]
                if fr.get("error") or fr.get("n") != n:
                    raise RuntimeError(f"prefix clone refused: {fr}")
            self._clone_lead_session(reserved, key)
            s, reused, how = self.s_prepare(key, prompt)
            log(f"agent-prefix hit {n} tokens -> {key}")
            return s, reused, "agent-prefix-" + how
        except Exception as e:
            log(f"agent-prefix seed rejected ({type(e).__name__}: {e}); cold")
            (self.split or self.store).drop([key])
            return self.s_prepare(key, prompt)

    def _store_agent_prefix(self, key, prompt, body, session):
        key = session.key
        reserved, n = self._agent_prefix_key(prompt, body)
        if reserved is None or len(session.tokens) != n:
            return
        if reserved in self.store.sessions:
            return
        try:
            if self.client is not None:
                fr = self.client.call("clone_to", src=key, dst=reserved)[0]
                if fr.get("error") or fr.get("n") != n:
                    raise RuntimeError(f"prefix checkpoint refused: {fr}")
            self._clone_lead_session(key, reserved)
            result = (self.split or self.store).save(reserved)
            log(f"agent-prefix stored {n} tokens ({result})")
        except Exception as e:
            log(f"agent-prefix store skipped ({type(e).__name__}: {e})")
            (self.split or self.store).drop([reserved])

    def _prefill_chunks(self, prompt, start, body):
        """Split a normal prefill chunk at the exact reusable boundary."""
        _, boundary = self._agent_prefix_key(prompt, body)
        end = len(prompt) - 1
        while start < end:
            stop = min(start + self.prefill_step, end)
            if start < boundary < stop:
                stop = boundary
            yield start, stop, stop == boundary
            start = stop

    def _can_trim_session(self, session, drop: int) -> bool:
        """True if every layer can drop `drop` tokens (sliding-window may refuse)."""
        if drop <= 0:
            return True
        ops = self.store.ops
        for c in session.cache:
            if ops.always_trimmable(c):
                continue
            if not c_trimmable(ops, c):
                return False
        return True

    def _trim_session_to(self, session, target_n: int) -> bool:
        """Trim lead-side session tokens+KV to target_n. False if not trimmable."""
        drop = len(session.tokens) - int(target_n)
        if drop < 0:
            return False
        if drop == 0:
            return True
        if not self._can_trim_session(session, drop):
            return False
        for c in session.cache:
            self.store.ops.trim(c, drop)
        session.tokens = session.tokens[:target_n]
        session.snaps = None
        return True

    def _materialize_shared_prefix(self, reserved: str, tokens: list) -> bool:
        """Cold-prefill `tokens` into reserved on lead (+ packer if split).

        Used when clone+trim is unsafe (Gemma/GPT-OSS sliding-window layers have
        wrapped). Returns True when both halves end with exactly len(tokens).
        """
        if not tokens:
            return False
        self.store.drop([reserved])
        if self.client is not None:
            try:
                self.client.call("drop", keys=[reserved])
            except Exception as e:
                log(f"shared-prefix materialize packer drop: {e}")
        pad = list(tokens) + [0]
        old_key = getattr(self.model, "session_key", None) if hasattr(self, "model") else None
        try:
            s, n, how = self.s_prepare(reserved, pad)
            if n != 0:
                self.s_reset(s)
                s, n, how = self.s_prepare(reserved, pad)
            if n != 0:
                log(f"shared-prefix materialize expected cold, got n={n} how={how}")
                return False
            if self.client is not None and hasattr(self.model, "session_key"):
                self.model.session_key = reserved
            mx = self.mx
            with request_wiring(self.wired_mode, self.G, self.model, self.stream):
                with mx.stream(self.stream):
                    for i in range(0, len(tokens), self.prefill_step):
                        chunk = mx.array(tokens[i:i + self.prefill_step])
                        self.model(chunk[None], cache=s.cache)
                        mx.eval([c.state for c in s.cache])
                        mx.clear_cache()
            self.s_checkpoint(s, tokens)
            if self.client is not None:
                fr = self.client.call("prepare", key=reserved, prompt=pad)[0]
                if fr.get("error"):
                    log(f"shared-prefix materialize packer check: {fr.get('error')}")
                    return False
                if int(fr.get("n") or -1) != len(tokens):
                    log(f"shared-prefix materialize packer n={fr.get('n')} want={len(tokens)}")
                    return False
            return True
        except Exception as e:
            log(f"shared-prefix materialize failed: {type(e).__name__}: {e}")
            return False
        finally:
            if old_key is not None and hasattr(self, "model") and hasattr(self.model, "session_key"):
                self.model.session_key = old_key

    def _maybe_store_shared_prefix(self, key, prompt, session):
        spc = getattr(self, "shared_prefix_cache", None)
        if spc is None or not getattr(self, "shared_prefix_enabled", False):
            return
        if session is None or not session.tokens:
            return
        # Store longest eligible length that is fully inside the checkpointed prompt.
        n_tok = len(session.tokens)
        candidates = [n for n in spc.lengths if spc.min_tokens <= n <= n_tok]
        if not candidates:
            return
        n = max(candidates)
        # Only store if prompt actually starts with these tokens
        if list(prompt[:n]) != list(session.tokens[:n]):
            return
        pkey = shared_prefix.prefix_key(prompt, n)
        reserved = self._spc_reserved_key(pkey)
        if reserved in self.store.sessions and spc.entries.get(pkey):
            return  # already have it
        try:
            n_store = min(n, len(session.tokens))
            if n_store < spc.min_tokens:
                return
            # Clone full session to reserved on both halves, then either trim
            # (plain KV) or re-prefill the prefix (sliding-window wrapped).
            self._clone_lead_session(key, reserved)
            if self.client is not None:
                fr = self.client.call("clone_to", src=key, dst=reserved)[0]
                if fr.get("error"):
                    log(f"shared-prefix packer store clone failed: {fr.get('error')}")
                    self.store.drop([reserved])
                    return
            rs = self.store.sessions[reserved]
            drop = len(rs.tokens) - n_store
            path = "exact"
            if drop > 0 and self._can_trim_session(rs, drop):
                if not self._trim_session_to(rs, n_store):
                    path = "materialize"
                else:
                    path = "trim"
                    if self.client is not None:
                        fr = self.client.call("trim_to", key=reserved, n=n_store)[0]
                        if fr.get("error") or int(fr.get("n") or -1) != n_store:
                            log(f"shared-prefix packer trim_to failed: {fr!r}; materializing")
                            path = "materialize"
            elif drop > 0:
                path = "materialize"
            if path == "materialize":
                if not self._materialize_shared_prefix(reserved, list(prompt[:n_store])):
                    self.store.drop([reserved])
                    if self.client is not None:
                        try:
                            self.client.call("drop", keys=[reserved])
                        except Exception:
                            pass
                    return
                rs = self.store.sessions.get(reserved)
                if rs is None or len(rs.tokens) != n_store:
                    log(f"shared-prefix materialize missing reserved n={None if rs is None else len(rs.tokens)}")
                    return
            nbytes = self.store.ops.nbytes(rs.cache)
            spc.store(prompt, n_store, lead_snaps=None, nbytes=nbytes)
            log(f"shared-prefix stored n={n_store} reserved={reserved} bytes={nbytes} via={path}")
        except Exception as e:
            log(f"shared-prefix store failed: {type(e).__name__}: {e}")

    # -- session ops: local store, or both halves of a split ---------------
    def s_prepare(self, key, prompt):
        return self.split.prepare(key, prompt) if self.split else self.store.prepare(key, prompt)

    def s_checkpoint(self, s, tokens):
        (self.split or self.store).checkpoint(s, tokens)

    def s_rewind(self, s, completed=True):
        (self.split or self.store).rewind(s, completed=completed)

    def s_reset(self, s):
        (self.split or self.store).reset(s)

    def s_save(self, key):
        return (self.split or self.store).save(key)

    def s_restore(self, key):
        return (self.split or self.store).restore(key)

    def s_drop(self, keys):
        return (self.split or self.store).drop(keys)

    def s_flush(self):
        return (self.split or self.store).flush()

    def split_info(self):
        if not self.split:
            return None
        front = self.client.call("stats")[0]
        front.pop("_s", None)
        import mlx_split as S
        lead = {"stage": self.store.ident.get("stage"),
                "name": S.stage_title("head", self.stage.range, self.stage.n_layers),
                "weights_gb": round(self.stage.nbytes() / 1e9, 2),
                "active_gb": round(self.mx.get_active_memory() / 1e9, 2),
                "peak_gb": round(self.mx.get_peak_memory() / 1e9, 2)}
        front.setdefault("name", S.title_from_label(front.get("stage")))
        # "lead" / "packers" are the names to use; "head" / "front" are deprecated aliases.
        return {"lead": lead, "packers": front.get("packers") or [front], "head": lead, "front": front, "peer": self.args.split_peer}

    def call(self, fn, *, between_rounds=False):
        """Run fn on the socket-owning mlx thread.

        Only read-only RPCs may opt into between-round execution. Cache-mutating
        administration remains deferred until all decoding slots are idle.
        """
        out = self._queue_mod.Queue()
        self.jobs.put(("read" if between_rounds else "call", fn, out))
        st, v = out.get()
        if st == "err":
            raise v
        return v

    def run(self, key, prompt, body):
        """Generator for a handler thread: ("piece", text, last) ... ("done", info).
        Closing it early (client gone) cancels the generation."""
        out = self._queue_mod.Queue()
        cancel = threading.Event()
        self.jobs.put(("gen", (key, prompt, body, cancel), out))
        try:
            while True:
                ev = out.get()
                if ev is None:
                    return
                if ev[0] == "error":
                    raise ev[1]
                yield ev
        finally:
            cancel.set()

    # -- memory guard (trim + archive + recall) -----------------------------
    def apply_memory_guard(self, body: dict, *, session_key: Optional[str] = None) -> tuple:
        """Return (body, meta). Archives trimmed turns; recalls snippets from notes."""
        import memory_guard as MG
        import memory_notes as MN
        msgs = list(body.get("messages") or [])
        if not msgs:
            return body, {"trimmed_turns": 0, "ok": True}
        max_tokens = int(body.get("max_tokens") or self.default_max_tokens or 512)
        kv_bits = int(getattr(self.args, "kv_bits", None) or 16)
        if self.client is not None and getattr(self, "stage", None) is not None:
            n_layers = int(self.stage.range[1] - self.stage.range[0])
            packer_layers = int(self.stage.range[0])
        else:
            n_layers = MG.model_layer_count(self.model_cfg or {})
            packer_layers = None
        packer_avail = None
        if self.client is not None:
            try:
                # HTTP handlers must never read/write the split socket themselves:
                # concurrent guards/status/decode can consume each other's frames.
                st = self.call(lambda: self.client.call("stats")[0], between_rounds=True)
                # N-stage stats contain every packer, not a top-level free value.
                # Total upstream layers + tightest free RAM is conservative even
                # when two simulated stages share one physical Mini.
                packer_avail = MG.peer_available_gb(st)
            except Exception:
                packer_avail = None

        def count_tokens(ms):
            b = dict(body)
            b["messages"] = ms
            try:
                return len(self.chat_prompt(b))
            except Exception:
                return sum(max(1, len(str(m.get("content") or "")) // 4) for m in ms)

        mem_dir = Path(getattr(self, "memory_dir", None) or MN.default_memory_dir()).expanduser()
        sid = session_key or body.get("session") or "anon"
        model_name = getattr(self, "model_dir", None)
        model_name = model_name.name if model_name is not None else ""

        # Drop any prior guard/recall system notes so they never accumulate.
        msgs = [
            m for m in msgs
            if not (
                str(m.get("role")) == "system"
                and MN.is_memory_guard_note(str(m.get("content") or ""))
            )
        ]

        # Recall BEFORE trim so archive search still sees older context.
        recall_all = bool(getattr(self.args, "memory_recall_all", False))
        user_q = ""
        for m in reversed(msgs):
            if str(m.get("role")) == "user":
                user_q = str(m.get("content") or "")
                break
        snippets = []
        try:
            snippets = MN.bm25_recall(
                mem_dir, sid, user_q, top_k=3,
                token_cap=int(getattr(self.args, "memory_recall_tokens", 500) or 500),
                all_sessions=recall_all,
            )
        except Exception as e:
            log(f"memory_notes: recall failed ({e!r})")

        n_archived = 0
        try:
            n_archived = int(MN.count_archived_turns(mem_dir, sid) or 0)
        except Exception as e:
            log(f"memory_notes: count failed ({e!r})")

        plan_kwargs = dict(
            cfg=self.model_cfg or {},
            n_layers=max(1, n_layers),
            max_tokens=max_tokens,
            count_tokens=count_tokens,
            kv_bits=kv_bits,
            safety_gb=getattr(self, "memory_safety_gb", MG.DEFAULT_SAFETY_GB),
            packer_available_gb=packer_avail,
            packer_layers=packer_layers,
        )

        # Pass 1 (no note): learn how many turns this reply will archive so N
        # on the trim reply includes them; note is injected for pass 2 so it
        # counts in the KV estimate.
        plan_pre = MG.plan(list(msgs), **plan_kwargs)
        drops_pre = [
            d for d in (plan_pre.get("dropped") or [])
            if not (
                str(d.get("role")) == "system"
                and MN.is_memory_guard_note(str(d.get("content") or ""))
            )
        ]
        # append_turns skips system/empty; count the same way for N.
        n_pending = sum(
            1 for d in drops_pre
            if str(d.get("role") or "") != "system" and str(d.get("content") or "").strip()
        )
        n_total = n_archived + n_pending

        recall_note = MN.format_recall_note(snippets, archived_turns=n_total)
        work_msgs = list(msgs)
        if recall_note:
            insert_at = len(work_msgs) - 1 if work_msgs else 0
            work_msgs.insert(insert_at, {"role": "system", "content": recall_note})
            plan = MG.plan(work_msgs, **plan_kwargs)
        else:
            plan = plan_pre

        meta = {k: plan[k] for k in plan if k not in ("messages", "dropped")}
        if "headroom_gb" in meta:
            meta["headroom_gb"] = round(float(meta["headroom_gb"]), 3)
        meta["recalled_snippets"] = len(snippets)
        meta["recalled"] = [
            {"turn": s["turn"], "role": s["role"], "score": s["score"]} for s in snippets
        ]
        meta["archived_total"] = n_total
        meta["archive_note"] = bool(recall_note)

        dropped = [
            d for d in (plan.get("dropped") or [])
            if not (
                str(d.get("role")) == "system"
                and MN.is_memory_guard_note(str(d.get("content") or ""))
            )
        ]
        archived_to = None
        if dropped:
            try:
                info = MN.append_turns(mem_dir, sid, dropped, model=model_name)
                archived_to = info.get("path")
                meta["archived_to"] = archived_to
                meta["archived_turns"] = info.get("turns")
                log(f"memory_notes: archived {info.get('turns')} turn(s) -> {archived_to}")
            except Exception as e:
                log(f"memory_notes: archive failed ({e!r})")
                meta["archive_error"] = str(e)

        # Refresh N from disk (and rewrite the injected note) so the model sees
        # the true total after this reply's archive; never leave a stale N.
        try:
            n_final = int(MN.count_archived_turns(mem_dir, sid) or 0)
        except Exception:
            n_final = n_total
        meta["archived_total"] = n_final
        if n_final != n_total or (n_final > 0 and recall_note):
            final_note = MN.format_recall_note(snippets, archived_turns=n_final)
            out_msgs = list(plan.get("messages") or [])
            # Replace existing guard note or insert fresh; never stack.
            out_msgs = [
                m for m in out_msgs
                if not (
                    str(m.get("role")) == "system"
                    and MN.is_memory_guard_note(str(m.get("content") or ""))
                )
            ]
            if final_note:
                insert_at = len(out_msgs) - 1 if out_msgs else 0
                out_msgs.insert(insert_at, {"role": "system", "content": final_note})
            plan = dict(plan)
            plan["messages"] = out_msgs
            recall_note = final_note
            meta["archive_note"] = bool(final_note)

        if plan.get("trimmed_turns"):
            log(f"memory_guard: trimmed {plan['trimmed_turns']} turn(s); "
                f"prompt~{plan.get('prompt_tokens')} tok, need~{plan.get('need_gb')} GB, "
                f"headroom {meta.get('headroom_gb')} GB; archive_note N={meta.get('archived_total')}")
            try:
                self.store.enforce_limits(keep=sid if sid in getattr(self.store, "sessions", {}) else None)
            except Exception as e:
                log(f"memory_guard: enforce_limits skipped ({e!r})")

        body = dict(body)
        body["messages"] = plan["messages"]
        meta["trimmed_turns"] = int(plan.get("trimmed_turns") or 0)
        return body, meta

    # -- prompt (tokenizer only; safe on any thread) ------------------------
    def chat_prompt(self, body):

        msgs = []
        for m in body.get("messages") or []:
            m = dict(m)
            m["content"] = _text_of(m.get("content"))
            # A client that sends llama.cpp-style reasoning_content back keeps
            # it out of the visible content; templates read "thinking"/"reasoning".
            m.pop("reasoning_content", None)
            m.pop("reasoning", None)
            msgs.append(m)
        kw = dict(body.get("chat_template_kwargs") or {})
        if body.get("tools"):
            kw["tools"] = body["tools"]
        prefill_close = False
        think = body.get("thinking")
        if not isinstance(think, bool) and body.get("reasoning_effort") == "none":
            think = False  # OpenAI/Hermes auxiliary calls explicitly opt out
        if isinstance(think, bool):
            kw, prefill_close = thinking_kwargs(self.tokenizer, think, kw)
        toks = self.tokenizer.apply_chat_template(msgs, add_generation_prompt=True, tokenize=True, **kw)
        if isinstance(toks, dict):
            toks = toks["input_ids"]
        toks = list(toks)
        body.pop("_caravan_agent_prefix", None)  # never trust a caller's boundary
        if body.get("tools"):
            # Preserve actual template order (including tools); never reorder
            # schemas or strip changing prompt content to manufacture a hit.
            first = next((i for i, m in enumerate(msgs)
                          if m.get("role") not in ("system", "developer")), None)
            if first is not None and msgs[first].get("role") == "user":
                probe = msgs[:first] + [{"role": "user", "content": "\x00Caravan-prefix-boundary"}]
                try:
                    other = self.tokenizer.apply_chat_template(
                        probe, add_generation_prompt=True, tokenize=True, **kw)
                    if isinstance(other, dict):
                        other = other["input_ids"]
                    n = common_prefix(toks, list(other))
                    if 1024 <= n < len(toks) - 1:
                        body["_caravan_agent_prefix"] = n
                except Exception:
                    pass  # exotic template: ordinary session caching remains safe
        if prefill_close:
            # Template has no thinking switch but the model thinks in tags:
            # open and close an empty think block so it answers straight away.
            start = getattr(self.tokenizer, "think_start", None)
            end = getattr(self.tokenizer, "think_end", None)
            if start and end:
                toks += list(self.tokenizer.encode(f"{start}\n\n{end}\n\n", add_special_tokens=False))
        return toks

    def text_prompt(self, body):
        p = body.get("prompt")
        if isinstance(p, list) and all(isinstance(t, int) for t in p):
            return list(p)
        return list(self.tokenizer.encode(p if isinstance(p, str) else ""))

    # -- generation (mlx thread) ------------------------------------------
    def _first_load_gate(self, dpath, pairing):
        """Quality + short speed A/B; cache per model+guesser on this machine."""
        cached = guess_ahead.get_first_load(self.model_dir, dpath)
        if cached is not None:
            keep = bool(cached.get("keep"))
            self.break_even_frac = float(cached.get("break_even_frac") or self.break_even_frac)
            if keep:
                log(f"split speculate: first-load cache hit keep=1 "
                    f"break_even={self.break_even_frac:.3f}")
            else:
                log("split speculate: first-load cache hit keep=0; disabling draft")
                self.draft_model = None
                self.draft_tokenizer = None
            return keep
        log("split speculate: running first-load quality + speed gate...")
        quality = []
        q_ok = 0
        # Temporarily use a dedicated session key so we don't pollute user caches.
        for q, expect in guess_ahead.QUALITY_PROBES:
            try:
                text_out = self._gate_complete(q, max_tokens=256, use_draft=True)
            except Exception as e:
                text_out = f"<err:{e}>"
            ok = guess_ahead.answer_ok(text_out, expect)
            quality.append({"q": q, "out": (text_out or "")[:400], "ok": ok})
            if ok:
                q_ok += 1
        if q_ok < len(guess_ahead.QUALITY_PROBES):
            result = {"keep": False, "quality": quality, "reason": f"quality {q_ok}/{len(guess_ahead.QUALITY_PROBES)}"}
            guess_ahead.set_first_load(self.model_dir, dpath, result)
            log(f"split speculate: first-load quality fail {q_ok}/3; disabling draft")
            self.draft_model = None
            self.draft_tokenizer = None
            return False
        # Short speed A/B on a count-style prompt (same session pattern as benches).
        prompt = "Count from 1 to 30, numbers only, space-separated."
        try:
            off = self._gate_timed(prompt, max_tokens=40, use_draft=False)
            on = self._gate_timed(prompt, max_tokens=40, use_draft=True)
        except Exception as e:
            result = {"keep": False, "quality": quality, "reason": f"speed err: {e}"}
            guess_ahead.set_first_load(self.model_dir, dpath, result)
            log(f"split speculate: first-load speed err ({e}); disabling draft")
            self.draft_model = None
            self.draft_tokenizer = None
            return False
        faster = on["tps"] > off["tps"] * 1.05
        k = int(self.speculate_k)
        be = guess_ahead.derive_break_even(off["tps"], on["tps"], k, on.get("accepted_frac") or 0.0)
        self.break_even_frac = be
        result = {
            "keep": bool(faster),
            "quality": quality,
            "baseline_tps": round(off["tps"], 2),
            "spec_tps": round(on["tps"], 2),
            "accepted_frac": on.get("accepted_frac"),
            "break_even_frac": be,
            "k": k,
            "pairing": (pairing or {}).get("id"),
            "ts": time.time(),
        }
        guess_ahead.set_first_load(self.model_dir, dpath, result)
        if faster:
            log(f"split speculate: first-load keep "
                f"baseline={result['baseline_tps']} spec={result['spec_tps']} "
                f"break_even={be:.3f}")
            return True
        log(f"split speculate: first-load not faster "
            f"({result['spec_tps']} vs {result['baseline_tps']}); disabling draft")
        self.draft_model = None
        self.draft_tokenizer = None
        return False

    def _gate_messages(self, user_text):
        # Qwen3 thinking models need /no_think for short factual probes.
        stem = str(self.model_dir.name).lower()
        if "qwen3" in stem and "/no_think" not in user_text:
            user_text = user_text + " /no_think"
        return [{"role": "user", "content": user_text}]

    def _gate_complete(self, user_text, max_tokens=24, use_draft=True):
        """One-shot non-stream completion for the first-load gate."""
        saved = self.draft_model
        if not use_draft:
            self.draft_model = None
        try:
            msgs = self._gate_messages(user_text)
            if hasattr(self.tokenizer, "apply_chat_template"):
                prompt = self.tokenizer.apply_chat_template(
                    msgs, tokenize=True, add_generation_prompt=True)
            else:
                prompt = self.tokenizer.encode(user_text)
            if not isinstance(prompt, list):
                prompt = list(prompt)
            key = f"__guess_gate_{int(time.time()*1000)}_{use_draft}"
            pieces = []
            import threading as _th
            cancel = _th.Event()
            body = {"temperature": 0.0, "max_tokens": max_tokens}
            for ev in self._run(key, prompt, body, cancel):
                if ev and ev[0] == "piece":
                    pieces.append(ev[1] or "")
            return "".join(pieces)
        finally:
            self.draft_model = saved

    def _gate_timed(self, user_text, max_tokens=40, use_draft=True):
        t0 = time.time()
        text = self._gate_complete(user_text, max_tokens=max_tokens, use_draft=use_draft)
        dt = max(time.time() - t0, 1e-6)
        # Prefer speculate stats when present
        st = getattr(self, "_last_speculate_stats", {}) or {}
        # n_gen approximate from text tokens
        n = max(1, len(self.tokenizer.encode(text)) if text else max_tokens)
        info = getattr(self, "_last_run_info", {}) or {}
        n_gen = int(info.get("completion_tokens") or n)
        tps = n_gen / dt
        frac = None
        if info.get("speculate"):
            frac = info["speculate"].get("accepted_frac")
        return {"tps": tps, "n_gen": n_gen, "dt": dt, "accepted_frac": frac, "text": text[:60]}

    @staticmethod
    def _prompt_lookup_draft(context, ngram_max, num_draft):
        """Draft-free: find longest n-gram match in earlier context; return following tokens.

        Searches n from ngram_max down to 1. Returns up to num_draft token ids, or [].
        """
        if num_draft <= 0 or len(context) < 2:
            return []
        nmax = min(int(ngram_max), len(context) - 1)
        for n in range(nmax, 0, -1):
            needle = context[-n:]
            # Search earlier region for an occurrence of needle.
            limit = len(context) - n
            # Prefer the rightmost match that still has following tokens.
            found_at = -1
            i = 0
            while i <= limit - 1:
                if context[i:i + n] == needle:
                    # Match must leave at least one following token in history.
                    if i + n < len(context):
                        found_at = i
                    i += 1
                else:
                    i += 1
            if found_at >= 0:
                start = found_at + n
                return context[start:start + num_draft]
        return []


    @staticmethod
    def _speculate_trim_room(cache, need: int) -> bool:
        """True if a verify of `need` tokens can still be trimmed afterward.

        RotatingKVCache (gpt-oss sliding window) sets is_trimmable False once
        offset >= max_size; refuse multi-token verify that would fill it.
        """
        for c in cache:
            name = type(c).__name__
            if name == "RotatingKVCache":
                max_size = getattr(c, "max_size", None)
                offset = getattr(c, "offset", 0)
                if max_size is None or offset + need >= max_size:
                    return False
            elif hasattr(c, "is_trimmable") and not c.is_trimmable():
                return False
        return True

    def _speculate_tokens(self, prompt, cache, max_tokens, sampler, procs, stream, cancel):
        """Idea 3: draft (model and/or prompt-lookup); one TB round trip verifies k.

        `prompt` is the FULL prompt token list (target KV already prefills all of it).
        Draft model, if any, prefills the full prompt into its own cache (fix vs
        earlier last-token-only prefill). Yields (token_id:int, from_draft:bool).
        """
        import time as _time
        import mlx.core as mx
        from mlx_lm.models.cache import make_prompt_cache, can_trim_prompt_cache, trim_prompt_cache

        model = self.model
        draft = self.draft_model
        use_draft = draft is not None
        use_pl = int(self.prompt_lookup_n) > 0
        gate = getattr(self, "_adaptive_pl_gate", None) if getattr(self, "prompt_lookup_adaptive", False) else None
        if gate is not None:
            gate.begin_request(prompt)
        if not use_draft and not use_pl:
            raise RuntimeError("speculate called with neither draft nor prompt-lookup")
        num_draft_tokens = int(self.speculate_k)
        def trim_target(n):
            if not n:
                return
            if hasattr(model, "trim_caches"):
                model.trim_caches(n, cache)
            elif trim_prompt_cache(cache, n) != n:
                raise RuntimeError("prompt lookup needs rewindable target caches")
        # RotatingKVCache may already be full after a long prompt; we still
        # run but only single-token steps until/unless trim room appears (it
        # will not for a full sliding window). Hard-fail only when no cache
        # object supports trim at all and we would need it — handled per round.
        _ = can_trim_prompt_cache  # kept for rewind path

        draft_cache = make_prompt_cache(draft) if use_draft else None
        remap_d2t = getattr(self, "draft_remap_d2t", None) or {}
        remap_t2d = getattr(self, "draft_remap_t2d", None) or {}
        shut = getattr(self, "_active_shutoff", None)

        def _to_draft_ids(ids):
            if not remap_t2d:
                return list(ids)
            return guess_ahead.apply_remap(list(ids), remap_t2d)

        def _to_target_ids(ids):
            if not remap_d2t:
                return list(ids)
            return guess_ahead.apply_remap(list(ids), remap_d2t)

        context = list(prompt)  # grows with accepted tokens (for prompt-lookup)
        y = mx.array([prompt[-1]], dtype=mx.uint32)  # target continues from last prompt tok
        prev_tokens = None

        # Timing accumulators (seconds)
        draft_s = 0.0
        verify_s = 0.0
        pl_hits = 0
        pl_misses = 0

        def _process_and_sample(tokens, logits):
            nonlocal prev_tokens
            if procs:
                for processor in procs:
                    logits = processor(tokens, logits)
            logprobs = logits - mx.logsumexp(logits, axis=-1, keepdims=True)
            sampled = sampler(logprobs)
            return sampled, logprobs

        def _step(m, c, y_in, n_predict=1):
            nonlocal prev_tokens
            logits = m(y_in[None], cache=c)
            logits = logits[:, -n_predict:, :]
            if procs:
                out_y, out_logprobs = [], []
                yy = y_in
                if n_predict > 1:
                    yy = yy[: -(n_predict - 1)]
                for i in range(n_predict):
                    prev_tokens = (
                        mx.concatenate([prev_tokens, yy]) if prev_tokens is not None else yy
                    )
                    tok, logprobs = _process_and_sample(prev_tokens, logits[:, i, :])
                    out_y.append(tok)
                    out_logprobs.append(logprobs)
                    yy = tok
                return mx.concatenate(out_y, axis=0), mx.concatenate(out_logprobs, axis=0)
            return _process_and_sample(None, logits.squeeze(0))

        def _prefill_draft(y_in):
            while y_in.size > 1:
                n_to = min(self.prefill_step, int(y_in.size) - 1)
                draft(y_in[:n_to][None], cache=draft_cache)
                mx.eval([c.state for c in draft_cache])
                y_in = y_in[n_to:]
                mx.clear_cache()
            return y_in

        def _rewind(num_draft, num_accept):
            trim_target(num_draft - num_accept)
            if draft_cache is not None:
                trim_prompt_cache(draft_cache, max(num_draft - num_accept - 1, 0))

        def _draft_model_generate(y_in, num_draft):
            if num_draft == 0:
                return mx.array([], mx.uint32)
            ys = []
            for _ in range(num_draft):
                y_in, _ = _step(draft, draft_cache, y_in)
                mx.async_eval(y_in)
                ys.append(y_in)
            return mx.concatenate(ys)

        def _propose(num_draft, draft_y):
            """Return (draft_tokens mx.uint32[n], source:str). Prefer prompt-lookup when it hits."""
            nonlocal draft_s, pl_hits, pl_misses
            t0 = _time.perf_counter()
            if gate is not None:
                gate.note_context(context)
            try_pl = use_pl and (gate is None or gate.should_try_pl(has_draft=use_draft))
            if try_pl:
                pl = self._prompt_lookup_draft(context, self.prompt_lookup_n, num_draft)
                if pl:
                    pl_hits += 1
                    draft_s += _time.perf_counter() - t0
                    # Keep draft-model cache in sync: run the proposed tokens through it.
                    if use_draft and draft_y is not None:
                        seq = mx.array(pl, mx.uint32)
                        # Feed each proposed token as the next input (like generate).
                        yy = draft_y
                        for tok in pl:
                            # Advance draft cache by running model on current yy, then set yy=tok
                            # Actually we need cache to contain the proposed tokens as if draft made them.
                            # Simplest: run _step for each but force the token? Draft cache must match
                            # accepted path. On reject we rewind. On propose-from-PL, if we also have
                            # a draft model, skip syncing unless accepted — rewind handles rejects.
                            # Leave draft_y as-is when PL proposes; on accept-all path with draft model
                            # the mlx_lm concat of last draft is messy. Prefer: when PL hits, don't
                            # use draft model this round.
                            pass
                    return mx.array(pl, mx.uint32), "prompt_lookup"
                pl_misses += 1
            if use_draft:
                toks = _draft_model_generate(draft_y, num_draft)
                mx.eval(toks)
                draft_s += _time.perf_counter() - t0
                raw = toks.tolist()
                if not isinstance(raw, list):
                    raw = [raw]
                self._last_draft_raw = [int(x) for x in raw]
                if remap_d2t:
                    toks = mx.array(_to_target_ids(raw), mx.uint32)
                return toks, "draft_model"
            draft_s += _time.perf_counter() - t0
            return mx.array([], mx.uint32), "none"

        with mx.stream(stream):
            draft_y = None
            if use_draft:
                t0 = _time.perf_counter()
                draft_y = _prefill_draft(mx.array(_to_draft_ids(prompt), dtype=mx.uint32))
                draft_s += _time.perf_counter() - t0
            ntoks = 0
            num_draft = 0
            n = 0
            stats = {"draft_s": 0.0, "verify_s": 0.0, "pl_hits": 0, "pl_misses": 0,
                     "source_counts": {"draft_model": 0, "prompt_lookup": 0, "none": 0}}
            try:
                while True:
                    if cancel.is_set():
                        raise KeyboardInterrupt("cancelled")
                    num_draft = min(max_tokens - ntoks, num_draft_tokens)
                    if shut is not None and shut.disabled:
                        num_draft = 0
                    # gpt-oss RotatingKVCache: only speculate while trim room remains
                    if num_draft > 0 and not self._speculate_trim_room(cache, num_draft + 1):
                        num_draft = 0
                    draft_tokens, src = _propose(num_draft, draft_y)
                    stats["source_counts"][src] = stats["source_counts"].get(src, 0) + 1
                    # If no proposals, fall back to single-token target step (still works).
                    dlen = int(draft_tokens.size) if hasattr(draft_tokens, "size") else 0
                    if dlen == 0:
                        num_draft = 0
                        draft_list = []
                        y_step = y
                        t1 = _time.perf_counter()
                        tokens, logprobs = _step(model, cache, y_step, 1)
                        mx.eval(tokens)
                        verify_s += _time.perf_counter() - t1
                        token_list = tokens.tolist()
                        if not isinstance(token_list, list):
                            token_list = [token_list]
                        n = 0
                        ntoks += 1
                        context.append(int(token_list[0]))
                        yield int(token_list[0]), False
                        if ntoks == max_tokens:
                            break
                        y = mx.array([token_list[0]], mx.uint32)
                        if use_draft:
                            # Advance draft with the accepted bonus token (draft-space id).
                            tid = int(token_list[0])
                            did = remap_t2d.get(tid, tid) if remap_t2d else tid
                            yin = draft_y if draft_y is not None else mx.array([did], mx.uint32)
                            draft_y, _ = _step(draft, draft_cache, yin)
                            mx.eval(draft_y)
                            draft_y = mx.array([did], mx.uint32)
                        continue

                    if prev_tokens is not None:
                        prev_tokens = prev_tokens[: prev_tokens.size - y.size - num_draft + 1]
                    # If prompt-lookup returned fewer than k, adjust.
                    num_draft = dlen
                    y_cat = mx.concatenate([y, draft_tokens])
                    t1 = _time.perf_counter()
                    tokens, logprobs = _step(model, cache, y_cat, num_draft + 1)
                    mx.eval(tokens, draft_tokens)
                    verify_s += _time.perf_counter() - t1
                    draft_list = draft_tokens.tolist()
                    token_list = tokens.tolist()
                    if not isinstance(draft_list, list):
                        draft_list = [draft_list]
                    if not isinstance(token_list, list):
                        token_list = [token_list]
                    n = 0
                    while n < num_draft:
                        if token_list[n] != draft_list[n]:
                            break
                        n += 1
                        ntoks += 1
                        context.append(int(token_list[n - 1]))
                        yield int(token_list[n - 1]), True
                        if ntoks == max_tokens:
                            break
                    if gate is not None and src == "prompt_lookup":
                        gate.observe_pl_round(proposed=num_draft, accepted=n)
                    if ntoks < max_tokens:
                        ntoks += 1
                        context.append(int(token_list[n]))
                        yield int(token_list[n]), False
                    if ntoks == max_tokens:
                        break
                    y = mx.array([token_list[n]], mx.uint32)
                    if use_draft:
                        bonus_t = int(token_list[n]) if ntoks <= max_tokens else int(y.tolist()[0])
                        bonus_d = remap_t2d.get(bonus_t, bonus_t) if remap_t2d else bonus_t
                        if src == "draft_model":
                            draft_y = mx.array([bonus_d], mx.uint32)
                            if n == num_draft:
                                raw = getattr(self, "_last_draft_raw", None) or draft_list
                                last_d = int(raw[-1]) if raw else bonus_d
                                draft_y = mx.concatenate(
                                    [mx.array([last_d], mx.uint32), draft_y]
                                )
                        else:
                            draft_y = mx.array([bonus_d], mx.uint32)
                    if prev_tokens is not None:
                        prev_tokens = prev_tokens[: -max(num_draft - n, 1)]
                    _rewind(num_draft, n)
                    num_draft = n = 0
                    if use_draft and src != "draft_model":
                        # After trim, advance draft cache by the accepted tokens we yielded this round
                        # (n drafts + 1 bonus if any). Simpler path: run draft on each accepted token
                        # starting from previous draft_y — for v1 skip perfect draft sync on PL mix;
                        # disable dual draft+PL for now by preferring PL-only when both set for propose.
                        pass
            finally:
                _rewind(num_draft, n)
                stats["draft_s"] = round(draft_s, 4)
                stats["verify_s"] = round(verify_s, 4)
                stats["pl_hits"] = pl_hits
                stats["pl_misses"] = pl_misses
                if gate is not None:
                    stats["adaptive_pl"] = gate.snapshot()
                # Stash on self for _run to pick up into info
                self._last_speculate_stats = stats

    def _run_native_mtp(self, key, prompt, body, cancel):
        from native_mtp import generate
        if float(body.get("temperature", 0) or 0) != 0 or body.get("repetition_penalty"):
            raise ValueError("native MTP experiment requires temperature 0 and no repetition penalty")
        enabled = body.get("native_mtp", True)
        if not isinstance(enabled, bool):
            raise ValueError("native_mtp must be a boolean")
        t0 = time.time()
        stats, n, ttft = {}, 0, None
        detok = self.tokenizer.detokenizer
        detok.reset()
        eos = getattr(self.tokenizer, "eos_token_ids", [])
        if isinstance(eos, int):
            eos = [eos]
        words = body.get("stop") or []
        if isinstance(words, str):
            words = [words]
        stops = self.G.make_stop_sequences(self.tokenizer, words).matcher()
        max_tokens = int(body.get("max_completion_tokens") or body.get("max_tokens") or self.default_max_tokens)
        finish = "length"
        gen = generate(self.model, self.native_mtp, prompt, max_tokens,
                       enabled=enabled, cancel=cancel, stats=stats)
        try:
            with self.mx.stream(self.stream):
                for token, drafted in gen:
                    if cancel.is_set():
                        return
                    if ttft is None:
                        ttft = time.time() - t0
                    n += 1
                    detok.add_token(token)
                    if token in eos or stops.advance(token):
                        finish = "stop"
                        yield ("piece", detok.last_segment, True)
                        break
                    yield ("piece", detok.last_segment, False)
        finally:
            gen.close()
        detok.finalize()
        stats["accepted_frac"] = stats.get("accepted", 0) / max(stats.get("proposed", 0), 1)
        info = {"prompt_tokens": len(prompt), "cached_tokens": 0, "how": "native-mtp-fresh-cache",
                "completion_tokens": n, "finish": finish, "prefill_s": round(ttft or 0, 4),
                "ttft_s": round(ttft or 0, 4), "total_s": round(time.time() - t0, 4),
                "peak_gb": round(self.mx.get_peak_memory() / 1e9, 3)}
        if enabled:
            info["speculate"] = stats
        info["active"] = self.active_settings(info)
        info["active"]["guess_ahead_mode"] = "native_mtp" if enabled else "off"
        yield ("done", info)

    def _run(self, key, prompt, body, cancel):
        # Serial worker request-local experiment: do not mutate saved UI choices.
        mode = body.get("prompt_lookup")
        if mode is None:
            yield from self._run_impl(key, prompt, body, cancel)
            return
        if mode not in ("off", "adaptive"):
            raise ValueError("prompt_lookup must be off or adaptive")
        if self.client is not None and int(self.pipeline_chats or 1) > 1:
            raise ValueError("request-local prompt lookup requires serial worker")
        saved = (self.prompt_lookup_n, self.prompt_lookup_adaptive, self._adaptive_pl_gate)
        self.prompt_lookup_n = 3 if mode == "adaptive" else 0
        self.prompt_lookup_adaptive = mode == "adaptive"
        self._adaptive_pl_gate = adaptive_pl.AdaptivePLGate(ngram_n=3) if mode == "adaptive" else None
        try:
            yield from self._run_impl(key, prompt, body, cancel)
        finally:
            self.prompt_lookup_n, self.prompt_lookup_adaptive, self._adaptive_pl_gate = saved

    def _run_impl(self, key, prompt, body, cancel):
        if getattr(self, "native_mtp", None) is not None:
            yield from self._run_native_mtp(key, prompt, body, cancel)
            return
        mx, G = self.mx, self.G
        t0 = time.time()
        if self.client is not None:
            self.client.reset_stats()
        if self.client is not None and hasattr(self.model, "session_key"):
            self.model.session_key = key
        s, n_reused, how = self._prepare_agent_prefix(key, prompt, body)
        completed = False
        n_gen = 0
        try:
            rest = prompt[n_reused:]
            with request_wiring(self.wired_mode, G, self.model, self.stream):
                with mx.stream(self.stream):
                    for begin, end, boundary in self._prefill_chunks(prompt, n_reused, body):
                        if cancel.is_set():
                            raise KeyboardInterrupt("cancelled")
                        chunk = mx.array(prompt[begin:end])
                        self.model(chunk[None], cache=s.cache)
                        mx.eval([c.state for c in s.cache])
                        mx.clear_cache()
                        if boundary:
                            self.s_checkpoint(s, prompt[:end])
                            self._store_agent_prefix(key, prompt, body, s)
            self.s_checkpoint(s, prompt[:-1])
            if n_reused == 0:
                self._maybe_store_shared_prefix(key, prompt, s)
            t_prefill = time.time() - t0
            if body.get("seed") is not None:
                mx.random.seed(int(body["seed"]))
            sampler = self.make_sampler(temp=float(body.get("temperature", 0.0) or 0.0),
                                        top_p=float(body.get("top_p", 1.0) or 1.0),
                                        min_p=float(body.get("min_p", 0.0) or 0.0),
                                        top_k=int(body.get("top_k", 0) or 0))
            rp = body.get("repetition_penalty")
            procs = self.make_logits_processors(repetition_penalty=rp) if rp else None
            max_tokens = int(body.get("max_completion_tokens") or body.get("max_tokens")
                             or self.default_max_tokens)
            stop_words = body.get("stop") or []
            if isinstance(stop_words, str):
                stop_words = [stop_words]
            stops = G.make_stop_sequences(self.tokenizer, stop_words).matcher()
            ttft = None
            finish = "length"
            n_from_draft = 0
            n_verify_rounds = 0
            shut = None
            if self.client is not None and self.draft_model is not None:
                shut = self._chat_shutoffs.get(key)
                if shut is None:
                    shut = guess_ahead.ChatShutoff(self.break_even_frac)
                    self._chat_shutoffs[key] = shut
                elif shut.disabled:
                    shut = shut  # keep disabled
            self._active_shutoff = shut
            # ROADMAP #13b: learn override can force guess-ahead off (or on when draft loaded).
            if self._learn_guess_override is False:
                draft_ok = False
            elif self._learn_guess_override is True:
                draft_ok = self.draft_model is not None and not (shut and shut.disabled)
            else:
                draft_ok = self.draft_model is not None and not (shut and shut.disabled)
            use_spec = ((self.client is not None and draft_ok) or int(self.prompt_lookup_n) > 0)
            if use_spec:
                # Detokenize ourselves (stream_generate path does this inside mlx_lm).
                detok = self.tokenizer
                if hasattr(detok, "detokenizer"):
                    detokenizer = detok.detokenizer
                else:
                    from mlx_lm.tokenizer_utils import TokenizerWrapper
                    detokenizer = TokenizerWrapper(detok).detokenizer
                detokenizer.reset()
                self._last_speculate_stats = {}
                for token, from_draft in self._speculate_tokens(
                        prompt, s.cache, max_tokens, sampler, procs, self.stream, cancel):
                    if cancel.is_set():
                        raise KeyboardInterrupt("cancelled")
                    if ttft is None:
                        ttft = time.time() - t0
                    n_gen += 1
                    if from_draft:
                        n_from_draft += 1
                    else:
                        n_verify_rounds += 1  # each non-draft yield ends a verify round
                    if shut is not None:
                        was = shut.disabled
                        shut.observe(bool(from_draft))
                        if shut.disabled and not was:
                            log(f"split speculate: {shut.reason}")
                    detokenizer.add_token(token)
                    text = detokenizer.last_segment
                    if stops.advance(token):
                        yield ("piece", text, True)
                        finish = "stop"
                        break
                    eos = getattr(self.tokenizer, "eos_token_ids", None) or []
                    if isinstance(eos, int):
                        eos = [eos]
                    if token in eos:
                        yield ("piece", text, True)
                        finish = "stop"
                        break
                    yield ("piece", text, False)
                else:
                    finish = "length"
                detokenizer.finalize()
            else:
                for gen in G.stream_generate(self.model, self.tokenizer, prompt[-1:],
                                             max_tokens=max_tokens, sampler=sampler,
                                             logits_processors=procs, prompt_cache=s.cache,
                                             stream=self.stream):
                    if cancel.is_set():
                        raise KeyboardInterrupt("cancelled")
                    if ttft is None:
                        ttft = time.time() - t0
                    if gen.finish_reason is None or gen.finish_reason == "length":
                        n_gen += 1
                    if gen.finish_reason is not None:
                        finish = gen.finish_reason
                    if stops.advance(gen.token):
                        yield ("piece", gen.text, True)
                        finish = "stop"
                        break
                    yield ("piece", gen.text, gen.finish_reason is not None)
                    if gen.finish_reason is not None:
                        break
            completed = True
            info = {"prompt_tokens": len(prompt), "cached_tokens": n_reused, "how": how,
                    "completion_tokens": n_gen, "finish": finish, "prefill_s": round(t_prefill, 3),
                    "ttft_s": round(ttft or 0, 3), "total_s": round(time.time() - t0, 3),
                    "peak_gb": round(mx.get_peak_memory() / 1e9, 2)}
            self._last_run_info = info
            if use_spec:
                st = getattr(self, "_last_speculate_stats", {}) or {}
                info["speculate"] = {
                    "k": self.speculate_k,
                    "from_draft": n_from_draft,
                    "accepted_frac": round(n_from_draft / max(n_gen, 1), 3),
                    "verify_rounds": n_verify_rounds,
                    "prompt_lookup_n": int(self.prompt_lookup_n) or None,
                    "draft_model": bool(self.draft_model),
                    "draft_s": st.get("draft_s"),
                    "verify_s": st.get("verify_s"),
                    "pl_hits": st.get("pl_hits"),
                    "pl_misses": st.get("pl_misses"),
                    "sources": st.get("source_counts"),
                    "adaptive_pl": st.get("adaptive_pl"),
                    "shutoff": (shut.snapshot() if shut is not None else None),
                }
            if self.client is not None:
                st = dict(self.client.stats)
                info["split"] = {"calls": st["calls"], "mb_out": round(st["bytes_out"] / 1e6, 2),
                                 "mb_in": round(st["bytes_in"] / 1e6, 2),
                                 "wait_s": round(st["wait_s"], 3), "front_s": round(st["front_s"], 3),
                                 "net_s": round(st["wait_s"] - st["front_s"], 3)}
        except BaseException as e:
            # Cancelled or failed: back to the last checkpoint if there is one.
            try:
                if s.snaps is not None:
                    self.s_rewind(s, completed=False)
                else:
                    self.s_reset(s)
            except Exception as e2:     # v3: the front may be the thing that failed
                log(f"session {s.key}: rewind after failure also failed ({e2!r}); dropping it here")
                self.store.reset(s)
            log(f"session {s.key}: generation stopped ({e!r}); rewound")
            if self.client is not None and hasattr(self.model, "session_key"):
                self.model.session_key = None
            if isinstance(e, KeyboardInterrupt):
                return
            raise
        self.s_rewind(s, completed=completed)
        log(f"session {s.key}: {how}, reused {n_reused}/{len(prompt)} tokens, read "
            f"{len(prompt) - n_reused} in {t_prefill:.2f}s, {n_gen} generated, "
            f"total {info['total_s']:.2f}s, peak {info['peak_gb']} GB")
        if self.client is not None and hasattr(self.model, "session_key"):
            self.model.session_key = None
        self._learn_observe(info)
        if getattr(self, "_last_learn", None):
            info["learn"] = self._last_learn
        info["active"] = self.active_settings(info)
        yield ("done", info)


    def _main_pipeline(self):
        """Idea 1: admit up to pipeline_chats sessions; overlap packer of one with lead of another."""
        Empty = self._queue_mod.Empty
        pending = []          # (key, prompt, body, cancel, out) awaiting prefill
        decoding = []         # _PipeSlot in decode phase

        def pull_available():
            while True:
                try:
                    job = self.jobs.get_nowait()
                except Empty:
                    return
                if job is None:
                    pending.append(None)
                    return
                kind, payload, out = job
                if kind in ("call", "read"):
                    # All RPCs execute here on the owner thread, between fully
                    # drained rounds. Read-only memory stats need not wait for
                    # an entire chat; mutating admin operations still do.
                    if kind == "call" and (decoding or pending):
                        pending.append(("call", payload, out))
                    else:
                        try:
                            out.put(("ok", payload()))
                        except BaseException as e:
                            out.put(("err", e))
                else:
                    pending.append(("gen", payload, out))

        while True:
            pull_available()
            # Drain deferred calls only when idle.
            while pending and pending[0] is not None and pending[0][0] == "call" and not decoding:
                _, payload, out = pending.pop(0)
                try:
                    out.put(("ok", payload()))
                except BaseException as e:
                    out.put(("err", e))
                pull_available()

            if pending and pending[0] is None and not decoding and not any(
                    p is not None and p[0] == "gen" for p in pending):
                return

            # Admit at most one prefill per outer loop so decode can start
            # before later chats finish reading. Prefill itself stays serial
            # (one socket); starvation of decode was the N=3 TTFT bug.
            if (len(decoding) < self.pipeline_chats and pending
                    and pending[0] is not None and pending[0][0] == "gen"):
                _, payload, out = pending.pop(0)
                key, prompt, body, cancel = payload
                try:
                    slot = self._pipe_prefill(key, prompt, body, cancel, out)
                except BaseException as e:
                    out.put(("error", e))
                    out.put(None)
                else:
                    if slot is None:
                        out.put(None)  # cancelled during prefill
                    else:
                        decoding.append(slot)
                pull_available()

            if not decoding:
                # Block for the next job.
                job = self.jobs.get()
                if job is None:
                    return
                kind, payload, out = job
                if kind in ("call", "read"):
                    try:
                        out.put(("ok", payload()))
                    except BaseException as e:
                        out.put(("err", e))
                else:
                    pending.append(("gen", payload, out))
                continue

            # One overlapped decode round (or single-slot fallback).
            self._pipe_round(decoding)
            # Remove finished slots
            still = []
            for slot in decoding:
                if slot.finished:
                    try:
                        self._pipe_finish(slot)
                    except BaseException as e:
                        slot.out.put(("error", e))
                    slot.out.put(None)
                else:
                    still.append(slot)
            decoding = still

    def _pipe_prefill(self, key, prompt, body, cancel, out):
        """Prepare + prefill + checkpoint; return a _PipeSlot ready to decode, or None if cancelled."""
        mx = self.mx
        if self.client is not None:
            # Don't reset_stats per chat — aggregate across the pipeline wave.
            pass
        if hasattr(self.model, "session_key"):
            self.model.session_key = key
        s, n_reused, how = self._prepare_agent_prefix(key, prompt, body)
        t0 = time.time()
        try:
            rest = prompt[n_reused:]
            with request_wiring(self.wired_mode, self.G, self.model, self.stream):
                with mx.stream(self.stream):
                    for begin, end, boundary in self._prefill_chunks(prompt, n_reused, body):
                        if cancel.is_set():
                            raise KeyboardInterrupt("cancelled")
                        chunk = mx.array(prompt[begin:end])
                        self.model(chunk[None], cache=s.cache)
                        mx.eval([c.state for c in s.cache])
                        mx.clear_cache()
                        if boundary:
                            self.s_checkpoint(s, prompt[:end])
                            self._store_agent_prefix(key, prompt, body, s)
            self.s_checkpoint(s, prompt[:-1])
        except BaseException as e:
            try:
                if s.snaps is not None:
                    self.s_rewind(s, completed=False)
                else:
                    self.s_reset(s)
            except Exception:
                self.store.reset(s)
            if hasattr(self.model, "session_key"):
                self.model.session_key = None
            if isinstance(e, KeyboardInterrupt):
                return None
            raise
        t_prefill = time.time() - t0
        if body.get("seed") is not None:
            mx.random.seed(int(body["seed"]))
        sampler = self.make_sampler(temp=float(body.get("temperature", 0.0) or 0.0),
                                    top_p=float(body.get("top_p", 1.0) or 1.0),
                                    min_p=float(body.get("min_p", 0.0) or 0.0),
                                    top_k=int(body.get("top_k", 0) or 0))
        rp = body.get("repetition_penalty")
        procs = self.make_logits_processors(repetition_penalty=rp) if rp else None
        max_tokens = int(body.get("max_completion_tokens") or body.get("max_tokens")
                         or self.default_max_tokens)
        stop_words = body.get("stop") or []
        if isinstance(stop_words, str):
            stop_words = [stop_words]
        stops = self.G.make_stop_sequences(self.tokenizer, stop_words).matcher()
        slot = _PipeSlot(key=key, session=s, prompt=prompt, body=body, cancel=cancel, out=out,
                         how=how, n_reused=n_reused, t0=t0, t_prefill=t_prefill,
                         sampler=sampler, procs=procs, max_tokens=max_tokens, stops=stops,
                         next_tokens=list(prompt[-1:]))
        # Day 12: draft state for pipeline guess-ahead (N>=2 path).
        # Day 15: honor a learned/pinned guess-ahead off here too (was single-chat only).
        if self.draft_model is not None and self._learn_guess_override is not False:
            import mlx.core as mx
            from mlx_lm.models.cache import make_prompt_cache
            draft = self.draft_model
            dcache = make_prompt_cache(draft)
            remap_t2d = getattr(self, "draft_remap_t2d", None) or {}
            ids = list(prompt)
            if remap_t2d:
                ids = guess_ahead.apply_remap(ids, remap_t2d)
            y_in = mx.array(ids, dtype=mx.uint32)
            while y_in.size > 1:
                n_to = min(self.prefill_step, int(y_in.size) - 1)
                draft(y_in[:n_to][None], cache=dcache)
                mx.eval([c.state for c in dcache])
                y_in = y_in[n_to:]
                mx.clear_cache()
            slot.draft_cache = dcache
            slot.draft_y = y_in
            shut = self._chat_shutoffs.get(key)
            if shut is None:
                shut = guess_ahead.ChatShutoff(self.break_even_frac)
                self._chat_shutoffs[key] = shut
            slot.shut = shut
        return slot

    def _pipe_round(self, decoding):
        """Advance decoding slots; with 2+ chats, send packer(B) before lead(A).

        Fairness: prefer slots with fewer tokens so far (then oldest). Without
        that, need[0] in list order is the chat that just finished lead, so a
        third never-started chat starves until one of the first two finishes
        (~4 s TTFT on tg128).
        """
        mx = self.mx
        model = self.model
        if getattr(self.client, "_inflight", False):
            raise RuntimeError("pipeline: packer call still in flight at round start")

        for slot in decoding:
            if slot.cancel.is_set() and not slot.finished:
                slot.finished = True
                slot.cancelled = True
                slot.h = None

        active = [s for s in decoding if not s.finished]
        if not active:
            return

        def _pipe_make_drafts(slot, k):
            """Append up to k draft tokens onto slot; return draft id list (target space)."""
            if (self.draft_model is None or slot.draft_cache is None or k <= 0
                    or self._learn_guess_override is False
                    or (slot.shut is not None and slot.shut.disabled)):
                slot.pending_draft = []
                return []
            import mlx.core as mx
            draft = self.draft_model
            remap_d2t = getattr(self, "draft_remap_d2t", None) or {}
            ys = []
            y_in = slot.draft_y
            with mx.stream(self.stream):
                for _ in range(k):
                    logits = draft(y_in[None], cache=slot.draft_cache)
                    logits = logits[:, -1, :]
                    # greedy for draft proposals (temp 0 sampler on target is separate)
                    tok = mx.argmax(logits, axis=-1)
                    mx.eval(tok)
                    ys.append(tok)
                    y_in = tok
                slot.draft_y = y_in
            raw = [int(t.flatten()[0].item()) if hasattr(t, "flatten") else int(t) for t in ys]
            if remap_d2t:
                raw_t = guess_ahead.apply_remap(raw, remap_d2t)
            else:
                raw_t = raw
            slot.pending_draft = list(raw_t)
            return list(raw_t)

        def packer_fetch(slot):
            model.session_key = slot.key
            toks = list(slot.next_tokens)
            room = max(0, slot.max_tokens - slot.n_gen)
            k = min(int(self.speculate_k), max(0, room - 1)) if self.draft_model is not None else 0
            if k and not self._speculate_trim_room(slot.session.cache, k + 1):
                k = 0
            drafts = _pipe_make_drafts(slot, k)
            if drafts:
                toks = toks + drafts
            slot.h_n = len(toks)
            with mx.stream(self.stream):
                # Sync fwd when drafting: begin/finish + later trim desyncs the TB socket.
                if drafts and hasattr(model, "packer_fwd"):
                    slot.h = model.packer_fwd(toks)
                else:
                    model.begin_packer(toks)
                    slot.h = model.finish_packer()

        def packer_begin(slot):
            model.session_key = slot.key
            toks = list(slot.next_tokens)
            room = max(0, slot.max_tokens - slot.n_gen)
            k = min(int(self.speculate_k), max(0, room - 1)) if self.draft_model is not None else 0
            if k and not self._speculate_trim_room(slot.session.cache, k + 1):
                k = 0
            drafts = _pipe_make_drafts(slot, k)
            if drafts:
                toks = toks + drafts
            slot.h_n = len(toks)
            with mx.stream(self.stream):
                model.begin_packer(toks)

        def packer_finish(slot):
            model.session_key = slot.key
            with mx.stream(self.stream):
                slot.h = model.finish_packer()

        def fair_key(s):
            return (s.n_gen, s.t0)

        ready = sorted([s for s in active if s.h is not None], key=fair_key)
        need = sorted([s for s in active if s.h is None], key=fair_key)

        # Nobody has hidden states yet: prime the neediest (serial); next rounds overlap.
        if not ready:
            packer_fetch(need[0])
            return

        # Draft/speculate issues trim RPCs during lead_sample. Overlapping that with
        # packer_begin/finish on the same TB socket desyncs the protocol (trim
        # response vs hidden-state). Keep chats multiplexed but serialize TB.
        if self.draft_model is not None or int(getattr(self, "prompt_lookup_n", 0) or 0) > 0:
            slot = ready[0]
            self._pipe_lead_sample(slot)
            # No trim RPC may overlap an in-flight forward, but rotate chats
            # after the block instead of repeatedly priming the same slot.
            if need:
                packer_fetch(need[0])
            elif not slot.finished:
                packer_fetch(slot)
            return

        if len(active) == 1:
            slot = ready[0]
            self._pipe_lead_sample(slot)
            if not slot.finished:
                packer_fetch(slot)
            return

        # Two or more: overlap packer of a needy slot with lead of a ready one.
        A = ready[0]
        B = need[0] if need else None
        if B is None:
            # Everyone has h — lead fairest ready; overlap its next packer with lead of next.
            others = ready[1:]
            if others:
                B = others[0]
                self._pipe_lead_sample(A)
                if A.finished and not B.finished:
                    self._pipe_lead_sample(B)
                    if not B.finished:
                        packer_fetch(B)
                    return
                if not A.finished:
                    packer_begin(A)
                    if not B.finished and B.h is not None:
                        self._pipe_lead_sample(B)
                    packer_finish(A)
                    if not B.finished and B.h is None:
                        packer_fetch(B)
                return
            self._pipe_lead_sample(A)
            if not A.finished:
                packer_fetch(A)
            return

        # Classic overlap: A ready, B needs packer (B is the most starved needy).
        packer_begin(B)
        self._pipe_lead_sample(A)
        packer_finish(B)
        # A now needs next h if still running — leave A.h None for next round.

    def _pipe_emit_token(self, slot, token, from_draft=False):
        """Detokenize + emit one piece; update counters; return finish reason or None."""
        if slot.ttft is None:
            slot.ttft = time.time() - slot.t0
        slot.n_gen += 1
        if from_draft:
            slot.n_from_draft += 1
        slot.all_tokens.append(token)
        if slot.shut is not None:
            was = slot.shut.disabled
            slot.shut.observe(bool(from_draft))
            if slot.shut.disabled and not was:
                log(f"split speculate: {slot.shut.reason}")
        if slot._detok is None:
            import copy
            detok = copy.deepcopy(getattr(self.tokenizer, "detokenizer", None))
            if detok is not None:
                try:
                    detok.reset()
                except Exception:
                    pass
                slot._detok = detok
        text_piece = ""
        if slot._detok is not None:
            try:
                slot._detok.add_token(token)
                # last_segment is "" while the detokenizer holds back a partial
                # word/byte; that's normal. Never fall back to .text (the whole
                # reply so far) or the stream re-sends everything from the start.
                text_piece = slot._detok.last_segment or ""
            except Exception:
                text_piece = self.tokenizer.decode([token])
        else:
            text_piece = self.tokenizer.decode([token])
        finish = None
        if slot.stops.advance(token):
            finish = "stop"
        eos = getattr(self.tokenizer, "eos_token_ids", None)
        if eos is None:
            eos = self.tokenizer.eos_token_id
        if isinstance(eos, (list, tuple, set, frozenset)):
            eos_set = set(eos)
        else:
            eos_set = {eos} if eos is not None else set()
        if token in eos_set:
            finish = "stop"
        if slot.n_gen >= slot.max_tokens:
            finish = finish or "length"
        if finish is not None and slot._detok is not None:
            try:
                slot._detok.finalize()
                text_piece += slot._detok.last_segment or ""
            except Exception:
                pass
        slot.out.put(("piece", text_piece, finish is not None))
        return finish

    def _pipe_lead_sample(self, slot):
        """Run lead layers on slot.h, sample; multi-token verify when drafts pending."""
        mx, G = self.mx, self.G
        model = self.model
        if slot.h is None or slot.finished:
            return
        if slot.cancel.is_set():
            slot.finished = True
            slot.cancelled = True
            slot.h = None
            return
        model.session_key = slot.key
        drafts = list(slot.pending_draft or [])
        n_in = int(getattr(slot, "h_n", 1) or 1)
        with request_wiring(self.wired_mode, G, self.model, self.stream):
            with mx.stream(self.stream):
                logits = model.lead_logits(slot.h, slot.session.cache)
                mx.eval(logits, [c.state for c in slot.session.cache])
                # logits: [1, n_in, vocab] for multi-token packer fwd
                if logits.ndim == 2:
                    logits = logits[:, None, :]
                n_pred = int(logits.shape[1])
                # Sample each position sequentially (processors see growing prefix)
                sampled = []
                prev = list(slot.all_tokens)
                for i in range(n_pred):
                    lg = logits[:, i, :]
                    if slot.procs:
                        for p in slot.procs:
                            lg = p(prev, lg)
                    y = slot.sampler(lg)
                    mx.eval(y)
                    tok = int(y.flatten()[0].item()) if hasattr(y, "flatten") else int(y)
                    sampled.append(tok)
                    prev.append(tok)
        slot.h = None
        # One packer forward carried [previous token, d1..dk]. Verify only
        # the accepted prefix, then emit one target bonus/replacement token.
        from verify_block import cache_plan
        n_draft = len(drafts)
        if n_pred != n_draft + 1:
            raise RuntimeError("split verify returned wrong token count")
        accepted, finish = 0, None
        while accepted < n_draft and sampled[accepted] == drafts[accepted]:
            finish = self._pipe_emit_token(slot, sampled[accepted], from_draft=True)
            accepted += 1
            if finish is not None:
                break
        stopped_in_draft = finish is not None
        if not stopped_in_draft:
            finish = self._pipe_emit_token(slot, sampled[accepted], from_draft=False)
        plan = cache_plan(n_draft, accepted, stopped_in_draft=stopped_in_draft)
        if plan["target_trim"]:
            # Never continue with corrupt KV after a failed trim.
            model.trim_caches(plan["target_trim"], slot.session.cache)
        if slot.draft_cache is not None and self.draft_model is not None and n_draft:
            from mlx_lm.models.cache import trim_prompt_cache
            if plan["draft_trim"]:
                trimmed = trim_prompt_cache(slot.draft_cache, plan["draft_trim"])
                if trimmed != plan["draft_trim"]:
                    raise RuntimeError("draft cache cannot rewind speculative block")
            remap = getattr(self, "draft_remap_t2d", None) or {}
            last = slot.all_tokens[-1]
            ids = [remap.get(last, last)]
            if plan["replay_last_draft"]:
                ids.insert(0, remap.get(drafts[-1], drafts[-1]))
            slot.draft_y = mx.array(ids, mx.uint32)
        slot.pending_draft = []
        if finish is not None:
            slot.finished = True
            slot.finish = finish
            slot.next_tokens = [slot.all_tokens[-1]]
            return
        slot.next_tokens = [slot.all_tokens[-1]]

    def _pipe_finish(self, slot):
        completed = not slot.cancelled and slot.finished
        try:
            if slot.cancelled:
                if slot.session.snaps is not None:
                    self.s_rewind(slot.session, completed=False)
                else:
                    self.s_reset(slot.session)
            else:
                self.s_rewind(slot.session, completed=True)
        except Exception as e2:
            log(f"session {slot.key}: pipeline rewind failed ({e2!r})")
            self.store.reset(slot.session)
        if hasattr(self.model, "session_key"):
            self.model.session_key = None
        if slot.cancelled:
            return
        mx = self.mx
        info = {"prompt_tokens": len(slot.prompt), "cached_tokens": slot.n_reused, "how": slot.how,
                "completion_tokens": slot.n_gen, "finish": slot.finish or "length",
                "prefill_s": round(slot.t_prefill, 3),
                "ttft_s": round(slot.ttft or 0, 3), "total_s": round(time.time() - slot.t0, 3),
                "t0": float(slot.t0),
                "peak_gb": round(mx.get_peak_memory() / 1e9, 2),
                "pipeline": True}
        if self.draft_model is not None and slot.draft_cache is not None:
            info["speculate"] = {
                "k": self.speculate_k,
                "from_draft": slot.n_from_draft,
                "accepted_frac": round(slot.n_from_draft / max(slot.n_gen, 1), 3),
                "pipeline": True,
            }
        if self.client is not None:
            st = dict(self.client.stats)
            info["split"] = {"calls": st["calls"], "mb_out": round(st["bytes_out"] / 1e6, 2),
                             "mb_in": round(st["bytes_in"] / 1e6, 2),
                             "wait_s": round(st["wait_s"], 3), "front_s": round(st["front_s"], 3),
                             "net_s": round(st["wait_s"] - st["front_s"], 3)}
        log(f"session {slot.key}: pipeline, reused {slot.n_reused}/{len(slot.prompt)}, "
            f"{slot.n_gen} generated, total {info['total_s']:.2f}s, peak {info['peak_gb']} GB")
        self._learn_observe(info)
        if getattr(self, "_last_learn", None):
            info["learn"] = self._last_learn
        info["active"] = self.active_settings(info)
        slot.out.put(("done", info))


    def text_machine(self, prompt, stop_words):
        if self.model_type == "gpt_oss":
            return HarmonyAdapter()
        return StateMachineAdapter(self.G, self.tokenizer, prompt, stop_words)



def _timing_rates(info):
    """Native rates shared by structured usage, UI and timing log."""
    pt = int(info.get("prompt_tokens") or 0)
    cached = int(info.get("cached_tokens") or 0)
    n = int(info.get("completion_tokens") or 0)
    ttft = float(info.get("ttft_s") or 0.0)
    pre = float(info.get("prefill_s") or ttft or 0.0)
    total = float(info.get("total_s") or 0.0)
    new = max(pt - cached, 0)
    read_tps = new / pre if pre > 0 else 0.0
    gen_s = total - ttft
    write_tps = (n - 1) / gen_s if n > 1 and gen_s > 0 else 0.0
    return {"read_tok_s": round(read_tps, 1), "write_tok_s": round(write_tps, 2)}


def _timing_line(info):
    """Per-reply timing summary, matching the UI stats line:
    Read X tok at Y tok/s . Write Z tok at W tok/s . first token A s . total B s"""
    pt = int(info.get("prompt_tokens") or 0)
    cached = int(info.get("cached_tokens") or 0)
    n = int(info.get("completion_tokens") or 0)
    ttft = float(info.get("ttft_s") or 0.0)
    total = float(info.get("total_s") or 0.0)
    rates = _timing_rates(info)
    read_tps, write_tps = rates["read_tok_s"], rates["write_tok_s"]
    mode = "split" if info.get("split") else "single"
    return (f"timing ({mode}): read {pt} tok ({cached} cached) at {read_tps:.1f} tok/s, "
            f"write {n} tok at {write_tps:.2f} tok/s, first token {ttft:.2f} s, total {total:.2f} s")


def _think_label(body):
    """Thinking setting a request asked for, for the log: on / off / effort / default."""
    t = body.get("thinking")
    if isinstance(t, bool):
        return "on" if t else "off"
    kw = body.get("chat_template_kwargs") or {}
    if kw.get("reasoning_effort"):
        return f"effort {kw['reasoning_effort']}"
    for k in ("enable_thinking", "thinking"):
        if isinstance(kw.get(k), bool):
            return "on" if kw[k] else "off"
    return "default"


def _ntok(tokenizer, text):
    if not text:
        return 0
    try:
        return len(tokenizer.encode(text, add_special_tokens=False))
    except Exception:
        return len(text) // 4


def thinking_kwargs(tokenizer, on, kw):
    """Turn a plain thinking on/off into whatever this model's template understands.

    Returns (kwargs, prefill_close). Explicit chat_template_kwargs win.
    - templates with a thinking switch (enable_thinking / thinking; mlx_lm maps
      enable_thinking to the model's own name): pass it through
    - gpt-oss style reasoning_effort (no off switch): off -> "low"
    - no switch but the model thinks in tags: off -> prefill an empty think block
    """
    kw = dict(kw)
    tpl = getattr(tokenizer, "chat_template", None) or ""
    if not isinstance(tpl, str):
        tpl = str(tpl)
    if "reasoning_effort" in tpl:
        if not on:
            kw.setdefault("reasoning_effort", "low")
        return kw, False
    if "enable_thinking" in tpl or getattr(tokenizer, "_thinking_kwarg", None) not in (None, "enable_thinking") \
            or "thinking" in tpl:
        kw.setdefault("enable_thinking", bool(on))
        return kw, False
    if not on and getattr(tokenizer, "has_thinking", False):
        return kw, True
    return kw, False


# Chat templates whose end-of-turn marker isn't in the model's eos list.
# Gemma 4 ends a reply with <turn|> but only lists <eos>; without this it
# keeps talking (often looping its own reasoning) until max_tokens.
TURN_END_TOKENS = ("<turn|>", "<end_of_turn>")


def add_turn_end_stops(tokenizer, log=None):
    """Add known end-of-turn tokens to the tokenizer's stop set when present."""
    vocab = {}
    try:
        vocab = tokenizer.get_vocab()
    except Exception:
        pass
    added = []
    for tok in TURN_END_TOKENS:
        if tok not in vocab:
            continue
        tid = vocab[tok]
        ids = getattr(tokenizer, "eos_token_ids", None)
        if ids is not None and tid in ids:
            continue
        try:
            tokenizer.add_eos_token(tok)
            added.append(tok)
        except Exception:
            pass
    if added and log:
        log(f"stop tokens: added {', '.join(added)}")
    return added

class _PipeSlot:
    __slots__ = ("key", "session", "prompt", "body", "cancel", "out", "how", "n_reused",
                 "t0", "t_prefill", "sampler", "procs", "max_tokens", "stops",
                 "next_tokens", "all_tokens", "h", "n_gen", "ttft", "finished",
                 "cancelled", "finish", "_detok", "draft_cache", "draft_y",
                 "pending_draft", "h_n", "n_from_draft", "shut")

    def __init__(self, **kw):
        for k, v in kw.items():
            setattr(self, k, v)
        self.all_tokens = list(self.prompt)
        self.h = None
        self.n_gen = 0
        self.ttft = None
        self.finished = False
        self.cancelled = False
        self.finish = None
        self._detok = None
        self.draft_cache = None
        self.draft_y = None
        self.pending_draft = []
        self.h_n = 1
        self.n_from_draft = 0
        self.shut = None



class HarmonyAdapter:
    def __init__(self):
        self.h = HarmonySplitter()

    def feed(self, text, final=False):
        out = self.h.feed(text)
        return out + (self.h.flush() if final else [])


class StateMachineAdapter:
    """mlx_lm.server's own reasoning/tool text state machine, used the same way."""

    def __init__(self, G, tokenizer, prompt, stop_words):
        self.TSM = G.TextStateMachine
        sm = G.make_text_state_machine(tokenizer, stop_words)
        initial = "normal"
        if tokenizer.has_thinking:
            if tokenizer.rfind_think_start(prompt) > tokenizer.rfind_think_end(prompt):
                initial = "reasoning"
        initial = getattr(tokenizer, "response_initial_state", None) or initial
        self.state = sm.make_state(initial)

    def feed(self, text, final=False):
        self.state, segs = self.TSM.split(self.state, text)
        if final:
            self.state, flushed, cur = self.TSM.flush(self.state)
            segs.append((cur, flushed))
        return [(k, t) for k, t in segs if t]


def _version(pkg):
    try:
        from importlib.metadata import version
        return version(pkg)
    except Exception:
        return "?"


def make_handler(engine: "Engine"):
    class H(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def log_message(self, fmt, *a):
            pass

        def _json(self, code, obj):
            data = json.dumps(obj).encode()
            self.send_response(code)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def _body(self):
            n = int(self.headers.get("Content-Length") or 0)
            try:
                return json.loads(self.rfile.read(n) or b"{}")
            except ValueError:
                return None

        def do_GET(self):
            if self.path.startswith("/caravan/settings"):
                fn = getattr(engine, "active_settings", None)
                if fn is None:
                    return self._json(404, {"error": "no settings on this worker"})
                try:
                    return self._json(200, {"active": fn()})
                except Exception as e:
                    return self._json(500, {"error": f"{type(e).__name__}: {e}"})
            if self.path.startswith("/health"):
                return self._json(200, {"status": "ok", "worker": "caravan",
                                        "split": bool(engine.split)})
            if self.path.startswith("/v1/models"):
                return self._json(200, {"object": "list", "data": [
                    {"id": str(engine.model_dir), "object": "model", "owned_by": "caravan"}]})
            if self.path.startswith("/caravan/split"):
                return self._json(200, engine.call(engine.split_info) or {"split": False})
            if self.path.startswith("/caravan/cache"):
                return self._json(200, engine.call(lambda: {
                    "sessions": engine.store.describe(), "persist": engine.store.persist,
                    "cache_dir": str(engine.store.cache_dir)}))
            self._json(404, {"error": "not found"})

        def do_POST(self):
            body = self._body()
            if not isinstance(body, dict):
                return self._json(400, {"error": "bad json"})
            if self.path.split("?")[0] == "/caravan/sweep":
                from sweep_control import apply
                try:
                    return self._json(200, engine.call(lambda: apply(engine, body)))
                except ValueError as e:
                    return self._json(400, {"error": str(e)})
                except Exception as e:
                    return self._json(500, {"error": f"{type(e).__name__}: {e}"})
            if self.path.startswith("/caravan/cache/"):
                op = self.path.split("?")[0].rsplit("/", 1)[-1]
                if op == "drop":
                    keys = [k for k in body.get("keys") or [] if valid_key(k)]
                    return self._json(200, {"dropped": engine.call(lambda: engine.s_drop(keys))})
                key = body.get("key")
                if not valid_key(key):
                    return self._json(400, {"error": "bad key"})
                if op == "save":
                    return self._json(200, {"result": engine.call(lambda: engine.s_save(key))})
                if op == "restore":
                    return self._json(200, {"result": engine.call(lambda: engine.s_restore(key))})
                return self._json(404, {"error": "unknown op"})
            if self.path.startswith("/v1/chat/completions"):
                return self._complete(body, chat=True)
            if self.path.startswith("/v1/completions"):
                return self._complete(body, chat=False)
            self._json(404, {"error": "not found"})

        def _complete(self, body, chat):
            key = self.headers.get("X-Caravan-Session")
            guard_meta = None
            if chat:
                try:
                    body, guard_meta = engine.apply_memory_guard(body, session_key=key)
                except Exception as e:
                    log(f"memory_guard failed open: {e!r}")
                    guard_meta = {"ok": True, "trimmed_turns": 0, "error": None, "note": f"guard skipped: {e}"}
                if guard_meta and guard_meta.get("error") and not guard_meta.get("ok", True):
                    return self._json(507, {"error": guard_meta["error"], "memory_guard": guard_meta})
            try:
                prompt = engine.chat_prompt(body) if chat else engine.text_prompt(body)
            except Exception as e:
                return self._json(400, {"error": f"prompt: {e}"})
            if len(prompt) < 1:
                return self._json(400, {"error": "empty prompt"})
            stream = bool(body.get("stream"))
            rid = f"chatcmpl-{uuid.uuid4().hex[:12]}"
            created = int(time.time())
            model = body.get("model") or str(engine.model_dir)
            obj = "chat.completion.chunk" if stream else "chat.completion"
            if not chat:
                obj = "text_completion"
            sm = engine.text_machine(prompt, body.get("stop") or []) if chat else None
            text, reasoning = [], []
            seen = {"r": [], "c": []}   # for the per-reply thinking log line

            def pack(content, rs, finish=None, usage=None):
                ch = {"index": 0, "finish_reason": finish}
                if chat:
                    k = "delta" if stream else "message"
                    ch[k] = {"role": "assistant"}
                    if content or not stream:
                        ch[k]["content"] = content if content else None
                    if rs:
                        # llama.cpp's field name, plus mlx_lm.server's, so either client style works
                        ch[k]["reasoning_content"] = rs
                        ch[k]["reasoning"] = rs
                else:
                    ch["text"] = content
                out = {"id": rid, "object": obj, "created": created, "model": model, "choices": [ch]}
                if usage:
                    out["usage"] = usage
                return out

            if stream:
                self.send_response(200)
                self.send_header("Content-Type", "text/event-stream")
                self.send_header("Cache-Control", "no-cache")
                self.send_header("Transfer-Encoding", "chunked")
                self.end_headers()

            def send(obj_):
                d = f"data: {json.dumps(obj_)}\n\n".encode() if isinstance(obj_, dict) else obj_
                self.wfile.write(b"%x\r\n%s\r\n" % (len(d), d))
                self.wfile.flush()

            info = None
            lead = [True]

            def strip_lead(c):
                # "<think>\n\n</think>\n\n" leaves blank lines before the answer;
                # llama.cpp trims them, so do the same.
                c = strip_end_markers(c)
                if lead[0] and c:
                    c = c.lstrip()
                    if c:
                        lead[0] = False
                return c

            gen = engine.run(key, prompt, body)
            try:
                for ev in gen:
                    if ev[0] == "done":
                        info = ev[1]
                        continue
                    _, piece, last = ev
                    segs = sm.feed(piece, final=last) if sm else [("normal", piece)]
                    c = strip_lead("".join(t for k, t in segs if k == "normal"))
                    r = "".join(t for k, t in segs if k == "reasoning")
                    seen["c"].append(c)
                    seen["r"].append(r)
                    if stream and (c or r):
                        send(pack(c, r))
                    else:
                        text.append(c)
                        reasoning.append(r)
                if sm:
                    tail = sm.feed("", final=True)
                    c = strip_lead("".join(t for k, t in tail if k == "normal"))
                    r = "".join(t for k, t in tail if k == "reasoning")
                    seen["c"].append(c)
                    seen["r"].append(r)
                    if stream and (c or r):
                        send(pack(c, r))
                    else:
                        text.append(c)
                        reasoning.append(r)
            except (BrokenPipeError, ConnectionResetError):
                return
            except Exception as e:
                log(f"generation failed: {e!r}")
                if stream:
                    return
                return self._json(500, {"error": str(e)})
            finally:
                gen.close()   # client gone -> cancels the generation on the mlx thread
            if chat and info is not None:
                try:
                    log(f"session {key}: thinking {_think_label(body)}, reasoning "
                        f"{_ntok(engine.tokenizer, ''.join(seen['r']))} tok, answer "
                        f"{_ntok(engine.tokenizer, ''.join(seen['c']))} tok "
                        f"(of {info['completion_tokens']} generated, max {body.get('max_tokens')})")
                except Exception:
                    pass
            if info is not None:
                try:
                    log(f"session {key}: " + _timing_line(info))
                except Exception:
                    pass
            if info is not None and guard_meta:
                info["memory_guard"] = guard_meta
            usage = {"prompt_tokens": info["prompt_tokens"], "completion_tokens": info["completion_tokens"],
                     "total_tokens": info["prompt_tokens"] + info["completion_tokens"],
                     "prompt_tokens_details": {"cached_tokens": info["cached_tokens"]},
                     "caravan": {k: info[k] for k in ("how", "prefill_s", "ttft_s", "total_s", "peak_gb", "split", "speculate", "learn", "active", "memory_guard")
                                 if k in info}}
            usage["caravan"].update(_timing_rates(info))
            try:
                if stream:
                    send(pack("", "", finish=info["finish"]))
                    if (body.get("stream_options") or {}).get("include_usage"):
                        u = pack("", "", usage=usage)
                        u["choices"] = []
                        send(u)
                    send(b"data: [DONE]\n\n")
                    self.wfile.write(b"0\r\n\r\n")
                    self.wfile.flush()
                else:
                    self._json(200, pack(strip_end_markers("".join(text)), "".join(reasoning), finish=info["finish"], usage=usage))
            except (BrokenPipeError, ConnectionResetError):
                pass

    return H


# End-of-turn tokens some tokenizers decode into the reply text (Llama 3.x
# <|eot_id|> in particular). They are never part of the answer.
END_MARKERS = ("<|eot_id|>", "<|eom_id|>", "<|end_of_text|>", "<|im_end|>")


def strip_end_markers(text):
    if not text:
        return text
    for m in END_MARKERS:
        if m in text:
            text = text.replace(m, "")
    return text


def parse_bytes(v):
    if v is None:
        return None
    s = str(v).strip().lower()
    mult = {"k": 1 << 10, "kib": 1 << 10, "m": 1 << 20, "mib": 1 << 20, "g": 1 << 30, "gib": 1 << 30}
    for suf in sorted(mult, key=len, reverse=True):
        if s.endswith(suf):
            return int(float(s[: -len(suf)]) * mult[suf])
    return int(float(s))


def build_parser():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--model", required=True)
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=8092)
    ap.add_argument("--prompt-cache-size", type=int, default=4, help="max sessions kept in memory")
    ap.add_argument("--prompt-cache-bytes", type=parse_bytes, default=2 << 30,
                    help="memory budget for all sessions' caches, default 2GiB "
                         "(the one in use is never evicted)")
    ap.add_argument("--prefill-step-size", type=int, default=2048)
    ap.add_argument("--max-tokens", type=int, default=512, help="default when a request sets none")
    ap.add_argument("--cache-dir", default=os.environ.get("CARAVAN_MLX_CACHE_DIR") or DEFAULT_CACHE_DIR)
    ap.add_argument("--no-persist", action="store_true", help="never write or read cache files")
    ap.add_argument("--kv-bits", type=int, choices=(4, 8), default=None,
                    help="quantize full-attention cache layers (mlx_lm QuantizedKVCache); "
                         "halves (8) or quarters (4) their memory and file size")
    ap.add_argument("--kv-group-size", type=int, default=64)
    ap.add_argument("--wired-limit", choices=("startup", "per-request", "off"), default="startup",
                    help="startup: set Metal wired limit once at load and hold it (like mlx_lm.server); "
                         "per-request: v2 behaviour (raise/drop around each request); off: never touch it")
    ap.add_argument("--cache-limit-gb", type=float, default=float(__import__("os").environ.get("CARAVAN_CACHE_LIMIT_GB", "1.5")),
                    help="mx.set_cache_limit GB (freed-buffer pool); env CARAVAN_CACHE_LIMIT_GB")
    ap.add_argument("--memory-limit-gb", type=float,
                    default=(float(__import__("os").environ["CARAVAN_MEMORY_LIMIT_GB"])
                             if __import__("os").environ.get("CARAVAN_MEMORY_LIMIT_GB") else None),
                    help="mx.set_memory_limit GB soft cap; env CARAVAN_MEMORY_LIMIT_GB")
    ap.add_argument("--memory-safety-gb", type=float,
                    default=float(__import__("os").environ.get("CARAVAN_MEMORY_SAFETY_GB", "1.75")),
                    help="RAM to keep free when sizing chat KV (memory guard)")
    ap.add_argument("--sweep-paused", action="store_true", help=argparse.SUPPRESS)
    ap.add_argument("--memory-dir", default=__import__("os").environ.get("CARAVAN_MEMORY_DIR") or "~/.caravan/memory",
                    help="Obsidian-style Markdown archive root (env CARAVAN_MEMORY_DIR)")
    ap.add_argument("--memory-recall-tokens", type=int, default=500,
                    help="Max tokens of recalled note snippets to inject")
    ap.add_argument("--memory-recall-all", action="store_true",
                    help="Search all session archives, not only this session")
    # v3: one model split across two Minis (agent/mlx_split.py)
    ap.add_argument("--split-role", choices=("none", "lead", "packer", "head", "front"), default="none",
                    help="lead: HTTP + last layers + lm_head, asks --split-peer (Packer 1) for the first layers; "
                         "packer: embeddings + first layers, listens on --split-listen (no HTTP). "
                         "head/front: deprecated aliases for lead/packer")
    ap.add_argument("--split-counts", help="N-stage layer counts in forward order, e.g. 10,10,12")
    ap.add_argument("--split-stage-index", type=int, help="packer index (zero-based) in --split-counts")
    ap.add_argument("--split-upstream", help="middle packer: previous packer's HOST:PORT")
    ap.add_argument("--split-peer", default=None, help="lead: Packer 1's HOST:PORT (Thunderbolt address)")
    ap.add_argument("--split-listen", default=None, help="packer: HOST:PORT to listen on (Thunderbolt address)")
    ap.add_argument("--split-packer-layers", "--split-front-layers", dest="split_front_layers", type=int, default=None, metavar="K",
                    help="layers on Packer 1 (default: auto from each Mini's RAM + model; "
                         "idea-5 balanced cuts when RAM is equal). "
                         "--split-front-layers is a deprecated alias")
    # Default on; CARAVAN_MLX_SPLIT_KEEPALIVE=0/false/off disables. --no-split-keepalive too.
    _ka_env = os.environ.get("CARAVAN_MLX_SPLIT_KEEPALIVE")
    _ka_default = True if _ka_env is None else _ka_env.strip().lower() not in ("0", "false", "off", "no")
    ap.add_argument("--split-keepalive", default=_ka_default, action=argparse.BooleanOptionalAction,
                    help="keep Metal warm while waiting on the peer (default: on; cuts ~5 ms/half/token "
                         "idle cool-down). --no-split-keepalive or CARAVAN_MLX_SPLIT_KEEPALIVE=0 disables")
    _pipe_env = os.environ.get("CARAVAN_MLX_SPLIT_PIPELINE_CHATS")
    _pipe_env_set = bool(_pipe_env and _pipe_env.strip().isdigit())
    _pipe_default = int(_pipe_env) if _pipe_env_set else None  # None = auto (ROADMAP #13a)
    ap.add_argument("--split-pipeline-chats", type=int, default=_pipe_default, metavar="N",
                    help="idea 1: overlap packer/lead across up to N concurrent split chats "
                         "(default: auto from free memory / model size, capped at 2; "
                         "pass N to pin). Env CARAVAN_MLX_SPLIT_PIPELINE_CHATS")
    ap.set_defaults(split_pipeline_chats_from_env=_pipe_env_set)
    _draft_env = os.environ.get("CARAVAN_MLX_SPLIT_DRAFT_MODEL")
    ap.add_argument("--native-mtp", action="store_true", help="experimental matching native MTP head; single Mini, greedy only")
    ap.add_argument("--split-draft-model", default=_draft_env or None, metavar="DIR",
                    help="idea 3: local MLX draft model dir on the lead (overrides auto-pair). "
                         "Env CARAVAN_MLX_SPLIT_DRAFT_MODEL")
    ap.add_argument("--no-split-draft", action="store_true",
                    help="idea 3: disable draft auto-pair and ignore --split-draft-model / env")
    _auto_env = os.environ.get("CARAVAN_MLX_SPLIT_DRAFT_AUTO_DOWNLOAD")
    _auto_default = bool(_auto_env and _auto_env.strip().lower() in ("1", "true", "yes", "on", "y"))
    ap.add_argument("--split-draft-auto-download", action="store_true", default=_auto_default,
                    help="idea 3: download a matched guesser without prompting "
                         "(non-interactive default is off). Env CARAVAN_MLX_SPLIT_DRAFT_AUTO_DOWNLOAD=1")
    ap.add_argument("--split-draft-skip-first-load", action="store_true",
                    help="idea 3: skip the first-load quality/speed gate (tests / already trusted)")
    _sk_env = os.environ.get("CARAVAN_MLX_SPLIT_SPECULATE_K")
    _sk_explicit = bool(_sk_env and _sk_env.strip().isdigit())
    _sk_default = int(_sk_env) if _sk_explicit else 4
    ap.add_argument("--split-speculate-k", type=int, default=_sk_default, metavar="K",
                    help="idea 3: draft tokens per verify round (default: pairing table, else 4). "
                         "Env CARAVAN_MLX_SPLIT_SPECULATE_K")
    # Stash whether k came from env; CLI presence refined after parse.
    ap.set_defaults(split_speculate_k_explicit=_sk_explicit)
    _pl_env = os.environ.get("CARAVAN_MLX_SPLIT_PROMPT_LOOKUP")
    _pl_default = int(_pl_env) if (_pl_env and _pl_env.strip().isdigit()) else 0
    ap.add_argument("--split-prompt-lookup", type=int, default=_pl_default, metavar="N",
                    help="idea 3 draft-free: prompt-lookup / n-gram max size N (0=off). "
                         "Env CARAVAN_MLX_SPLIT_PROMPT_LOOKUP")
    _pla_env = os.environ.get("CARAVAN_MLX_SPLIT_PROMPT_LOOKUP_ADAPTIVE", "")
    _pla_default = _pla_env.strip().lower() in ("1", "true", "yes", "on")
    ap.add_argument("--split-prompt-lookup-adaptive", action="store_true", default=_pla_default,
                    help="Day 12: only use prompt-lookup when overlapping/accepting "
                         "(needs --split-prompt-lookup N>0; also "
                         "CARAVAN_MLX_SPLIT_PROMPT_LOOKUP_ADAPTIVE=1)")
    _spc_env = os.environ.get("CARAVAN_MLX_SPLIT_SHARED_PREFIX_CACHE", "")
    _spc_default = _spc_env.strip().lower() in ("1", "true", "yes", "on")
    ap.add_argument("--split-shared-prefix-cache", action="store_true", default=_spc_default,
                    help="Day 12/13: cache shared system-prompt prefixes across sessions "
                         "(off by default; learn-from-chats may turn it on per model; "
                         "flag/env pins on — also CARAVAN_MLX_SPLIT_SHARED_PREFIX_CACHE=1)")
    # ROADMAP #13b: learn from real chats (Day 10). CARAVAN_NO_LEARN=1 disables.
    _learn_env = os.environ.get("CARAVAN_NO_LEARN", "")
    _learn_off = _learn_env.strip().lower() in ("1", "true", "yes", "on")
    ap.add_argument("--no-split-shared-prefix-cache", action="store_true",
                    help="Day 15: pin shared start off (learn won't turn it on)")
    ap.add_argument("--pin-guess-ahead", action="store_true",
                    help="Day 15: pin guess-ahead on when a draft is loaded (learn won't turn it off)")
    ap.add_argument("--no-learn", action="store_true", default=_learn_off,
                    help="ROADMAP #13b: disable learn-from-real-chats (also CARAVAN_NO_LEARN=1)")
    ap.add_argument("--learn-reload-auto", default="", metavar="NAMES",
                    help="Day 15: comma list of reload options left on Auto "
                         "(kv_bits,fuse_kernels,keepalive); self-tuning scores them "
                         "and queues reload trials. The web launcher sets this.")
    ap.add_argument("--tuned-settings", default=os.environ.get("CARAVAN_TUNED_SETTINGS") or None,
                    metavar="PATH",
                    help="ROADMAP #13b: path for per-model learned settings "
                         "(default ~/.caravan/mlx/tuned-settings.json; env CARAVAN_TUNED_SETTINGS)")
    # ROADMAP #17 fused kernels (Day 12). Off by default. Env CARAVAN_FUSE_KERNELS.
    _fuse_env = os.environ.get("CARAVAN_FUSE_KERNELS")
    ap.add_argument("--fuse-kernels", default=_fuse_env or None, metavar="MODE",
                    help="ROADMAP #17: off|force-fused|metal-swiglu|all (default off; "
                         "also CARAVAN_FUSE_KERNELS). Off-by-default experiment.")
    return ap


def front_main(args):
    """v3 front stage: embeddings + the first layers, its own session caches."""
    import mlx.core as mx
    import mlx_split as S
    try:
        import fuse_kernels as FK
        FK.apply_fuse_kernels(FK.resolve_mode(getattr(args, "fuse_kernels", None)), log=log)
    except Exception as e:
        log(f"fuse kernels: skipped ({type(e).__name__}: {e})")
    from mlx_lm.utils import maybe_set_recommended_wired_limit
    t0 = time.time()
    model_dir = Path(args.model).expanduser().resolve()
    mem_total, mem_avail = S.host_memory_gb()
    counts = S.parse_counts(getattr(args, "split_counts", None))
    stage_index = getattr(args, "split_stage_index", None)
    if counts:
        ranges = S.plan_ranges(S.read_n_layers(model_dir), counts)
        if stage_index is None or not 0 <= stage_index < len(counts) - 1:
            raise ValueError("packer requires --split-stage-index before the lead")
        if bool(stage_index) != bool(getattr(args, "split_upstream", None)):
            raise ValueError("only middle packers require --split-upstream")
        args.split_front_layers = ranges[stage_index][1]
    elif args.split_front_layers is None:
        n_layers = S.read_n_layers(model_dir)
        mt = S.read_model_type(model_dir)
        # Peer RAM unknown at packer start; assume symmetric (two Minis). Lead
        # re-checks with packer-reported mem and errors if K would differ.
        k, reason = S.choose_packer_layers(n_layers, mem_total, mem_total, mt)
        args.split_front_layers = k
        log(f"auto split: packer_layers={k} ({reason})")
    stage = S.Stage(model_dir, "front", args.split_front_layers, counts, stage_index)
    wired = apply_startup_wiring(getattr(args, "wired_limit", "startup"), mx, maybe_set_recommended_wired_limit)
    if args.cache_limit_gb is not None and args.cache_limit_gb > 0:
        mx.set_cache_limit(int(args.cache_limit_gb * (1 << 30)))
        log(f"mlx cache_limit {args.cache_limit_gb} GB")
    if getattr(args, "memory_limit_gb", None):
        try:
            mx.set_memory_limit(int(float(args.memory_limit_gb) * (1 << 30)))
            log(f"mlx memory_limit {args.memory_limit_gb} GB")
        except Exception as e:
            log(f"mlx memory_limit skipped: {e!r}")
    label = S.stage_label("front", stage.range, stage.n_layers)
    ident = {"model": str(model_dir), "tokenizer": tokenizer_hash(model_dir), "mlx_lm": _version("mlx_lm"),
             "model_type": stage.model_type, "kv_bits": args.kv_bits or 0, "stage": label}

    class _M:                       # MlxOps only needs make_cache()
        make_cache = staticmethod(stage.make_cache)
    ops = MlxOps(_M(), args.kv_bits, args.kv_group_size)
    # The head decides evictions (count + bytes over both halves); the front mirrors them.
    store = SessionStore(ops, args.cache_dir, ident, max_sessions=1 << 20, max_bytes=None,
                         persist=not args.no_persist)
    stream = mx.new_stream(mx.default_device())

    def forward(tokens, cache):
        with mx.stream(stream):
            return stage.front_forward(tokens, cache)

    packer_name = f"packer {(stage_index or 0) + 1}: layers {stage.range[0]}-{stage.range[1]-1} of {stage.n_layers}"
    info = {"name": packer_name, "stage": label, "range": list(stage.range), "n_layers": stage.n_layers,
            "model_type": stage.model_type, "mlx_lm": _version("mlx_lm"),
            "mem_total_gb": round(mem_total, 2), "mem_available_gb": round(mem_avail, 2),
            "packer_layers": int(stage.range[1])}
    state = S.FrontState(store, forward, info, new_scratch=ops.new_cache)
    if getattr(args, "split_keepalive", True):
        state.keepalive = S.GpuKeepalive(mx)
        log("packer GPU keepalive on (warms Metal while waiting for the lead)")

    def stats():
        try:
            _tot, _avail = S.host_memory_gb()
        except Exception:
            _tot, _avail = info.get("mem_total_gb"), info.get("mem_available_gb")
        return {"name": packer_name, "stage": label, "weights_gb": round(stage.nbytes() / 1e9, 2),
                "active_gb": round(mx.get_active_memory() / 1e9, 2),
                "peak_gb": round(mx.get_peak_memory() / 1e9, 2),
                "sessions": len(store.sessions), "session_gb": round(store.total_bytes() / 1e9, 3),
                "mem_total_gb": _tot, "mem_available_gb": _avail}
    if counts and stage_index > 0:
        upstream = S.FrontClient(args.split_upstream)
        hello = upstream.call("hello", proto=S.PROTO)[0]
        actual = [tuple(x["range"]) for x in hello.get("stages", [hello])]
        if actual != ranges[:stage_index] or hello.get("n_layers") != stage.n_layers:
            raise ValueError("upstream pipeline ranges do not match this stage")
        def hidden_forward(header, payload, cache):
            with mx.stream(stream):
                return stage.middle_forward(header, payload, cache)
        local = state
        state = S.ChainState(local, upstream, hidden_forward, stats_fn=stats)
        if getattr(args, "split_keepalive", True):
            state.keepalive = S.GpuKeepalive(mx)
    stop = threading.Event()

    def _term(*_):
        n = store.flush()
        log(f"packer 1 shutting down; saved {n} session(s) with unsaved turns")
        stop.set()
    signal.signal(signal.SIGTERM, _term)
    signal.signal(signal.SIGINT, _term)
    log(f"packer stage {S.title_from_label(label)} of {model_dir.name} loaded in {time.time() - t0:.1f}s, "
        f"{stage.nbytes() / 1e9:.1f} GB of layers; wired {wired}; persist="
        + (f"on {store.cache_dir}" if store.persist else "off"))
    S.serve_front(args.split_listen, state, log=log, stats_fn=stats, stop=stop)
    return 0


def main(argv=None):
    enable_stack_dumps()
    ap = build_parser()
    args = ap.parse_args(argv)
    if any(a == '--split-speculate-k' or a.startswith('--split-speculate-k=') for a in (argv or [])):
        args.split_speculate_k_explicit = True
    # Internal role names stay "head"/"front"; "lead"/"packer" are the user-facing ones.
    args.split_role = {"lead": "head", "packer": "front"}.get(args.split_role, args.split_role)
    if args.split_role == "front":
        if not args.split_listen:
            raise SystemExit("--split-role packer needs --split-listen HOST:PORT")
        return front_main(args)
    if args.split_role == "head" and not args.split_peer:
        raise SystemExit("--split-role lead needs --split-peer HOST:PORT")
    engine = Engine(args)
    srv = ThreadingHTTPServer((args.host, args.port), make_handler(engine))
    srv.daemon_threads = True

    def _term(*_):
        def _stop():
            n = engine.call(engine.s_flush)
            log(f"shutting down; saved {n} session(s) with unsaved turns")
            srv.shutdown()
        threading.Thread(target=_stop, daemon=True).start()
    signal.signal(signal.SIGTERM, _term)
    signal.signal(signal.SIGINT, _term)
    log(f"listening on http://{args.host}:{args.port}")
    srv.serve_forever()
    return 0


if __name__ == "__main__":
    sys.exit(main())
