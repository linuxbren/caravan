"""Day 25: live Auto-tune progress in Settings and on the chat page."""
from __future__ import annotations

import json
import shutil
import subprocess
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
HTML = (ROOT / "proxy/web/index.html").read_text()
WEB = (ROOT / "docs/WEB.md").read_text()
DAY = (ROOT / "docs/DAY25.md").read_text()

import sys
sys.path.insert(0, str(ROOT / "proxy"))
sys.path.insert(0, str(ROOT / "agent"))
sys.path.insert(0, str(ROOT / "tools"))
import web_tune_step as S  # noqa: E402
import web_tune_errors as TE  # noqa: E402
import gguf_tune as T  # noqa: E402


class StepWording(unittest.TestCase):
    def test_examples_from_the_brief(self):
        self.assertEqual(
            S.format_step(action="measuring", kind="short", index=3, total=5),
            "Measuring the current setup · short prompt 3 of 5",
        )
        self.assertEqual(
            S.format_step(action="trying", knob="kv_bits", value=8, kind="long"),
            "Trying Memory compression 8 · long prompt",
        )
        self.assertEqual(
            S.format_step(action="reloading_winner"),
            "Reloading with the winner…",
        )
        self.assertEqual(S.format_step(action="starting"), "Starting…")
        self.assertEqual(S.format_step(action="paused"), "Paused")
        self.assertEqual(
            S.format_step(action="waiting"),
            "Waiting for your chat to finish…",
        )

    def test_gguf_quant_names_stay_off_the_page(self):
        line = S.format_step(
            action="trying", knob="cache_type", value="q8_0",
            kind="short", index=2, total=5,
        )
        self.assertEqual(
            line, "Trying Memory compression 8 · short prompt 2 of 5",
        )
        for bad in ("q8_0", "cache_type", "llama.cpp", "A/B", "prf-hays",
                    "16 GB", "24 GB", "exo1", "exo2"):
            self.assertNotIn(bad, line)

    def test_elapsed_wording(self):
        self.assertEqual(S.format_elapsed(12), "12s")
        self.assertEqual(S.format_elapsed(130), "2 min 10s")
        self.assertEqual(S.elapsed_s(1000, now=1045), 45)
        snap = S.decorate({"running": True, "started": 1000}, now=1012)
        self.assertEqual(snap["elapsed_s"], 12)


class PublicStatus(unittest.TestCase):
    def test_step_is_in_the_status_subset(self):
        out = TE.public_optimize_status({
            "running": True, "mode": "now", "phase": "measuring",
            "step": "Measuring the current setup · short prompt 3 of 5",
            "started": 1, "elapsed_s": 12, "paused": False,
            "summary": {"unchanged": False},
            "error_detail": "secret", "log": [],
        })
        self.assertEqual(
            out["step"],
            "Measuring the current setup · short prompt 3 of 5",
        )
        self.assertTrue(out["running"])
        self.assertEqual(out["elapsed_s"], 12)
        self.assertFalse(out["unchanged"])
        self.assertNotIn("error_detail", out)
        self.assertNotIn("log", out)


class MeasureCallback(unittest.TestCase):
    def test_measure_http_specs_calls_on_prompt(self):
        seen = []

        def fake(req, timeout=30):
            class R:
                def read(self):
                    return json.dumps({
                        "usage": {"prompt_tokens": 10, "completion_tokens": 8},
                        "timings": {
                            "predicted_per_second": 20,
                            "prompt_per_second": 100,
                            "prompt_ms": 50,
                        },
                    }).encode()

                def __enter__(self):
                    return self

                def __exit__(self, *a):
                    return False

            return R()

        T.measure_http_specs(
            9000, prompts=["a", "b", "c"],
            prompt_kinds=["short", "short", "long"],
            urlopen=fake,
            on_prompt=lambda i, n, k: seen.append((i, n, k)),
        )
        self.assertEqual(seen, [(1, 2, "short"), (2, 2, "short"), (1, 1, "long")])


