"""Caravan's user-facing text, looked up by key (Day 32 localization, step 1).

Every string the web page, the ``caravan`` command and the installer show
lives in ``locales/en.json``, keyed by name::

    {"cli.status.running": "Caravan is running", ...}

English is the fallback: a missing key or language never shows a blank.
Adding a language later is adding ``locales/<code>.json`` with some or all
of the same keys, plus choosing it (see :func:`language`).

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
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LOCALES = ROOT / "locales"
DEFAULT_LANGUAGE = "en"
_LANG_OK = re.compile(r"^[a-z]{2,3}(-[A-Za-z0-9]{2,8})?$")
_CACHE: dict[str, dict[str, str]] = {}


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


def mac_language() -> str | None:
    """Hook: the Mac's preferred language (AppleLanguages). Not used yet.

    Step 1 ships English only, so this returns None and nothing is read.
    A later step can read ``defaults read -g AppleLanguages`` here.
    """
    return None


def language() -> str:
    """The language to show: CARAVAN_LANG, else a saved setting, else the
    Mac's language, else English. Only languages with a file are used."""
    for code in (os.environ.get("CARAVAN_LANG"), _saved_language(), mac_language()):
        if code and _LANG_OK.match(code) and code in available_languages():
            return code
    return DEFAULT_LANGUAGE


def _saved_language() -> str | None:
    """Hook for a Settings override (``language`` in ~/.caravan/prefs). Not built yet."""
    return None


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


def t_in(lang: str | None, key: str, /, **values) -> str:
    """Like :func:`t`, for a given language code."""
    table = strings(lang)
    text = table.get(key)
    if text is None:
        text = _load(DEFAULT_LANGUAGE).get(key, key)
    if not values:
        return text
    dec = table.get("fmt.decimal", ".")
    return text.format(**values) if dec == "." else _NumberFormatter(dec).format(text, **values)


class _NumberFormatter(string.Formatter):
    """str.format, with the language's decimal mark in ``{x:.1f}``-style
    numbers. English (".") never comes here, so its text is unchanged."""

    def __init__(self, decimal: str):
        super().__init__()
        self.decimal = decimal

    def format_field(self, value, format_spec):
        out = super().format_field(value, format_spec)
        if isinstance(value, float) or (isinstance(value, int) and not isinstance(value, bool)
                                        and format_spec[-1:] in ("f", "g", "e", "%")):
            out = out.replace(".", self.decimal)
        return out


# --- plurals and numbers (Day 32, t1109u) ---------------------------------
# A count-dependent text has two keys, ``<key>_one`` and ``<key>_other``
# (more forms, e.g. ``_few``, can be added per language later); the count
# is passed as ``{count}``. Numbers with units go through fmt_* so the
# decimal mark and the unit wording come from the strings file.

def plural_form(count, lang: str | None = None) -> str:
    """CLDR-style plural category. English: 'one' for exactly 1, else 'other'.
    Other languages can be added here as they arrive."""
    try:
        return "one" if float(count) == 1 else "other"
    except (TypeError, ValueError):
        return "other"


def t_plural(key: str, count, /, **values) -> str:
    """``<key>_one`` / ``<key>_other`` for ``count``, filled with ``{count}``
    and any other values."""
    form = plural_form(count)
    table = strings()
    full = f"{key}_{form}"
    if full not in table and full not in _load(DEFAULT_LANGUAGE):
        full = f"{key}_other"
    values.setdefault("count", count)
    return t(full, **values)


def fmt_num(value, digits: int = 0) -> str:
    """A number with ``digits`` decimals, in the language's style
    (English: like ``f"{value:.{digits}f}"``)."""
    out = f"{float(value):.{int(digits)}f}"
    dec = strings().get("fmt.decimal", ".")
    return out if dec == "." else out.replace(".", dec)


def fmt_unit(unit: str, value, digits: int = 0) -> str:
    """``value`` with a unit key from the strings file: fmt.gb, fmt.mb,
    fmt.mb_s, fmt.tok_s, fmt.pct, fmt.seconds. English: "12.3 GB" etc."""
    return t(f"fmt.{unit}", n=fmt_num(value, digits))


def fmt_gb(value, digits: int = 1) -> str:
    return fmt_unit("gb", value, digits)


def fmt_pct(value, digits: int = 0) -> str:
    return fmt_unit("pct", value, digits)


def fmt_tok_s(value, digits: int = 1) -> str:
    return fmt_unit("tok_s", value, digits)


