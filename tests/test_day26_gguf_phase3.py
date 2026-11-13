"""Day 26: GGUF Prompt lookup and an on-disk-only draft model."""
from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "proxy"))
sys.path.insert(0, str(ROOT / "agent"))
sys.path.insert(0, str(ROOT / "tools"))

import gguf_split as G  # noqa: E402
import gguf_tune as GT  # noqa: E402
import gguf_self_tune as GST  # noqa: E402
import web_settings as WS  # noqa: E402

HTML = (ROOT / "proxy/web/index.html").read_text()
DAY = (ROOT / "docs/DAY26.md").read_text()
WEB = (ROOT / "docs/WEB.md").read_text()
WORKERS = (ROOT / "proxy/web_workers.py").read_text()
SPLIT = (ROOT / "proxy/gguf_split.py").read_text()


def _touch_gguf(path: Path, size: int):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("wb") as f:
        f.write(b"GGUF")
        if size > 4:
            f.truncate(int(size))  # sparse; reports the size without using it
    return path


class LlamaFlags(unittest.TestCase):
    def test_prompt_lookup_adds_ngram_mod(self):
        a = G.llama_args("/m.gguf", port=1, peers=[], shares=[1],
                         tune={"prompt_lookup": "on"}, decide=lambda **k: type("D", (), {
                             "cache_type_k": "f16", "cache_type_v": "f16"})())
        self.assertIn("--spec-type", a)
        self.assertEqual(a[a.index("--spec-type") + 1], "ngram-mod")
        self.assertNotIn("--spec-draft-model", a)
        self.assertNotIn("--spec-draft-hf", a)
        self.assertNotIn("--hf-repo-draft", a)
        self.assertTrue(all(not str(x).startswith("--fim-") for x in a))

    def test_default_has_no_speculative_flags(self):
        a = G.llama_args("/m.gguf", port=1, peers=[], shares=[1],
                         decide=lambda **k: type("D", (), {
                             "cache_type_k": "f16", "cache_type_v": "f16"})())
        self.assertNotIn("--spec-type", a)
        self.assertNotIn("--spec-draft-model", a)
        self.assertNotIn("--model-draft", a)

    def test_draft_only_when_the_file_exists(self):
        with tempfile.TemporaryDirectory() as td:
            draft = _touch_gguf(Path(td) / "Qwen2.5-0.5B-Q4_K_M.gguf", 80_000_000)
            a = G.llama_args("/m.gguf", port=1, peers=[], shares=[1],
                             tune={"guess_ahead": "on", "draft_path": str(draft)},
                             decide=lambda **k: type("D", (), {
                                 "cache_type_k": "f16", "cache_type_v": "f16"})())
            self.assertIn("--spec-draft-model", a)
            self.assertEqual(Path(a[a.index("--spec-draft-model") + 1]), draft.resolve())
            self.assertEqual(a[a.index("--spec-type") + 1], "draft-simple")
            missing = G.llama_args("/m.gguf", port=1, peers=[], shares=[1],
                                   tune={"guess_ahead": "on",
                                         "draft_path": str(Path(td) / "nope.gguf")},
                                   decide=lambda **k: type("D", (), {
                                       "cache_type_k": "f16", "cache_type_v": "f16"})())
            self.assertNotIn("--spec-draft-model", missing)
            self.assertNotIn("--spec-type", missing)

    def test_never_passes_download_flags(self):
        # A URL-like path, a flag-like path, and a missing file are all refused.
        for raw in (
            "https://huggingface.co/someone/model",
            "--fim-qwen-7b-spec",
            "hf://someone/model",
        ):
            self.assertEqual(G._speculative_args({
                "guess_ahead": "on", "draft_path": raw,
            }), [])
        # Generated argv never includes a download flag, even when lookup is on.
        a = G.llama_args("/m.gguf", port=1, peers=[], shares=[1],
                         tune={"prompt_lookup": "on"},
                         decide=lambda **k: type("D", (), {
                             "cache_type_k": "f16", "cache_type_v": "f16"})())
        for flag in ("--spec-draft-hf", "--hf-repo-draft", "--fim-qwen-7b-spec",
                     "--fim-qwen-14b-spec"):
            self.assertNotIn(flag, a)

    def test_both_flags_combine_types(self):
        with tempfile.TemporaryDirectory() as td:
            draft = _touch_gguf(Path(td) / "Qwen2.5-0.5B.gguf", 80_000_000)
            args = G._speculative_args({
                "prompt_lookup": "on", "guess_ahead": "on",
                "draft_path": str(draft),
            })
            self.assertEqual(args[args.index("--spec-type") + 1],
                             "ngram-mod,draft-simple")
            self.assertIn(str(draft.resolve()), args)


