"""v2 (2026-10-31): Caravan's MLX worker (agent/mlx_worker.py) -- the
per-session prompt cache bookkeeping, disk save/restore, eviction, and the
gpt-oss (harmony) reply parsing. No mlx needed: cache layers are fakes that
behave like mlx_lm's KVCache (always trimmable) and RotatingKVCache
(sliding window; can't trim once it has wrapped).
"""
import json
import random
import sys
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "agent"))

import mlx_worker as W  # noqa: E402


class KVCache:
    def __init__(self):
        self.toks = []

    def feed(self, toks):
        self.toks += list(toks)

    def is_trimmable(self):
        return True


class RotatingKVCache:
    """Keeps the last `window` tokens; offset counts everything seen."""

    def __init__(self, window=8):
        self.window, self.toks, self.offset = window, [], 0

    def feed(self, toks):
        for t in toks:
            self.toks = (self.toks + [t])[-self.window:]
            self.offset += 1

    def is_trimmable(self):
        return self.offset < self.window


class FakeOps:
    """The SessionStore side of MlxOps, over the fake layers."""

    def __init__(self, layout=("KVCache", "RotatingKVCache"), window=8):
        self.layout, self.window = layout, window
        self.saved, self.released = [], 0

    def new_cache(self):
        return [KVCache() if n == "KVCache" else RotatingKVCache(self.window) for n in self.layout]

    def always_trimmable(self, c):
        return type(c).__name__ in W.ALWAYS_TRIMMABLE

    def trim(self, c, n):
        if n <= 0:
            return
        if isinstance(c, KVCache):
            del c.toks[-n:]
        else:
            assert c.is_trimmable(), "trimmed a wrapped rotating cache"
            del c.toks[-n:]
            c.offset -= n

    def offset(self, c):
        return len(c.toks) if isinstance(c, KVCache) else c.offset

    def snapshot(self, c):
        return ("rot", c.window, list(c.toks), c.offset)

    def from_snapshot(self, snap):
        _, w, toks, off = snap
        r = RotatingKVCache(w)
        r.toks, r.offset = list(toks), off
        return r

    def nbytes(self, cache):
        return sum(len(c.toks) for c in cache) * 100

    def snap_nbytes(self, snaps):
        return sum(len(s[2]) for s in snaps.values()) * 100

    def classes(self, cache):
        return [type(c).__name__ for c in cache]

    def save(self, path, cache, md):
        self.saved.append(path)
        Path(path).write_text(json.dumps({
            "md": md, "layers": [[type(c).__name__, c.toks, getattr(c, "offset", None)] for c in cache]}))

    def load(self, path):
        d = json.loads(Path(path).read_text())
        cache = []
        for name, toks, off in d["layers"]:
            if name == "KVCache":
                c = KVCache()
                c.toks = toks
            else:
                c = RotatingKVCache(self.window)
                c.toks, c.offset = toks, off
            cache.append(c)
        return cache, d["md"]

    def release(self):
        self.released += 1


IDENT = {"model": "/m/gemma", "tokenizer": "abc", "mlx_lm": "0.32.2", "model_type": "gemma4"}
KEY = "0123456789abcdef"


def turn(store, key, prompt, reply):
    """What Engine.run does: prepare, prefill to len-1, checkpoint, generate, rewind."""
    s, n, how = store.prepare(key, prompt)
    for c in s.cache:
        c.feed(prompt[n:-1])
    store.checkpoint(s, prompt[:-1])
    for c in s.cache:
        c.feed(prompt[-1:] + reply)       # last prompt token + the reply
    store.rewind(s, completed=True)
    return s, n, how


class SessionStoreTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name) / "cache"
        self.ops = FakeOps()
        self.store = W.SessionStore(self.ops, self.dir, IDENT)

    def tearDown(self):
        self.tmp.cleanup()

    def chat(self):
        p1 = list(range(100, 140))              # 40-token first prompt (window 8 -> wraps)
        reply = [7, 7, 7]                       # what the model generated (with its thinking)
        rerendered = [8, 8]                     # how the template renders that reply next turn
        p2 = p1 + rerendered + list(range(200, 210))
        return p1, reply, p2

    def test_turn_two_reuses_whole_previous_prompt_despite_wrapped_window(self):
        p1, reply, p2 = self.chat()
        s, n, how = turn(self.store, KEY, p1, reply)
        self.assertEqual((n, how), (0, "cold"))
        # after the reply the cache is back at the checkpoint: p1[:-1]
        self.assertEqual(s.cache[0].toks, p1[:-1])
        self.assertEqual(s.cache[1].toks, p1[:-1][-8:])
        self.assertEqual(s.cache[1].offset, len(p1) - 1)
        self.assertFalse(s.cache[1].is_trimmable())   # wrapped: mlx_lm.server would miss here
        s, n, how = turn(self.store, KEY, p2, [5])
        self.assertEqual((n, how), (len(p1) - 1, "hit-memory"))
        # only the re-rendered reply + new message (+1) were read on turn 2
        self.assertEqual(len(p2) - n, len(p2) - len(p1) + 1)
        self.assertEqual(s.cache[0].toks, p2[:-1])
        self.assertEqual(s.cache[1].toks, p2[:-1][-8:])

    def test_without_checkpoint_a_wrapped_window_cannot_rewind(self):
        """mlx_lm.server's situation: the cache holds prompt+reply, the next
        prompt diverges inside it, the rotating layer can't trim -> cold."""
        p1, reply, p2 = self.chat()
        s, _, _ = self.store.prepare(KEY, p1)
        for c in s.cache:
            c.feed(p1 + reply)
        s.tokens, s.snaps = p1 + reply, None
        s2, n, how = self.store.prepare(KEY, p2)
        self.assertEqual((n, how), (0, "diverged-memory"))
        self.assertEqual(s2.cache[0].toks, [])

    def test_trimmable_layout_trims_on_divergence(self):
        store = W.SessionStore(FakeOps(layout=("KVCache", "KVCache")), self.dir, IDENT)
        p1, reply, p2 = self.chat()
        turn(store, KEY, p1, reply)
        edited = p1[:20] + [999] + p1[21:]           # client edited an earlier message
        s, n, how = store.prepare(KEY, edited)
        self.assertEqual((n, how), (20, "trimmed-memory"))
        self.assertEqual(s.cache[0].toks, p1[:20])

    def test_always_reads_at_least_one_token(self):
        p1, reply, _ = self.chat()
        turn(self.store, KEY, p1, reply)
        s, n, how = self.store.prepare(KEY, p1[:-1])   # same prompt as the checkpoint
        self.assertLess(n, len(p1) - 1)
        self.assertEqual(n, len(p1) - 2) if how.startswith("trimmed") else self.assertTrue(how.startswith("diverged"))

    def test_save_and_restore_after_restart(self):
        p1, reply, p2 = self.chat()
        turn(self.store, KEY, p1, reply)
        self.assertEqual(self.store.save(KEY), "saved")
        self.assertEqual(self.store.save(KEY), "unchanged")
        f = self.dir / f"{KEY}.safetensors"
        self.assertTrue(f.is_file())
        self.assertEqual(list(self.dir.glob("*.tmp-*")), [])
        # "restart": a fresh store, same model
        store2 = W.SessionStore(FakeOps(), self.dir, IDENT)
        self.assertEqual(store2.restore(KEY), "restored")
        self.assertEqual(store2.restore(KEY), "warm")
        s, n, how = turn(store2, KEY, p2, [1])
        self.assertEqual((n, how), (len(p1) - 1, "hit-memory"))
        # lazily on the first request too, without an explicit restore
        store3 = W.SessionStore(FakeOps(), self.dir, IDENT)
        _, n, how = store3.prepare(KEY, p2)
        self.assertEqual((n, how), (len(p1) - 1, "hit-disk"))

    def test_mismatched_or_corrupt_file_is_cold_never_a_crash(self):
        p1, reply, _ = self.chat()
        turn(self.store, KEY, p1, reply)
        self.store.save(KEY)
        other = W.SessionStore(FakeOps(), self.dir, dict(IDENT, model="/m/qwen"))
        self.assertEqual(other.restore(KEY), "rejected")
        _, n, how = other.prepare(KEY, p1)
        self.assertEqual((n, how), (0, "cold"))
        layout = W.SessionStore(FakeOps(layout=("KVCache", "KVCache")), self.dir, IDENT)
        self.assertEqual(layout.restore(KEY), "rejected")
        quant = W.SessionStore(FakeOps(), self.dir, dict(IDENT, kv_bits=8))
        self.assertEqual(quant.restore(KEY), "rejected")  # saved with a 16-bit cache
        (self.dir / f"{KEY}.safetensors").write_text("garbage")
        self.assertEqual(W.SessionStore(FakeOps(), self.dir, IDENT).restore(KEY), "rejected")

    def test_metadata_token_count_must_match_cache(self):
        s = W.Session(KEY, self.ops.new_cache())
        s.cache[0].feed([1, 2, 3])
        s.tokens = [1, 2]
        md = self.store._metadata(s)
        self.assertIn("doesn't match", self.store.check_metadata(md, s.cache))
        s.tokens = [1, 2, 3]
        self.assertIsNone(self.store.check_metadata(self.store._metadata(s), s.cache))

    def test_bad_keys_and_anonymous_session_never_touch_disk(self):
        p1, reply, _ = self.chat()
        for key in (None, "../../etc/passwd", "a/b", "x" * 65, W.ANON):
            s, _, _ = turn(self.store, key, p1, reply)
            self.assertEqual(s.key, W.ANON)
        self.assertEqual(self.store.save(W.ANON), "off")
        self.assertEqual(self.store.flush(), 0)
        self.assertFalse(self.dir.exists())

    def test_no_persist(self):
        store = W.SessionStore(self.ops, self.dir, IDENT, persist=False)
        turn(store, KEY, *self.chat()[:2])
        self.assertEqual(store.save(KEY), "off")
        self.assertEqual(store.restore("ffffffffffffffff"), "miss")

    def test_lru_eviction_saves_dirty_sessions_first(self):
        store = W.SessionStore(self.ops, self.dir, IDENT, max_sessions=2, clock=iter(range(1000)).__next__)
        p1, reply, _ = self.chat()
        for k in ("aaaa", "bbbb", "cccc"):
            turn(store, k, p1, reply)
        self.assertEqual(sorted(store.sessions), ["bbbb", "cccc"])
        self.assertTrue((self.dir / "aaaa.safetensors").is_file())   # saved before eviction
        _, n, how = store.prepare("aaaa", p1 + [1, 2])
        self.assertEqual(how, "hit-disk")

    def test_active_session_is_never_evicted_by_byte_limit(self):
        store = W.SessionStore(self.ops, self.dir, IDENT, max_bytes=1)
        p1, reply, p2 = self.chat()
        turn(store, "aaaa", p1, reply)
        turn(store, "bbbb", p1, reply)
        self.assertEqual(list(store.sessions), ["bbbb"])
        _, n, how = store.prepare("bbbb", p2)
        self.assertEqual(how, "hit-memory")

    def test_drop_and_describe(self):
        turn(self.store, KEY, *self.chat()[:2])
        d = self.store.describe()
        self.assertEqual((d[0]["key"], d[0]["dirty"], d[0]["turns"], d[0]["on_disk"]), (KEY, True, 1, False))
        self.assertEqual(self.store.drop([KEY, "nope"]), [KEY])
        self.assertEqual(self.store.describe(), [])

    def test_cancelled_turn_rewinds_without_marking_dirty(self):
        p1, reply, p2 = self.chat()
        s, _, _ = self.store.prepare(KEY, p1)
        for c in s.cache:
            c.feed(p1[:-1])
        self.store.checkpoint(s, p1[:-1])
        for c in s.cache:
            c.feed([1, 2])
        self.store.rewind(s, completed=False)
        self.assertFalse(s.dirty)
        self.assertEqual(s.cache[0].toks, p1[:-1])
        _, n, how = self.store.prepare(KEY, p2)
        self.assertEqual((n, how), (len(p1) - 1, "hit-memory"))