def ordinal_form(n) -> str:
    """CLDR ordinal category; English: 1st/21st one, 2nd two, 3rd few, else other."""
    n = abs(int(n))
    if n % 10 == 1 and n % 100 != 11:
        return "one"
    if n % 10 == 2 and n % 100 != 12:
        return "two"
    if n % 10 == 3 and n % 100 != 13:
        return "few"
    return "other"


def ordinal(n) -> str:
    """"1st", "2nd", … from fmt.ordinal_<form>."""
    return t(f"fmt.ordinal_{ordinal_form(n)}", n=int(n))


def join_words(items, kind: str = "list") -> str:
    """Join user-facing words with the language's separator: kind "list"
    (", "), "clause" ("; "), "and" (" and "), "or" (" or ")."""
    return t(f"fmt.{kind}_sep").join(str(x) for x in items)


def and_list(items) -> str:
    """"a, b and c" in the language's style (English: no comma before "and")."""
    items = [str(x) for x in items]
    if len(items) < 2:
        return "".join(items)
    return t("fmt.and_list", rest=join_words(items[:-1]), last=items[-1])


TP = t_plural
# The same helpers on T, like the page's T.plural / T.num / T.join (i18n.js).
t.plural = t_plural
t.num = fmt_num
t.unit = fmt_unit
t.join = join_words
t.and_list = and_list
t.ordinal = ordinal


_PLACEHOLDER = re.compile(r"\{\{([a-z0-9_.]+)\}\}")


def render_page(source: str, lang: str | None = None, prefix: str = "web.") -> str:
    """Fill ``{{key}}`` in a web page and hand the page's strings to its script.

    ``<!--caravan-strings-->`` becomes a small script that sets
    ``window.CARAVAN_STRINGS`` (English plus the chosen language) and
    ``window.CARAVAN_LANG``, which ``/i18n.js`` reads.
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
        out = out.replace("<!--caravan-strings-->",
                          f"<script>window.CARAVAN_LANG={json.dumps(code)};window.CARAVAN_STRINGS={blob};</script>")
    return out


T = t  # the name the CLI uses (t is a common local name)


SHELL_START = "# >>> caravan strings (generated from locales/en.json; edit there, then run: python3 tools/caravan_i18n.py --sync-shell) >>>"
SHELL_END = "# <<< caravan strings <<<"
SHELL_SCRIPTS = ("install", "scripts/install.sh")
_NAME = re.compile(r"\{(\w+)\}")


def shell_block(prefix: str = "install.", lang: str | None = DEFAULT_LANGUAGE, used_in: str | None = None) -> str:
    """Shell functions for the installer: ``S_<name> arg...`` prints one string.

    With ``used_in``, only the functions that script calls are included.

    The bootstrap is downloaded on its own, before the rest of Caravan, so it
    can't read locales/en.json; this block is copied into it instead (tests
    check it matches). Placeholders become positional arguments in the order
    they first appear in the English text.
    """
    en = _load(DEFAULT_LANGUAGE)
    table = strings(lang)
    lines = [SHELL_START]
    for key, english in en.items():
        if not key.startswith(prefix):
            continue
        if used_in is not None and not re.search(r"\bS_%s\b" % re.escape(key[len(prefix):]), used_in):
            continue
        order = []
        for name in _NAME.findall(english):
            if name not in order:
                order.append(name)
        text = table.get(key, english)

        def esc(chunk: str) -> str:
            return chunk.replace("\\", "\\\\").replace('"', '\\"').replace("$", "\\$").replace("`", "\\`")

        body, pos = "", 0
        for m in _NAME.finditer(text):
            body += esc(text[pos:m.start()])
            body += "${%d}" % (order.index(m.group(1)) + 1) if m.group(1) in order else esc(m.group(0))
            pos = m.end()
        body += esc(text[pos:])
        lines.append(f"S_{key[len(prefix):]}() {{ printf '%s' \"{body}\"; }}")
    lines.append(SHELL_END)
    return "\n".join(lines)


def sync_shell(root: Path = ROOT, check: bool = False) -> list[str]:
    """Rewrite (or, with check, just compare) the strings block in each installer script."""
    stale = []
    for rel in SHELL_SCRIPTS:
        path = root / rel
        text = path.read_text(encoding="utf-8")
        start, end = text.find(SHELL_START), text.find(SHELL_END)
        if start < 0 or end < 0:
            stale.append(rel)
            continue
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
        print("updated: " + ", ".join(changed) if changed else "installer strings already match locales/en.json")
    elif "--check-shell" in sys.argv:
        stale = sync_shell(check=True)
        print("stale: " + ", ".join(stale) if stale else "ok")
        sys.exit(1 if stale else 0)
    else:
        print(__doc__)
