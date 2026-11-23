"""Caravan's user-facing text, looked up by key (Day 32 localization, step 1).

Every string the web page, the ``caravan`` command and the installer show
lives in ``locales/<code>.json``, keyed by name::

    {"cli.status.running": "Caravan is running", ...}

English (``locales/en.json``) is the fallback: a missing key or language
never shows a blank. Adding a language is adding ``locales/<code>.json``
with the same keys, plus choosing it (see :func:`language`).

The language to show is ``CARAVAN_LANG``, else a saved Settings override
(``language`` in ``~/.caravan/prefs``), else the Mac's preferred language,
else English. Only languages that have a strings file are used.

Placeholders use ``{name}``, filled by :func:`t` with ``str.format`` rules,
so ``{{`` and ``}}`` are literal braces in a string that takes values.
Keys ending in ``_html`` hold markup and are put into the web page as-is;
every other key is escaped when the page is rendered.
"""
from __future__ import annotations

import html
import json
import os
import re
import string
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LOCALES = ROOT / "locales"
DEFAULT_LANGUAGE = "en"
_LANG_OK = re.compile(r"^[a-z]{2,3}(-[A-Za-z0-9]{2,8})?$")
_CACHE: dict[str, dict[str, str]] = {}
# Picker metadata. A language only appears once it has a strings file.
# Spanish (and later ja / zh-Hans / ru) stay beta until a native review.
LANGUAGE_META = {
    "en": {"beta": False},
    "es": {"beta": True},
    "ja": {"beta": True},
    "zh-Hans": {"beta": True},
    "ru": {"beta": True},
}


def _load(code: str) -> dict[str, str]:
    if code not in _CACHE:
        path = LOCALES / f"{code}.json"
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            data = {}
        _CACHE[code] = {k: v for k, v in data.items()
                        if isinstance(k, str) and isinstance(v, str) and not k.startswith("_")}
    return _CACHE[code]


def available_languages() -> list[str]:
    """Language codes with a strings file (always includes English)."""
    codes = {p.stem for p in LOCALES.glob("*.json") if _LANG_OK.match(p.stem)}
    codes.add(DEFAULT_LANGUAGE)
    return sorted(codes)


def normalize_language(code, available=None):
    """Map a locale tag (es-MX, es_419.UTF-8, zh_CN) to a strings-file code."""
    if not code or not isinstance(code, str):
        return None
    raw = code.strip().replace("_", "-").split(".")[0]
    if not raw or raw.lower() in ("c", "posix"):
        return None
    parts = [p for p in raw.split("-") if p]
    if not parts:
        return None
    lang = parts[0].lower()
    rest = parts[1:]
    avail = set(available if available is not None else available_languages())
    candidates = []
    if lang == "zh":
        tokens = {p.lower() for p in rest}
        if tokens & {"hant", "tw", "hk", "mo"}:
            candidates += ["zh-Hant", "zh"]
        else:
            candidates += ["zh-Hans", "zh"]
    else:
        if rest:
            candidates.append("%s-%s" % (lang, rest[0]))
        candidates.append(lang)
    for cand in candidates:
        if cand in avail:
            return cand
        for a in avail:
            if a.lower() == cand.lower():
                return a
    return None


def caravan_dir():
    """``~/.caravan``, or ``$CARAVAN_HOME/.caravan`` when that env is set."""
    home = os.environ.get("CARAVAN_HOME") or str(Path.home())
    return Path(home).expanduser() / ".caravan"


def prefs_path():
    """Settings file for the language override (JSON)."""
    return caravan_dir() / "prefs"

def mac_language():
    """The Mac's preferred language (AppleLanguages), if we have that file.

    On macOS this reads ``defaults read -g AppleLanguages``. Cached for the
    process. Other platforms return None here; LANG is only used as a last
    resort in the installer script, so the test suite stays on English.
    """
    if getattr(mac_language, "_done", False):
        return mac_language._cached
    found = _read_apple_languages()
    mac_language._cached = found
    mac_language._done = True
    return found


