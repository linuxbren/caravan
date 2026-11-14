"""Day 27: guesses-kept readout, the reply line and the --speedups bench."""
from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "proxy"))
sys.path.insert(0, str(ROOT / "agent"))
sys.path.insert(0, str(ROOT / "tools"))

import guess_stats as GS  # noqa: E402
import gguf_split as G  # noqa: E402
import web_timing as WT  # noqa: E402
import web_speed as S  # noqa: E402
import caravan_prompts as P  # noqa: E402
import caravan_speedups as SU  # noqa: E402

HTML = (ROOT / "proxy/web/index.html").read_text()


class Readout(unittest.TestCase):
    def test_llama_timings(self):
        r = GS.from_llama_timings({"predicted_n": 346, "draft_n": 320,
                                   "draft_n_accepted": 281})
        self.assertEqual(r["guessed"], 320)
        self.assertEqual(r["kept"], 281)
        self.assertEqual(r["kept_pct"], 87.8)
        self.assertEqual(r["reply_pct"], 81.2)
        self.assertEqual(GS.label(r), "guesses kept 88%")

    def test_no_guesses_no_readout(self):
        self.assertIsNone(GS.from_llama_timings({"predicted_n": 21}))
        self.assertIsNone(GS.from_llama_timings(None))
        self.assertIsNone(GS.from_speculate({}))
        self.assertIsNone(GS.readout(0, 0, 10))
        self.assertEqual(GS.label(None), "")

    def test_mlx_without_proposed_uses_reply_share(self):
        r = GS.from_speculate({"from_draft": 30, "accepted_frac": 0.3}, 100)
        self.assertIsNone(r["kept_pct"])
        self.assertEqual(r["reply_pct"], 30.0)
        self.assertEqual(GS.label(r), "30% of words guessed")

    def test_mlx_with_proposed(self):
        r = GS.from_speculate({"from_draft": 30, "proposed": 60, "accepted": 30}, 100)
        self.assertEqual(r["kept_pct"], 50.0)

    def test_never_more_kept_than_guessed(self):
        r = GS.readout(10, 12, 20)
        self.assertEqual(r["kept"], 10)

    def test_combine(self):
        c = GS.combine([GS.readout(10, 5, 20), None, GS.readout(30, 15, 40)])
        self.assertEqual((c["guessed"], c["kept"], c["kept_pct"], c["replies"]),
                         (40, 20, 50.0, 2))
        self.assertIsNone(GS.combine([None, None]))


class ReplyLine(unittest.TestCase):
    def test_usage_from_timings_maps_speculate(self):
        u = G.usage_from_timings({}, {"prompt_n": 10, "prompt_ms": 100,
                                      "predicted_n": 50, "predicted_ms": 1000,
                                      "draft_n": 40, "draft_n_accepted": 30})
        spec = u["caravan"]["speculate"]
        self.assertEqual((spec["proposed"], spec["accepted"]), (40, 30))
        stats = WT.reply_stats(u)
        self.assertEqual(stats["guess_kept"]["kept_pct"], 75.0)

    def test_plain_reply_has_no_readout(self):
        u = G.usage_from_timings({}, {"prompt_n": 10, "prompt_ms": 100,
                                      "predicted_n": 50, "predicted_ms": 1000})
        self.assertNotIn("speculate", u["caravan"])
        self.assertIsNone(WT.reply_stats(u)["guess_kept"])

    def test_python_line_and_js_wording(self):
        line = S.format_reply_stats(20.0, 0.3, guess_kept=GS.readout(10, 9, 20))
        self.assertTrue(line.endswith("guesses kept 90%"), line)
        self.assertEqual(S.format_reply_stats(20.0, 0.3),
                         "Write 20.0 tok/s · first token 0.30s")
        self.assertIn("function guessKeptText", HTML)
        self.assertIn("guesses kept ${", HTML)
        self.assertIn("% of words guessed", HTML)


class EditPrompts(unittest.TestCase):
    def test_five_unique_openings(self):
        e = P.edit_prompts()
        self.assertEqual(len(e), 5)
        self.assertEqual(len({x.split(")")[0] for x in e}), 5)
        self.assertTrue(all("Return the whole file" in x for x in e))


