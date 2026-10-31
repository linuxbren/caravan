#!/usr/bin/env python3
"""Caravan v3 (2026-10-31): one MLX model split across two Minis.

Pipeline split by layers, the way exo and llama.cpp's RPC backend do it,
but with Caravan's per-session caches kept on both sides:

    proxy --HTTP--> head worker (Mini A)            front stage (Mini B)
                    mlx_worker.py --split-role head  mlx_worker.py --split-role front
                    layers K..N-1, norm, lm_head      embeddings, layers 0..K-1
                    sampling, sessions, HTTP API      its own sessions for its layers
                          |  tokens ------------------------>  |
                          |  <------------ hidden states (h)   |
                          '---- one TCP connection over the Thunderbolt link

Why not mx.distributed? Measured 2026-10-31 on these two M4 Minis
(mlx 0.32.4): the ring backend connects and all_sum works, but transfers of
~2 MB and up (one prefill chunk of hidden states is 8-12 MB) abort with
"[ring] Receiving from socket .. failed with errno 60" / "connection to a
peer was lost", while plain Python TCP over the same link moves 8 MB both
ways in ~2 ms and the same ring test passes on localhost. jaccl (RDMA)
needs Thunderbolt 5, which the M4 Mini doesn't have. And mlx-lm 0.32.2 only
has pipeline code for some architectures (qwen3_moe yes; gemma4 and
gpt_oss no). So Caravan moves the hidden states itself: one request /
reply per forward pass, no collective ops, nothing that can deadlock if a
client goes away mid-reply.

The head drives everything; the front only answers. Each side keeps a
SessionStore (agent/mlx_worker.py) for its own layers' cache, in lockstep:
prepare / checkpoint / rewind / reset / save / restore / drop / evict are
mirrored as small ops. Each side saves its own layers to its own disk
(<key>.safetensors, metadata says which stage); a restore only counts when
both sides restore the same token list (digest compare) -- otherwise both
drop it and the chat is re-read cold, never mixed.

Pure parts (no mlx): plan_split, framing, digests, combine_restore,
FrontClient, FrontState, SplitSessions -- unit-tested in
tests/test_mlx_split.py with the fake cache layers of test_mlx_worker.py.
"""
import hashlib
import json
import socket
import struct
import threading
import time
import uuid

PROTO = "caravan-split-1"


# --- plan -------------------------------------------------------------------
def plan_split(n_layers: int, front_layers=None):
    """(front_range, head_range) as (start, end) layer index pairs.
    Default: an even split, the odd layer to the head (it also holds the
    lm_head)."""
    n = int(n_layers)
    if n < 2:
        raise ValueError("need at least 2 layers to split")
    k = n // 2 if front_layers in (None, "", 0) else int(front_layers)
    if not 1 <= k <= n - 1:
        raise ValueError(f"front layers must be 1..{n - 1}, got {k}")
    return (0, k), (k, n)


def stage_label(role, rng, n):
    return f"{role} {rng[0]}-{rng[1] - 1} of {n}"


def tokens_digest(tokens) -> str:
    return hashlib.sha1(json.dumps(list(tokens)).encode()).hexdigest()[:16]


# --- framing ----------------------------------------------------------------
def encode_frame(header: dict, payload: bytes = b"") -> bytes:
    h = json.dumps(header, separators=(",", ":")).encode()
    return struct.pack(">IQ", len(h), len(payload)) + h + payload


def _recv_exact(sock, n) -> bytes:
    buf = bytearray(n)
    view = memoryview(buf)
    got = 0
    while got < n:
        r = sock.recv_into(view[got:], n - got)
        if r == 0:
            raise ConnectionError("peer closed the connection")
        got += r
    return bytes(buf)


def read_frame(sock):
    hl, pl = struct.unpack(">IQ", _recv_exact(sock, 12))
    header = json.loads(_recv_exact(sock, hl))
    payload = _recv_exact(sock, pl) if pl else b""
    return header, payload


# --- restore agreement --------------------------------------------------------
HAVE = ("warm", "restored")


def combine_restore(head_result, head_digest, front_result, front_digest):
    """'ok' (both sides hold the same tokens), 'miss' (neither has it),
    or 'mismatch' (one side only, or different tokens: drop both)."""
    h, f = head_result in HAVE, front_result in HAVE
    if h and f:
        return "ok" if head_digest == front_digest else "mismatch"
    if not h and not f:
        return "miss"
    return "mismatch"