def split_all(raw, pieces):
    sp = W.HarmonySplitter()
    out = []
    for p in pieces:
        out += sp.feed(p)
    out += sp.flush()
    return ("".join(t for k, t in out if k == "reasoning"), "".join(t for k, t in out if k == "normal"))


class HarmonyTest(unittest.TestCase):
    RAW = ('<|channel|>analysis<|message|>The user asks: 17*23 = 391. Answer briefly.<|end|>'
           '<|start|>assistant<|channel|>final<|message|>391<|return|>')

    def test_final_and_reasoning_split_cleanly(self):
        r, c = split_all(self.RAW, [self.RAW])
        self.assertEqual(c, "391")
        self.assertEqual(r, "The user asks: 17*23 = 391. Answer briefly.")

    def test_any_chunking_gives_the_same_result(self):
        """Tokens arrive as '<|channel|>', 'final', '<|message|>' -- or worse."""
        want = split_all(self.RAW, [self.RAW])
        rng = random.Random(7)
        for _ in range(200):
            cuts = sorted(rng.sample(range(1, len(self.RAW)), rng.randint(1, 40)))
            pieces = [self.RAW[i:j] for i, j in zip([0] + cuts, cuts + [len(self.RAW)])]
            self.assertEqual(split_all(self.RAW, pieces), want)
        self.assertEqual(split_all(self.RAW, list(self.RAW)), want)

    def test_reply_without_channels_is_content(self):
        self.assertEqual(split_all("", list("5 < 6, ok")), ("", "5 < 6, ok"))

    def test_tool_call_commentary_is_not_content(self):
        raw = '<|channel|>commentary to=functions.get <|constrain|>json<|message|>{"a":1}<|call|>'
        self.assertEqual(split_all(raw, list(raw)), ('{"a":1}', ""))

    def test_unfinished_reasoning_stays_reasoning(self):
        raw = "<|channel|>analysis<|message|>still thinking"
        self.assertEqual(split_all(raw, [raw]), ("still thinking", ""))


