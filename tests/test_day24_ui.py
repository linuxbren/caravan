"""Day 24 UI: Advanced sections, filters, chat wording, and speed averages."""
import ast
import io
import json
import subprocess
import threading
import tempfile
import unittest
from pathlib import Path
from unittest import mock
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "proxy"))
import web_picker as P
import web_speed as S
import web_nodes as N

HTML = (ROOT / "proxy/web/index.html").read_text()
BALANCE = (ROOT / "proxy/web/balance.js").read_text()
PAIRING = (ROOT / "proxy/web/pairing.html").read_text()
SERVER = (ROOT / "proxy/web_server.py").read_text()


class TaglineAndChrome(unittest.TestCase):
    def test_title_is_just_caravan(self):
        self.assertIn("<title>Caravan</title>", HTML)
        self.assertNotIn("built in the open", HTML.lower())
        self.assertNotIn("Built in the open", HTML)

    def test_tagline_has_no_journey_or_open_message(self):
        self.assertIn("Your Macs. One model.", HTML)
        self.assertNotIn("Your Mac minis", HTML)
        self.assertNotIn("built in the open", PAIRING.lower())
        self.assertNotIn("Built in the open", PAIRING)

    def test_clear_chat_renamed_new_session(self):
        self.assertIn(">New session</button>", HTML)
        self.assertNotIn("Clear chat", HTML)

    def test_specifications_box_removed(self):
        self.assertNotIn("id=\"statGrid\"", HTML)
        self.assertNotIn("Specifications", HTML)
        self.assertNotIn("id=\"featTags\"", HTML)
        self.assertIn('id="avgSpeed"', HTML)
        # Average sits under the input, above Current optimizations.
        avg = HTML.index('id="avgSpeed"')
        opts = HTML.index('Current optimizations')
        inp = HTML.index('id="input"')
        self.assertLess(inp, avg)
        self.assertLess(avg, opts)

    def test_current_optimizations_box_and_hints(self):
        self.assertIn("Current optimizations", HTML)
        self.assertIn("id=\"currentOpts\"", HTML)
        self.assertIn("CHIP_HINTS", HTML)
        self.assertIn("Caravan learns faster settings from your chats.", HTML)
        self.assertIn("A smaller model guesses upcoming words to speed up replies.", HTML)
        # Chips stay read-only labels, ordered with Self-tuning first.
        self.assertIn('order.filter(id => items[id])', HTML)
        self.assertIn('"self_tune","guess_ahead"', HTML)
        self.assertIn("Chips stay read-only labels", HTML)


class SettingsAdvanced(unittest.TestCase):
    def test_self_tuning_stays_visible_others_in_closed_advanced(self):
        self.assertIn('id="optAdvanced"', HTML)
        self.assertIn("<summary>Advanced</summary>", HTML)
        self.assertIn('id="optAdvancedRows"', HTML)
        self.assertIn('state.opts.filter(o => o.id === "self_tune")', HTML)
        self.assertIn('state.opts.filter(o => o.id !== "self_tune")', HTML)
        # Closed by default: the details tag itself has no open attribute.
        start = HTML.index('id="optAdvanced"')
        snippet = HTML[start - 80:start + 80]
        self.assertIn("<details", snippet)
        self.assertNotIn(" open", snippet)
        # Auto-tune sits outside Advanced, after Self-tuning.
        # Apply & restart stays inside Advanced.
        opt_box = HTML.index('id="optBox"')
        adv = HTML.index('id="optAdvanced"')
        adv_end = HTML.index("</details>", adv)
        self.assertLess(opt_box, adv)
        apply = HTML.index('id="btnApply"')
        note = HTML.index('id="optNote"')
        self.assertLess(adv, apply)
        self.assertLess(apply, adv_end)
        self.assertLess(adv, note)
        self.assertLess(note, adv_end)
        rows = HTML.index('id="optRows"')
        heading = HTML.index('id="autoTuneHeading"')
        start_btn = HTML.index('id="btnOptStart"')
        self.assertTrue(rows < opt_box < adv)
        self.assertTrue(rows < heading < start_btn < adv)
        self.assertFalse(rows < apply < adv)
        self.assertIn("Auto = Caravan decides (learned per model)", HTML)
        self.assertIn(">Auto-tune</h3>", HTML)
        self.assertIn(">Start</button>", HTML[start_btn:adv])
        self.assertIn(">Reset tuning</button>", HTML)
        self.assertNotIn(">Optimize now</b>", HTML)
        # Default label is Start (never tuned). JS swaps it to Tune again
        # once a saved result exists; that string lives in the script, not
        # as a second button.
        self.assertIn('has ? "Tune again" : "Start"', HTML)
        self.assertNotIn(">Tune again</button>", HTML)
        # No Tune / Optimize / Auto-tune button inside Advanced.
        self.assertNotIn("Optimize now", HTML[adv:adv_end])
        self.assertNotIn("Tune again", HTML[adv:adv_end])
        self.assertNotIn("btnOptStart", HTML[adv:adv_end])
        self.assertNotIn("Auto-tune", HTML[adv:adv_end])
        self.assertNotIn("Reset tuning", HTML[adv:adv_end])

    def test_self_tuning_applies_immediately_without_reload(self):
        # Clicking On/Off saves and applies live; it does not call Load / Apply.
        self.assertIn("function applySelfTune(", HTML)
        self.assertIn("/api/settings/self-tune", HTML)
        self.assertIn('if (row.dataset.id === "self_tune") applySelfTune(b.dataset.v)', HTML)
        self.assertIn('id="selfTuneNote"', HTML)
        self.assertIn("def set_self_tune", Path(ROOT / "proxy/web_workers.py").read_text())
        self.assertIn("def set_self_tune", Path(ROOT / "agent/mlx_worker.py").read_text())
        workers = Path(ROOT / "proxy/web_workers.py").read_text()
        # Must not fall back to a model reload.
        start = workers.index("def set_self_tune")
        body = workers[start:workers.index("def _page_self_tune")]
        self.assertIn('"reloaded": False', body)
        self.assertNotIn("self.switch", body)
        self.assertNotIn("/api/models/load", body)
        self.assertIn("/caravan/self-tune", body)


