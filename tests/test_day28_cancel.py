"""Day 28: Auto-tune cancel feedback, "Cancel Auto-tune and apply", and
busy/result states on buttons that gave none."""
from __future__ import annotations

import re
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
sys.path.insert(0, str(ROOT / "proxy"))
sys.path.insert(0, str(ROOT / "agent"))
import web_gguf_optimize as WGO  # noqa: E402
from i18n_check import english_source  # Day 32: page/CLI text lives in locales/en.json

HTML = english_source(ROOT / "proxy" / "web" / "index.html")
NODE = shutil.which("node")


class Mgr:
    _loaded_entry = None

    def snapshot(self):
        return {"status": "ready", "model_id": "gguf/m", "backend": "llama",
                "settings": {}, "gguf": {"nodes": [1]}}

    def switch(self, *a, **k):
        return self.snapshot()


class CancelState(unittest.TestCase):
    def test_gguf_snapshot_says_cancelling_until_the_run_ends(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        gate = threading.Event()

        class SlowTuner:
            def __init__(self, *a, cancelled=None, **k):
                self.cancelled = cancelled

            def run(self):
                gate.wait(5)  # the "current step" still finishing
                return {"status": "cancelled" if self.cancelled() else "done", "best": {},
                        "tried": [], "before": None, "after": None}

        mgr = Mgr()
        mgr._loaded_entry = {"source": "gguf", "lead_path": str(Path(tmp.name) / "m.gguf")}
        Path(mgr._loaded_entry["lead_path"]).write_bytes(b"x")
        opt = WGO.GgufOptimizer(mgr, tuner_cls=SlowTuner, measure=lambda: 1.0,
                                store_path=Path(tmp.name) / "t.json")
        s = opt.start()
        self.assertFalse(s.get("cancelling"))
        s = opt.cancel()
        self.assertTrue(s["running"])
        self.assertTrue(s["cancelling"])
        gate.set()
        opt._thread.join(5)
        s = opt.snapshot()
        self.assertFalse(s["running"])
        self.assertFalse(s["cancelling"])
        self.assertIn("cancel", s["phase"])

    def test_mlx_snapshot_reports_cancelling(self):
        src = english_source(ROOT / "proxy" / "web_optimize.py")
        self.assertIn('out["cancelling"] = bool(out.get("running") and self._cancel.is_set())', src)

    def test_load_409_while_tuning_has_a_code(self):
        src = english_source(ROOT / "proxy" / "web_server.py")
        self.assertEqual(src.count('"code": "optimize_running"'), 2)


class CancelPage(unittest.TestCase):
    @unittest.skipUnless(NODE, "node not installed")
    def test_cancel_harness(self):
        r = subprocess.run([NODE, str(ROOT / "tests/js/tune_cancel_harness.js")],
                           capture_output=True, text=True, timeout=60)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn("tune cancel harness ok", r.stdout)

    def test_cancel_and_apply_dialog(self):
        self.assertIn('<dialog id="tuneBlockDialog"', HTML)
        self.assertIn(">Cancel Auto-tune and apply</button>", HTML)
        self.assertIn(">Keep tuning</button>", HTML)
        self.assertIn('e.code === "optimize_running"', HTML)
        self.assertIn('$("btnApply").onclick = () => loadPicked(false);', HTML)
        self.assertIn('setApplyBusy("Cancelling Auto-tune…")', HTML)

    def test_end_states_keep_a_fixed_box(self):
        m = re.search(r"\.tune-badge\.is-cancelling::before, \.tune-badge\.is-ended::before \{([^}]*)\}", HTML)
        self.assertIsNotNone(m)
        for rule in ("width: 1em", "height: 1em", "line-height: 1", "overflow: hidden"):
            self.assertIn(rule, m.group(1))
        self.assertIn("@keyframes tune-ember", HTML)
        self.assertIn("#tuneHeaderBadge { min-width: 6.6rem;", HTML)

    def test_buttons_show_busy_and_result(self):
        for needle in ('b.textContent = "Resetting…"', 'showTuneDone("Tuning reset',
                       'b.textContent = "Unloading…"', 'b.textContent = "Saving…"',
                       'b.textContent = "Removing…"', 'c.textContent = "Stopping…"',
                       'del.textContent = "Deleting…"', 'l.textContent = "Loading…"',
                       '"Turning on…" : "Turning off…"', '"Resuming…" : "Pausing…"'):
            self.assertIn(needle, HTML)
        self.assertIn("Stopping download…", english_source(ROOT / "proxy/web/helpers.js"))
        self.assertIn("'Stopping…'", english_source(ROOT / "proxy/web/helper_line.js"))
        self.assertIn("Stopping this fetch…", english_source(ROOT / "proxy/web/balance.js"))


if __name__ == "__main__":
    unittest.main()
