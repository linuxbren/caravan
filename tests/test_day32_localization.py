"""Day 32 localization, step 1: all user-facing text in locales/en.json.

English only for now. These tests keep the strings file and the code in
step: every key used exists, no key goes unused, values match placeholders,
the installer copies match, and no new hard-coded text slips into the page,
the CLI or the installers.
"""
from __future__ import annotations

import ast
import importlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import i18n_check as I

ROOT = I.ROOT
sys.path.insert(0, str(ROOT / "tools"))
import caravan_i18n as C  # noqa: E402

KEY = re.compile(r"^(web|install|fmt|(cli|server|agent)\.[a-z0-9_]+)\.[a-z0-9_]+$")
WORDS = re.compile(r"[A-Za-z]{2,}[’']?[a-z]* [A-Za-z]{2,}")

# Strings that look like words but are not shown as text, with the reason.
JS_ALLOWED = {
    "use strict": "JavaScript directive",
    "noopener noreferrer": "link rel attribute",
    "dot err": "CSS class names",
    "tb-status unverified": "CSS class names",
    "garble-note recovered-note": "CSS class names",
    "primary drawer-control": "CSS class names",
    "ghost drawer-control": "CSS class names",
    'disabled aria-disabled="true"': "HTML attributes",
    "#themeSwitch button": "CSS selector",
    "#remoteAccessSwitch button": "CSS selector",
    "#lanAccessSwitch button": "CSS selector",
    "#updateDailySwitch button": "CSS selector",
    "#barColorSwitch button": "CSS selector",
    ".seg button": "CSS selector",
    "(no reply": "recognises replies already saved in chat history (English history keeps working when a language is added)",
    "can't read": "matches a server download message, which stays English in step 1",
    " layers ready": "matches a server status message, which stays English in step 1",
}
# Markup-only templates may hold short non-word text such as units.
MARKUP_TEXT_ALLOWED = {"s"}

# proxy/agent strings in message positions that are not text for people, with the reason.
SERVER_ALLOWED = {
    "Ollama Cloud": "product name in the cloud model list",
    "Ollama Cloud · coding": "product name in the cloud model list",
    "com.caravan.v3.": "launchd label prefix",
    "Qwen": "model family name", "Llama": "model family name", "Gemma": "model family name",
    "Mistral": "model family name", "Phi": "model family name",
    "no ssh target for worker tunnel": "TunnelError detail, written to the log only",
}


def _markup_text(s: str) -> str:
    s = re.sub(r"<[^>]*>|&[a-z#0-9]+;|\{\}", " ", s)
    return re.sub(r"^[^<>]*\"[^<>]*>|<[^<>]*$", " ", s)  # a tag cut by either end of the string


class StringsFile(unittest.TestCase):
    def test_valid_flat_english_file(self):
        data = json.loads(I.EN_PATH.read_text(encoding="utf-8"))
        self.assertGreater(len(data), 1000)
        for k, v in data.items():
            self.assertRegex(k, KEY)
            self.assertIsInstance(v, str, k)
            self.assertTrue(v.strip(), k)

    def test_english_only_for_now(self):
        self.assertEqual(sorted(p.name for p in (ROOT / "locales").glob("*.json")), ["en.json"])
        self.assertEqual(C.available_languages(), ["en"])

    def test_markup_keys_are_named_html(self):
        for k, v in I.en().items():
            if not k.startswith("web."):
                continue
            has_markup = bool(re.search(r"<[a-zA-Z/!]|&[a-z#0-9]+;", v))
            self.assertEqual(has_markup, k.endswith("_html"), f"{k}: {v!r}")


