"""Day 32: Spanish localization (engine, es.json, picker, formatting)."""
from __future__ import annotations

import json
import os
import re
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
import sys
sys.path.insert(0, str(ROOT / "tools"))
sys.path.insert(0, str(ROOT / "tests"))

import caravan_i18n as C
import i18n_check as I


TAG = re.compile(r"</?[A-Za-z][A-Za-z0-9]*\b[^>]*>|&[a-zA-Z#0-9]+;")


def _es():
    path = ROOT / "locales" / "es.json"
    return json.loads(path.read_text(encoding="utf-8"))


class PluralEngine(unittest.TestCase):
    def test_spanish_one_other(self):
        self.assertEqual(C.plural_form(1, "es"), "one")
        self.assertEqual(C.plural_form(0, "es"), "other")
        self.assertEqual(C.plural_form(2, "es"), "other")
        self.assertEqual(C.plural_form(21, "es"), "other")
        self.assertEqual(C.plural_form(1.5, "es"), "other")

    def test_russian_one_few_many_other(self):
        self.assertEqual(C.plural_form(1, "ru"), "one")
        self.assertEqual(C.plural_form(21, "ru"), "one")
        self.assertEqual(C.plural_form(2, "ru"), "few")
        self.assertEqual(C.plural_form(22, "ru"), "few")
        self.assertEqual(C.plural_form(4, "ru"), "few")
        self.assertEqual(C.plural_form(5, "ru"), "many")
        self.assertEqual(C.plural_form(11, "ru"), "many")
        self.assertEqual(C.plural_form(0, "ru"), "many")
        self.assertEqual(C.plural_form(1.5, "ru"), "other")

    def test_japanese_and_chinese_other_only(self):
        for code in ("ja", "zh-Hans", "zh"):
            self.assertEqual(C.plural_form(1, code), "other")
            self.assertEqual(C.plural_form(8, code), "other")

    def test_fallback_to_other_then_english(self):
        with tempfile.TemporaryDirectory() as d:
            loc = Path(d)
            shutil.copy(I.EN_PATH, loc / "en.json")
            # Russian would want _few; only _other is provided in the language file.
            (loc / "ru.json").write_text(json.dumps({
                "web.n_macs_one": "RU one {count}",
                "web.n_macs_other": "RU other {count}",
            }), encoding="utf-8")
            with mock.patch.object(C, "LOCALES", loc):
                C.clear_language_cache()
                self.assertEqual(C.t_plural_in("ru", "web.n_macs", 1), "RU one 1")
                self.assertEqual(C.t_plural_in("ru", "web.n_macs", 2), "RU other 2")
                # A key missing entirely in ru falls back to English.
                self.assertIn("model", C.t_plural_in("ru", "web.n_models", 3).lower())
            C.clear_language_cache()


