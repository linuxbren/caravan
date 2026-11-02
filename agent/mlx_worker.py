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
        self.draft_model = None
        self.draft_tokenizer = None
        self.speculate_k = int(getattr(args, "split_speculate_k", 4) or 4)
        if self.speculate_k < 1:
            self.speculate_k = 1
        # Idea 3 draft-free: prompt-lookup / n-gram from context (0 = off).
        self.prompt_lookup_n = int(getattr(args, "split_prompt_lookup", 0) or 0)
        if self.prompt_lookup_n < 0:
            self.prompt_lookup_n = 0
        # Idea 3 auto-pair / remap / shut-off (populated in _setup when lead).
        self.draft_remap_d2t = {}
        self.draft_remap_t2d = {}
        self.draft_path = None
        self.guess_pairing = None
        self.break_even_frac = 0.35
        self._chat_shutoffs = {}
        self._speculate_k_explicit = bool(getattr(args, "split_speculate_k_explicit", False))
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
            self.stage = S.Stage(self.model_dir, "head", args.split_front_layers)
            self.model = S.SplitModel(self.stage, self.client)
            self.tokenizer = load_tokenizer(self.model_dir, eos_token_ids=cfg0.get("eos_token_id"))
            hello = self.client.call("hello", proto=S.PROTO)[0]
            if hello.get("range") != [0, self.stage.range[0]] or hello.get("n_layers") != self.stage.n_layers:
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
        else:
            self.model, self.tokenizer = load(str(self.model_dir))
        cfg = json.loads((self.model_dir / "config.json").read_text())
        self.model_type = cfg.get("model_type", "")
        self.wired_mode = getattr(args, "wired_limit", "startup")
        from mlx_lm.utils import maybe_set_recommended_wired_limit
        self.wired = apply_startup_wiring(self.wired_mode, mx, maybe_set_recommended_wired_limit)
        if self.wired:
            log(f"wired limit {self.wired[0]} -> {self.wired[1]} bytes (held for process lifetime)")
        else:
            log(f"wired limit mode {self.wired_mode}: not set at startup")
        if args.cache_limit_gb is not None:
            mx.set_cache_limit(int(args.cache_limit_gb * (1 << 30)))
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
        if self.pipeline_chats is None:
            self.pipeline_chats = 1

    def _main(self, ready):
        try:
            self._setup()
        except BaseException as e:
            ready.put(e)
            return
        ready.put(None)
        if self.pipeline_chats <= 1 or self.client is None:
            while True:
                job = self.jobs.get()
                if job is None:
                    return
                kind, payload, out = job
                if kind == "call":
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
            if self.pipeline_chats is None:
                self.pipeline_chats = 1
            log(f"split pipeline chats={self.pipeline_chats} (idea 1; overlap packer/lead across sessions)")
            self._main_pipeline()

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
        return {"lead": lead, "packers": [front], "head": lead, "front": front, "peer": self.args.split_peer}

    def call(self, fn):
        """Run fn() on the mlx thread (after any queued generation)."""
        out = self._queue_mod.Queue()
        self.jobs.put(("call", fn, out))
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
        toks = self.tokenizer.apply_chat_template(msgs, add_generation_prompt=True, tokenize=True, **kw)
        if isinstance(toks, dict):
            toks = toks["input_ids"]
        return list(toks)

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
        if not use_draft and not use_pl:
            raise RuntimeError("speculate called with neither draft nor prompt-lookup")
        num_draft_tokens = int(self.speculate_k)
        if not hasattr(model, "trim_caches"):
            raise RuntimeError("idea 3 requires SplitModel.trim_caches")
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
            model.trim_caches(num_draft - num_accept, cache)
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
            if use_pl:
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
                # Stash on self for _run to pick up into info
                self._last_speculate_stats = stats

    def _run(self, key, prompt, body, cancel):
        mx, G = self.mx, self.G
        t0 = time.time()
        if self.client is not None:
            self.client.reset_stats()
        if self.client is not None and hasattr(self.model, "session_key"):
            self.model.session_key = key
        s, n_reused, how = self.s_prepare(key, prompt)
        completed = False
        n_gen = 0
        try:
            rest = prompt[n_reused:]
            with request_wiring(self.wired_mode, G, self.model, self.stream):
                with mx.stream(self.stream):
                    todo = rest[:-1]
                    for i in range(0, len(todo), self.prefill_step):
                        if cancel.is_set():
                            raise KeyboardInterrupt("cancelled")
                        chunk = mx.array(todo[i:i + self.prefill_step])
                        self.model(chunk[None], cache=s.cache)
                        mx.eval([c.state for c in s.cache])
                        mx.clear_cache()
            self.s_checkpoint(s, prompt[:-1])
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
            use_spec = self.client is not None and (
                (self.draft_model is not None and not (shut and shut.disabled))
                or int(self.prompt_lookup_n) > 0)
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
                if kind == "call":
                    # Run admin calls only when the pipeline is idle (avoid racing the socket).
                    if decoding or pending:
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
                if kind == "call":
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
        s, n_reused, how = self.s_prepare(key, prompt)
        t0 = time.time()
        try:
            rest = prompt[n_reused:]
            with request_wiring(self.wired_mode, self.G, self.model, self.stream):
                with mx.stream(self.stream):
                    todo = rest[:-1]
                    for i in range(0, len(todo), self.prefill_step):
                        if cancel.is_set():
                            raise KeyboardInterrupt("cancelled")
                        chunk = mx.array(todo[i:i + self.prefill_step])
                        self.model(chunk[None], cache=s.cache)
                        mx.eval([c.state for c in s.cache])
                        mx.clear_cache()
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

        def packer_fetch(slot):
            model.session_key = slot.key
            with mx.stream(self.stream):
                model.begin_packer(slot.next_tokens)
                slot.h = model.finish_packer()

        def packer_begin(slot):
            model.session_key = slot.key
            with mx.stream(self.stream):
                model.begin_packer(slot.next_tokens)

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

    def _pipe_lead_sample(self, slot):
        """Run lead layers on slot.h, sample one token, emit piece; clear h."""
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
        with request_wiring(self.wired_mode, G, self.model, self.stream):
            with mx.stream(self.stream):
                logits = model.lead_logits(slot.h, slot.session.cache)
                mx.eval(logits, [c.state for c in slot.session.cache])
                logits = logits[:, -1, :]
                if slot.procs:
                    for p in slot.procs:
                        logits = p(slot.all_tokens, logits)
                y = slot.sampler(logits)
                mx.eval(y)
                token = int(y.flatten()[0].item()) if hasattr(y, "flatten") else int(y)
        slot.h = None
        if slot.ttft is None:
            slot.ttft = time.time() - slot.t0
        slot.n_gen += 1
        slot.all_tokens.append(token)
        # Detokenize like mlx_lm.generate
        if slot._detok is None:
            detok = getattr(self.tokenizer, "detokenizer", None)
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
                text_piece = getattr(slot._detok, "last_segment", None) or getattr(slot._detok, "text", "") or ""
                # Prefer last_segment; fall back to full text delta
                if not text_piece and hasattr(slot._detok, "text"):
                    full = slot._detok.text
                    prev = getattr(slot, "_detok_prev", "")
                    text_piece = full[len(prev):]
                    slot._detok_prev = full
            except Exception:
                text_piece = self.tokenizer.decode([token])
        else:
            text_piece = self.tokenizer.decode([token])
        finish = None
        if slot.stops.advance(token):
            finish = "stop"
        eos = self.tokenizer.eos_token_id
        if isinstance(eos, (list, tuple)):
            eos_set = set(eos)
        else:
            eos_set = {eos} if eos is not None else set()
        if token in eos_set:
            finish = "stop"
        if slot.n_gen >= slot.max_tokens:
            finish = finish or "length"
        slot.out.put(("piece", text_piece, finish is not None))
        if finish is not None:
            slot.finished = True
            slot.finish = finish
            slot.next_tokens = [token]
            return
        slot.next_tokens = [token]

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
                "peak_gb": round(mx.get_peak_memory() / 1e9, 2),
                "pipeline": True}
        if self.client is not None:
            st = dict(self.client.stats)
            info["split"] = {"calls": st["calls"], "mb_out": round(st["bytes_out"] / 1e6, 2),
                             "mb_in": round(st["bytes_in"] / 1e6, 2),
                             "wait_s": round(st["wait_s"], 3), "front_s": round(st["front_s"], 3),
                             "net_s": round(st["wait_s"] - st["front_s"], 3)}
        log(f"session {slot.key}: pipeline, reused {slot.n_reused}/{len(slot.prompt)}, "
            f"{slot.n_gen} generated, total {info['total_s']:.2f}s, peak {info['peak_gb']} GB")
        slot.out.put(("done", info))


    def text_machine(self, prompt, stop_words):
        if self.model_type == "gpt_oss":
            return HarmonyAdapter()
        return StateMachineAdapter(self.G, self.tokenizer, prompt, stop_words)


