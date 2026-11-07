import time, unittest
import web_picker


class TestMonotonic(unittest.TestCase):
    def test_never_backwards(self):
        prev = {"have_bytes": 500, "pct": 50, "total_bytes": 1000}
        out = web_picker.monotonic_snap(prev, {"have_bytes": 100, "pct": 10})
        self.assertEqual(out["have_bytes"], 500)
        self.assertEqual(out["pct"], 50)

    def test_caps_below_100_until_done(self):
        out = web_picker.monotonic_snap({}, {"have_bytes": 2000, "pct": 0, "total_bytes": 1000})
        self.assertEqual(out["pct"], 99)


class TestRemoteRawFolded(unittest.TestCase):
    def test_raw_remote_measure_gets_pct_and_msg(self):
        calls = {"n": 0}
        def measure():
            calls["n"] += 1
            return {"have_bytes": 400 * calls["n"], "n_incomplete": 1, "source": "disk"}
        def run(repo, dest, layers, prog):
            prog(30, "downloading shards")
            time.sleep(2.2)
        job = web_picker.start_download("x/y", runners=[{
            "id": "exo2", "label": "EXO2", "role": "packer", "dest": "/nonexistent",
            "run": run, "measure": measure, "total_bytes": 10000}])
        time.sleep(1.9)
        j = web_picker.get_job(job["id"])
        p = j["progress"]["exo2"]
        self.assertGreater(p["have_bytes"], 0)
        self.assertGreater(p["pct"], 0)
        self.assertIn("GB", p["msg"])
        self.assertEqual(p.get("stage"), "downloading shards")
        time.sleep(1.2)
        j = web_picker.get_job(job["id"])
        self.assertEqual(j["status"], "done")
        self.assertEqual(j["progress"]["exo2"]["pct"], 100)
        self.assertEqual(j["progress"]["exo2"]["state"], "done")

    def test_measure_error_is_shown(self):
        def measure():
            return {"have_bytes": 0, "source": "starting", "measure_error": "SyntaxError"}
        def run(repo, dest, layers, prog):
            time.sleep(1.5)
        job = web_picker.start_download("x/z", runners=[{
            "id": "exo2", "label": "EXO2", "role": "packer", "dest": "/nonexistent",
            "run": run, "measure": measure, "total_bytes": 10000}])
        time.sleep(1.2)
        p = web_picker.get_job(job["id"])["progress"]["exo2"]
        self.assertIn("can't read progress", p["msg"])