class SpanishFile(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.en = I.en()
        cls.es = _es()

    def test_every_english_key_is_present(self):
        missing = sorted(k for k in self.en if k not in self.es)
        self.assertEqual(missing, [])

    def test_no_empty_strings(self):
        empty = sorted(k for k, v in self.es.items() if not isinstance(v, str) or not v.strip())
        self.assertEqual(empty, [])

    def test_placeholders_match_english(self):
        bad = []
        for k, ev in self.en.items():
            if k not in self.es:
                continue
            if I.placeholders(ev) != I.placeholders(self.es[k]):
                bad.append("%s: en=%s es=%s" % (k, I.placeholders(ev), I.placeholders(self.es[k])))
        self.assertEqual(bad, [])

    def test_html_markup_tags_match(self):
        bad = []
        for k, ev in self.en.items():
            if not k.endswith("_html") or k not in self.es:
                continue
            if TAG.findall(ev) != TAG.findall(self.es[k]):
                bad.append("%s: en=%s es=%s" % (k, TAG.findall(ev), TAG.findall(self.es[k])))
        self.assertEqual(bad, [])


class LanguageChoice(unittest.TestCase):
    def setUp(self):
        C.clear_language_cache()

    def tearDown(self):
        C.clear_language_cache()

    def test_order_is_env_then_prefs_then_mac_then_english(self):
        with tempfile.TemporaryDirectory() as d:
            with mock.patch.dict(os.environ, {"CARAVAN_HOME": d, "CARAVAN_LANG": ""}, clear=False):
                os.environ.pop("CARAVAN_LANG", None)
                self.assertEqual(C.language(), "en")
                C.save_language("es")
                C.clear_language_cache()
                self.assertEqual(C._saved_language(), "es")
                self.assertEqual(C.language(), "es")
                with mock.patch.dict(os.environ, {"CARAVAN_LANG": "en"}):
                    self.assertEqual(C.language(), "en")  # env wins
            # mac language is used when env and prefs are empty
        C.clear_language_cache()
        with mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop("CARAVAN_LANG", None)
            with mock.patch.object(C, "_saved_language", return_value=None):
                with mock.patch.object(C, "mac_language", return_value="es"):
                    self.assertEqual(C.language(), "es")

    def test_locale_tags_map_to_available_files(self):
        self.assertEqual(C.normalize_language("es-MX"), "es")
        self.assertEqual(C.normalize_language("es_419.UTF-8"), "es")
        self.assertEqual(C.normalize_language("en-US"), "en")
        self.assertIsNone(C.normalize_language("C"))

    def test_picker_marks_spanish_beta(self):
        langs = {row["code"]: row for row in C.picker_languages("en")}
        self.assertIn("en", langs)
        self.assertFalse(langs["en"]["beta"])
        self.assertIn("es", langs)
        self.assertTrue(langs["es"]["beta"])
        self.assertIn("beta", langs["es"]["label"].lower())
        self.assertIn("Español", langs["es"]["label"])
        self.assertNotIn("beta", langs["en"]["label"].lower())


class Formatting(unittest.TestCase):
    def tearDown(self):
        C.clear_language_cache()

    def test_spanish_decimal_thousands_lists_units_dates(self):
        self.assertEqual(C.fmt_num(1234.5, 1, "es"), "1.234,5")
        self.assertEqual(C.fmt_num(12.3, 1, "es"), "12,3")
        self.assertEqual(C.fmt_unit("gb", 12.3, 1, "es"), C.t_in("es", "fmt.gb", n="12,3"))
        self.assertIn(" y ", C.and_list(["a", "b", "c"], lang="es"))
        self.assertTrue(C.and_list(["a", "b", "c"], lang="es").endswith(" y c") or
                        " y c" in C.and_list(["a", "b", "c"], lang="es"))
        from datetime import datetime
        d = datetime(2026, 11, 13, 18, 0, 0)
        self.assertEqual(C.fmt_date(d, "month_day", lang="en"), "November 13")
        es_day = C.fmt_date(d, "month_day", lang="es")
        self.assertIn("13", es_day)
        self.assertIn("noviembre", es_day.lower())
        es_year = C.fmt_date(d, "month_year", lang="es")
        self.assertIn("2026", es_year)
        self.assertIn("noviembre", es_year.lower())

    def test_english_numbers_stay_ungrouped(self):
        self.assertEqual(C.fmt_num(1234.5, 1, "en"), "1234.5")


class InstallerLanguage(unittest.TestCase):
    def test_shell_block_can_print_spanish(self):
        if not shutil.which("bash"):
            self.skipTest("bash not installed")
        import subprocess
        # Generate a block (does not rewrite the install scripts unless sync_shell runs).
        block = C.shell_block()
        self.assertIn("CARAVAN_UI_LANG", block)
        # A known install key: S_update_macos_to_14_or_newer
        out = subprocess.run(
            ["bash", "-c", "CARAVAN_LANG=en\n" + block + '\nS_update_macos_to_14_or_newer "13.1"; echo'],
            capture_output=True, text=True, timeout=30,
        )
        self.assertIn("Update macOS to 14 or newer", out.stdout)
        out_es = subprocess.run(
            ["bash", "-c", "CARAVAN_LANG=es\n" + block + '\nS_update_macos_to_14_or_newer "13.1"; echo'],
            capture_output=True, text=True, timeout=30,
        )
        self.assertNotEqual(out.stdout, out_es.stdout)
        self.assertIn("13.1", out_es.stdout)
        self.assertNotIn("Update macOS", out_es.stdout)


if __name__ == "__main__":
    unittest.main()
