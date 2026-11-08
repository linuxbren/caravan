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
        self.assertEqual(T.best_tune("/m/x.gguf", 2, self.store), {"flash_attn": "off", "ubatch": 512})

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


if __name__ == "__main__":
    unittest.main()
