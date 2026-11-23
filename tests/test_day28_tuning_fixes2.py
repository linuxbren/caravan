"""Day 28 tuning fix 2: Auto-tune never keeps settings slower than stock
(same-session stock check, fresh starts from stock), thinking-model replies
are not 'garbled', and a GGUF split tunnels over Thunderbolt."""
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
for _p in ("tools", "proxy", "agent"):
    if str(ROOT / _p) not in sys.path:
        sys.path.insert(0, str(ROOT / _p))
import gguf_split as G  # noqa: E402
import gguf_tune as T  # noqa: E402
import web_workers as W  # noqa: E402
from i18n_check import english_source  # Day 32: page/CLI text lives in locales/en.json


def specs(write, total=10.0, edit=None, garbled=False):
    s = {"write_tok_s": write, "short_write_tok_s": write, "total_s": total,
         "short_total_s": total, "read_tok_s": 300.0, "ttft_s": 0.3}
    if edit is not None:
        s["edit_write_tok_s"] = edit
    if garbled:
        s["garbled"] = True
    return s


class Run:
    def __init__(self, measure_for, best=None, losses=None, fresh=True):
        self.loads = []
        self.d = tempfile.TemporaryDirectory()
        self.store = Path(self.d.name) / "t.json"
        self.model = Path(self.d.name) / "m.gguf"
        if best is not None:
            T.save_store({T.entry_key(self.model, 1): {"best": dict(best), "losses": list(losses or []),
                                                       "trials": []}}, self.store)
        self.tuner = T.GgufTuner(self.model, 1, restart=self.loads.append,
                                 measure=lambda: measure_for(self.loads[-1], len(self.loads)),
                                 store_path=self.store, log=lambda m: None, fresh=fresh)

    def go(self):
        res = self.tuner.run()
        e = T.load_store(self.store)[T.entry_key(self.model, 1)]
        self.d.cleanup()
        return res, e


class FinalStockCheckTest(unittest.TestCase):
    def test_pick_slower_than_stock_goes_back_to_stock(self):
        # Prompt lookup "wins" on code edits during its trial, but the
        # same-session check finds chats slower than stock: back to stock.
        def m(tune, n):
            if tune.get("prompt_lookup") == "on":
                return specs(20.0 if n <= 8 else 15.0, edit=30.0)
            return specs(20.0, edit=20.0)
        res, e = Run(m).go()
        self.assertEqual(res["final_check"]["won"], False)
        self.assertEqual(res["best"]["prompt_lookup"], "off")
        self.assertIn("prompt_lookup=on", e["losses"])
        self.assertEqual(res["tried"][-1]["name"], "final_check")
        self.assertEqual(T.stock_tune(), {k: res["best"][k] for k in T.STOCK_TUNE})

    def test_pick_within_noise_is_kept(self):
        def m(tune, n):
            if tune.get("prompt_lookup") == "on":
                return specs(19.8, edit=30.0)
            return specs(20.0, edit=20.0)
        res, _ = Run(m).go()
        self.assertTrue(res["final_check"]["won"])
        self.assertEqual(res["best"]["prompt_lookup"], "on")

    def test_final_check_interleaves_stock_and_pick(self):
        seen = []

        def m(tune, n):
            seen.append(tune.get("prompt_lookup"))
            return specs(25.0 if tune.get("prompt_lookup") == "on" else 20.0)
        r = Run(m)
        r.go()
        self.assertEqual(seen[-4:], ["off", "on", "off", "on"])
        self.assertEqual(r.loads[-1].get("prompt_lookup"), "on")   # winner left running

    def test_no_final_check_when_nothing_changed(self):
        res, e = Run(lambda t, n: specs(20.0)).go()
        self.assertNotIn("final_check", res)
        self.assertFalse(any(t["name"] == "final_check" for t in e["trials"]))

    def test_pick_that_fails_to_load_goes_back_to_stock(self):
        state = {"n": 0}

        def m(tune, n):
            return specs(25.0 if tune.get("prompt_lookup") == "on" else 20.0)
        r = Run(m)
        orig = r.loads.append

        def restart(t):
            orig(t)
            state["n"] += 1
            if state["n"] > 8 and t.get("prompt_lookup") == "on":
                raise RuntimeError("first test reply failed")
        r.tuner.restart = restart
        res, _ = r.go()
        self.assertFalse(res["final_check"]["won"])
        self.assertEqual(res["best"]["prompt_lookup"], "off")

    def test_fresh_starts_from_stock(self):
        seen = []

        def m(tune, n):
            seen.append(dict(tune))
            return specs(20.0)
        Run(m, best={"flash_attn": "off", "ubatch": 256, "prompt_lookup": "on"}).go()
        first = seen[0]
        self.assertEqual(first["ubatch"], G.GGUF_DEFAULT_UBATCH)
        self.assertEqual(first["prompt_lookup"], "off")

    def test_pinned_rows_keep_their_value(self):
        st = T.stock_tune({"prompt_lookup": "on", "ubatch": 256}, pinned=("prompt_lookup",))
        self.assertEqual(st["prompt_lookup"], "on")
        self.assertEqual(st["ubatch"], G.GGUF_DEFAULT_UBATCH)