# --- head side: connection to the front ---------------------------------------
class FrontError(RuntimeError):
    pass


class FrontClient:
    """One TCP connection to the front stage, used only from the head's
    mlx thread (so no locking). Reconnects lazily; `epoch` changes when the
    front process restarted (its in-memory sessions are gone)."""

    def __init__(self, addr, connect=None, timeout=600.0):
        self.addr = addr
        self._connect = connect or (lambda: socket.create_connection(_hostport(addr), timeout=10))
        self.timeout = timeout
        self.sock = None
        self.epoch = None
        self.hello = None
        self.on_new_epoch = None     # callback(old, new) when the front restarted
        self.reset_stats()

    def reset_stats(self):
        self.stats = {"calls": 0, "bytes_out": 0, "bytes_in": 0, "wait_s": 0.0, "front_s": 0.0}

    def _ensure(self):
        if self.sock is not None:
            return
        s = self._connect()
        try:
            s.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
        except (OSError, AttributeError):
            pass
        s.settimeout(self.timeout)
        self.sock = s
        hello = self._roundtrip({"op": "hello", "proto": PROTO})[0]
        if hello.get("proto") != PROTO:
            self.close()
            raise FrontError(f"front speaks {hello.get('proto')!r}, need {PROTO}")
        old, self.epoch, self.hello = self.epoch, hello.get("epoch"), hello
        if old is not None and old != self.epoch and self.on_new_epoch:
            self.on_new_epoch(old, self.epoch)

    def close(self):
        if self.sock is not None:
            try:
                self.sock.close()
            except OSError:
                pass
        self.sock = None

    def _roundtrip(self, header, payload=b""):
        t0 = time.perf_counter()
        data = encode_frame(header, payload)
        try:
            self.sock.sendall(data)
            rh, rp = read_frame(self.sock)
        except (OSError, ConnectionError) as e:
            self.close()
            raise FrontError(f"front {self.addr}: {e}") from e
        st = self.stats
        st["calls"] += 1
        st["bytes_out"] += len(data)
        st["bytes_in"] += 12 + len(rp) + len(json.dumps(rh))
        st["wait_s"] += time.perf_counter() - t0
        st["front_s"] += float(rh.get("_s", 0.0))
        if "error" in rh:
            raise FrontError(f"front: {rh['error']}")
        return rh, rp

    def call(self, op, payload=b"", **kw):
        self._ensure()
        kw["op"] = op
        return self._roundtrip(kw, payload)


def _hostport(addr):
    host, _, port = str(addr).rpartition(":")
    return host.strip("[]"), int(port)


# --- front side: the op handler (pure; the mlx forward is passed in) ----------
class FrontState:
    """What the front does with each op. `store` is a SessionStore over the
    front's layers; `forward(tokens, cache) -> (header_extra, payload)` runs
    the embeddings + front layers and returns the hidden states."""

    def __init__(self, store, forward, info: dict, new_scratch):
        self.store, self.forward, self.info = store, forward, dict(info)
        self.new_scratch = new_scratch
        self.epoch = uuid.uuid4().hex[:12]
        self.cur = None          # Session the head is working on
        self.prompt = None
        self.scratch = None

    def handle(self, h: dict, payload: bytes):
        op = h.get("op")
        st = self.store
        if op == "hello":
            return dict(self.info, proto=PROTO, epoch=self.epoch), b""
        if op == "prepare":
            prompt = list(h["prompt"])
            s, n, how = st.prepare(h.get("key"), prompt, allow_load=False)
            self.cur, self.prompt = s, prompt
            return {"n": n, "how": how, "key": s.key}, b""
        if op == "fwd":
            toks = list(h["tokens"])
            if h.get("ctx") == "scratch":
                if h.get("new") or self.scratch is None:
                    self.scratch = self.new_scratch()
                cache = self.scratch
            else:
                if self.cur is None:
                    return {"error": "fwd before prepare"}, b""
                cache = self.cur.cache
            return self.forward(toks, cache)
        if op == "end_scratch":
            self.scratch = None
            st.ops.release()
            return {}, b""
        if op == "checkpoint":
            st.checkpoint(self.cur, self.prompt[: int(h["n"])])
            return {}, b""
        if op == "rewind":
            if self.cur is not None:
                st.rewind(self.cur, completed=bool(h.get("completed")))
            return {}, b""
        if op == "reset":
            if self.cur is not None:
                st.reset(self.cur)
            return {}, b""
        if op == "restore":
            key = h.get("key")
            r = st.restore(key)
            s = st.sessions.get(key)
            return {"result": r, "digest": tokens_digest(s.tokens) if s else None,
                    "tokens": len(s.tokens) if s else 0}, b""
        if op == "save":
            return {"result": st.save(h.get("key"))}, b""
        if op in ("drop", "evict"):
            keys = list(h.get("keys") or [])
            if op == "evict":
                for k in keys:
                    s = st.sessions.get(k)
                    if s is not None and s.dirty and st.persist:
                        st.save(k)
            if self.cur is not None and self.cur.key in keys:
                self.cur = None
            return {"dropped": st.drop(keys)}, b""
        if op == "flush":
            return {"saved": st.flush()}, b""
        if op == "describe":
            return {"sessions": st.describe()}, b""
        return {"error": f"unknown op {op!r}"}, b""