class PickerFilters(unittest.TestCase):
    def test_default_and_advanced_chip_sets(self):
        self.assertEqual(P.FILTER_DEFAULT, ("chat", "coding", "thinking", "tools", "vision"))
        self.assertEqual(P.FILTER_ADVANCED, (
            "embedding", "any-to-any", "text-to-image",
            "text-to-video", "text-to-speech", "speech-to-text", "decision",
        ))
        self.assertIn('CATEGORY_DEFAULT = ["chat","coding","thinking","tools","vision"]', HTML)
        self.assertIn('thinking: "Thinking"', HTML)
        self.assertNotIn('reasoning: "Reasoning"', HTML)
        self.assertIn('id="pickerAdvanced"', HTML)
        self.assertIn('id="pickerAdvancedChips"', HTML)
        # Advanced picker details closed by default.
        start = HTML.index('id="pickerAdvanced"')
        self.assertNotIn(" open", HTML[start - 60:start + 40])

    def test_reasoning_renamed_and_aliased(self):
        self.assertEqual(P._FILTER_ALIASES["reasoning"], "thinking")
        self.assertIn("thinking", P._filters_for("", ["reasoning"], "DeepSeek-R1"))
        self.assertNotIn("reasoning", P._filters_for("", ["reasoning"], "DeepSeek-R1"))
        self.assertIn("thinking", P._FILTER_TAGS)
        self.assertNotIn("reasoning", P._FILTER_TAGS)
        self.assertIn("thinking", P._FILTER_SEARCH)

    def test_new_filter_tags(self):
        self.assertIn("tools", P._filters_for("", ["function-calling"], "model-tool-use"))
        self.assertIn("embedding", P._filters_for("feature-extraction", [], "nomic-embed-text"))
        self.assertIn("any-to-any", P._filters_for("any-to-any", [], "qwen-omni"))
        self.assertIn("text-to-image", P._filters_for("text-to-image", [], "flux"))
        self.assertIn("text-to-video", P._filters_for("text-to-video", [], "x"))
        self.assertIn("text-to-speech", P._filters_for("text-to-speech", [], "kokoro-tts"))
        self.assertIn("speech-to-text", P._filters_for("automatic-speech-recognition", [], "whisper-tiny"))
        self.assertIn("decision", P._filters_for("", ["decision"], "nimble"))
        self.assertIn("vision", P._filters_for("image-text-to-text", [], "llama-vl-instruct"))
        self.assertIn("chat", P._filters_for("text-generation", []))

    def test_search_accepts_legacy_reasoning_name(self):
        src = (ROOT / "proxy/web_picker.py").read_text()
        self.assertIn("filt = _FILTER_ALIASES.get(filt, filt)", src)
        self.assertIn('"reasoning": "thinking"', src)


class TopologyCollapse(unittest.TestCase):
    def test_balance_and_thunderbolt_are_closed_details(self):
        for panel in ("balancePanel", "thunderboltPanel"):
            i = HTML.index(f'id="{panel}"')
            snippet = HTML[i - 120:i + 40]
            self.assertIn("<details", snippet, panel)
            self.assertNotIn("<section", snippet, panel)
            self.assertNotIn(" open", snippet, panel)
        self.assertIn("topo-collapse", HTML)
        self.assertIn("<summary class=\"tb-heading\"><h3>Thunderbolt</h3></summary>", HTML)

    def test_balance_status_is_quiet_and_split(self):
        self.assertIn("This split is already applied.", BALANCE)
        self.assertIn("This split is not safe to apply.", BALANCE)
        self.assertIn("Ready to apply a new split.", BALANCE)
        self.assertNotIn("already applied or not safe to apply", BALANCE)
        self.assertIn("function quietStatus", BALANCE)
        self.assertIn('id="balanceIdleStatus"', HTML)
        self.assertIn("class=\"balance-idle\"", HTML)
        # Idle status is plain text, not the bold notice box.
        self.assertIn(".balance-idle", HTML)
        self.assertIn("border: 0", HTML[HTML.index(".balance-idle"):HTML.index(".balance-idle") + 200])