class FakeTokenizer:
    def __init__(self):
        self.seen = []

    def apply_chat_template(self, msgs, add_generation_prompt, tokenize, **kw):
        self.seen.append(msgs)
        return [ord(ch) for ch in json.dumps(msgs, sort_keys=True)]


class ChatHistoryTest(unittest.TestCase):
    """The history a client sends back must render to the same tokens
    whether or not it echoes llama.cpp-style reasoning_content, so turn-2
    reuse still finds the cached prefix."""

    def test_reasoning_fields_are_not_rendered(self):
        eng = W.Engine.__new__(W.Engine)
        eng.tokenizer = FakeTokenizer()
        base = [{"role": "user", "content": "hi"}, {"role": "assistant", "content": "391"},
                {"role": "user", "content": "next"}]
        echoed = json.loads(json.dumps(base))
        echoed[1]["reasoning_content"] = "The user asks..."
        echoed[1]["reasoning"] = "The user asks..."
        parts = json.loads(json.dumps(base))
        parts[1]["content"] = [{"type": "text", "text": "391"}]
        a = W.Engine.chat_prompt(eng, {"messages": base})
        b = W.Engine.chat_prompt(eng, {"messages": echoed})
        c = W.Engine.chat_prompt(eng, {"messages": parts})
        self.assertEqual(a, b)
        self.assertEqual(a, c)