class _PipeSlot:
    __slots__ = ("key", "session", "prompt", "body", "cancel", "out", "how", "n_reused",
                 "t0", "t_prefill", "sampler", "procs", "max_tokens", "stops",
                 "next_tokens", "all_tokens", "h", "n_gen", "ttft", "finished",
                 "cancelled", "finish", "_detok")

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
                    if stream and (c or r):
                        send(pack(c, r))
                    else:
                        text.append(c)
                        reasoning.append(r)
                if sm:
                    tail = sm.feed("", final=True)
                    c = strip_lead("".join(t for k, t in tail if k == "normal"))
                    r = "".join(t for k, t in tail if k == "reasoning")
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
            usage = {"prompt_tokens": info["prompt_tokens"], "completion_tokens": info["completion_tokens"],
                     "total_tokens": info["prompt_tokens"] + info["completion_tokens"],
                     "prompt_tokens_details": {"cached_tokens": info["cached_tokens"]},
                     "caravan": {k: info[k] for k in ("how", "prefill_s", "ttft_s", "total_s", "peak_gb", "split", "speculate")
                                 if k in info}}
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
                    self._json(200, pack("".join(text), "".join(reasoning), finish=info["finish"], usage=usage))
            except (BrokenPipeError, ConnectionResetError):
                pass

    return H


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
    ap.add_argument("--cache-limit-gb", type=float, default=None, help="mx.set_cache_limit (freed-buffer pool)")
    # v3: one model split across two Minis (agent/mlx_split.py)
    ap.add_argument("--split-role", choices=("none", "lead", "packer", "head", "front"), default="none",
                    help="lead: HTTP + last layers + lm_head, asks --split-peer (Packer 1) for the first layers; "
                         "packer: embeddings + first layers, listens on --split-listen (no HTTP). "
                         "head/front: deprecated aliases for lead/packer")
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
    return ap


