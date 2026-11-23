"""Day 32: Russian localization (ru.json, picker, formatting, plurals)."""
from __future__ import annotations

import json
import os
import re
import shutil
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
import sys
sys.path.insert(0, str(ROOT / "tools"))
sys.path.insert(0, str(ROOT / "tests"))

import caravan_i18n as C
import i18n_check as I


TAG = re.compile(r"</?[A-Za-z][A-Za-z0-9]*\b[^>]*>|&[a-zA-Z#0-9]+;")

# Count-plural families (English has _one and _other). fmt.ordinal is a
# different CLDR set and is checked separately.
def _cardinal_bases(en: dict[str, str]) -> list[str]:
    bases = []
    for k in en:
        if k.endswith("_one") and (k[:-4] + "_other") in en:
            base = k[:-4]
            if base != "fmt.ordinal":
                bases.append(base)
    return sorted(bases)


def _ru():
    path = ROOT / "locales" / "ru.json"
    return json.loads(path.read_text(encoding="utf-8"))


def _empty(key: str, val) -> bool:
    if not isinstance(val, str):
        return True
    if key == "fmt.thousands":
        return val == ""
    return not val.strip()


class RussianFile(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.en = I.en()
        cls.ru = _ru()

    def test_every_english_key_is_present(self):
        missing = sorted(k for k in self.en if k not in self.ru)
        self.assertEqual(missing, [])

    def test_no_empty_strings(self):
        empty = sorted(k for k, v in self.ru.items() if _empty(k, v))
        self.assertEqual(empty, [])

    def test_placeholders_match_english(self):
        bad = []
        for k, ev in self.en.items():
            if k not in self.ru:
                continue
            if I.placeholders(ev) != I.placeholders(self.ru[k]):
                bad.append("%s: en=%s ru=%s" % (k, I.placeholders(ev), I.placeholders(self.ru[k])))
        self.assertEqual(bad, [])

    def test_html_markup_tags_match(self):
        bad = []
        for k, ev in self.en.items():
            if not k.endswith("_html") or k not in self.ru:
                continue
            if TAG.findall(ev) != TAG.findall(self.ru[k]):
                bad.append("%s: en=%s ru=%s" % (k, TAG.findall(ev), TAG.findall(self.ru[k])))
        self.assertEqual(bad, [])

    def test_count_plurals_have_one_few_many_other(self):
        bases = _cardinal_bases(self.en)
        self.assertTrue(bases)
        missing = []
        for base in bases:
            for form in ("one", "few", "many", "other"):
                key = "%s_%s" % (base, form)
                if key not in self.ru:
                    missing.append(key)
                    continue
                # Extra forms must keep the English placeholders of _one/_other
                # (those two share placeholders in the current English file).
                ev = self.en.get(key) or self.en.get(base + "_other") or self.en.get(base + "_one")
                if ev is not None and I.placeholders(ev) != I.placeholders(self.ru[key]):
                    missing.append("%s placeholders %s vs %s" % (
                        key, I.placeholders(ev), I.placeholders(self.ru[key])))
        self.assertEqual(missing, [])

    def test_plural_forms_in_real_strings(self):
        # 1 модель, 2 модели, 5 моделей, 1,5 модели
        self.assertEqual(C.t_plural_in("ru", "web.n_models", 1), "1 модель")
        self.assertEqual(C.t_plural_in("ru", "web.n_models", 21), "21 модель")
        self.assertEqual(C.t_plural_in("ru", "web.n_models", 2), "2 модели")
        self.assertEqual(C.t_plural_in("ru", "web.n_models", 22), "22 модели")
        self.assertEqual(C.t_plural_in("ru", "web.n_models", 5), "5 моделей")
        self.assertEqual(C.t_plural_in("ru", "web.n_models", 11), "11 моделей")
        self.assertEqual(C.t_plural_in("ru", "web.n_models", 0), "0 моделей")
        # Fractional counts use "other" (same shape as few).
        other = C.t_plural_in("ru", "web.n_models", 1.5)
        self.assertEqual(other, "1,5 модели")
        # Another real family: shards
        self.assertIn("фрагмент", C.t_plural_in("ru", "server.model_inventory.missing_shards", 1))
        self.assertIn("фрагмента", C.t_plural_in("ru", "server.model_inventory.missing_shards", 3))
        self.assertIn("фрагментов", C.t_plural_in("ru", "server.model_inventory.missing_shards", 5))


class LanguageChoice(unittest.TestCase):
    def setUp(self):
        C.clear_language_cache()

    def tearDown(self):
        C.clear_language_cache()

    def test_locale_tags_map_to_russian(self):
        self.assertEqual(C.normalize_language("ru-RU"), "ru")
        self.assertEqual(C.normalize_language("ru_RU.UTF-8"), "ru")
        self.assertEqual(C.normalize_language("ru"), "ru")

    def test_picker_marks_russian_beta(self):
        langs = {row["code"]: row for row in C.picker_languages("en")}
        self.assertIn("en", langs)
        self.assertFalse(langs["en"]["beta"])
        self.assertIn("es", langs)
        self.assertTrue(langs["es"]["beta"])
        self.assertIn("ru", langs)
        self.assertTrue(langs["ru"]["beta"])
        self.assertIn("beta", langs["ru"]["label"].lower())
        self.assertIn("Русский", langs["ru"]["label"])
        self.assertNotIn("beta", langs["en"]["label"].lower())
        # Russian UI also names the language
        ru_picker = {row["code"]: row for row in C.picker_languages("ru")}
        self.assertIn("Русский", ru_picker["ru"]["label"])
        self.assertIn("beta", ru_picker["ru"]["label"].lower())


class Formatting(unittest.TestCase):
    def tearDown(self):
        C.clear_language_cache()

    def test_russian_decimal_thousands_lists_units_dates(self):
        self.assertEqual(C.fmt_num(1234.5, 1, "ru"), "1 234,5")
        self.assertEqual(C.fmt_num(12.3, 1, "ru"), "12,3")
        self.assertEqual(C.fmt_unit("gb", 12.3, 1, "ru"), C.t_in("ru", "fmt.gb", n="12,3"))
        listed = C.and_list(["a", "b", "c"], lang="ru")
        self.assertIn(" и ", listed)
        self.assertTrue(listed.endswith(" и c") or " и c" in listed)
        d = datetime(2026, 11, 13, 18, 0, 0)
        self.assertEqual(C.fmt_date(d, "month_day", lang="en"), "November 13")
        ru_day = C.fmt_date(d, "month_day", lang="ru")
        self.assertEqual(ru_day, "13 ноября")
        ru_year = C.fmt_date(d, "month_year", lang="ru")
        self.assertEqual(ru_year, "ноябрь 2026")
        ru_short = C.fmt_date(d, "short", lang="ru")
        self.assertIn("13", ru_short)
        self.assertIn("нояб", ru_short)
        # Spanish dates still use nominative month names (no genitive keys).
        self.assertIn("noviembre", C.fmt_date(d, "month_day", lang="es").lower())

    def test_english_numbers_stay_ungrouped(self):
        self.assertEqual(C.fmt_num(1234.5, 1, "en"), "1234.5")


class InstallerLanguage(unittest.TestCase):
    def test_shell_block_can_print_russian(self):
        if not shutil.which("bash"):
            self.skipTest("bash not installed")
        import subprocess
        block = C.shell_block()
        self.assertIn("CARAVAN_UI_LANG", block)
        # Have-list is available codes, sorted (ja may also be present).
        self.assertRegex(block, r"en\|es\|(?:ja\|)?ru")
        out_en = subprocess.run(
            ["bash", "-c", "CARAVAN_LANG=en\n" + block + '\nS_update_macos_to_14_or_newer "13.1"; echo'],
            capture_output=True, text=True, timeout=30,
        )
        self.assertIn("Update macOS to 14 or newer", out_en.stdout)
        out_ru = subprocess.run(
            ["bash", "-c", "CARAVAN_LANG=ru\n" + block + '\nS_update_macos_to_14_or_newer "13.1"; echo'],
            capture_output=True, text=True, timeout=30,
        )
        self.assertNotEqual(out_en.stdout, out_ru.stdout)
        self.assertIn("13.1", out_ru.stdout)
        self.assertNotIn("Update macOS", out_ru.stdout)


if __name__ == "__main__":
    unittest.main()