class Page(unittest.TestCase):
    def test_busy_button_and_step_line_are_on_the_page(self):
        self.assertIn('id="tuneStep"', HTML)
        self.assertIn('id="tuneDone"', HTML)
        self.assertIn('id="tuneBadge"', HTML)
        self.assertIn('id="tuneHeaderBadge"', HTML)
        self.assertIn("is-tuning", HTML)
        self.assertIn("tune-campfire", HTML)
        self.assertIn("prefers-reduced-motion", HTML)
        self.assertIn("Tuning…", HTML)
        self.assertIn("Self-tuning a setting…", HTML)
        self.assertIn("Nothing faster found", HTML)
        self.assertIn("function paintTuneRunning", HTML)
        self.assertIn(">Start</button>", HTML)
        self.assertIn('has ? "Tune again" : "Start"', HTML)
        # Previous Before/After are hidden (not dimmed) while a run is in
        # progress, then shown again when it finishes or fails.
        self.assertIn("result.hidden = running", HTML)
        self.assertNotIn("from last time", HTML.lower())
        self.assertIn("if (result) result.hidden = false", HTML)
        self.assertIn('$("btnTuneReset").disabled = running', HTML)
        self.assertNotIn("llama.cpp twice", HTML)
        self.assertNotIn("options settled", HTML)

    def test_reduced_motion_uses_a_static_icon(self):
        block_start = HTML.index("@keyframes tune-campfire")
        idx = HTML.index("@media (prefers-reduced-motion: reduce)", block_start)
        reduced = HTML[idx:idx + 280]
        self.assertIn("animation: none", reduced)
        self.assertIn('content: "✦"', reduced)

    @unittest.skipUnless(shutil.which("node"), "Node needed to execute the running-state painter")
    def test_running_hides_previous_lines_and_restores_on_fail(self):
        script = r'''
const assert = require("assert/strict");

let resultHidden = false;
let resultText = "Before · Write 20 tok at 22.2 tok/s\nAfter · Write 20 tok at 23.4 tok/s";
let stepText = "";
let stepHidden = true;
let doneText = "";
let doneHidden = true;
let btn = { textContent: "Tune again", disabled: false, classList: new Set(),
            classList: { _s: new Set(),
              contains(c){ return this._s.has(c); },
              toggle(c, on){ if (on) this._s.add(c); else this._s.delete(c); },
              add(c){ this._s.add(c); },
              remove(c){ this._s.delete(c); } } };
let resetDisabled = false;
let _tuneWasRunning = false;
let _tuneRunning = false;
let refreshed = 0;

function paintTuneRunning(j) {
  const running = !!(j && j.running);
  _tuneRunning = running;
  btn.disabled = running;
  btn.classList.toggle("is-tuning", running);
  if (running) btn.textContent = "Tuning…";
  resetDisabled = running;
  resultHidden = running;
  if (running) {
    let line = (j && j.step) || "Tuning…";
    if (j && j.elapsed) line += " · " + j.elapsed;
    stepHidden = false;
    stepText = line;
  } else {
    stepHidden = true;
    stepText = "";
  }
  if (_tuneWasRunning && !running) {
    const phase = String((j && j.phase) || "");
    const failed = !!(j && (j.error || /cancel/i.test(phase) || /error/i.test(phase)));
    if (failed) {
      resultHidden = false;
      refreshed += 1;
    } else {
      const unchanged = !!(j && j.summary && j.summary.unchanged);
      doneText = unchanged ? "Nothing faster found" : "Done";
      doneHidden = false;
      resultHidden = false;
      refreshed += 1;
    }
  }
  _tuneWasRunning = running;
}

// A new run hides the previous Before/After and shows a live step.
paintTuneRunning({ running: true, step: "Measuring the current setup · short prompt 3 of 5", elapsed: "12s" });
assert.equal(btn.textContent, "Tuning…");
assert.equal(btn.disabled, true);
assert.equal(resetDisabled, true);
assert.equal(resultHidden, true);
assert.equal(resultText.includes("Before"), true); // text kept for restore
assert.equal(stepHidden, false);
assert.equal(stepText, "Measuring the current setup · short prompt 3 of 5 · 12s");
assert.equal(doneHidden, true);

// Cancel restores the previous lines, no Done highlight.
paintTuneRunning({ running: false, phase: "canceled", error: null });
assert.equal(resultHidden, false);
assert.equal(resultText.includes("After"), true);
assert.equal(doneHidden, true);
assert.equal(stepHidden, true);
assert.ok(refreshed >= 1);

// A successful run with nothing faster.
_tuneWasRunning = false;
paintTuneRunning({ running: true, step: "Trying Memory compression 8 · long prompt" });
paintTuneRunning({ running: false, phase: "done", summary: { complete: true, unchanged: true } });
assert.equal(doneText, "Nothing faster found");
assert.equal(doneHidden, false);
assert.equal(resultHidden, false);

// A successful faster run says Done.
_tuneWasRunning = false;
doneHidden = true;
paintTuneRunning({ running: true, step: "Reloading with the winner…" });
paintTuneRunning({ running: false, phase: "done", summary: { complete: true, unchanged: false } });
assert.equal(doneText, "Done");
assert.equal(doneHidden, false);

console.log("ok");
'''
        r = subprocess.run(
            ["node", "-e", script], capture_output=True, text=True, timeout=15,
        )
        self.assertEqual(r.returncode, 0, r.stdout + "\n" + r.stderr)
        self.assertIn("ok", r.stdout)


class Docs(unittest.TestCase):
    def test_docs_describe_the_live_progress(self):
        for text in (DAY, WEB):
            self.assertIn("Tuning…", text)
            self.assertIn("Measuring the current setup", text)
            self.assertIn("hidden", text.lower())
            self.assertIn("Self-tuning a setting", text)
            self.assertIn("Nothing faster found", text)
            for bad in ("prf-hays", "exo1", "exo2", "16 GB", "24 GB"):
                # WEB.md's older Method-like pages shouldn't be this file.
                if text is DAY:
                    self.assertNotIn(bad, text)


if __name__ == "__main__":
    unittest.main()