class KeysInUse(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.uses = I.used_keys()
        cls.en = I.en()

    def test_every_key_used_exists_in_english(self):
        missing = sorted(k for k in self.uses if k not in self.en)
        self.assertEqual(missing, [])

    def test_no_unused_keys(self):
        unused = sorted(k for k in self.en if k not in self.uses)
        self.assertEqual(unused, [])

    def test_values_match_placeholders(self):
        for key, uses in self.uses.items():
            if key not in self.en or key.startswith("install."):
                continue
            wanted = I.placeholders(self.en[key])
            for where, has_values, names in uses:
                if has_values is None:  # a key built at run time
                    continue
                if has_values:
                    got = set(names)
                    if key.endswith(("_one", "_other")):  # a plural form may leave out {count}
                        got = (got - {"count"}) | (wanted & {"count"})
                    self.assertEqual(got, wanted, f"{key} in {where}")
                else:
                    self.assertEqual(wanted, set(), f"{key} in {where} needs values {wanted}")

    def test_text_without_values_has_no_escaped_braces(self):
        # {{ }} are only literal braces in strings that take values.
        for key, uses in self.uses.items():
            if key in self.en and not any(u[1] for u in uses) and not key.startswith("install."):
                self.assertNotRegex(self.en[key], r"\{\{|\}\}", key)


class Lookup(unittest.TestCase):
    def test_python_lookup_and_fallbacks(self):
        self.assertEqual(C.t("cli.update.installer_failed"), "Installer failed")
        self.assertEqual(C.T, C.t)
        self.assertEqual(C.t("no.such.key"), "no.such.key")
        self.assertEqual(C.language(), "en")
        with mock.patch.dict(os.environ, {"CARAVAN_LANG": "xx"}):
            self.assertEqual(C.language(), "en")  # no xx.json: stay English

    def test_a_second_language_falls_back_to_english(self):
        with tempfile.TemporaryDirectory() as d:
            loc = Path(d)
            shutil.copy(I.EN_PATH, loc / "en.json")
            (loc / "xx.json").write_text(json.dumps({"web.ok": "Okey"}), encoding="utf-8")
            with mock.patch.object(C, "LOCALES", loc), mock.patch.dict(C._CACHE, clear=True):
                self.assertEqual(C.available_languages(), ["en", "xx"])
                self.assertEqual(C.t_in("xx", "web.ok"), "Okey")
                self.assertEqual(C.t_in("xx", "web.recommended_tag"), "recommended")
                with mock.patch.dict(os.environ, {"CARAVAN_LANG": "xx"}):
                    self.assertEqual(C.language(), "xx")
                    page = C.render_page("<b>{{web.ok}}</b><!--caravan-strings-->")
                    self.assertTrue(page.startswith("<b>Okey</b><script>window.CARAVAN_LANG=\"xx\";"))
                    self.assertIn('"web.recommended_tag":"recommended"', page)

    def test_hooks_for_mac_language_and_settings_exist_but_are_off(self):
        self.assertIsNone(C.mac_language())
        self.assertIsNone(C._saved_language())

    def test_tools_modules_use_the_lookup_not_another_T(self):
        for path in I.CLI_FILES:
            src = path.read_text(encoding="utf-8")
            if "from caravan_i18n import T" not in src:
                continue
            tree = ast.parse(src)
            for node in ast.walk(tree):
                if isinstance(node, (ast.Import, ast.ImportFrom)):
                    for a in node.names:
                        if (a.asname or a.name) == "T" and getattr(node, "module", None) != "caravan_i18n":
                            self.fail(f"{path.name} binds T to {a.name}")
                elif isinstance(node, ast.Assign):
                    for tgt in node.targets:
                        if isinstance(tgt, ast.Name) and tgt.id == "T":
                            self.fail(f"{path.name} assigns T")

    @unittest.skipUnless(shutil.which("node"), "node not installed")
    def test_js_lookup(self):
        code = (
            "const {T} = require(%s);"
            "console.log(JSON.stringify([T('web.ok'), T('web.gap_plus_s', {s: 1.5}), T('web.nope')]));"
        ) % json.dumps(str(I.WEB / "i18n.js"))
        out = subprocess.run(["node", "-e", code], capture_output=True, text=True, timeout=30)
        self.assertEqual(out.returncode, 0, out.stderr)
        self.assertEqual(json.loads(out.stdout), ["OK", "(+1.5 s)", "web.nope"])


class Page(unittest.TestCase):
    def test_render_fills_every_key_and_injects_strings(self):
        for name in ("index.html", "pairing.html"):
            src = (I.WEB / name).read_text(encoding="utf-8")
            out = C.render_page(src)
            self.assertNotRegex(out, r"\{\{web\.", name)
            self.assertIn("window.CARAVAN_STRINGS=", out)
            self.assertLess(out.index("window.CARAVAN_STRINGS="), out.index('<script src="/i18n.js">'))
        self.assertIn("<title>Caravan</title>", C.render_page((I.WEB / "index.html").read_text()))

    def test_strings_blob_cannot_close_the_script(self):
        out = C.render_page("<!--caravan-strings-->")
        blob = out[len("<script>"):-len("</script>")]
        self.assertNotIn("</", blob)

    def test_js_in_the_page_parses_with_english_put_back(self):
        if not shutil.which("node"):
            self.skipTest("node not installed")
        for path in I.WEB_FILES:
            src = I.english_source(path)
            parts = [src] if path.suffix == ".js" else [
                m.group(2) for m in re.finditer(r"<script(\s[^>]*)?>(.*?)</script>", src, re.S)
                if not (m.group(1) and "src=" in m.group(1))]
            with tempfile.NamedTemporaryFile("w", suffix=".js", delete=False) as f:
                f.write("\n;\n".join(parts))
            try:
                out = subprocess.run(["node", "--check", f.name], capture_output=True, text=True, timeout=30)
            finally:
                os.unlink(f.name)
            self.assertEqual(out.returncode, 0, f"{path.name}: {out.stderr[:500]}")


class NoHardCodedText(unittest.TestCase):
    """Lint: words shown to people come from locales/en.json, not the code."""

    def test_page_markup(self):
        for path in (I.WEB / "index.html", I.WEB / "pairing.html"):
            text = path.read_text(encoding="utf-8")
            markup = re.sub(r"<(script|style)\b.*?</\1>", lambda m: "\n" * m.group(0).count("\n"), text, flags=re.S)
            markup = re.sub(r"<!--.*?-->", lambda m: "\n" * m.group(0).count("\n"), markup, flags=re.S)
            bad = []
            for m in re.finditer(r">([^<]+)<", markup):
                rest = re.sub(r"\{\{web\.[a-z0-9_.]+\}\}|&[a-z#0-9]+;", "", m.group(1))
                if re.search(r"[A-Za-z]{2,}", rest):
                    bad.append((markup[:m.start()].count("\n") + 1, m.group(1).strip()[:60]))
            for m in re.finditer(r"\s(title|placeholder|aria-label|alt)=\"([^\"]*)\"", markup):
                if re.search(r"[A-Za-z]{2,}", re.sub(r"\{\{web\.[a-z0-9_.]+\}\}", "", m.group(2))):
                    bad.append((markup[:m.start()].count("\n") + 1, m.group(0).strip()[:60]))
            self.assertEqual(bad, [], path.name)
            self.assertGreater(len(re.findall(r"\{\{web\.", markup)), 5 if path.name == "pairing.html" else 150)

    def test_page_scripts(self):
        bad = []
        for path in I.WEB_FILES:
            whole = path.read_text(encoding="utf-8")
            for off, code in I.script_parts(path):
                for s, _e, _q, text in I.js_strings(code):
                    if re.fullmatch(r"web\.[a-z0-9_.]+", text) or text in JS_ALLOWED:
                        continue
                    line = whole[:off + s].count("\n") + 1
                    if "<" in text:
                        words = [w for w in re.findall(r"[A-Za-z]+", _markup_text(text)) if w not in MARKUP_TEXT_ALLOWED]
                        if words:
                            bad.append(f"{path.name}:{line}: {text[:70]!r}")
                    elif WORDS.search(text):
                        bad.append(f"{path.name}:{line}: {text[:70]!r}")
        self.assertEqual(bad, [])

    def test_cli(self):
        sinks = {"print", "say", "fail", "warn", "info", "add", "exit", "SystemExit", "error", "die", "note", "ok", "write", "emit"}
        bad = []
        for path in I.CLI_FILES:
            tree = ast.parse(path.read_text(encoding="utf-8"))
            for node in ast.walk(tree):
                if not isinstance(node, ast.Call):
                    continue
                f = node.func
                name = f.attr if isinstance(f, ast.Attribute) else getattr(f, "id", "")
                if name == "T":
                    continue
                args = list(node.args) if (name in sinks or re.search(r"(Error|Exception|Exit)$", name or "")) else []
                args += [k.value for k in node.keywords if k.arg in ("help", "description", "epilog", "usage")]
                for a in args:
                    stack = [a]
                    while stack:
                        sub = stack.pop()
                        if isinstance(sub, ast.Call) and getattr(sub.func, "id", "") == "T":
                            continue
                        if isinstance(sub, ast.Constant) and isinstance(sub.value, str) and WORDS.search(sub.value):
                            bad.append(f"{path.name}:{sub.lineno}: {sub.value[:70]!r}")
                        stack.extend(ast.iter_child_nodes(sub))
        self.assertEqual(bad, [])

    def test_server_and_worker_messages(self):
        """proxy/ and agent/ text that reaches the page or the CLI: raised
        errors, progress notes and the error/message/note/... fields of
        replies come from the strings file. Logs, the request journal,
        lab tools, model prompts and config/plist text are left as code."""
        # Two words, or one capitalised word such as "Self-tuning".
        words = re.compile(WORDS.pattern + r"|^[A-Z][a-z]{2,}(-[a-z]+)*$")
        sink_call = re.compile(r"(^|\.)(_note|note|prog|progress|_later|sentence|record_loss|_fail|fail)$")
        sink_keys = {"error", "message", "msg", "note", "notice", "reason", "detail", "warning", "label",
                     "help", "help_gguf", "why"}
        bad = []
        for path in I.SERVER_FILES:
            tree = ast.parse(path.read_text(encoding="utf-8"))
            for node in ast.walk(tree):
                args = []
                if isinstance(node, ast.Call):
                    f = node.func
                    name = f.attr if isinstance(f, ast.Attribute) else getattr(f, "id", "")
                    full = ast.unparse(f)
                    if name == "T" or full.startswith("T."):
                        continue
                    if re.search(r"(Error|Exception)$", name or "") or sink_call.search(full):
                        args = list(node.args) + [k.value for k in node.keywords
                                                  if k.arg in ("message", "msg", "note", "reason", "detail")]
                elif isinstance(node, ast.Dict):
                    args = [v for k, v in zip(node.keys, node.values)
                            if isinstance(k, ast.Constant) and k.value in sink_keys]
                for a in args:
                    stack = [a]
                    while stack:
                        sub = stack.pop()
                        if isinstance(sub, ast.Call) and (getattr(sub.func, "id", "") == "T"
                                                          or ast.unparse(sub.func).startswith("T.")):
                            continue
                        if (isinstance(sub, ast.Constant) and isinstance(sub.value, str)
                                and words.search(sub.value) and sub.value not in SERVER_ALLOWED):
                            bad.append(f"{path.parent.name}/{path.name}:{sub.lineno}: {sub.value[:70]!r}")
                        stack.extend(ast.iter_child_nodes(sub))
        self.assertEqual(bad, [])

    def test_installers(self):
        bad = []
        for path in I.SHELL_FILES:
            text = path.read_text(encoding="utf-8")
            start, end = text.find(C.SHELL_START), text.find(C.SHELL_END)
            self.assertGreater(start, 0, path.name)
            body = text[:start] + text[end:]
            for n, line in enumerate(body.splitlines(), 1):
                if line.lstrip().startswith("#"):
                    continue
                if re.search(r"\b(say|fail|warn|echo)\s+['\"][^'\"$]*[A-Za-z]{2,} [A-Za-z]{2,}", line):
                    bad.append(f"{path.name}:{n}: {line.strip()[:80]}")
        self.assertEqual(bad, [])


class Installers(unittest.TestCase):
    def test_strings_blocks_match_english(self):
        self.assertEqual(C.sync_shell(check=True), [])

    def test_strings_functions_print_english(self):
        if not shutil.which("bash"):
            self.skipTest("bash not installed")
        text = (ROOT / "install").read_text(encoding="utf-8")
        block = text[text.index(C.SHELL_START):text.index(C.SHELL_END)]
        out = subprocess.run(["bash", "-c", block + '\nS_update_macos_to_14_or_newer "13.1"; echo; S_port_must_be_1_65535'],
                             capture_output=True, text=True, timeout=30)
        self.assertEqual(out.stdout, "Update macOS to 14 or newer (found 13.1).\nPort must be 1–65535.")

    def test_installer_help_is_unchanged(self):
        if not shutil.which("bash"):
            self.skipTest("bash not installed")
        out = subprocess.run(["bash", str(ROOT / "scripts/install.sh"), "--help"], capture_output=True, text=True, timeout=30)
        self.assertEqual(out.stdout.splitlines()[0], "Usage: bash scripts/install.sh [--role lead|worker] [--repo PATH] [--ref REF]")
        self.assertEqual(len(out.stdout.splitlines()), 5)

    def test_shell_values_are_safe(self):
        # A value with $, quotes or backslashes prints as given; nothing is re-evaluated.
        text = (ROOT / "scripts/install.sh").read_text(encoding="utf-8")
        block = text[text.index(C.SHELL_START):text.index(C.SHELL_END)]
        out = subprocess.run(["bash", "-c", block + '\nS_macos_14_or_newer_is_required \'$(id) "x" \\n\''],
                             capture_output=True, text=True, timeout=30)
        self.assertEqual(out.stdout, 'macOS 14 or newer is required (found $(id) "x" \\n).')


if __name__ == "__main__":
    unittest.main()
