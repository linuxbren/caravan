from __future__ import annotations

import tempfile
import time
import unittest
from pathlib import Path

import download_progress as dp
import web_picker


class DiskNoDoubleCount(unittest.TestCase):
    def test_incomplete_beside_final_counted_once(self):
        with tempfile.TemporaryDirectory() as d:
            (Path(d) / "model-00001.safetensors").write_bytes(b"x" * 1000)
            c = Path(d) / ".cache" / "huggingface" / "download"
            c.mkdir(parents=True)
            (c / "model-00001.safetensors.incomplete").write_bytes(b"x" * 1000)
            (c / "model-00002.safetensors.incomplete").write_bytes(b"x" * 300)
            m = dp.measure_disk(d)
            self.assertEqual(m["have_bytes"], 1300)
            self.assertEqual(m["n_incomplete"], 1)


class Clamp(unittest.TestCase):
    def test_have_never_above_total(self):
        with tempfile.TemporaryDirectory() as d:
            (Path(d) / "a.safetensors").write_bytes(b"x" * 5000)
            snap = dp.combine_progress(dest=d, repo_id="none/none-day18", total_bytes=3000, pid=-1)
            self.assertLessEqual(snap["have_bytes"], 3000)


class StallOnGrowth(unittest.TestCase):
    def test_disk_growth_resets_stall_even_when_shown_bytes_flat(self):
        old = time.time() - 120
        prev = {"have_bytes": 100, "disk_have": 50, "net_raw": 10, "last_byte_t": old}
        self.assertTrue(dp.grew(prev, 100, 60, 10))
        self.assertTrue(dp.grew(prev, 100, 50, 11))
        self.assertFalse(dp.grew(prev, 100, 50, 10))
        self.assertTrue(dp.grew({"have_bytes": 0, "net_last": 5}, 0, None, 6))


class ReportedTotal(unittest.TestCase):
    def test_fetcher_report_sets_node_total(self):
        jid = "day18tot"
        web_picker._job_set(jid, repo_id="r/x", status="running", totals={"exo2": 11_770_000_000})
        try:
            tb = web_picker.apply_reported_total("r/x", "exo2", '{"my_gb": 20.7, "role": "packer"}')
            self.assertEqual(tb, 20_700_000_000)
            self.assertEqual(web_picker.get_job(jid)["totals"]["exo2"], 20_700_000_000)
            self.assertIsNone(web_picker.apply_reported_total("r/x", "exo2", "not json"))
        finally:
            web_picker._job_set(jid, status="done")


if __name__ == "__main__":
    unittest.main()
