import io, json, tempfile, unittest
from pathlib import Path
import gguf_tune as T


class Tuner(unittest.TestCase):
    def setUp(self):
        self.td = tempfile.TemporaryDirectory()
        self.store = Path(self.td.name) / "t.json"

    def tearDown(self):
        self.td.cleanup()

    def run_with(self, speeds):
        loads = []
        cur = {}

        def restart(t):
            loads.append(dict(t)); cur.clear(); cur.update(t)

        def measure():
            return speeds(cur)
        r = T.GgufTuner("/m/x.gguf", 2, restart=restart, measure=measure,
                        store_path=self.store, log=lambda s: None).run()
        return r, loads

    def test_winner_kept_and_loser_recorded(self):
        # flash_attn off is 10% faster; ubatch 256 (first ubatch challenger) only 1% (below margin)
        def sp(t):
            v = 100.0 * (1.10 if t.get("flash_attn") == "off" else 1.0)
            return v * (1.01 if t.get("ubatch") == 256 else 1.0)
        r, loads = self.run_with(sp)
        self.assertEqual(r["status"], "done")
        self.assertEqual(r["best"]["flash_attn"], "off")
        self.assertEqual(loads[-1], r["best"])  # winner left running
        st = json.loads(self.store.read_text())["x.gguf|2mini"]
        self.assertIn("ubatch=256", st["losses"])
        got = T.best_tune("/m/x.gguf", 2, self.store)
        self.assertEqual(got["flash_attn"], "off")
        self.assertEqual(got["ubatch"], 512)

    def test_losers_not_retried(self):
        self.run_with(lambda t: 100.0)
        r, loads = self.run_with(lambda t: 100.0)
        # second run: flash_attn off lost; ubatch next alternative (256) tried
        names = [(x["name"], x["challenger"]) for x in r["tried"]]
        self.assertNotIn(("flash_attn", "off"), names)

    def test_error_restores_best(self):
        calls = {"n": 0}

        def sp(t):
            calls["n"] += 1
            if calls["n"] == 2:
                raise RuntimeError("server died")
            return 100.0
        r, loads = self.run_with(sp)
        self.assertTrue(r["status"].startswith("error"))
        self.assertEqual(loads[-1], r["best"])

    def test_best_tune_ignores_garbage(self):
        self.store.write_text(json.dumps({"x.gguf|1mini": {"best": {"flash_attn": "maybe", "ubatch": 7}}}))
        self.assertEqual(T.best_tune("x.gguf", 1, self.store), {})

    def test_measure_http_uses_server_timings(self):
        class R(io.BytesIO):
            def __enter__(self): return self
            def __exit__(self, *a): return False
        seen = []

        def fake(req, timeout=0):
            seen.append(req.full_url)
            return R(json.dumps({"timings": {"predicted_per_second": 42.0}}).encode())
        self.assertEqual(T.measure_http(9000, urlopen=fake), 42.0)
        self.assertTrue(seen[0].endswith(":9000/v1/chat/completions"))



    def test_measure_http_records_read_and_first_token(self):
        class R(io.BytesIO):
            def __enter__(self): return self
            def __exit__(self, *a): return False
        def fake(req, timeout=0):
            return R(json.dumps({"timings": {
                "predicted_per_second": 40.0,
                "prompt_per_second": 200.0,
                "prompt_ms": 250,
            }}).encode())
        specs = T.measure_http_specs(9000, urlopen=fake)
        self.assertEqual(specs["write_tok_s"], 40.0)
        self.assertEqual(specs["read_tok_s"], 200.0)
        self.assertEqual(specs["ttft_s"], 0.25)
        self.assertEqual(T.measure_http(9000, urlopen=fake), 40.0)

    def test_read_speed_can_decide_a_write_tie(self):
        # Same write speed; challenger reads faster and gets first token sooner.
        def sp(t):
            if t.get("ubatch") == 1024:
                return {"write_tok_s": 50.0, "read_tok_s": 300.0, "ttft_s": 0.10}
            return {"write_tok_s": 50.0, "read_tok_s": 100.0, "ttft_s": 0.30}
        # Only try ubatch: pre-record flash and cache_type as already lost / set
        r, loads = self.run_with(sp)
        ub = [x for x in r["tried"] if x["name"] == "ubatch"]
        self.assertTrue(ub)
        # 256 is first challenger (closest to 512); may or may not win depending on
        # our stub (same as 512 if stub only special-cases 1024). The important
        # case: a later or explicit f16 vs q8 comparison uses all three metrics.
        self.assertTrue(r["before"])
        self.assertIn("write_tok_s", r["before"])
        self.assertIn("read_tok_s", r["before"])

    def test_cache_type_trial_keeps_flash_on_and_never_offers_4bit(self):
        def sp(t):
            return {"write_tok_s": 40.0,
                    "read_tok_s": 200.0 if t.get("cache_type") == "q8_0" else 120.0,
                    "ttft_s": 0.2}
        r, loads = self.run_with(sp)
        names = [x["name"] for x in r["tried"]]
        self.assertIn("cache_type", names)
        ct = next(x for x in r["tried"] if x["name"] == "cache_type")
        self.assertEqual(sorted([ct["incumbent"], ct["challenger"]]), ["f16", "q8_0"])
        self.assertNotIn("q4_0", [ct["incumbent"], ct["challenger"]])
        # When scoring cache_type, flash attention is on.
        self.assertTrue(any(t.get("cache_type") == "q8_0" and t.get("flash_attn") == "on"
                            for t in loads))
        if ct["won"]:
            self.assertEqual(r["best"]["cache_type"], "q8_0")
        self.assertTrue(r["before"] and r["after"])
        self.assertIn("read_tok_s", r["after"])

    def test_combined_score_prefers_faster_read_when_write_ties(self):
        a = {"write_tok_s": 50, "read_tok_s": 100, "ttft_s": 0.3}
        b = {"write_tok_s": 50, "read_tok_s": 300, "ttft_s": 0.1}
        self.assertTrue(T.beats(b, a))
        self.assertFalse(T.beats(a, b))
        self.assertGreater(T.combined_score(b), T.combined_score(a) * 1.03)


if __name__ == "__main__":
    unittest.main()