def _fake(responses):
    """A fake urlopen for the Caravan web API."""
    state = {"model": "orig", "pid": 1, "loads": [], "settings": {"kv_bits": "8"}}

    def status_fn(port, urlopen=None):
        s = state["settings"]
        return {"worker": {"status": "ready", "model_id": state["model"],
                           "model_name": state["model"], "lead_pid": state["pid"],
                           "page_settings": dict({"guess_ahead": "auto"}, **s)},
                "lead_healthy": True,
                "active": {"guess_ahead": s.get("guess_ahead") == "on" and state.get("helper"),
                           "prompt_lookup": {"enabled": s.get("prompt_lookup") == "on"}}}

    def urlopen(url, data=None, timeout=30, headers=None):
        body = json.loads(data.decode()) if data else {}
        if url.endswith("/api/models/load"):
            state["model"] = body["id"]
            state["pid"] += 1
            state["settings"] = dict(body.get("settings") or {})
            state["loads"].append((body["id"], dict(body.get("settings") or {})))
            return {"ok": True}
        if url.endswith("/api/chat"):
            mode = state["settings"]
            if mode.get("prompt_lookup") == "on":
                return responses["lookup"]
            return responses["off"]
        raise AssertionError(url)
    return state, status_fn, urlopen


def _resp(write, timings_extra=None):
    t = {"prompt_n": 50, "prompt_ms": 200, "predicted_n": 100,
         "predicted_ms": 100000 / write, "predicted_per_second": write,
         "prompt_per_second": 250}
    t.update(timings_extra or {})
    return {"timings": t, "usage": {"prompt_tokens": 50, "completion_tokens": 100}}


class Speedups(unittest.TestCase):
    def run_fake(self, helper=False):
        state, status_fn, urlopen = _fake({
            "off": _resp(20.0),
            "lookup": _resp(40.0, {"draft_n": 80, "draft_n_accepted": 60}),
        })
        state["helper"] = helper
        res = SU.run_speedups(
            "gguf/q", "mlx/q", port=1, urlopen=urlopen, status_fn=status_fn,
            window_fn=lambda *a: 32768, sides=("gguf",),
            sets_args={"run_short": True, "run_edits": True, "run_long": False},
        )
        return state, res

    def test_modes_restore_and_verdicts(self):
        state, res = self.run_fake()
        rows = res["sides"]["gguf"]["rows"]
        modes = [r["mode"] for r in rows]
        self.assertEqual(modes.count("Off"), 2)
        self.assertIn("Prompt lookup", modes)
        ga = [r for r in rows if r["mode"] == "Guess-ahead"]
        self.assertTrue(ga[0]["skipped"])
        self.assertIn("no helper", ga[0]["reason"])
        v = SU.verdicts(rows)
        self.assertEqual(v["Prompt lookup"]["Short (5)"]["verdict"], "faster")
        self.assertEqual(v["Auto"]["Short (5)"]["verdict"], "same")
        # Non-Auto rows pin Self-tuning off; Auto sends no settings.
        self.assertEqual(state["loads"][0][1]["self_tune"], "off")
        self.assertEqual(state["loads"][3][1], {})
        # Original model is put back with its pinned settings.
        self.assertEqual(state["loads"][-1], ("orig", {"kv_bits": "8"}))
        self.assertIsNone(res["error"])

    def test_table_shows_kept_and_no_invented_numbers(self):
        _, res = self.run_fake()
        text = "\n".join(SU.render(res))
        self.assertIn("75% (300 of 400)", text)
        self.assertIn("+100%", text)
        self.assertIn("skipped — no helper", text)
        self.assertIn("Auto ran with: Prompt lookup off, Guess-ahead off.", text)

    def test_save_keeps_recent_runs(self):
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "s.json"
            for i in range(25):
                SU.save({"sides": {}, "i": i}, path=p, now=i)
            data = json.loads(p.read_text())
            self.assertEqual(len(data["runs"]), 20)
            self.assertEqual(data["runs"][-1]["i"], 24)

    def test_reply_readout_prefers_caravan_stats(self):
        r = SU.reply_readout({"caravan_web": {"stats": {"guess_kept": {"kept": 1}}},
                              "timings": {"draft_n": 9, "draft_n_accepted": 9}})
        self.assertEqual(r, {"kept": 1})
        r = SU.reply_readout({"usage": {"completion_tokens": 10,
                                        "caravan": {"speculate": {"from_draft": 5}}}})
        self.assertEqual(r["reply_pct"], 50.0)


if __name__ == "__main__":
    unittest.main()