class CliTest(unittest.TestCase):
    def test_parser_defaults_and_sizes(self):
        a = W.build_parser().parse_args(["--model", "/m"])
        self.assertEqual((a.port, a.prompt_cache_size, a.prefill_step_size), (8092, 4, 2048))
        self.assertEqual(W.parse_bytes("512M"), 512 << 20)
        self.assertEqual(W.parse_bytes("2G"), 2 << 30)
        self.assertEqual(W.parse_bytes("1000"), 1000)
        self.assertIsNone(a.kv_bits)
        q = W.build_parser().parse_args(["--model", "/m", "--kv-bits", "8"])
        self.assertEqual((q.kv_bits, q.kv_group_size), (8, 64))
        with self.assertRaises(SystemExit):
            W.build_parser().parse_args(["--model", "/m", "--kv-bits", "3"])

    def test_valid_key(self):
        self.assertTrue(W.valid_key("0123456789abcdef"))
        for bad in ("", "../x", "a b", None, 5, W.ANON, "x" * 65):
            self.assertFalse(W.valid_key(bad))


class WiredLimitTest(unittest.TestCase):
    """v2.1: the Metal wired limit is set once at startup and held, not
    raised/dropped around every request (v2's per-request behaviour)."""

    class FakeMx:
        REC = 18_190_000_000

        def __init__(self):
            self.limit = 0
            self.calls = []

        def device_info(self):
            return {"max_recommended_working_set_size": self.REC}

        def set_wired_limit(self, n):
            old, self.limit = self.limit, n
            self.calls.append(n)
            return old

    class FakeG:
        def __init__(self, mx):
            self.mx, self.entered = mx, 0

        def wired_limit(self, model, streams):
            import contextlib
            g = self

            @contextlib.contextmanager
            def cm():
                g.entered += 1
                old = g.mx.set_wired_limit(g.mx.REC)
                try:
                    yield
                finally:
                    g.mx.set_wired_limit(old)
            return cm()

    def _setup(self, mode):
        mx = self.FakeMx()
        G = self.FakeG(mx)
        res = W.apply_startup_wiring(mode, mx, lambda: mx.set_wired_limit(mx.REC))
        return mx, G, res

    def test_default_mode_is_startup(self):
        self.assertEqual(W.build_parser().parse_args(["--model", "/m"]).wired_limit, "startup")
        with self.assertRaises(SystemExit):
            W.build_parser().parse_args(["--model", "/m", "--wired-limit", "bogus"])

    def test_startup_sets_once_and_requests_never_toggle(self):
        mx, G, res = self._setup("startup")
        self.assertEqual(res, (0, mx.REC))
        self.assertEqual(mx.calls, [mx.REC])
        for _ in range(5):
            with W.request_wiring("startup", G, object(), None):
                self.assertEqual(mx.limit, mx.REC)
            self.assertEqual(mx.limit, mx.REC)  # still held after the request
        self.assertEqual(G.entered, 0)
        self.assertEqual(mx.calls, [mx.REC])  # never touched again

    def test_per_request_reproduces_v2_toggle(self):
        mx, G, res = self._setup("per-request")
        self.assertIsNone(res)
        self.assertEqual(mx.calls, [])
        for _ in range(3):
            with W.request_wiring("per-request", G, object(), None):
                self.assertEqual(mx.limit, mx.REC)
            self.assertEqual(mx.limit, 0)  # dropped back after each request
        self.assertEqual(G.entered, 3)
        self.assertEqual(mx.calls, [mx.REC, 0] * 3)

    def test_off_never_touches_limit(self):
        mx, G, res = self._setup("off")
        self.assertIsNone(res)
        with W.request_wiring("off", G, object(), None):
            pass
        self.assertEqual((mx.calls, G.entered), ([], 0))

    def test_no_recommended_size(self):
        mx = self.FakeMx()
        self.assertIsNone(W.apply_startup_wiring("startup", mx, lambda: None))


if __name__ == "__main__":
    unittest.main()