class SpeedAverages(unittest.TestCase):
    def test_format_and_separate_slots(self):
        self.assertEqual(
            S.format_line(
                20.7, 0.34,
                prompt_tokens=165, read_tok_s=200,
                completion_tokens=10, total_s=0.78,
            ),
            "Average · Read 165 tok at 200 tok/s · Write 10 tok at 20.7 tok/s · first token 0.34s · total 0.78s",
        )
        # Rounding matches the page's fmt()/toFixed: read 0 decimals, write 1, times 2.
        self.assertEqual(S.format_reply_stats(20.7, 0.34, prompt_tokens=165, read_tok_s=200, completion_tokens=10, total_s=0.78),
                         "Read 165 tok at 200 tok/s · Write 10 tok at 20.7 tok/s · first token 0.34s · total 0.78s")
        self.assertEqual(S.format_line(42, 1.2), "Average · Write 42.0 tok/s · first token 1.20s")
        self.assertEqual(S.format_line(42, None), "Average · Write 42.0 tok/s")
        self.assertEqual(S.format_line(None, 0.34), "Average · first token 0.34s")
        self.assertEqual(S.format_line(None, None), "")
        self.assertEqual(
            S.format_line(None, None, prompt_tokens=165, read_tok_s=None),
            "Average · Read 165 tok",
        )
        opts_on = {k: "auto" for k in S.OPT_IDS}
        opts_on["guess_ahead"] = "on"
        opts_off = dict(opts_on)
        opts_off["guess_ahead"] = "off"
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "speed.json"
            self.assertIsNone(S.get("model-a", opts_on, path=path)["line"])
            first = S.record("model-a", opts_on, write_tok_s=40, ttft_s=1.2, path=path)
            self.assertEqual(first["count"], 1)
            second = S.record("model-a", opts_on, write_tok_s=44, ttft_s=1.0, path=path)
            self.assertEqual(second["write_tok_s"], 42.0)
            self.assertEqual(second["line"], "Average · Write 42.0 tok/s · first token 1.10s")
            other_opts = S.get("model-a", opts_off, path=path)
            self.assertEqual(other_opts["count"], 0)
            other_model = S.get("model-b", opts_on, path=path)
            self.assertEqual(other_model["count"], 0)
            # Bad or missing numbers do not change the store.
            same = S.record("model-a", opts_on, write_tok_s="nope", path=path)
            self.assertEqual(same["count"], 2)
            empty = S.record("", opts_on, write_tok_s=1, path=path)
            self.assertEqual(empty["count"], 0)
            # Full reply stats are averaged per field; a missing field is left out.
            full = S.record(
                "model-c", opts_on,
                prompt_tokens=160, read_tok_s=190,
                completion_tokens=8, write_tok_s=20.0,
                ttft_s=0.30, total_s=0.70, path=path,
            )
            full = S.record(
                "model-c", opts_on,
                prompt_tokens=170, read_tok_s=210,
                completion_tokens=12, write_tok_s=21.4,
                ttft_s=0.38, total_s=0.86, path=path,
            )
            self.assertEqual(full["prompt_tokens"], 165)
            self.assertEqual(full["completion_tokens"], 10)
            self.assertEqual(full["read_tok_s"], 200.0)
            self.assertEqual(full["write_tok_s"], 20.7)
            self.assertAlmostEqual(full["ttft_s"], 0.34, places=4)
            self.assertAlmostEqual(full["total_s"], 0.78, places=4)
            self.assertEqual(
                full["line"],
                "Average · Read 165 tok at 200 tok/s · Write 10 tok at 20.7 tok/s · first token 0.34s · total 0.78s",
            )
            # An older store entry with only write and first-token still formats cleanly.
            self.assertEqual(
                S.get("model-a", opts_on, path=path)["line"],
                "Average · Write 42.0 tok/s · first token 1.10s",
            )

    def test_fingerprint_is_stable(self):
        a = S.fingerprint({"kv_bits": "8", "guess_ahead": "ON", "self_tune": "auto"})
        b = S.fingerprint({"guess_ahead": "on", "kv_bits": 8, "self_tune": "auto"})
        self.assertEqual(a, b)
        self.assertNotEqual(a, S.fingerprint({"guess_ahead": "off", "kv_bits": "8", "self_tune": "auto"}))

    def test_page_and_api_are_wired(self):
        self.assertIn("function recordAvgSpeed", HTML)
        self.assertIn("function refreshAvgSpeed", HTML)
        self.assertIn("function formatReplyStats", HTML)
        self.assertIn("prompt_tokens: stats.prompt_tokens", HTML)
        self.assertIn("completion_tokens: stats.completion_tokens", HTML)
        self.assertIn("read_tok_s: readTs", HTML)
        self.assertIn("total_s: stats.total_s", HTML)
        self.assertIn("/api/speed-average", HTML)
        self.assertIn("/api/speed-average", SERVER)
        self.assertIn("import web_speed", SERVER)
        self.assertIn("def _api_speed_average", SERVER)
        self.assertIn("prompt_tokens=body.get(\"prompt_tokens\")", SERVER)
        self.assertIn("total_s=body.get(\"total_s\")", SERVER)