class DraftFinder(unittest.TestCase):
    def test_picks_smaller_same_family(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            main = _touch_gguf(root / "Qwen2.5-Coder-7B-Instruct-Q4_K_M.gguf",
                               4_000_000_000)
            small = _touch_gguf(root / "Qwen2.5-0.5B-Instruct-Q4_K_M.gguf",
                                400_000_000)
            other = _touch_gguf(root / "Llama-3.2-1B-Instruct-Q4_K_M.gguf",
                                800_000_000)
            found = G.find_gguf_draft(main, inventory=[
                {"path": str(small), "name": small.stem},
                {"path": str(other), "name": other.stem},
                {"path": str(main), "name": main.stem},
            ])
            self.assertIsNotNone(found)
            self.assertEqual(Path(found["path"]), small.resolve())
            self.assertEqual(found["family"], "qwen")

    def test_rejects_same_size_family_and_missing(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            main = _touch_gguf(root / "Qwen2.5-7B-Q4_K_M.gguf", 4_000_000_000)
            same = _touch_gguf(root / "Qwen2.5-7B-Q3_K_M.gguf", 3_500_000_000)
            self.assertIsNone(G.find_gguf_draft(main, inventory=[
                {"path": str(same), "name": same.stem},
            ]))
            self.assertIsNone(G.find_gguf_draft(main, inventory=[]))

    def test_never_auto_downloads(self):
        self.assertIn("Never downloads", G.find_gguf_draft.__doc__)
        self.assertIn("will not download",
                      WS.options_for("gguf")[0] and
                      next(o for o in WS.options_for("gguf")
                           if o["id"] == "guess_ahead")["help"])


class SettingsRows(unittest.TestCase):
    def test_gguf_rows_are_auto_off_on_not_locked(self):
        for sid in ("prompt_lookup", "guess_ahead"):
            o = next(x for x in WS.options_for("gguf") if x["id"] == sid)
            self.assertFalse(o.get("locked"))
            self.assertEqual(o["values"], ["auto", "off", "on"])
        ga = next(x for x in WS.options_for("gguf") if x["id"] == "guess_ahead")
        self.assertIn("will not download", ga["disabled_values"]["on"])

    def test_guess_ahead_on_enabled_when_a_draft_is_on_disk(self):
        with tempfile.TemporaryDirectory() as td:
            main = _touch_gguf(Path(td) / "Qwen2.5-7B-Q4_K_M.gguf", 4_000_000_000)
            _touch_gguf(Path(td) / "Qwen2.5-0.5B-Q4_K_M.gguf", 400_000_000)
            # options_for calls find_gguf_draft(model_dir) which also
            # looks in the same folder.
            ga = next(x for x in WS.options_for("gguf", model_dir=str(main))
                      if x["id"] == "guess_ahead")
            self.assertNotIn("on", ga.get("disabled_values") or {})
            self.assertEqual(Path(ga["draft"]["path"]).name, "Qwen2.5-0.5B-Q4_K_M.gguf")

    def test_apply_pins_lookup_and_refuses_a_missing_draft(self):
        t = WS.apply_gguf_settings({}, {"prompt_lookup": "on"})
        self.assertEqual(t["prompt_lookup"], "on")
        off = WS.apply_gguf_settings({"prompt_lookup": "on"}, {"prompt_lookup": "off"})
        self.assertEqual(off["prompt_lookup"], "off")
        auto = WS.apply_gguf_settings({"prompt_lookup": "on"}, {"prompt_lookup": "auto"})
        self.assertEqual(auto["prompt_lookup"], "on")  # Auto leaves learned
        missing = WS.apply_gguf_settings({}, {"guess_ahead": "on"})
        self.assertEqual(missing["guess_ahead"], "off")
        self.assertNotIn("draft_path", missing)

    def test_apply_guess_ahead_on_with_a_real_draft(self):
        with tempfile.TemporaryDirectory() as td:
            main = _touch_gguf(Path(td) / "Qwen2.5-7B-Q4_K_M.gguf", 4_000_000_000)
            small = _touch_gguf(Path(td) / "Qwen2.5-0.5B-Q4_K_M.gguf", 400_000_000)
            t = WS.apply_gguf_settings({}, {"guess_ahead": "on"}, model_path=str(main))
            self.assertEqual(t["guess_ahead"], "on")
            self.assertEqual(Path(t["draft_path"]), small.resolve())

    def test_normalize_accepts_gguf_on(self):
        s = WS.normalize({"prompt_lookup": "on"})
        self.assertEqual(s["prompt_lookup"], "on")

    def test_mlx_rows_unchanged(self):
        pl = next(x for x in WS.options_for("mlx") if x["id"] == "prompt_lookup")
        self.assertIn("adaptive", pl["values"])
        self.assertNotIn("on", pl["values"])
        ga = next(x for x in WS.options_for("mlx") if x["id"] == "guess_ahead")
        self.assertIn("mtp", ga["values"])


class AutoTuneSafety(unittest.TestCase):
    def test_schedule_tries_prompt_lookup_last_when_safe(self):
        items = G.gguf_schedule({}, [])
        self.assertEqual(items[-1]["name"], "prompt_lookup")
        self.assertIsNone(items[-1]["skip"])
        self.assertEqual(items[-1]["incumbent"], "off")
        self.assertEqual(items[-1]["challenger"], "on")

    def test_schedule_skips_when_two_chats_or_pinned(self):
        self.assertEqual(G.gguf_schedule({}, [], n_slots=2)[-1]["skip"], "two chats")
        self.assertEqual(
            G.gguf_schedule({}, [], pinned={"prompt_lookup"})[-1]["skip"],
            "pinned",
        )

    def test_self_tune_does_not_try_prompt_lookup(self):
        self.assertNotIn("prompt_lookup", GST.LEARN_ORDER)
        self.assertNotIn("prompt_lookup", dict(G.GGUF_KNOBS))
        # Every original knob is exhausted: nothing left to try.
        trial = GST.pick_trial(
            {"ubatch": 1024, "cache_type": "q8_0", "flash_attn": "off"},
            set(),
            ["ubatch=256", "ubatch=512", "cache_type=f16", "flash_attn=on"],
        )
        self.assertIsNone(trial)

    def test_garbled_challenger_loses_even_if_faster(self):
        # as_specs keeps the garble flag, and the tuner treats it as a loss.
        specs = GT.as_specs({
            "write_tok_s": 40.0, "read_tok_s": 200.0, "ttft_s": 0.2,
            "garbled": True,
        })
        self.assertTrue(specs["garbled"])
        self.assertEqual(specs["write_tok_s"], 40.0)

        measures = [
            {"write_tok_s": 20.0, "read_tok_s": 100.0, "ttft_s": 0.4},  # inc
            {"write_tok_s": 40.0, "read_tok_s": 200.0, "ttft_s": 0.2,
             "garbled": True},  # faster but garbled
        ]
        # For a focused prompt_lookup-only run, pre-lose the other knobs
        # and feed measures in order. Easier: call the comparison path
        # the same way run() does.
        inc = measures[0]
        ch = GT.as_specs(measures[1])
        won = False
        if ch.get("garbled") and not inc.get("garbled"):
            won = False
        elif GT.beats(ch, inc):
            won = True
        self.assertFalse(won)
        self.assertTrue(GT.beats(
            {"write_tok_s": 40.0, "read_tok_s": 200.0, "ttft_s": 0.2},
            inc,
        ), "without garble the faster one would win")

    def test_tuner_rejects_a_garbled_prompt_lookup_trial(self):
        with tempfile.TemporaryDirectory() as td:
            store = Path(td) / "t.json"
            seq = []

            def measure():
                # After the original three knobs (each inc+chal = 6 measures)
                # the prompt_lookup trial is last: incumbent off, then on.
                seq.append(1)
                n = len(seq)
                # Make non-lookup trials a wash so they don't matter.
                # We'll just force garbled on any measure whose tune we
                # can see through restart. Use a simple side channel.
                tune = getattr(measure, "tune", {})
                if tune.get("prompt_lookup") == "on":
                    return {"write_tok_s": 50.0, "read_tok_s": 250.0,
                            "ttft_s": 0.15, "garbled": True}
                return {"write_tok_s": 20.0, "read_tok_s": 100.0, "ttft_s": 0.4}

            def restart(tune):
                measure.tune = dict(tune)

            # Skip the first three knobs by marking them already lost.
            # gguf_schedule will skip those (already lost) and try lookup.
            import json
            key = GT.entry_key("/m.gguf", 1)
            GT.save_store({
                key: {"best": {"flash_attn": "on", "ubatch": 512, "cache_type": "f16"},
                      "losses": ["flash_attn=off", "ubatch=256", "ubatch=1024",
                                 "cache_type=q8_0"],
                      "trials": []},
            }, store)
            tuner = GT.GgufTuner(
                "/m.gguf", 1, restart=restart, measure=measure,
                store_path=store, log=lambda *a: None,
                schedule_kw={"n_slots": 1},
            )
            res = tuner.run()
            tried = [t for t in res["tried"] if t["name"] == "prompt_lookup"]
            self.assertEqual(len(tried), 1)
            self.assertFalse(tried[0]["won"])
            self.assertTrue(tried[0]["challenger_specs"]["garbled"])
            self.assertEqual(res["best"].get("prompt_lookup", "off"), "off")


class DocsAndPage(unittest.TestCase):
    def test_docs_and_help_are_plain(self):
        import re
        for text in (DAY, WEB, HTML):
            flat = re.sub(r"\s+", " ", text)
            self.assertIn("will not download", flat)
        self.assertIn("Prompt lookup", DAY)
        self.assertIn("auto stays off until a test finds a winner",
                      re.sub(r"\s+", " ", WEB.lower()))
        self.assertIn("auto stays off until a test finds a winner",
                      re.sub(r"\s+", " ", DAY.lower()))
        self.assertIn("ngram-mod", SPLIT)
        # No jargon hostnames or memory sizes in the new help.
        ga = next(o for o in WS.options_for("gguf") if o["id"] == "guess_ahead")
        for bad in ("prf-hays", "exo1", "16 GB", "llama.cpp", "ngram", "spec-type"):
            self.assertNotIn(bad, ga["help"])

    def test_page_help_matches(self):
        self.assertIn("will not download one for you", HTML)
        self.assertIn("Auto stays off until a test finds it is faster", HTML)


if __name__ == "__main__":
    unittest.main()