def front_main(args):
    """v3 front stage: embeddings + the first layers, its own session caches."""
    import mlx.core as mx
    import mlx_split as S
    from mlx_lm.utils import maybe_set_recommended_wired_limit
    t0 = time.time()
    model_dir = Path(args.model).expanduser().resolve()
    mem_total, mem_avail = S.host_memory_gb()
    if args.split_front_layers is None:
        n_layers = S.read_n_layers(model_dir)
        mt = S.read_model_type(model_dir)
        # Peer RAM unknown at packer start; assume symmetric (two Minis). Lead
        # re-checks with packer-reported mem and errors if K would differ.
        k, reason = S.choose_packer_layers(n_layers, mem_total, mem_total, mt)
        args.split_front_layers = k
        log(f"auto split: packer_layers={k} ({reason})")
    stage = S.Stage(model_dir, "front", args.split_front_layers)
    wired = apply_startup_wiring(getattr(args, "wired_limit", "startup"), mx, maybe_set_recommended_wired_limit)
    if args.cache_limit_gb is not None:
        mx.set_cache_limit(int(args.cache_limit_gb * (1 << 30)))
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

    info = {"stage": label, "range": list(stage.range), "n_layers": stage.n_layers,
            "model_type": stage.model_type, "mlx_lm": _version("mlx_lm"),
            "mem_total_gb": round(mem_total, 2), "mem_available_gb": round(mem_avail, 2),
            "packer_layers": int(stage.range[1])}
    state = S.FrontState(store, forward, info, new_scratch=ops.new_cache)
    if getattr(args, "split_keepalive", True):
        state.keepalive = S.GpuKeepalive(mx)
        log("packer GPU keepalive on (warms Metal while waiting for the lead)")

    def stats():
        return {"stage": label, "weights_gb": round(stage.nbytes() / 1e9, 2),
                "active_gb": round(mx.get_active_memory() / 1e9, 2),
                "peak_gb": round(mx.get_peak_memory() / 1e9, 2),
                "sessions": len(store.sessions), "session_gb": round(store.total_bytes() / 1e9, 3)}
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