class DocsMentionDay24(unittest.TestCase):
    def test_user_docs_cover_filters_and_advanced(self):
        web = (ROOT / "docs/WEB.md").read_text()
        picker = (ROOT / "docs/MODEL_PICKER.md").read_text()
        day = (ROOT / "docs/DAY24.md").read_text()
        self.assertIn("New session", web)
        self.assertIn("Current optimizations", web)
        self.assertIn("Advanced", web)
        self.assertIn("Thinking", picker)
        self.assertIn("Embedding", picker)
        self.assertIn("agent app", picker.lower())
        self.assertNotIn("built in the open", web.lower())
        # Public guides must not name Hermes.
        self.assertNotRegex(picker, r"(?i)\bhermes\b")
        self.assertNotRegex(web, r"(?i)\bhermes\b")
        self.assertIn("Decision", day)
        self.assertIn("speed_averages.json", day)
        self.assertIn("Family", picker)
        self.assertIn("Qwen", picker)
        self.assertIn("maker", picker)
        self.assertIn("own card", picker)
        self.assertIn("friendly Mac name", picker)
        self.assertNotIn("prf-hays", picker)
        self.assertNotIn("prf-hays", web)
        self.assertNotIn("prf-hays", day)
        self.assertIn("Family", day)
        self.assertIn("job id", day)
        self.assertIn("Before ·", day)
        self.assertIn("Before ·", web)
        def flat(s):
            return " ".join(s.split())
        self.assertIn("Average · Read 165 tok at 200 tok/s", flat(web))
        self.assertIn("Average · Read 165 tok at 200 tok/s", flat(day))
        self.assertIn("first token 0.34s", flat(web))
        self.assertIn("first token 0.34s", flat(day))
        self.assertIn("total 0.78s", flat(web))
        self.assertIn("total 0.78s", flat(day))
        self.assertNotIn("Usually 42 words/s", web)
        self.assertNotIn("Usually 42 words/s", day)
        self.assertNotIn("Average 42 words/s", web)
        self.assertNotIn("Average 42 words/s", day)
        self.assertIn("Before · Write 88.4 tok/s", day)
        self.assertIn("Before · Write 88.4 tok/s", web)
        self.assertIn("After · Write 94.5 tok/s", day)
        self.assertIn("After · Write 94.5 tok/s", web)
        web_docs = (ROOT / "docs/WEB.md").read_text()
        # Settings before/after uses the same tok/s wording as the reply stats.
        after_before = web_docs.split("Before", 1)[1][:800] if "Before" in web_docs else ""
        self.assertIn("tok/s", after_before)
        self.assertNotIn("words/s", after_before)
        self.assertIn("first token 0.29s", after_before)



class FitSummary(unittest.TestCase):
    def test_status_uses_selected_fit_and_says_macs(self):
        self.assertIn('function macWord(n)', HTML)
        self.assertIn('n === 1 ? "Mac" : "Macs"', HTML)
        self.assertIn('parts.push("fit on " + ks[0] + " " + macWord(ks[0]))', HTML)
        self.assertIn("function passFit(q)", HTML)
        self.assertIn("filteredQuants(g)", HTML)
        self.assertIn(".filter(passFit)", HTML)
        self.assertNotIn('data.nodes_used || "?"', HTML)
        self.assertNotIn("fit on 2 nodes", HTML)
        # status is refreshed when chips change (renderList -> updatePickerStatus)
        self.assertIn("updatePickerStatus()", HTML)


