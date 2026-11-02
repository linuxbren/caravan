"""v3 (2026-10-31): one MLX model split across two Minis (agent/mlx_split.py).
No mlx: both stages use the fake cache layers from test_mlx_worker.py, the
"forward pass" just feeds tokens to each layer, and the head talks to a
FrontState over a real socketpair, so the lockstep, the per-stage disk
files and the "both halves or neither" restore rule are all exercised."""
import socket
import sys
import tempfile
import threading
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "agent"))
sys.path.insert(0, str(REPO / "tests"))

import mlx_split as S  # noqa: E402
import mlx_worker as W  # noqa: E402
from test_mlx_worker import FakeOps, KEY  # noqa: E402

IDENT = {"model": "/m/gemma", "tokenizer": "abc", "mlx_lm": "0.32.2", "model_type": "gemma4"}


class PlanTest(unittest.TestCase):
    def test_even_and_odd(self):
        self.assertEqual(S.plan_split(48), ((0, 24), (24, 48)))
        self.assertEqual(S.plan_split(30), ((0, 15), (15, 30)))
        self.assertEqual(S.plan_split(25), ((0, 12), (12, 25)))   # odd layer to the head

    def test_explicit_and_bad(self):
        self.assertEqual(S.plan_split(24, 10), ((0, 10), (10, 24)))
        for bad in (0, 24, 30, -1):
            if bad == 0:
                continue        # 0 means default
            with self.assertRaises(ValueError):
                S.plan_split(24, bad)
        with self.assertRaises(ValueError):
            S.plan_split(1)

    def test_label(self):
        self.assertEqual(S.stage_label("front", (0, 24), 48), "front 0-23 of 48")
        # saved-cache ids keep the old wording; people see lead / packer
        self.assertEqual(S.stage_title("front", (0, 24), 48), "packer 1: layers 0-23 of 48")
        self.assertEqual(S.stage_title("head", (24, 48), 48), "lead: layers 24-47 of 48")
        self.assertEqual(S.title_from_label("front 0-23 of 48"), "packer 1: layers 0-23 of 48")


class FrameTest(unittest.TestCase):
    def test_roundtrip_big_payload(self):
        a, b = socket.socketpair()
        payload = bytes(range(256)) * 40000          # ~10 MB, a prefill chunk of hidden states
        t = threading.Thread(target=lambda: a.sendall(S.encode_frame({"op": "x", "n": 3}, payload)))
        t.start()
        h, p = S.read_frame(b)
        t.join()
        self.assertEqual(h, {"op": "x", "n": 3})
        self.assertEqual(p, payload)
        a.close()
        with self.assertRaises(ConnectionError):
            S.read_frame(b)
        b.close()


class RestoreRuleTest(unittest.TestCase):
    def test_rule(self):
        self.assertEqual(S.combine_restore("restored", "d1", "restored", "d1"), "ok")
        self.assertEqual(S.combine_restore("warm", "d1", "restored", "d1"), "ok")
        self.assertEqual(S.combine_restore("restored", "d1", "restored", "d2"), "mismatch")
        self.assertEqual(S.combine_restore("restored", "d1", "miss", None), "mismatch")
        self.assertEqual(S.combine_restore("miss", None, "warm", "d1"), "mismatch")
        self.assertEqual(S.combine_restore("miss", None, "miss", None), "miss")
        self.assertEqual(S.combine_restore("rejected", None, "miss", None), "miss")


def feed(tokens, cache):
    for c in cache:
        c.feed(tokens)


class Pair:
    """A head store + SplitSessions and a front FrontState on a socketpair."""

    def __init__(self, root, max_sessions=4, max_bytes=None, layout_head=("KVCache", "RotatingKVCache"),
                 layout_front=("RotatingKVCache", "KVCache")):
        self.root = Path(root)
        self.head_ops, self.front_ops = FakeOps(layout_head), FakeOps(layout_front)
        self.head = W.SessionStore(self.head_ops, self.root / "head", dict(IDENT, stage="head 1-1 of 2"),
                                   max_sessions=max_sessions, max_bytes=max_bytes)
        self.start_front()
        self.split = S.SplitSessions(self.head, self.client, log=lambda m: None)

    def start_front(self, store=None):
        self.front_store = store or W.SessionStore(self.front_ops, self.root / "front",
                                                   dict(IDENT, stage="front 0-0 of 2"),
                                                   max_sessions=1 << 20)
        self.front_fwd = []

        def forward(tokens, cache):
            self.front_fwd.append(list(tokens))
            feed(tokens, cache)
            return {"dtype": "bfloat16", "shape": [1, len(tokens), 1]}, b"h" * len(tokens)
        self.state = S.FrontState(self.front_store, forward, {"stage": "front 0-0 of 2"},
                                  new_scratch=self.front_ops.new_cache)
        a, b = socket.socketpair()
        self._srv = b

        def serve():
            try:
                while True:
                    h, p = S.read_frame(b)
                    rh, rp = self.state.handle(h, p)
                    b.sendall(S.encode_frame(rh, rp))
            except (ConnectionError, OSError):
                pass
        threading.Thread(target=serve, daemon=True).start()
        if not hasattr(self, "client"):
            self.client = S.FrontClient("front:1", connect=lambda: a)
        else:
            self.client.close()
            self.client._connect = lambda: a

    def turn(self, key, prompt, reply):
        """Engine._run in split mode: prepare both, prefill (front then head), checkpoint, generate, rewind."""
        s, n, how = self.split.prepare(key, prompt)
        todo = prompt[n:-1]
        if todo:
            self.client.call("fwd", tokens=todo, ctx="session")
            feed(todo, s.cache)
        self.split.checkpoint(s, prompt[:-1])
        for t in prompt[-1:] + reply:
            self.client.call("fwd", tokens=[t], ctx="session")
            feed([t], s.cache)
        self.split.rewind(s, completed=True)
        return s, n, how

    def front_session(self, key):
        return self.front_store.sessions.get(key)


class SplitSessionsTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.p = Pair(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def chat(self, p=None):
        p = p or self.p
        p1 = list(range(100, 140))
        s, n, how = p.turn(KEY, p1, [7, 7, 7])
        self.assertEqual((n, how), (0, "cold"))
        p2 = p1 + [9, 9] + list(range(200, 210))       # reply re-rendered + new message
        s, n, how = p.turn(KEY, p2, [8])
        self.assertEqual(n, len(p1) - 1)
        self.assertTrue(how.startswith("hit"), how)
        return p2

    def test_lockstep_reuse_and_only_new_tokens_cross(self):
        p2 = self.chat()
        hs, fs = self.p.head.sessions[KEY], self.p.front_session(KEY)
        self.assertEqual(hs.tokens, fs.tokens)
        self.assertEqual(hs.tokens, p2[:-1])
        # second turn sent only the new part of the prompt to the front
        self.assertEqual(self.p.front_fwd[5], p2[39:-1])

    def test_save_writes_one_file_per_stage_and_restore_needs_both(self):
        self.chat()
        self.assertEqual(self.p.split.save(KEY), "saved")
        self.assertTrue((Path(self.tmp.name) / "head" / f"{KEY}.safetensors").is_file())
        self.assertTrue((Path(self.tmp.name) / "front" / f"{KEY}.safetensors").is_file())
        # restart both: fresh stores on the same dirs
        p = Pair(self.tmp.name)
        self.assertEqual(p.split.restore(KEY), "restored")
        self.assertEqual(p.head.sessions[KEY].tokens, p.front_session(KEY).tokens)

    def test_one_half_missing_means_cold_on_both(self):
        self.chat()
        self.p.split.save(KEY)
        (Path(self.tmp.name) / "front" / f"{KEY}.safetensors").unlink()
        p = Pair(self.tmp.name)
        self.assertEqual(p.split.restore(KEY), "rejected")
        self.assertNotIn(KEY, p.head.sessions)
        self.assertIsNone(p.front_session(KEY))
        s, n, how = p.turn(KEY, list(range(100, 150)), [1])
        self.assertEqual(n, 0)

    def test_halves_from_different_turns_are_not_mixed(self):
        p2 = self.chat()
        self.p.split.save(KEY)
        front_file = Path(self.tmp.name) / "front" / f"{KEY}.safetensors"
        old = front_file.read_bytes()
        self.p.turn(KEY, p2 + [5, 5] + list(range(300, 305)), [4])
        self.p.split.save(KEY)
        front_file.write_bytes(old)                 # front half is one turn behind
        p = Pair(self.tmp.name)
        self.assertEqual(p.split.restore(KEY), "rejected")

    def test_prepare_restores_lazily_without_proxy_call(self):
        self.chat()
        self.p.split.save(KEY)
        p = Pair(self.tmp.name)
        p1 = list(range(100, 140))
        s, n, how = p.turn(KEY, p1 + [9, 9] + list(range(200, 210)) + [1, 2, 3], [5])
        self.assertGreater(n, 0)
        self.assertTrue(how.endswith("disk"), how)

    def test_eviction_is_mirrored(self):
        p = Pair(self.tmp.name + "/e", max_sessions=1)
        p.turn("a" * 16, list(range(10, 30)), [1])
        p.turn("b" * 16, list(range(40, 60)), [1])
        self.assertEqual(list(p.head.sessions), ["b" * 16])
        self.assertEqual(sorted(p.front_store.sessions), ["b" * 16])
        # the evicted one was saved on both sides first, and comes back whole
        self.assertEqual(p.split.restore("a" * 16), "restored")

    def test_drop_and_flush(self):
        self.chat()
        self.assertEqual(self.p.split.flush(), 1)
        self.assertTrue((Path(self.tmp.name) / "front" / f"{KEY}.safetensors").is_file())
        self.assertEqual(self.p.split.drop([KEY]), [KEY])
        self.assertIsNone(self.p.front_session(KEY))

    def test_front_restart_drops_head_memory_then_disk_pairs_up(self):
        self.chat()
        self.p.split.save(KEY)
        # front process restarts: new epoch, empty memory, same disk
        self.p.start_front()
        s, n, how = self.p.turn(KEY, self.p.head.sessions[KEY].tokens + [1, 2], [3]) \
            if KEY in self.p.head.sessions else (None, None, None)
        self.assertIsNotNone(s)
        self.assertGreater(n, 0)                    # restored on both sides from disk
        self.assertTrue(how.endswith("disk"), how)

    def test_divergent_reuse_resyncs_cold(self):
        self.chat()
        # front forgets (as if it evicted on its own): head would reuse, front can't
        self.p.front_store.sessions.clear()
        s, n, how = self.p.split.prepare(KEY, self.p.head.sessions[KEY].tokens + [1, 2])
        self.assertEqual((n, how), (0, "split-resync"))

    def test_scratch_forward_does_not_touch_sessions(self):
        self.chat()
        before = list(self.p.front_session(KEY).tokens)
        self.p.client.call("fwd", tokens=[1] * 16, ctx="scratch", new=True)
        self.p.client.call("end_scratch")
        self.assertEqual(self.p.front_session(KEY).tokens, before)

    def test_errors_come_back_as_front_error(self):
        with self.assertRaises(S.FrontError):
            self.p.client.call("nope")
        st = self.p.client.stats
        self.assertGreater(st["calls"], 0)
        self.assertGreater(st["bytes_out"], 0)


if __name__ == "__main__":
    unittest.main()


class KeyFwdTest(unittest.TestCase):
    """Idea 1: packer fwd can name the session key; begin/finish overlaps two sessions."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.p = Pair(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def test_fwd_by_key_two_sessions(self):
        p = self.p
        ka, kb = "sessA", "sessB"
        pa, pb = list(range(10, 20)), list(range(30, 40))
        p.split.prepare(ka, pa)
        p.split.prepare(kb, pb)
        # Interleave fwds by key (not depending on cur alone)
        p.client.call("fwd", tokens=pa[-1:], ctx="session", key=ka)
        p.client.call("fwd", tokens=pb[-1:], ctx="session", key=kb)
        p.client.call("fwd", tokens=[99], ctx="session", key=ka)
        self.assertEqual(p.front_fwd[-3], pa[-1:])
        self.assertEqual(p.front_fwd[-2], pb[-1:])
        self.assertEqual(p.front_fwd[-1], [99])

    def test_begin_finish_call_roundtrip(self):
        p = self.p
        p.split.prepare("s", list(range(5)))
        p.client.begin_call("fwd", tokens=[1], ctx="session", key="s")
        rh, rp = p.client.finish_call()
        self.assertIn("dtype", rh)
        self.assertTrue(len(rp) >= 1)


class AutoTuneTest(unittest.TestCase):
    """ROADMAP #13a: self-tuning packer layers + pipeline chat count."""

    def test_equal_ram_idea5_cuts(self):
        k, reason = S.choose_packer_layers(30, 24.0, 24.0, "gemma4")
        self.assertEqual(k, 16)
        self.assertIn("balanced", reason)
        k, _ = S.choose_packer_layers(24, 24.0, 24.0, "gpt_oss")
        self.assertEqual(k, 13)
        k, _ = S.choose_packer_layers(48, 24.0, 24.0, "qwen3")
        self.assertEqual(k, 24)
        k, _ = S.choose_packer_layers(32, 24.0, 24.0, "llama")
        self.assertEqual(k, 16)
        k, _ = S.choose_packer_layers(48, 24.0, 24.0, "qwen2")
        self.assertEqual(k, 24)

    def test_memory_skew(self):
        # Packer has half the RAM → fewer layers
        k, reason = S.choose_packer_layers(48, 48.0, 24.0, "qwen3")
        self.assertLess(k, 24)
        self.assertGreaterEqual(k, 1)
        self.assertIn("skew", reason.lower())
        # Packer has more RAM → more layers
        k2, _ = S.choose_packer_layers(48, 24.0, 48.0, "qwen3")
        self.assertGreater(k2, 24)

    def test_pipeline_caps_at_two(self):
        n, reason = S.choose_pipeline_chats(total_gb=24.0, weights_gb=5.0, available_gb=18.0)
        self.assertEqual(n, 2)
        self.assertIn("2 chats", reason)
        # Tiny box / huge weights → 1
        n1, reason1 = S.choose_pipeline_chats(total_gb=8.0, weights_gb=6.0, available_gb=1.5)
        self.assertEqual(n1, 1)
        self.assertIn("1 chat", reason1)

    def test_pipeline_never_picks_three(self):
        # Even with huge headroom, auto stays at 2 (Mini wall tops out at 2).
        n, _ = S.choose_pipeline_chats(total_gb=128.0, weights_gb=4.0, available_gb=100.0)
        self.assertEqual(n, 2)

    def test_host_memory_returns_positive(self):
        total, avail = S.host_memory_gb()
        self.assertGreater(total, 0.5)
        self.assertGreaterEqual(avail, 0.0)