def _read_apple_languages():
    if sys.platform != "darwin":
        return None
    try:
        out = subprocess.check_output(
            ["defaults", "read", "-g", "AppleLanguages"],
            text=True, timeout=2, stderr=subprocess.DEVNULL,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    tags = re.findall(r'"([A-Za-z0-9-]+)"', out)
    avail = available_languages()
    for tag in tags:
        mapped = normalize_language(tag, avail)
        if mapped:
            return mapped
    return None


def clear_language_cache():
    """Drop cached strings and the Mac-language reading (for tests)."""
    _CACHE.clear()
    for attr in ("_cached", "_done"):
        if hasattr(mac_language, attr):
            delattr(mac_language, attr)


def language():
    """The language to show: CARAVAN_LANG, else a saved setting, else the
    Mac's language, else English. Only languages with a file are used."""
    avail = available_languages()
    for code in (os.environ.get("CARAVAN_LANG"), _saved_language(), mac_language()):
        mapped = normalize_language(code, avail)
        if mapped:
            return mapped
    return DEFAULT_LANGUAGE


def _saved_language():
    """Settings override: ``language`` in ``~/.caravan/prefs``."""
    try:
        data = json.loads(prefs_path().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if not isinstance(data, dict):
        return None
    code = data.get("language")
    return code if isinstance(code, str) and code.strip() else None


def save_language(code, *, home=None):
    """Write the Settings language override. ``code`` must have a strings file
    (or be empty to follow the Mac / default again). Returns the language
    that will now be shown (after CARAVAN_LANG, if that is set)."""
    path = (Path(home).expanduser() / ".caravan" / "prefs") if home is not None else prefs_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            data = {}
    except (OSError, ValueError):
        data = {}
    mapped = normalize_language(code) if code else None
    if mapped:
        data["language"] = mapped
    else:
        data.pop("language", None)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return language()


def picker_languages(lang=None):
    """Languages to show in the Settings picker, with names from T()."""
    show_in = lang or language()
    out = []
    for code in available_languages():
        meta = LANGUAGE_META.get(code, {"beta": code != DEFAULT_LANGUAGE})
        name_key = "web.language_name_" + code.replace("-", "_")
        name = t_in(show_in, name_key)
        if name == name_key:
            name = code
        beta = bool(meta.get("beta"))
        if beta:
            label = t_in(show_in, "web.language_option_beta",
                         name=name, beta=t_in(show_in, "web.language_beta"))
        else:
            label = name
        out.append({"code": code, "name": name, "beta": beta, "label": label})
    return out


def strings(lang: str | None = None) -> dict[str, str]:
    """English, with the chosen language's strings on top (cached; restart
    after editing a strings file). Treat the result as read-only."""
    code = lang or language()
    slot = "+" + code  # kept in _CACHE too, so clearing it clears both
    if slot not in _CACHE:
        merged = dict(_load(DEFAULT_LANGUAGE))
        if code != DEFAULT_LANGUAGE:
            merged.update(_load(code))
        _CACHE[slot] = merged
    return _CACHE[slot]


def t(key: str, /, **values) -> str:
    """The text for ``key``; English if the language lacks it; the key itself
    if even English lacks it (tests make sure that never ships)."""
    return t_in(None, key, **values)


def t_in(lang, key, /, **values):
    """Like :func:`t`, for a given language code."""
    table = strings(lang)
    text = table.get(key)
    if text is None:
        text = _load(DEFAULT_LANGUAGE).get(key, key)
    if not values:
        return text
    return _format_text(text, table, values)


def _format_text(text, table, values):
    dec = table.get("fmt.decimal", ".")
    grp = table.get("fmt.thousands", "")
    if dec == "." and not grp:
        return text.format(**values)
    return _NumberFormatter(dec, grp).format(text, **values)


class _NumberFormatter(string.Formatter):
    """str.format, with the language's decimal mark and optional grouping."""

    def __init__(self, decimal, thousands=""):
        super().__init__()
        self.decimal = decimal
        self.thousands = thousands

    def format_field(self, value, format_spec):
        out = super().format_field(value, format_spec)
        numeric = isinstance(value, float) or (
            isinstance(value, int) and not isinstance(value, bool)
            and (not format_spec or format_spec[-1:] in ("f", "g", "e", "%", "d", "n")
                 or format_spec[-1:].isdigit())
        )
        if not numeric:
            return out
        if self.thousands or self.decimal != ".":
            out = _regroup(out, ".", ",", self.decimal, self.thousands)
        return out


def _regroup(out, src_dec, src_grp, dec, grp):
    """Rewrite a ``str.format`` number from ASCII punctuation to the locale."""
    sign = ""
    body = out
    if body[:1] in "+-":
        sign, body = body[0], body[1:]
    if src_grp and src_grp in body and src_dec in body:
        left, right = body.split(src_dec, 1)
        left = left.replace(src_grp, "")
        body = left + src_dec + right
    elif src_grp and src_grp in body and src_dec not in body:
        body = body.replace(src_grp, "")
    if src_dec in body:
        whole, frac = body.split(src_dec, 1)
        frac_part = dec + frac
    else:
        whole, frac_part = body, ""
    if grp:
        digits = whole
        prefix = ""
        while digits and not digits[0].isdigit():
            prefix += digits[0]
            digits = digits[1:]
        grouped = []
        while len(digits) > 3:
            grouped.append(digits[-3:])
            digits = digits[:-3]
        if digits:
            grouped.append(digits)
        whole = prefix + grp.join(reversed(grouped))
    return sign + whole + frac_part


def _cldr_parts(count):
    """Integer and visible-fraction operands for CLDR plural rules."""
    try:
        if isinstance(count, bool):
            raise TypeError
        if isinstance(count, int):
            n = abs(count)
            return n, n, 0
        orig = str(count).strip()
        if orig[:1] in "+-":
            orig = orig[1:]
        if "." in orig:
            whole, frac = orig.split(".", 1)
            v = len(frac)
            i = int(whole or "0")
            return abs(float(count)), i, v
        n = abs(float(count))
        i = int(n)
        return n, i, 0 if float(count) == i else 1
    except (TypeError, ValueError):
        return None, None, None


def plural_form(count, lang=None):
    """CLDR cardinal category for ``lang`` (or the active language).

    es / en: one / other. ru: one / few / many / other. ja and zh: other
    only. Unknown languages use the English one / other rule.
    """
    code = (lang or language() or DEFAULT_LANGUAGE)
    primary = code.split("-", 1)[0].lower()
    n, i, v = _cldr_parts(count)
    if n is None:
        return "other"
    if primary in ("ja", "zh", "ko", "vi", "th", "id", "ms"):
        return "other"
    if primary == "ru":
        if v != 0:
            return "other"
        if i % 10 == 1 and i % 100 != 11:
            return "one"
        if i % 10 in (2, 3, 4) and i % 100 not in (12, 13, 14):
            return "few"
        return "many"
    if v == 0 and i == 1:
        return "one"
    return "other"


def t_plural(key, count, /, **values):
    """``<key>_<form>`` for ``count``, falling back to ``_other`` then English."""
    return t_plural_in(None, key, count, **values)


def t_plural_in(lang, key, count, /, **values):
    code = lang or language()
    form = plural_form(count, code)
    table = strings(code)
    en = _load(DEFAULT_LANGUAGE)
    values = dict(values)
    values.setdefault("count", count)
    for cand in ("%s_%s" % (key, form), "%s_other" % key):
        if cand in table or cand in en:
            return t_in(code, cand, **values)
    return t_in(code, "%s_other" % key, **values)


def fmt_num(value, digits=0, lang=None):
    """A number with ``digits`` decimals, in the language's style
    (English: like ``f"{value:.{digits}f}"``, no grouping)."""
    table = strings(lang)
    dec = table.get("fmt.decimal", ".")
    grp = table.get("fmt.thousands", "")
    out = "{0:.{1}f}".format(float(value), int(digits))
    if dec == "." and not grp:
        return out
    return _regroup(out, ".", ",", dec, grp)


def fmt_unit(unit, value, digits=0, lang=None):
    """``value`` with a unit key from the strings file: fmt.gb, fmt.mb,
    fmt.mb_s, fmt.tok_s, fmt.pct, fmt.seconds. English: "12.3 GB" etc."""
    return t_in(lang, "fmt.%s" % unit, n=fmt_num(value, digits, lang))


def fmt_gb(value, digits=1):
    return fmt_unit("gb", value, digits)


def fmt_pct(value, digits=0):
    return fmt_unit("pct", value, digits)


def fmt_tok_s(value, digits=1):
    return fmt_unit("tok_s", value, digits)


def ordinal_form(n, lang=None):
    """CLDR ordinal category. English: 1st/21st one, 2nd two, 3rd few,
    else other. Spanish uses a single other form (1.º, 2.º, …)."""
    code = (lang or language() or DEFAULT_LANGUAGE)
    primary = code.split("-", 1)[0].lower()
    try:
        n = abs(int(n))
    except (TypeError, ValueError):
        return "other"
    if primary in ("ja", "zh", "ko", "vi", "th", "id", "ms", "es", "ru"):
        return "other"
    if n % 10 == 1 and n % 100 != 11:
        return "one"
    if n % 10 == 2 and n % 100 != 12:
        return "two"
    if n % 10 == 3 and n % 100 != 13:
        return "few"
    return "other"


def ordinal(n, lang=None):
    """"1st", "2nd", … from fmt.ordinal_<form>."""
    code = lang or language()
    form = ordinal_form(n, code)
    table = strings(code)
    en = _load(DEFAULT_LANGUAGE)
    key = "fmt.ordinal_%s" % form
    if key not in table and key not in en:
        key = "fmt.ordinal_other"
    return t_in(code, key, n=int(n))


def join_words(items, kind="list", lang=None):
    """Join user-facing words with the language's separator: kind "list"
    (", "), "clause" ("; "), "and" (" and "), "or" (" or ")."""
    return t_in(lang, "fmt.%s_sep" % kind).join(str(x) for x in items)


def and_list(items, lang=None):
    """"a, b and c" in the language's style (English: no comma before "and")."""
    items = [str(x) for x in items]
    if len(items) < 2:
        return "".join(items)
    return t_in(lang, "fmt.and_list", rest=join_words(items[:-1], lang=lang), last=items[-1])


def month_name(month, *, abbr=False, lang=None):
    """Full or abbreviated month name from the strings file (1 = January)."""
    month = int(month)
    key = "fmt.month_abbr_%s" % month if abbr else "fmt.month_%s" % month
    return t_in(lang, key)


def fmt_date(dt, style="month_day", lang=None):
    """A friendly date in the language's style.

    ``month_day``: English "November 13", Spanish "13 de noviembre".
    ``month_year``: English "November 2026", Spanish "noviembre de 2026".
    ``short``: English "Nov 13 07:43:00", Spanish "13 nov 07:43:00".
    ``dt`` may be a datetime, a time.struct_time, or a timestamp.
    """
    import datetime as _dt
    if isinstance(dt, (int, float)):
        dt = _dt.datetime.fromtimestamp(dt)
    if hasattr(dt, "tm_mon"):
        month, day, year = dt.tm_mon, dt.tm_mday, dt.tm_year
        time_s = "%02d:%02d:%02d" % (dt.tm_hour, dt.tm_min, dt.tm_sec)
    else:
        month, day, year = dt.month, dt.day, dt.year
        time_s = dt.strftime("%H:%M:%S")
    code = lang or language()
    values = {
        "month": month_name(month, lang=code),
        "month_abbr": month_name(month, abbr=True, lang=code),
        "day": str(int(day)),
        "year": str(int(year)),
        "time": time_s,
    }
    key = {
        "month_day": "fmt.date_month_day",
        "month_year": "fmt.date_month_year",
        "short": "fmt.date_short",
    }.get(style, "fmt.date_month_day")
    return t_in(code, key, **values)


TP = t_plural
# The same helpers on T, like the page's T.plural / T.num / T.join (i18n.js).
t.plural = t_plural
t.num = fmt_num
t.unit = fmt_unit
t.join = join_words
t.and_list = and_list
t.ordinal = ordinal
t.date = fmt_date
t.month = month_name


_PLACEHOLDER = re.compile(r"\{\{([a-z0-9_.]+)\}\}")


def render_page(source: str, lang: str | None = None, prefix: str = "web.") -> str:
    """Fill ``{{key}}`` in a web page and hand the page's strings to its script.

    ``<!--caravan-strings-->`` becomes a small script that sets
    ``window.CARAVAN_STRINGS`` (English plus the chosen language),
    ``window.CARAVAN_LANG`` and ``window.CARAVAN_LANGUAGES``, which
    ``/i18n.js`` and the Settings picker read.
    """
    table = strings(lang)
    en = _load(DEFAULT_LANGUAGE)

    def fill(m: re.Match) -> str:
        key = m.group(1)
        text = table.get(key, en.get(key))
        if text is None:
            return m.group(0)
        return text if key.endswith("_html") else html.escape(text, quote=True).replace("&#x27;", "'")

    code = lang or language()
    # <html lang="{{lang}}">: the active language (Day 32 step 1: "en").
    out = _PLACEHOLDER.sub(fill, source.replace('lang="{{lang}}"', f'lang="{html.escape(code)}"'))
    if "<!--caravan-strings-->" in out:
        page = {k: v for k, v in table.items() if k.startswith(prefix) or k.startswith("fmt.")}
        blob = json.dumps(page, ensure_ascii=False, separators=(",", ":"))
        blob = blob.replace("</", "<\\/").replace("\u2028", "\\u2028").replace("\u2029", "\\u2029")
        langs = json.dumps(picker_languages(code), ensure_ascii=False, separators=(",", ":"))
        langs = langs.replace("</", "<\\/")
        out = out.replace("<!--caravan-strings-->",
                          f"<script>window.CARAVAN_LANG={json.dumps(code)};"
                          f"window.CARAVAN_STRINGS={blob};"
                          f"window.CARAVAN_LANGUAGES={langs};</script>")
    return out


T = t  # the name the CLI uses (t is a common local name)


SHELL_START = "# >>> caravan strings (generated from locales/*.json; edit those, then run: python3 tools/caravan_i18n.py --sync-shell) >>>"
SHELL_START_OLD = "# >>> caravan strings (generated from locales/en.json; edit there, then run: python3 tools/caravan_i18n.py --sync-shell) >>>"
SHELL_END = "# <<< caravan strings <<<"
SHELL_SCRIPTS = ("install", "scripts/install.sh")
_NAME = re.compile(r"\{(\w+)\}")


def _shell_pick_lang_fn(have_codes):
    """Bash that sets CARAVAN_UI_LANG from CARAVAN_LANG, prefs, Mac, or LANG."""
    here = Path(__file__).resolve().parent
    for path in (here / "shell_pick.sh",
                 here.parent / "locales" / "shell_pick.sh",
                 Path("/tmp/i18n-parts/shell_pick.sh")):
        if path.is_file():
            text = path.read_text(encoding="utf-8")
            break
    else:
        raise FileNotFoundError("tools/shell_pick.sh language picker template is missing")
    return text.replace("__HAVE__", "|".join(have_codes) or "en")


def _shell_esc(chunk):
    return chunk.replace("\\", "\\\\").replace('"', '\\"').replace("$", "\\$").replace("`", "\\`")


def _shell_body(text, order):
    body, pos = "", 0
    for m in _NAME.finditer(text):
        body += _shell_esc(text[pos:m.start()])
        body += "${%d}" % (order.index(m.group(1)) + 1) if m.group(1) in order else _shell_esc(m.group(0))
        pos = m.end()
    body += _shell_esc(text[pos:])
    return body


def shell_block(prefix="install.", lang=None, used_in=None):
    """Shell functions for the installer: ``S_<name> arg...`` prints one string.

    With ``used_in``, only the functions that script calls are included.

    The bootstrap is downloaded on its own, before the rest of Caravan, so it
    can't read locales/*.json; this block is copied into it instead (tests
    check it matches). Placeholders become positional arguments in the order
    they first appear in the English text. Each function prints the string in
    ``CARAVAN_UI_LANG`` (CARAVAN_LANG, else the saved setting, else the Mac
    or LANG, else English).
    """
    en = _load(DEFAULT_LANGUAGE)
    langs = [c for c in available_languages() if c != DEFAULT_LANGUAGE]
    langs = [c for c in langs if any(k.startswith(prefix) for k in _load(c))]
    have = [DEFAULT_LANGUAGE] + langs
    pick = _shell_pick_lang_fn(have).rstrip()
    lines = [SHELL_START, pick]
    for key, english in en.items():
        if not key.startswith(prefix):
            continue
        if used_in is not None and not re.search(r"\bS_%s\b" % re.escape(key[len(prefix):]), used_in):
            continue
        order = []
        for name in _NAME.findall(english):
            if name not in order:
                order.append(name)
        if not langs:
            body = _shell_body(english, order)
            lines.append("S_%s() { printf '%%s' \"%s\"; }" % (key[len(prefix):], body))
            continue
        arms = []
        for code in langs:
            text = _load(code).get(key, english)
            arms.append("%s) printf '%%s' \"%s\" ;;" % (code, _shell_body(text, order)))
        en_body = _shell_body(english, order)
        case = " ".join(arms) + " *) printf '%%s' \"%s\" ;;" % en_body
        lines.append(
            "S_%s() { case \"${CARAVAN_UI_LANG}\" in %s esac; }" % (key[len(prefix):], case)
        )
    lines.append(SHELL_END)
    return "\n".join(lines)


def _find_shell_span(text):
    for start_mark in (SHELL_START, SHELL_START_OLD):
        start = text.find(start_mark)
        end = text.find(SHELL_END)
        if start >= 0 and end >= 0:
            return start, end
    return None


def sync_shell(root=ROOT, check=False):
    """Rewrite (or, with check, just compare) the strings block in each installer script."""
    stale = []
    for rel in SHELL_SCRIPTS:
        path = root / rel
        text = path.read_text(encoding="utf-8")
        span = _find_shell_span(text)
        if not span:
            stale.append(rel)
            continue
        start, end = span
        block = shell_block(used_in=text[:start] + text[end:])
        new = text[:start] + block + text[end + len(SHELL_END):]
        if new != text:
            stale.append(rel)
            if not check:
                path.write_text(new, encoding="utf-8")
    return stale


if __name__ == "__main__":
    import sys
    if "--sync-shell" in sys.argv:
        changed = sync_shell()
        print("updated: " + ", ".join(changed) if changed else "installer strings already match locales/*.json")
    elif "--check-shell" in sys.argv:
        stale = sync_shell(check=True)
        print("stale: " + ", ".join(stale) if stale else "ok")
        sys.exit(1 if stale else 0)
    else:
        print(__doc__)