class FamilyFilters(unittest.TestCase):
    def test_known_set_and_labels(self):
        ids = [f["id"] for f in P.FAMILIES]
        self.assertEqual(ids, ["qwen", "llama", "gemma", "mistral", "deepseek", "gpt-oss", "phi"])
        labels = {f["id"]: f["label"] for f in P.FAMILIES}
        self.assertEqual(labels["gpt-oss"], "gpt-oss")
        self.assertEqual(labels["deepseek"], "DeepSeek")

    def test_aliases_and_phi_boundary(self):
        self.assertEqual(P.family_of("QwQ-32B")["id"], "qwen")
        self.assertEqual(P.family_of("Qwen2.5-7B")["id"], "qwen")
        self.assertEqual(P.family_of("Mixtral-8x7B")["id"], "mistral")
        self.assertEqual(P.family_of("CodeLlama-7b")["id"], "llama")
        self.assertEqual(P.family_of("Phi-3-mini")["id"], "phi")
        self.assertEqual(P.family_of("phi3")["id"], "phi")
        self.assertIsNone(P.family_of("sophia-7b"))
        self.assertIsNone(P.family_of("something-graphic"))

    def test_families_present_only_those_with_matches(self):
        groups = [
            {"family": "qwen", "base": "Qwen2"},
            {"family": "qwen", "base": "QwQ"},
            {"base": "mystery-model", "quants": [{"repo_id": "org/mystery"}]},
        ]
        present = P.families_present(groups)
        self.assertEqual([f["id"] for f in present], ["qwen"])

    def test_page_has_family_dropdown(self):
        self.assertIn('id="pickerFamily"', HTML)
        self.assertIn('id="pickerFamilyRow"', HTML)
        self.assertIn("function rebuildFamily()", HTML)
        self.assertIn("function passFamily(g)", HTML)
        self.assertIn("passFamily(g)", HTML)
        self.assertIn("state.families", HTML)
        self.assertIn("data.families", HTML)
        # own row, same kind of styling as the size filter, not mixed into chips
        self.assertIn("picker-family-row", HTML)
        self.assertIn("Any family", HTML)


class RowTooltip(unittest.TestCase):
    def test_full_tooltip_is_plain_and_two_lines(self):
        g = {
            "base": "Qwen2-VL",
            "family_label": "Qwen",
            "quants": [{
                "repo_id": "Qwen/Qwen2-VL-7B",
                "author": "Qwen",
                "created_at": "2025-10-12T00:00:00Z",
                "tags": ["128k", "image-text-to-text", "tool-use"],
            }],
        }
        tip = P.row_tooltip(g)
        self.assertIn("Qwen", tip)
        self.assertIn("October 2025", tip)
        self.assertIn("Handles long chats", tip)
        self.assertIn("128k", tip)
        self.assertIn("Can use tools", tip)
        self.assertIn("reads images", tip)
        self.assertNotIn("?", tip)
        self.assertNotRegex(tip, r"(?i)speed|token/s|tok/s|words/s")
        self.assertLessEqual(tip.count("\n"), 1)

    def test_omits_unknown_fields(self):
        self.assertEqual(P.row_tooltip({"base": "mystery", "quants": [{"repo_id": "mystery"}]}), "")
        # maker only
        tip = P.row_tooltip({"base": "x", "quants": [{"repo_id": "Acme/model", "author": "Acme"}]})
        self.assertEqual(tip, "Acme")
        self.assertNotIn("?", tip)
        self.assertNotIn("None", tip)

    def test_context_rounding(self):
        self.assertIn("128k", P.context_phrase("128k"))
        self.assertIn("32k", P.context_phrase(config={"max_position_embeddings": 32768}))
        self.assertNotIn("125k", P.context_phrase("128k"))

    def test_page_uses_server_tooltip(self):
        self.assertIn("if (g.tooltip) head.title = g.tooltip;", HTML)
        self.assertNotIn("head.title = fit.reason || g.base", HTML)


class MultiJobCards(unittest.TestCase):
    def test_stacked_cards_keyed_by_job_id(self):
        self.assertIn("function showJobs()", HTML)
        self.assertIn("function upsertJob(j)", HTML)
        self.assertIn("function renderJobCard(card, j)", HTML)
        self.assertIn("state.jobs", HTML)
        self.assertIn("dataset.jobId", HTML)
        self.assertIn("data-job-id", HTML)
        self.assertIn('data-act="cancel"', HTML)
        self.assertIn('data-act="resume"', HTML)
        self.assertIn('data-act="load"', HTML)
        self.assertIn(">Stop<", HTML)
        self.assertIn(">Resume<", HTML)
        # no single-job slot that polls would overwrite
        self.assertNotIn("state.job =", HTML)
        self.assertNotIn("function showJob()", HTML)
        self.assertNotIn('id="btnCancelJob"', HTML)

    def test_adopt_attaches_every_running_job(self):
        start = HTML.index("async function adoptLiveFetches()")
        end = HTML.index("function closePicker()")
        body = HTML[start:end]
        self.assertIn("for (const run of running)", body)
        self.assertNotIn("[0]", body)
        self.assertIn("upsertJob(run)", body)
        self.assertIn("pollJob(run.id", body)

    def test_poll_does_not_start_twice_and_skips_dismissed(self):
        start = HTML.index("async function pollJob(id, q)")
        body = HTML[start:start+2500]
        self.assertIn("state.polling.has(id)", body)
        self.assertIn("if (!state.jobs[id]) return", body)

    def test_friendly_mac_names_are_consistent(self):
        inv = [
            {"id": "local", "label": "My Mac", "role": "lead", "host": "local"},
            {"id": "prf-hays-exo02", "label": "prf-hays-exo02", "role": "packer",
             "host": "prf-hays-exo02"},
        ]
        # The live-test case: MLX snap used the hostname, GGUF used "My Mac".
        mlx_lead = N.friendly_mac_label(
            label="prf-hays-exo01", role="lead", node_id="local", inventory=inv)
        gguf_lead = N.friendly_mac_label(
            label="My Mac", role="lead", node_id="local", inventory=inv)
        self.assertEqual(mlx_lead, gguf_lead)
        self.assertEqual(mlx_lead, "My Mac")
        self.assertEqual(
            N.friendly_mac_label(label="prf-hays-exo02", role="packer",
                                 node_id="prf-hays-exo02", inventory=inv),
            "2nd Mac")
        self.assertTrue(N.looks_like_hostname("prf-hays-exo02"))
        self.assertTrue(N.looks_like_hostname("exo2"))
        self.assertFalse(N.looks_like_hostname("My Mac"))
        self.assertFalse(N.looks_like_hostname("1st Mac"))
        job = N.friendly_job({
            "id": "j1",
            "repo_id": "mlx-community/MiniCPM5-2B-chat-mlx-4bit",
            "runners": [{"id": "prf-hays-exo02", "label": "prf-hays-exo02", "role": "packer"}],
            "progress": {"prf-hays-exo02": {"label": "prf-hays-exo02", "role": "packer", "pct": 10}},
        }, inventory=inv)
        self.assertEqual(job["runners"][0]["label"], "2nd Mac")
        self.assertEqual(job["progress"]["prf-hays-exo02"]["label"], "2nd Mac")
        self.assertIn("function friendlyMacName", HTML)
        self.assertIn("function looksLikeHostname", HTML)
        self.assertIn("_friendly_job", SERVER)
        self.assertNotIn('"label": "EXO1"', Path(ROOT / "proxy/web_picker.py").read_text())
        self.assertNotIn('"label": "EXO2"', Path(ROOT / "proxy/web_picker.py").read_text())



