import time, unittest
import web_picker


class NetAccumulate(unittest.TestCase):
    def test_drop_when_flow_closes_is_not_backwards(self):
        prev = None
        seq = [0, 400, 969, 836, 900]
        for raw in seq:
            acc = web_picker.accumulate_net(prev, raw)
            prev = {"net_acc": acc, "net_last": raw}
        self.assertEqual(acc, 969 + 64)

    def test_none_keeps_value(self):
        self.assertEqual(web_picker.accumulate_net({"net_acc": 7, "net_last": 3}, None), 7)


class NetworkErrorClass(unittest.TestCase):
    def test_classify(self):
        self.assertTrue(web_picker.is_network_error(RuntimeError("Read timed out")))
        self.assertTrue(web_picker.is_network_error(RuntimeError("Connection reset by peer")))
        self.assertFalse(web_picker.is_network_error(RuntimeError("401 Unauthorized")))
        self.assertFalse(web_picker.is_network_error(RuntimeError("cancelled")))


class Retry(unittest.TestCase):
    def test_retries_network_then_succeeds(self):
        old = web_picker.RETRY_BACKOFF_S
        web_picker.RETRY_BACKOFF_S = (0.1, 0.1, 0.1)
        try:
            calls = {"n": 0}
            def run(*a):
                calls["n"] += 1
                if calls["n"] < 3:
                    raise RuntimeError("Connection reset by peer")
            job = web_picker.start_download("x/retry", runners=[{
                "id": "exo2", "label": "EXO2", "role": "packer", "dest": "/nonexistent",
                "run": run, "measure": lambda: {"have_bytes": 0}, "total_bytes": 10}])
            for _ in range(60):
                if web_picker.get_job(job["id"])["status"] in ("done", "error"):
                    break
                time.sleep(0.1)
            j = web_picker.get_job(job["id"])
            self.assertEqual(j["status"], "done")
            self.assertEqual(calls["n"], 3)
            self.assertEqual(j["progress"]["exo2"]["retry"]["n"], 2)
        finally:
            web_picker.RETRY_BACKOFF_S = old

    def test_auth_error_not_retried(self):
        calls = {"n": 0}
        def run(*a):
            calls["n"] += 1
            raise RuntimeError("401 Unauthorized")
        job = web_picker.start_download("x/auth", runners=[{
            "id": "exo2", "label": "EXO2", "role": "packer", "dest": "/nonexistent",
            "run": run, "measure": lambda: {"have_bytes": 0}, "total_bytes": 10}])
        for _ in range(40):
            if web_picker.get_job(job["id"])["status"] in ("done", "error"):
                break
            time.sleep(0.1)
        self.assertEqual(web_picker.get_job(job["id"])["status"], "error")
        self.assertEqual(calls["n"], 1)


class ResumeBase(unittest.TestCase):
    def test_progress_starts_from_bytes_on_disk(self):
        seq = iter([{"have_bytes": 600, "disk_have": 600, "net_raw": None}] +
                   [{"have_bytes": 600, "disk_have": 600, "net_raw": 100}] * 20)
        job = web_picker.start_download("x/resume", runners=[{
            "id": "exo2", "label": "EXO2", "role": "packer", "dest": "/nonexistent",
            "run": lambda *a: time.sleep(2.5), "measure": lambda: next(seq), "total_bytes": 1000}])
        time.sleep(2.0)
        p = web_picker.get_job(job["id"])["progress"]["exo2"]
        self.assertEqual(p["resume_base"], 600)
        self.assertEqual(p["have_bytes"], 700)


if __name__ == "__main__":
    unittest.main()


class DoneBeforeFirstMeasure(unittest.TestCase):
    def test_done_uses_planned_size(self):
        job = web_picker.start_download("x/fast", runners=[{
            "id": "exo1", "label": "EXO1", "role": "lead", "dest": "/nonexistent",
            "run": lambda *a: None, "measure": lambda: (time.sleep(2) or {"have_bytes": 0}),
            "total_bytes": 278064920}])
        for _ in range(30):
            if web_picker.get_job(job["id"])["status"] == "done":
                break
            time.sleep(0.1)
        p = web_picker.get_job(job["id"])["progress"]["exo1"]
        self.assertEqual(p["have_bytes"], 278064920)
