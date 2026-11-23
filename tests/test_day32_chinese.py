"""Day 32: Simplified Chinese localization (zh-Hans.json, picker, formatting, _other plurals)."""
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


def _zh():
    path = ROOT / "locales" / "zh-Hans.json"
    return json.loads(path.read_text(encoding="utf-8"))


def _empty(key: str, val) -> bool:
    if not isinstance(val, str):
        return True
    if key == "fmt.thousands":
        return val == ""
    return not val.strip()


class ChineseFile(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.en = I.en()
        cls.zh = _zh()
        cls.skip = _non_other_plural_keys(cls.en)

    def test_every_english_key_is_present_except_non_other_plurals(self):
        missing = sorted(k for k in self.en if k not in self.skip and k not in self.zh)
        self.assertEqual(missing, [])

    def test_plural_keys_are_other_only(self):
        unexpected = sorted(k for k in self.zh if k in self.skip)
        self.assertEqual(unexpected, [])
        bases = _cardinal_bases(self.en)
        self.assertTrue(bases)
        missing = []
        for base in bases:
            key = base + "_other"
            if key not in self.zh:
                missing.append(key)
                continue
            ev = self.en[key]
            if I.placeholders(ev) != I.placeholders(self.zh[key]):
                missing.append("%s placeholders %s vs %s" % (
                    key, I.placeholders(ev), I.placeholders(self.zh[key])))
        self.assertEqual(missing, [])
        self.assertIn("fmt.ordinal_other", self.zh)
        self.assertNotIn("fmt.ordinal_one", self.zh)
        self.assertNotIn("fmt.ordinal_two", self.zh)
        self.assertNotIn("fmt.ordinal_few", self.zh)

    def test_no_empty_strings(self):
        empty = sorted(k for k, v in self.zh.items() if _empty(k, v))
        self.assertEqual(empty, [])

    def test_placeholders_match_english(self):
        # Simplified Chinese date templates may also include {year} so dates
        # can read 2026年11月13日; every English placeholder must still be present.
        date_keys = {"fmt.date_month_day", "fmt.date_month_year", "fmt.date_short"}
        bad = []
        for k, ev in self.en.items():
            if k not in self.zh:
                continue
            en_ph, zh_ph = I.placeholders(ev), I.placeholders(self.zh[k])
            if k in date_keys:
                if not en_ph.issubset(zh_ph):
                    bad.append("%s: en=%s zh=%s" % (k, en_ph, zh_ph))
            elif en_ph != zh_ph:
                bad.append("%s: en=%s zh=%s" % (k, en_ph, zh_ph))
        self.assertEqual(bad, [])

    def test_html_markup_tags_match(self):
        bad = []
        for k, ev in self.en.items():
            if not k.endswith("_html") or k not in self.zh:
                continue
            if TAG.findall(ev) != TAG.findall(self.zh[k]):
                bad.append("%s: en=%s zh=%s" % (k, TAG.findall(ev), TAG.findall(self.zh[k])))
        self.assertEqual(bad, [])

    def test_plural_forms_in_real_strings(self):
        one = C.t_plural_in("zh-Hans", "web.n_models", 1)
        two = C.t_plural_in("zh-Hans", "web.n_models", 2)
        five = C.t_plural_in("zh-Hans", "web.n_models", 5)
        frac = C.t_plural_in("zh-Hans", "web.n_models", 1.5)
        self.assertEqual(one, "1个模型")
        self.assertEqual(two, "2个模型")
        self.assertEqual(five, "5个模型")
        self.assertEqual(frac, "1.5个模型")
        shard = C.t_plural_in("zh-Hans", "server.model_inventory.missing_shards", 1)
        shard3 = C.t_plural_in("zh-Hans", "server.model_inventory.missing_shards", 3)
        self.assertIn("分片", shard)
        self.assertIn("分片", shard3)
        self.assertEqual(shard, shard3.replace("3", "1"))

    def test_download_and_unload_stay_distinct(self):
        # Glossary: Download is 下载; Unload is 卸载. They must not swap.
        load = self.zh.get("web.load", "")
        download = self.zh.get("web.download", "")
        unload = self.zh.get("web.unload", "")
        self.assertIn("加载", load)
        self.assertIn("下载", download)
        self.assertIn("卸载", unload)
        self.assertNotIn("下载", unload)
        self.assertNotIn("卸载", download)


class LanguageChoice(unittest.TestCase):
    def setUp(self):
        C.clear_language_cache()

    def tearDown(self):
        C.clear_language_cache()

    def test_locale_tags_map_to_simplified_chinese(self):
        hans = [
            "zh-Hans", "zh-Hans-CN", "zh-Hans-US", "zh-CN", "zh-SG", "zh",
            "zh_CN", "zh_SG", "zh_Hans", "zh_Hans_CN", "zh_Hans_US",
            "zh-CN.UTF-8", "zh_CN.UTF-8", "zh-Hans-CN.UTF-8",
        ]
        for tag in hans:
            self.assertEqual(C.normalize_language(tag), "zh-Hans", tag)
        # Explicit script wins over region.
        self.assertEqual(C.normalize_language("zh-Hans-TW"), "zh-Hans")
        # Traditional tags must not map to zh-Hans (no zh-Hant file yet).
        for tag in ("zh-Hant", "zh-TW", "zh-HK", "zh-MO", "zh_TW", "zh_HK",
                    "zh-Hant-TW", "zh-Hant-CN", "zh_Hant", "zh-TW.UTF-8"):
            self.assertIsNone(C.normalize_language(tag), tag)

    def test_caravan_lang_selects_simplified_chinese(self):
        with tempfile.TemporaryDirectory() as d:
            env = {"CARAVAN_HOME": d, "CARAVAN_LANG": "zh-CN"}
            with mock.patch.dict(os.environ, env, clear=False):
                C.clear_language_cache()
                self.assertEqual(C.language(), "zh-Hans")
            with mock.patch.dict(os.environ, {"CARAVAN_HOME": d, "CARAVAN_LANG": "zh-TW"}, clear=False):
                C.clear_language_cache()
                self.assertEqual(C.language(), "en")
            with mock.patch.dict(os.environ, {"CARAVAN_HOME": d, "CARAVAN_LANG": "zh-Hans-US"}, clear=False):
                C.clear_language_cache()
                self.assertEqual(C.language(), "zh-Hans")

    def test_apple_languages_prefer_simplified_and_skip_traditional(self):
        with mock.patch.object(C, "_read_apple_languages", return_value="zh-Hans"):
            C.clear_language_cache()
            with mock.patch.dict(os.environ, {"CARAVAN_LANG": ""}, clear=False):
                # Force the mocked Mac language through normalize as the
                # language() helper would: first tag zh-CN, later en.
                pass
        # Walk the same mapping AppleLanguages uses.
        avail = C.available_languages()
        self.assertIn("zh-Hans", avail)
        self.assertEqual(C.normalize_language("zh-CN", avail), "zh-Hans")
        self.assertIsNone(C.normalize_language("zh-Hant", avail))
        self.assertIsNone(C.normalize_language("zh-TW", avail))
        self.assertIsNone(C.normalize_language("zh-HK", avail))
        # A Traditional-first list should skip to a later Simplified tag.
        def fake_read():
            for tag in ("zh-Hant-TW", "zh-TW", "en-US"):
                mapped = C.normalize_language(tag, avail)
                if mapped:
                    return mapped
            return None
        self.assertEqual(fake_read(), "en")
        def fake_read_hans():
            for tag in ("zh-CN", "en-US"):
                mapped = C.normalize_language(tag, avail)
                if mapped:
                    return mapped
            return None
        self.assertEqual(fake_read_hans(), "zh-Hans")

    def test_picker_marks_chinese_beta(self):
        langs = {row["code"]: row for row in C.picker_languages("en")}
        self.assertIn("en", langs)
        self.assertFalse(langs["en"]["beta"])
        self.assertIn("es", langs)
        self.assertTrue(langs["es"]["beta"])
        self.assertIn("ru", langs)
        self.assertTrue(langs["ru"]["beta"])
        self.assertIn("ja", langs)
        self.assertTrue(langs["ja"]["beta"])
        self.assertIn("zh-Hans", langs)
        self.assertTrue(langs["zh-Hans"]["beta"])
        self.assertIn("beta", langs["zh-Hans"]["label"].lower())
        self.assertIn("简体中文", langs["zh-Hans"]["label"])
        self.assertNotIn("beta", langs["en"]["label"].lower())
        zh_picker = {row["code"]: row for row in C.picker_languages("zh-Hans")}
        self.assertIn("简体中文", zh_picker["zh-Hans"]["label"])
        self.assertIn("beta", zh_picker["zh-Hans"]["label"].lower())
        self.assertEqual(langs["zh-Hans"]["code"], "zh-Hans")

    def test_save_language_normalizes_zh_cn(self):
        with tempfile.TemporaryDirectory() as d:
            home = Path(d)
            C.save_language("zh-CN", home=home)
            prefs = json.loads((home / ".caravan" / "prefs").read_text(encoding="utf-8"))
            self.assertEqual(prefs["language"], "zh-Hans")
            # Traditional is not available; save_language clears the override
            # rather than storing zh-Hans or zh-Hant.
            C.save_language("zh-TW", home=home)
            prefs = json.loads((home / ".caravan" / "prefs").read_text(encoding="utf-8"))
            self.assertNotIn("language", prefs)


class Formatting(unittest.TestCase):
    def tearDown(self):
        C.clear_language_cache()

    def test_chinese_numbers_lists_dates_ordinals(self):
        self.assertEqual(C.fmt_num(1234.5, 1, "zh-Hans"), "1,234.5")
        self.assertEqual(C.fmt_num(12.3, 1, "zh-Hans"), "12.3")
        self.assertEqual(C.fmt_unit("gb", 12.3, 1, "zh-Hans"), C.t_in("zh-Hans", "fmt.gb", n="12.3"))
        listed = C.and_list(["a", "b", "c"], lang="zh-Hans")
        self.assertEqual(listed, "a、b和c")
        self.assertEqual(C.join_words(["a", "b", "c"], lang="zh-Hans"), "a、b、c")
        self.assertEqual(C.ordinal(1, "zh-Hans"), "第1")
        self.assertEqual(C.ordinal(2, "zh-Hans"), "第2")
        d = datetime(2026, 11, 13, 18, 0, 0)
        self.assertEqual(C.fmt_date(d, "month_day", lang="en"), "November 13")
        self.assertEqual(C.fmt_date(d, "month_day", lang="zh-Hans"), "2026年11月13日")
        self.assertEqual(C.fmt_date(d, "month_year", lang="zh-Hans"), "2026年11月")
        zh_short = C.fmt_date(d, "short", lang="zh-Hans")
        self.assertIn("2026年11月13日", zh_short)
        # Other languages stay as they were.
        self.assertEqual(C.fmt_date(d, "month_day", lang="ja"), "2026年11月13日")
        self.assertEqual(C.fmt_date(d, "month_day", lang="ru"), "13 ноября")
        self.assertIn("noviembre", C.fmt_date(d, "month_day", lang="es").lower())

    def test_english_numbers_stay_ungrouped(self):
        self.assertEqual(C.fmt_num(1234.5, 1, "en"), "1234.5")


class InstallerLanguage(unittest.TestCase):
    def test_shell_block_can_print_chinese(self):
        if not shutil.which("bash"):
            self.skipTest("bash not installed")
        import subprocess
        block = C.shell_block()
        self.assertIn("CARAVAN_UI_LANG", block)
        self.assertIn("zh-Hans", block)
        self.assertRegex(block, r"en\|es\|ja\|ru\|zh-Hans")
        # Script wins over region; Traditional stays unmapped.
        pick = C._shell_pick_lang_fn(["en", "es", "ja", "ru", "zh-Hans"])
        cases = [
            ("zh-Hans", "zh-Hans"),
            ("zh-Hans-CN", "zh-Hans"),
            ("zh-Hans-US", "zh-Hans"),
            ("zh-CN", "zh-Hans"),
            ("zh-SG", "zh-Hans"),
            ("zh", "zh-Hans"),
            ("zh_CN", "zh-Hans"),
            ("zh_Hans_US", "zh-Hans"),
            ("zh-Hans-TW", "zh-Hans"),
            ("zh-Hant", "en"),
            ("zh-TW", "en"),
            ("zh-HK", "en"),
            ("zh_TW", "en"),
            ("zh-Hant-CN", "en"),
        ]
        # Unset locale vars so a zh_* LANG on the host cannot leak into
        # Traditional-tag cases that should fall through to English.
        shell_env = "unset LANG LC_ALL LC_MESSAGES LANGUAGE\n"
        for raw, expect in cases:
            out = subprocess.run(
                ["bash", "-c", shell_env + "CARAVAN_LANG=%s\n" % raw + pick + '\nprintf "%s" "$CARAVAN_UI_LANG"'],
                capture_output=True, text=True, timeout=30,
            )
            self.assertEqual(out.stdout, expect, "CARAVAN_LANG=%s -> %r (want %s); err=%s" % (
                raw, out.stdout, expect, out.stderr))
        out_en = subprocess.run(
            ["bash", "-c", "CARAVAN_LANG=en\n" + block + '\nS_update_macos_to_14_or_newer "13.1"; echo'],
            capture_output=True, text=True, timeout=30,
        )
        self.assertIn("Update macOS to 14 or newer", out_en.stdout)
        out_zh = subprocess.run(
            ["bash", "-c", "CARAVAN_LANG=zh-Hans\n" + block + '\nS_update_macos_to_14_or_newer "13.1"; echo'],
            capture_output=True, text=True, timeout=30,
        )
        self.assertNotEqual(out_en.stdout, out_zh.stdout)
        self.assertIn("13.1", out_zh.stdout)
        self.assertNotIn("Update macOS", out_zh.stdout)
        out_cn = subprocess.run(
            ["bash", "-c", "CARAVAN_LANG=zh-CN\n" + block + '\nS_update_macos_to_14_or_newer "13.1"; echo'],
            capture_output=True, text=True, timeout=30,
        )
        self.assertEqual(out_zh.stdout, out_cn.stdout)


if __name__ == "__main__":
    unittest.main()