class TuneBeforeAfter(unittest.TestCase):
    def test_format_matches_plain_words(self):
        lines = S.format_tuning_lines(
            {"write_tok_s": 88.4, "ttft_s": 0.29},
            {"write_tok_s": 94.5, "ttft_s": 0.15},
        )
        self.assertEqual(lines, [
            "Before · Write 88.4 tok/s · first token 0.29s",
            "After · Write 94.5 tok/s · first token 0.15s",
        ])
        self.assertEqual(
            S.format_tuning_line(
                {"write_tok_s": 88.4, "ttft_s": 0.29},
                {"write_tok_s": 94.5, "ttft_s": 0.15},
            ),
            "\n".join(lines),
        )
        # Extra fields use the same wording as the reply stats and chat average.
        extra = S.format_tuning_side("Before", {
            "write_tok_s": 20.7, "ttft_s": 0.34,
            "prompt_tokens": 165, "read_tok_s": 200,
            "completion_tokens": 10, "total_s": 0.78,
        })
        self.assertEqual(
            extra,
            "Before · Read 165 tok at 200 tok/s · Write 10 tok at 20.7 tok/s · "
            "first token 0.34s · total 0.78s",
        )
        self.assertNotIn("words/s", "\n".join(lines))

    def test_omits_unknown_and_hides_when_empty(self):
        self.assertEqual(
            S.format_tuning_line({"write_tok_s": 31}, {"write_tok_s": 42}),
            "Before · Write 31.0 tok/s\nAfter · Write 42.0 tok/s",
        )
        self.assertEqual(S.format_tuning_line({}, {}), "")
        same = {"write_tok_s": 92.457, "ttft_s": 0.2863,
                "completion_tokens": 67, "total_s": 0.9416}
        self.assertEqual(
            S.format_tuning_lines(same, same),
            [S.NOTHING_FASTER],
        )
        self.assertEqual(
            S.format_tuning_line(same, same),
            S.NOTHING_FASTER,
        )
        self.assertIn("Nothing faster found", S.NOTHING_FASTER)

        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "speed.json"
            empty = S.get_tuning("model-a", path=path)
            self.assertIsNone(empty["line"])
            self.assertIsNone(empty["before"])
            # One-sided results are not shown.
            none = S.record_tuning("model-a", before={"write_tok_s": 31}, after={}, path=path)
            self.assertIsNone(none["line"])

    def test_persists_per_model(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "speed.json"
            a = S.record_tuning(
                "model-a",
                before={"write_tok_s": 31, "ttft_s": 2.1},
                after={"write_tok_s": 42, "ttft_s": 1.2},
                path=path,
            )
            self.assertEqual(a["lines"], [
                "Before · Write 31.0 tok/s · first token 2.10s",
                "After · Write 42.0 tok/s · first token 1.20s",
            ])
            self.assertIn("Before · Write 31.0 tok/s", a["line"])
            self.assertIsNone(S.get_tuning("model-b", path=path)["line"])
            # Last finished run for this model replaces the previous one.
            b = S.record_tuning(
                "model-a",
                before={"write_tok_s": 20, "ttft_s": 3},
                after={"write_tok_s": 25, "ttft_s": 2},
                source="self_tune",
                path=path,
            )
            self.assertIn("Before · Write 20.0 tok/s", b["line"])
            self.assertEqual(b["source"], "self_tune")
            # Chat averages in the same file stay independent.
            opts = {k: "auto" for k in S.OPT_IDS}
            S.record("model-a", opts, write_tok_s=40, ttft_s=1.0, path=path)
            self.assertIsNotNone(S.get("model-a", opts, path=path)["line"])
            self.assertIn("Before · Write 20.0 tok/s", S.get_tuning("model-a", path=path)["line"])

    def test_self_tune_observe_freezes_after_winners(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "speed.json"
            # Baseline chats, no winners yet.
            S.observe_tuning("m", write_tok_s=30, ttft_s=2.2, has_winners=False, path=path)
            S.observe_tuning("m", write_tok_s=32, ttft_s=2.0, has_winners=False, path=path)
            self.assertIsNone(S.get_tuning("m", path=path)["line"])
            # Trial in progress: do not close the run.
            S.observe_tuning("m", write_tok_s=50, ttft_s=0.5, has_winners=True, settling=True, path=path)
            self.assertIsNone(S.get_tuning("m", path=path)["line"])
            # Winners chosen, trial over: first after-reply closes it.
            got = S.observe_tuning("m", write_tok_s=42, ttft_s=1.2, has_winners=True, path=path)
            self.assertEqual(
                got["line"],
                "Before · Write 31.0 tok/s · first token 2.10s\n"
                "After · Write 42.0 tok/s · first token 1.20s",
            )
            self.assertEqual(got["source"], "self_tune")
            # Further replies do not move a frozen result.
            S.observe_tuning("m", write_tok_s=99, ttft_s=0.1, has_winners=True, path=path)
            self.assertEqual(S.get_tuning("m", path=path)["after"]["write_tok_s"], 42)

    def test_settings_shows_line_outside_advanced(self):
        # In Auto-tune (above Advanced): one reserved two-line slot,
        # filled by Auto-tune or Self-tuning results. Not under Self-tuning.
        self.assertIn('id="tuneResult"', HTML)
        self.assertIn('data-tune-slot="auto_tune"', HTML)
        self.assertNotIn('data-tune-slot="self_tune"', HTML)
        self.assertNotIn('id="tuneResultOpt"', HTML)
        self.assertIn("function refreshTuneResult", HTML)
        self.assertIn("function paintTuneResult", HTML)
        self.assertIn("j.tuning", HTML)
        self.assertIn("format_tuning_lines", Path(ROOT / "proxy/web_speed.py").read_text())
        self.assertIn(".tune-slot", HTML)
        self.assertIn("min-height: 2.25rem", HTML)
        adv_pos = HTML.find('id="optAdvanced"')
        heading = HTML.find('id="autoTuneHeading"')
        slot = HTML.find('data-tune-slot="auto_tune"')
        self.assertTrue(0 < heading < slot < adv_pos)
        opt_pos = HTML.find('id="btnOptStart"')
        self.assertTrue(0 < opt_pos < adv_pos)
        self.assertIn('JSON.stringify({ fresh: true })', HTML)
        # Both Auto-tune and Self-tuning results paint this one slot.
        self.assertIn("paintTuneResult(el, tuneResultText(tun))", HTML)
        # The element is not hidden in the static HTML. While a new Auto-tune
        # run is in progress the lines are hidden in JS; reserved height
        # lives on .tune-slot so the layout does not jump.
        self.assertNotIn('tune-result" id="tuneResult" hidden', HTML)
        self.assertIn(".tune-result[hidden]", HTML)
        self.assertIn("result.hidden = running", HTML)
        self.assertIn("min-height: 2.25rem", HTML)
        self.assertIn("get_tuning", SERVER)
        self.assertIn("observe_tuning", SERVER)
        # paintTuneResult skips a write when the text is unchanged.
        self.assertIn("if (el.textContent !== next)", HTML)


class HelperFlicker(unittest.TestCase):
    """Settings 'Helper download…' must not flash on repeated identical polls."""

    def _node(self, name):
        script = ROOT / "tests/js/helper_flicker_harness.js"
        p = subprocess.run(
            ["node", str(script), name],
            cwd=ROOT, capture_output=True, text=True, timeout=15,
        )
        self.assertEqual(p.returncode, 0, p.stdout + "\n" + p.stderr)
        self.assertIn("ok " + name, p.stdout)

    def test_repeated_identical_polls_do_not_toggle(self):
        self._node("identical_polls_do_not_toggle")

    def test_restore_after_wipe_then_stable(self):
        self._node("restore_after_wipe_then_stable")

    def test_render_skip_and_polls_together(self):
        self._node("render_skip_and_polls_together")

    def test_page_skips_unchanged_settings_and_reserves_slot(self):
        self.assertIn("function optsRenderSignature()", HTML)
        self.assertIn("state.optsRenderSignature", HTML)
        self.assertIn("if (sig === state.optsRenderSignature", HTML)
        # Reserved slot lives on the Guess-ahead row, which is inside Advanced.
        self.assertIn('o.id === "guess_ahead" && !gguf ? `<div class="helper-slot" data-helper-slot>', HTML)
        self.assertIn('Helper download…', HTML)
        self.assertIn(".helper-slot", HTML)
        self.assertIn("min-height: 2.25rem", HTML)
        helpers = (ROOT / "proxy/web/helpers.js").read_text()
        self.assertIn("function applyHelperPoll(", helpers)
        self.assertIn("function paintHelperButton()", helpers)
        # The old append-if-missing path is gone; identical polls must not write.
        self.assertNotIn("if (row && !row.querySelector('[data-helper]'))", helpers)
        self.assertIn("if (!button)", helpers)
        self.assertIn("paintHelperButton()", HTML)


class SelfTuneImmediate(unittest.TestCase):
    """Self-tuning On/Off saves and applies live; it never reloads the model."""

    def test_worker_toggles_learning_without_reload(self):
        sys.path.insert(0, str(ROOT / "agent"))
        import mlx_worker as W
        class E:
            def __init__(self):
                self._learn_enabled = False
                self._learn_entry = None
                self.opens = 0
            def _learn_apply_startup(self):
                self.opens += 1
                self._learn_entry = {"winner": {}}
        E.set_self_tune = W.Engine.set_self_tune
        e = E()
        out = e.set_self_tune(True)
        self.assertTrue(out["self_tune"])
        self.assertTrue(e._learn_enabled)
        self.assertEqual(e.opens, 1)
        # Already has an entry: do not reopen the store.
        out = e.set_self_tune(True)
        self.assertEqual(e.opens, 1)
        out = e.set_self_tune(False)
        self.assertFalse(out["self_tune"])
        self.assertFalse(e._learn_enabled)
        self.assertEqual(e.opens, 1)  # off does not touch startup

    def test_manager_idle_saves_without_reload(self):
        import web_workers as WW
        state = tempfile.TemporaryDirectory()
        self.addCleanup(state.cleanup)
        mgr = WW.WorkerManager(lead_port=8194, packer_peer="127.0.0.1:5560",
                               packer_ssh="nobody@127.0.0.1",
                               state_dir=Path(state.name), repo=ROOT)
        out = mgr.set_self_tune("off")
        self.assertEqual(out["self_tune"], "off")
        self.assertFalse(out["reloaded"])
        self.assertFalse(out["applied"])
        self.assertEqual(mgr.snapshot()["page_settings"]["self_tune"], "off")
        self.assertEqual(mgr.snapshot()["settings"]["self_tune"], "off")
        self.assertIn("takes effect when you load a model", out["notice"])
        out = mgr.set_self_tune("auto")
        self.assertEqual(out["self_tune"], "auto")
        self.assertFalse(out["reloaded"])
        self.assertIn("takes effect when you load a model", out["notice"])

    def test_manager_ready_mlx_applies_live_no_reload(self):
        import web_workers as WW
        hits = []
        class H(BaseHTTPRequestHandler):
            def do_POST(self):
                n = int(self.headers.get("Content-Length") or 0)
                body = self.rfile.read(n)
                hits.append((self.path, body))
                data = b'{"self_tune": true}'
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)
            def log_message(self, *a):
                pass
        httpd = ThreadingHTTPServer(("127.0.0.1", 0), H)
        port = httpd.server_address[1]
        th = threading.Thread(target=httpd.serve_forever, daemon=True)
        th.start()
        self.addCleanup(lambda: (httpd.shutdown(), httpd.server_close()))
        state = tempfile.TemporaryDirectory()
        self.addCleanup(state.cleanup)
        mgr = WW.WorkerManager(lead_port=port, packer_peer="127.0.0.1:5560",
                               packer_ssh="nobody@127.0.0.1",
                               state_dir=Path(state.name), repo=ROOT)
        mgr._set(status="ready", backend=None)
        out = mgr.set_self_tune("auto")
        self.assertFalse(out["reloaded"])
        self.assertTrue(out["applied"])
        self.assertEqual(out["self_tune"], "auto")
        self.assertIn("learn from your next chats", out["notice"])
        self.assertEqual(len(hits), 1)
        self.assertEqual(hits[0][0], "/caravan/self-tune")
        self.assertIn(b"true", hits[0][1])
        # GGUF: preference is saved; no live worker call, no reload.
        hits.clear()
        mgr._set(status="ready", backend="llama")
        out = mgr.set_self_tune("off")
        self.assertFalse(out["reloaded"])
        self.assertFalse(out["applied"])
        self.assertEqual(hits, [])
        self.assertIn("keep the current settings", out["notice"])
        self.assertNotIn("MLX only", out["notice"])
        out = mgr.set_self_tune("auto")
        self.assertFalse(out["reloaded"])
        self.assertIn("reloads", out["notice"])
        self.assertEqual(hits, [])



if __name__ == "__main__":
    unittest.main()