def serve_front(listen, state: FrontState, log=print, stats_fn=None, stop=None):
    """Accept one head at a time and answer its ops, on the calling thread
    (MLX work stays on one thread). A dropped connection just waits for the
    next one; sessions stay in memory."""
    host, port = _hostport(listen)
    srv = socket.socket(socket.AF_INET6 if ":" in host else socket.AF_INET)
    srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    srv.bind((host, port))
    srv.listen(1)
    srv.settimeout(1.0)
    log(f"front stage listening on {listen} (epoch {state.epoch})")
    while not (stop and stop.is_set()):
        try:
            conn, peer = srv.accept()
        except socket.timeout:
            continue
        conn.settimeout(None)
        try:
            conn.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
        except OSError:
            pass
        log(f"head connected from {peer[0]}")
        try:
            while True:
                h, p = read_frame(conn)
                t0 = time.perf_counter()
                if h.get("op") == "stats" and stats_fn:
                    rh, rp = stats_fn(), b""
                else:
                    try:
                        rh, rp = state.handle(h, p)
                    except Exception as e:     # report, keep serving
                        rh, rp = {"error": f"{type(e).__name__}: {e}"}, b""
                rh["_s"] = round(time.perf_counter() - t0, 6)
                conn.sendall(encode_frame(rh, rp))
        except (ConnectionError, OSError) as e:
            log(f"head disconnected ({e})")
        finally:
            try:
                conn.close()
            except OSError:
                pass
    srv.close()


# --- head side: keeping both stores in lockstep --------------------------------
class SplitSessions:
    """The head's view of a session across both stages. `store` is the
    head's SessionStore (its on_evict hook is wired to the front here)."""

    def __init__(self, store, client: FrontClient, log=print):
        self.store, self.client, self.log = store, client, log
        store.on_evict = self._evicted
        client.on_new_epoch = self._front_restarted

    def _evicted(self, keys):
        try:
            self.client.call("evict", keys=list(keys))
        except FrontError as e:
            self.log(f"front evict failed: {e}")

    def _front_restarted(self, old, new):
        # The front lost its in-memory sessions; ours no longer have a
        # matching other half. Disk files on both sides still pair up by digest.
        n = len(self.store.sessions)
        for k in list(self.store.sessions):
            if self.store.sessions[k].dirty and self.store.persist:
                self.store.save(k)
        self.store.sessions.clear()
        self.store.ops.release()
        self.log(f"front restarted (epoch {old} -> {new}); dropped {n} in-memory session(s) here")

    def restore(self, key) -> str:
        """Both halves or neither."""
        self.client._ensure()       # may clear our sessions if the front restarted
        r = self.store.restore(key)
        s = self.store.sessions.get(key)
        hd = tokens_digest(s.tokens) if s else None
        fr = self.client.call("restore", key=key)[0]
        verdict = combine_restore(r, hd, fr.get("result"), fr.get("digest"))
        if verdict == "ok":
            return r
        if verdict == "miss":
            return r if r in ("miss", "rejected") else "miss"
        self.log(f"session {key}: halves disagree (head {r}/{hd}, front {fr.get('result')}/"
                 f"{fr.get('digest')}) -- dropping both, re-reading cold")
        self.store.drop([key])
        self.client.call("drop", keys=[key])
        return "rejected"

    def prepare(self, key, prompt):
        self.client._ensure()       # notice a restarted front before trusting our memory
        from_disk = False
        if key not in self.store.sessions:
            from_disk = self.restore(key) == "restored" if _valid(self.store, key) else False
        s, n, how = self.store.prepare(key, prompt, allow_load=False)
        if from_disk and how.endswith("-memory"):
            how = how[: -len("memory")] + "disk"
        fr = self.client.call("prepare", key=key, prompt=list(prompt))[0]
        if fr.get("n") != n:
            self.log(f"session {s.key}: head reuses {n}, front {fr.get('n')} -- both re-read cold")
            self.store.reset(s)
            self.client.call("reset")
            fr = self.client.call("prepare", key=key, prompt=list(prompt))[0]
            if fr.get("n") != 0:
                raise FrontError("front could not reset the session")
            return s, 0, "split-resync"
        return s, n, how

    def checkpoint(self, s, tokens):
        self.store.checkpoint(s, tokens)
        self.client.call("checkpoint", n=len(tokens))

    def rewind(self, s, completed=True):
        # front first: our rewind may evict, which also tells the front
        try:
            self.client.call("rewind", completed=bool(completed))
        finally:
            self.store.rewind(s, completed=completed)

    def reset(self, s):
        self.store.reset(s)
        try:
            self.client.call("reset")
        except FrontError as e:
            self.log(f"front reset failed: {e}")

    def save(self, key):
        r = self.store.save(key)
        f = self.client.call("save", key=key)[0].get("result")
        return r if r == f else f"{r}/front-{f}"

    def drop(self, keys):
        out = self.store.drop(keys)
        self.client.call("drop", keys=list(keys))
        return out

    def flush(self):
        n = self.store.flush()
        try:
            self.client.call("flush")
        except FrontError as e:
            self.log(f"front flush failed: {e}")
        return n


