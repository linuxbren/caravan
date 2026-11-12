"""Day 24 UI: Advanced sections, filters, chat wording, and speed averages."""
import ast
import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock
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
        # Optimize now lives inside Advanced.
        opt_box = HTML.index('id="optBox"')
        adv = HTML.index('id="optAdvanced"')
        adv_end = HTML.index("</details>", opt_box)
        self.assertLess(adv, opt_box)
        self.assertLess(opt_box, adv_end)


class PickerFilters(unittest.TestCase):
    def test_default_and_advanced_chip_sets(self):
        self.assertEqual(P.FILTER_DEFAULT, ("chat", "coding", "thinking", "tools", "vision"))
        self.assertEqual(P.FILTER_ADVANCED, (
            "embedding", "any-to-any", "text-to-image",
            "text-to-video", "text-to-speech", "decision",
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
        self.assertEqual(S.format_line(42, 1.2), "Usually 42 words/s, first word in 1.2 s")
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
            self.assertEqual(second["line"], "Usually 42 words/s, first word in 1.1 s")
            other_opts = S.get("model-a", opts_off, path=path)
            self.assertEqual(other_opts["count"], 0)
            other_model = S.get("model-b", opts_on, path=path)
            self.assertEqual(other_model["count"], 0)
            # Bad or missing numbers do not change the store.
            same = S.record("model-a", opts_on, write_tok_s="nope", path=path)
            self.assertEqual(same["count"], 2)
            empty = S.record("", opts_on, write_tok_s=1, path=path)
            self.assertEqual(empty["count"], 0)

    def test_fingerprint_is_stable(self):
        a = S.fingerprint({"kv_bits": "8", "guess_ahead": "ON", "self_tune": "auto"})
        b = S.fingerprint({"guess_ahead": "on", "kv_bits": 8, "self_tune": "auto"})
        self.assertEqual(a, b)
        self.assertNotEqual(a, S.fingerprint({"guess_ahead": "off", "kv_bits": "8", "self_tune": "auto"}))

    def test_page_and_api_are_wired(self):
        self.assertIn("function recordAvgSpeed", HTML)
        self.assertIn("function refreshAvgSpeed", HTML)
        self.assertIn("/api/speed-average", HTML)
        self.assertIn("/api/speed-average", SERVER)
        self.assertIn("import web_speed", SERVER)
        self.assertIn("def _api_speed_average", SERVER)


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



if __name__ == "__main__":
    unittest.main()