class GarbledBothSidesTest(unittest.TestCase):
    def test_both_garbled_is_judged_on_speed(self):
        # Qwen3 14B: every reply looked "garbled" (thinking only), so the
        # helper's +40% was thrown away. Equal flags now compare speed.
        with tempfile.TemporaryDirectory() as d:
            draft = Path(d) / "h.gguf"
            draft.write_bytes(b"x")

            def m(tune, n):
                return specs(16.4 if tune.get("guess_ahead") == "on" else 11.7, garbled=True)
            loads = []
            tuner = T.GgufTuner(Path(d) / "m.gguf", 1, restart=loads.append,
                                measure=lambda: m(loads[-1], len(loads)),
                                store_path=Path(d) / "t.json", log=lambda x: None, fresh=True,
                                schedule_kw={"draft_path": str(draft)})
            res = tuner.run()
        self.assertEqual(res["best"]["guess_ahead"], "on")
        self.assertTrue(res["final_check"]["won"])

    def test_one_side_garbled_still_loses(self):
        def m(tune, n):
            if tune.get("prompt_lookup") == "on":
                return specs(30.0, garbled=True)
            return specs(20.0)
        res, _ = Run(m).go()
        self.assertEqual(res["best"]["prompt_lookup"], "off")

    def test_thinking_reply_is_not_garbled(self):
        reply = {"choices": [{"message": {"content": "", "reasoning_content":
                                          "Okay, the user wants a short haiku about rain. Let me think."},
                              "finish_reason": "length"}],
                 "usage": {"completion_tokens": 192, "prompt_tokens": 20},
                 "timings": {"predicted_per_second": 12.0, "prompt_per_second": 100.0,
                             "prompt_ms": 200.0, "predicted_ms": 16000.0}}

        class R:
            def __init__(self, *a, **k): pass
            def __enter__(self): return self
            def __exit__(self, *a): return False
            def read(self): return json.dumps(reply).encode()
        out = T.measure_http_specs(1, prompts=["hi", "there"], urlopen=lambda *a, **k: R())
        self.assertNotIn("garbled", out)

    def test_empty_reply_is_still_garbled(self):
        reply = {"choices": [{"message": {"content": ""}}], "usage": {"completion_tokens": 5}}

        class R:
            def __init__(self, *a, **k): pass
            def __enter__(self): return self
            def __exit__(self, *a): return False
            def read(self): return json.dumps(reply).encode()
        out = T.measure_http_specs(1, prompts=["hi"], urlopen=lambda *a, **k: R())
        self.assertTrue(out.get("garbled"))


class ThunderboltTunnelTest(unittest.TestCase):
    def mgr(self):
        m = W.WorkerManager.__new__(W.WorkerManager)
        m.notes = []
        m._note = m.notes.append
        return m

    def test_split_tunnel_uses_thunderbolt_when_paired_over_it(self):
        m = self.mgr()
        node = {"id": "p", "ssh": "caravan-x", "peer": "ssh+tb://caravan-x/en2:5560"}
        tb = ["ssh", "-o", "HostName=169.254.1.2", "-o", "HostKeyAlias=caravan-x", "-N", "caravan-x"]
        with mock.patch("web_gguf_shares.tunnel_args", return_value=tb) as ta, \
                mock.patch.object(W.subprocess, "Popen") as popen:
            proc, route = m._open_tunnel("caravan-x", 50062, node=node)
        self.assertEqual(route, "thunderbolt")
        self.assertEqual(popen.call_args[0][0], tb)
        ta.assert_called_once()

    def test_falls_back_to_network_when_thunderbolt_is_not_ready(self):
        m = self.mgr()
        node = {"id": "p", "ssh": "caravan-x", "peer": "ssh+tb://caravan-x/en2:5560"}
        with mock.patch("web_gguf_shares.tunnel_args", side_effect=RuntimeError("no link")), \
                mock.patch.object(W.subprocess, "Popen") as popen:
            proc, route = m._open_tunnel("caravan-x", 50062, node=node)
        self.assertEqual(route, "network")
        self.assertEqual(popen.call_args[0][0], G.ssh_tunnel_args("caravan-x", 50062))
        self.assertTrue(any("Thunderbolt" in n for n in m.notes))

    def test_no_thunderbolt_peer_uses_network(self):
        m = self.mgr()
        with mock.patch.object(W.subprocess, "Popen") as popen:
            _, route = m._open_tunnel("host", 50062, node={"id": "p", "ssh": "host"})
        self.assertEqual(route, "network")
        self.assertEqual(popen.call_args[0][0], G.ssh_tunnel_args("host", 50062))

    def test_load_path_passes_the_node(self):
        src = english_source(ROOT / "proxy" / "web_workers.py")
        self.assertIn("self._open_tunnel(target, lp, node=n)", src)


class OneSlotTest(unittest.TestCase):
    def test_one_chat_is_one_slot(self):
        with mock.patch.object(G, "resolve_launch", return_value={"ctx": 32768, "n_slots": 1, "total_ctx": 32768}):
            a = G.llama_args("/m.gguf", port=8194, peers=["127.0.0.1:50062"], shares=[1, 1], tune={})
        self.assertEqual(a[a.index("--parallel") + 1], "1")
        self.assertNotIn("--no-kv-unified", a)
        self.assertEqual(a[a.index("-c") + 1], "32768")

    def test_two_chats_still_two_slots(self):
        with mock.patch.object(G, "resolve_launch", return_value={"ctx": 16384, "n_slots": 2, "total_ctx": 32768}):
            a = G.llama_args("/m.gguf", port=8194, peers=[], shares=[1], tune={"n_slots": 2})
        self.assertEqual(a[a.index("--parallel") + 1], "2")
        self.assertIn("--no-kv-unified", a)


if __name__ == "__main__":
    unittest.main()