def _valid(store, key):
    import re
    return isinstance(key, str) and bool(re.match(r"^[A-Za-z0-9_-]{1,64}$", key)) and key != "_anon"


# --- mlx: one stage of a split model ------------------------------------------
def check_local_shards(model_dir, role, front_layers=None):
    """A split-downloaded model dir (agent/mlx_split_fetch.py) holds only some
    shards; strict=False loading would then silently leave missing weights at
    their random init. Refuse to start unless this stage's shards are here."""
    import json
    from pathlib import Path
    d = Path(model_dir)
    idx, cfg = d / "model.safetensors.index.json", d / "config.json"
    if not idx.exists() or not cfg.exists():
        return []
    from mlx_split_fetch import plan_files
    need = plan_files(json.loads(cfg.read_text()), json.loads(idx.read_text()), front_layers)[role]
    missing = sorted(f for f in need if not (d / f).exists())
    if missing:
        raise FileNotFoundError(f"{role} stage needs {missing} in {d} (run mlx_split_fetch.py --role {role})")
    return sorted(need)


class Stage:
    """Loads only this stage's layers (lazy load, then evaluate just the
    needed weights) and runs them. Works for qwen3_moe, qwen3_5(_moe),
    gemma4 and gpt_oss by reading layer attributes, not by per-model forks."""

    def __init__(self, model_dir, role, front_layers=None):
        import mlx.core as mx
        import mlx.nn as nn  # noqa: F401
        from mlx_lm.utils import load_model
        from mlx_lm.models.base import create_attention_mask, create_ssm_mask
        self.mx = mx
        self._cam, self._csm = create_attention_mask, create_ssm_mask
        check_local_shards(model_dir, role, front_layers)
        model, self.config = load_model(model_dir, lazy=True, strict=False)
        self.model = model
        self.lm = getattr(model, "language_model", None) or model
        self.inner = self.lm.model
        self.model_type = self.config.get("model_type", "")
        n = len(self.inner.layers)
        self.n_layers = n
        fr, hr = plan_split(n, front_layers)
        self.role = role
        self.range = fr if role == "front" else hr
        a, b = self.range
        self.layers = list(self.inner.layers[a:b])
        self.kinds = [self._kind(i, l) for i, l in zip(range(a, b), self.layers)]
        self.tied = not hasattr(self.lm, "lm_head")
        self.cap = getattr(self.lm, "final_logit_softcapping", None)
        self.embed_scale = getattr(self.inner, "embed_scale", None)
        self.window = getattr(self.inner, "window_size", None)
        # Only these weights get read from disk.
        need = [l.parameters() for l in self.layers]
        if role == "front" or self.tied:
            need.append(self.inner.embed_tokens.parameters())
        if role == "head":
            need.append(self.inner.norm.parameters())
            if not self.tied:
                need.append(self.lm.lm_head.parameters())
        mx.eval(need)
        # Drop the other stage's (never evaluated) layers.
        for i in range(n):
            if not a <= i < b:
                self.inner.layers[i] = None
        from mlx_lm.models.cache import make_prompt_cache
        self._make_full = lambda: make_prompt_cache(self.model)

    def _kind(self, i, layer):
        if getattr(layer, "is_linear", False):
            return "linear"
        lt = getattr(layer, "layer_type", None)
        if lt is None and hasattr(self.inner, "layer_types"):
            lt = self.inner.layer_types[i]
        return "sliding" if lt == "sliding_attention" else "full"

    def make_cache(self):
        a, b = self.range
        return self._make_full()[a:b]

    def nbytes(self):
        from mlx.utils import tree_flatten
        n = 0
        for l in self.layers:
            n += sum(v.nbytes for _, v in tree_flatten(l.parameters()))
        return n

    def _masks(self, h, cache):
        memo, out = {}, []
        for kind, c in zip(self.kinds, cache):
            if kind not in memo:
                if kind == "linear":
                    memo[kind] = self._csm(h, c)
                elif kind == "sliding":
                    memo[kind] = self._cam(h, c, window_size=self.window)
                else:
                    memo[kind] = self._cam(h, c)
            out.append(memo[kind])
        return out

    def run_layers(self, h, cache):
        if cache is None:
            cache = [None] * len(self.layers)
        for layer, c, m in zip(self.layers, cache, self._masks(h, cache)):
            r = layer(h, m, c)
            h = r[0] if isinstance(r, tuple) else r
        return h

    def embed(self, tokens):
        h = self.inner.embed_tokens(tokens)
        if self.embed_scale is not None:
            h = h * self.embed_scale
        return h

    def logits(self, h):
        mx = self.mx
        out = self.inner.norm(h)
        out = self.inner.embed_tokens.as_linear(out) if self.tied else self.lm.lm_head(out)
        if self.cap:
            out = mx.tanh(out / self.cap) * self.cap
        return out

    # front: tokens -> hidden states (bytes)
    def front_forward(self, tokens, cache):
        mx = self.mx
        x = mx.array(tokens, dtype=mx.int32)[None]
        h = self.run_layers(self.embed(x), cache)
        mx.eval(h, [c.state for c in cache])
        return {"dtype": str(h.dtype).split(".")[-1], "shape": list(h.shape)}, array_bytes(mx, h)


