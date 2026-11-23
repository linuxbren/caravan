"""Day 32: Japanese localization (ja.json, picker, formatting, _other plurals)."""
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
# different CLDR set and is checked separately. Japanese keeps _other only.
def _cardinal_bases(en: dict[str, str]) -> list[str]:
    bases = []
    for k in en:
        if k.endswith("_one") and (k[:-4] + "_other") in en:
            base = k[:-4]
            if base != "fmt.ordinal":
                bases.append(base)
    return sorted(bases)


def _non_other_plural_keys(en: dict[str, str]) -> set[str]:
    skip = set()
    for k in en:
        if k.endswith("_one") and (k[:-4] + "_other") in en:
            base = k[:-4]
            for form in ("one", "two", "few", "many"):
                key = "%s_%s" % (base, form)
                if key in en:
                    skip.add(key)
    return skip


def _ja():
    path = ROOT / "locales" / "ja.json"
    return json.loads(path.read_text(encoding="utf-8"))


def _empty(key: str, val) -> bool:
    if not isinstance(val, str):
        return True
    if key == "fmt.thousands":
        return val == ""
    return not val.strip()


class JapaneseFile(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.en = I.en()
        cls.ja = _ja()
        cls.skip = _non_other_plural_keys(cls.en)

    def test_every_english_key_is_present_except_non_other_plurals(self):
        missing = sorted(k for k in self.en if k not in self.skip and k not in self.ja)
        self.assertEqual(missing, [])

    def test_plural_keys_are_other_only(self):
        unexpected = sorted(k for k in self.ja if k in self.skip)
        self.assertEqual(unexpected, [])
        bases = _cardinal_bases(self.en)
        self.assertTrue(bases)
        missing = []
        for base in bases:
            key = base + "_other"
            if key not in self.ja:
                missing.append(key)
                continue
            ev = self.en[key]
            if I.placeholders(ev) != I.placeholders(self.ja[key]):
                missing.append("%s placeholders %s vs %s" % (
                    key, I.placeholders(ev), I.placeholders(self.ja[key])))
        self.assertEqual(missing, [])
        # Ordinal is other-only too.
        self.assertIn("fmt.ordinal_other", self.ja)
        self.assertNotIn("fmt.ordinal_one", self.ja)
        self.assertNotIn("fmt.ordinal_two", self.ja)
        self.assertNotIn("fmt.ordinal_few", self.ja)

    def test_no_empty_strings(self):
        empty = sorted(k for k, v in self.ja.items() if _empty(k, v))
        self.assertEqual(empty, [])

    def test_placeholders_match_english(self):
        # Japanese date templates may also include {year} so dates can read
        # 2026年11月13日; every English placeholder must still be present.
        date_keys = {"fmt.date_month_day", "fmt.date_month_year", "fmt.date_short"}
        bad = []
        for k, ev in self.en.items():
            if k not in self.ja:
                continue
            en_ph, ja_ph = I.placeholders(ev), I.placeholders(self.ja[k])
            if k in date_keys:
                if not en_ph.issubset(ja_ph):
                    bad.append("%s: en=%s ja=%s" % (k, en_ph, ja_ph))
            elif en_ph != ja_ph:
                bad.append("%s: en=%s ja=%s" % (k, en_ph, ja_ph))
        self.assertEqual(bad, [])

    def test_html_markup_tags_match(self):
        bad = []
        for k, ev in self.en.items():
            if not k.endswith("_html") or k not in self.ja:
                continue
            if TAG.findall(ev) != TAG.findall(self.ja[k]):
                bad.append("%s: en=%s ja=%s" % (k, TAG.findall(ev), TAG.findall(self.ja[k])))
        self.assertEqual(bad, [])

    def test_plural_forms_in_real_strings(self):
        # Japanese uses a single other form for every count.
        one = C.t_plural_in("ja", "web.n_models", 1)
        two = C.t_plural_in("ja", "web.n_models", 2)
        five = C.t_plural_in("ja", "web.n_models", 5)
        frac = C.t_plural_in("ja", "web.n_models", 1.5)
        self.assertEqual(one, "1件のモデル")
        self.assertEqual(two, "2件のモデル")
        self.assertEqual(five, "5件のモデル")
        self.assertEqual(frac, "1.5件のモデル")
        shard = C.t_plural_in("ja", "server.model_inventory.missing_shards", 1)
        shard3 = C.t_plural_in("ja", "server.model_inventory.missing_shards", 3)
        self.assertIn("シャード", shard)
        self.assertIn("シャード", shard3)
        self.assertEqual(shard, shard3.replace("3", "1"))


class LanguageChoice(unittest.TestCase):
    def setUp(self):
        C.clear_language_cache()

    def tearDown(self):
        C.clear_language_cache()

    def test_locale_tags_map_to_japanese(self):
        self.assertEqual(C.normalize_language("ja-JP"), "ja")
        self.assertEqual(C.normalize_language("ja_JP.UTF-8"), "ja")
        self.assertEqual(C.normalize_language("ja"), "ja")

    def test_picker_marks_japanese_beta(self):
        langs = {row["code"]: row for row in C.picker_languages("en")}
        self.assertIn("en", langs)
        self.assertFalse(langs["en"]["beta"])
        self.assertIn("es", langs)
        self.assertTrue(langs["es"]["beta"])
        self.assertIn("ru", langs)
        self.assertTrue(langs["ru"]["beta"])
        self.assertIn("ja", langs)
        self.assertTrue(langs["ja"]["beta"])
        self.assertIn("beta", langs["ja"]["label"].lower())
        self.assertIn("日本語", langs["ja"]["label"])
        self.assertNotIn("beta", langs["en"]["label"].lower())
        ja_picker = {row["code"]: row for row in C.picker_languages("ja")}
        self.assertIn("日本語", ja_picker["ja"]["label"])
        self.assertIn("beta", ja_picker["ja"]["label"].lower())


class Formatting(unittest.TestCase):
    def tearDown(self):
        C.clear_language_cache()

    def test_japanese_numbers_lists_dates(self):
        self.assertEqual(C.fmt_num(1234.5, 1, "ja"), "1,234.5")
        self.assertEqual(C.fmt_num(12.3, 1, "ja"), "12.3")
        self.assertEqual(C.fmt_unit("gb", 12.3, 1, "ja"), C.t_in("ja", "fmt.gb", n="12.3"))
        listed = C.and_list(["a", "b", "c"], lang="ja")
        self.assertEqual(listed, "a、bとc")
        d = datetime(2026, 11, 13, 18, 0, 0)
        self.assertEqual(C.fmt_date(d, "month_day", lang="en"), "November 13")
        self.assertEqual(C.fmt_date(d, "month_day", lang="ja"), "2026年11月13日")
        self.assertEqual(C.fmt_date(d, "month_year", lang="ja"), "2026年11月")
        ja_short = C.fmt_date(d, "short", lang="ja")
        self.assertIn("2026年11月13日", ja_short)
        # Other languages stay as they were.
        self.assertEqual(C.fmt_date(d, "month_day", lang="ru"), "13 ноября")
        self.assertIn("noviembre", C.fmt_date(d, "month_day", lang="es").lower())

    def test_english_numbers_stay_ungrouped(self):
        self.assertEqual(C.fmt_num(1234.5, 1, "en"), "1234.5")


class InstallerLanguage(unittest.TestCase):
    def test_shell_block_can_print_japanese(self):
        if not shutil.which("bash"):
            self.skipTest("bash not installed")
        import subprocess
        block = C.shell_block()
        self.assertIn("CARAVAN_UI_LANG", block)
        self.assertIn("ja", block)
        self.assertRegex(block, r"en\|es\|ja\|ru(?:\|zh-Hans)?")
        out_en = subprocess.run(
            ["bash", "-c", "CARAVAN_LANG=en\n" + block + '\nS_update_macos_to_14_or_newer "13.1"; echo'],
            capture_output=True, text=True, timeout=30,
        )
        self.assertIn("Update macOS to 14 or newer", out_en.stdout)
        out_ja = subprocess.run(
            ["bash", "-c", "CARAVAN_LANG=ja\n" + block + '\nS_update_macos_to_14_or_newer "13.1"; echo'],
            capture_output=True, text=True, timeout=30,
        )
        self.assertNotEqual(out_en.stdout, out_ja.stdout)
        self.assertIn("13.1", out_ja.stdout)
        self.assertNotIn("Update macOS", out_ja.stdout)


if __name__ == "__main__":
    unittest.main()