_VIEW = {"bfloat16": "uint16", "float16": "uint16", "float32": "uint32"}


def array_bytes(mx, a) -> bytes:
    import numpy as np
    name = str(a.dtype).split(".")[-1]
    v = a.view(getattr(mx, _VIEW[name])) if name in _VIEW else a
    return np.asarray(v).tobytes()


def array_from(mx, header, payload):
    import numpy as np
    name = header["dtype"]
    raw = np.frombuffer(payload, dtype=_VIEW.get(name, name))
    a = mx.array(raw).reshape(header["shape"])
    return a.view(getattr(mx, name)) if name in _VIEW else a


class SplitModel:
    """What the head's Engine sees as `model`: model(inputs, cache) asks the
    front for the first layers' output, then runs the rest here."""

    def __init__(self, stage: Stage, client: FrontClient):
        self.stage, self.client, self.mx = stage, client, stage.mx
        self.ctx = "scratch"
        self._new_scratch = True
        self.model_type = stage.model_type

    @property
    def layers(self):
        return self.stage.layers

    def make_cache(self):
        return self.stage.make_cache()

    def __call__(self, inputs, cache=None, input_embeddings=None, **_):
        mx = self.mx
        toks = inputs.reshape(-1).tolist()      # forces the previous step: tokens must be concrete
        kw = {"tokens": toks, "ctx": self.ctx}
        if self.ctx == "scratch":
            kw["new"], self._new_scratch = self._new_scratch, False
        rh, rp = self.client.call("fwd", **kw)
        h = array_from(mx, rh, rp)
        h = self.stage.run_layers(h, cache)
        return self.stage.logits(h)

    def begin_scratch(self):
        self.ctx, self._new_scratch = "scratch", True

    def end_scratch(self):
        self.client.call("end_scratch")
        self.ctx = "session"
