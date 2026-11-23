"""Helpers for the Day 32 localization tests (strings file, lookups, lint).

``english_source(path)`` gives a web/CLI/installer file with each string
lookup put back as its English text, so older tests that look for a phrase
in the page source keep working after the text moved to locales/en.json.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
EN_PATH = ROOT / "locales" / "en.json"
WEB = ROOT / "proxy" / "web"
WEB_FILES = [WEB / "index.html", WEB / "pairing.html"] + sorted(
    p for p in WEB.glob("*.js") if p.name != "i18n.js")
CLI_FILES = sorted(p for p in (ROOT / "tools").glob("caravan*.py") if p.name != "caravan_i18n.py")
SHELL_FILES = [ROOT / "install", ROOT / "scripts" / "install.sh"]
# Server and worker modules whose messages reach the page or the CLI.
SERVER_FILES = sorted(p for d in ("proxy", "agent") for p in (ROOT / d).glob("*.py")
                      if "from caravan_i18n import T" in p.read_text(encoding="utf-8"))
PY_KEY = r"(?:cli|server|agent)\.[a-z0-9_.]*[a-z0-9_]"


def en() -> dict:
    return json.loads(EN_PATH.read_text(encoding="utf-8"))


# ---- JS scanning -----------------------------------------------------------

_REGEX_PREV = set("(,=:[!&|?{};+-*%<>~^") | {""}
_REGEX_WORDS = {"return", "typeof", "case", "in", "of", "delete", "void", "throw", "new", "else", "do"}


def js_strings(code: str):
    """Yield (start, end, quote, text) for each JS string/template literal.

    Template literals yield their static text with ``${...}`` shown as ``{}``.
    Comments and regex literals are skipped. Good enough for Caravan's code.
    """
    i, n = 0, len(code)
    prev = ""  # last significant token (char or word)
    stack = []  # for templates: depth of braces inside ${}
    while i < n:
        c = code[i]
        if c in " \t\r\n":
            i += 1
            continue
        if code.startswith("//", i):
            j = code.find("\n", i)
            i = n if j < 0 else j
            continue
        if code.startswith("/*", i):
            j = code.find("*/", i + 2)
            i = n if j < 0 else j + 2
            continue
        if c in "'\"":
            j = i + 1
            buf = []
            while j < n and code[j] != c:
                if code[j] == "\\":
                    buf.append(code[j:j + 2])
                    j += 2
                    continue
                buf.append(code[j])
                j += 1
            yield i, j + 1, c, _unescape("".join(buf))
            i = j + 1
            prev = "str"
            continue
        if c == "`":
            j = i + 1
            buf = []
            while j < n and code[j] != "`":
                if code[j] == "\\":
                    buf.append(code[j:j + 2])
                    j += 2
                    continue
                if code.startswith("${", j):
                    inner_start = j + 2
                    k = _expr_end(code, inner_start)
                    inner = code[inner_start:k - 1]
                    for s0, e0, q0, t0 in js_strings(inner):
                        yield inner_start + s0, inner_start + e0, q0, t0
                    buf.append("{}")
                    j = k
                    continue
                buf.append(code[j])
                j += 1
            yield i, j + 1, "`", _unescape("".join(buf))
            i = j + 1
            prev = "str"
            continue
        if c == "/" and (prev in _REGEX_PREV or prev in _REGEX_WORDS):
            i = _regex_end(code, i)
            prev = "re"
            continue
        m = re.match(r"[A-Za-z_$][\w$]*|\d[\w.]*", code[i:i + 80])
        if m:
            prev = m.group(0)
            i += len(prev)
            continue
        prev = c
        i += 1


def literal_end(code: str, i: int) -> int:
    """Index just past the string or template literal starting at code[i]."""
    q, j, n = code[i], i + 1, len(code)
    while j < n and code[j] != q:
        if code[j] == "\\":
            j += 2
            continue
        if q == "`" and code.startswith("${", j):
            j = _expr_end(code, j + 2)
            continue
        j += 1
    return j + 1


def _expr_end(code: str, j: int) -> int:
    """Index just past the ``}`` closing a template ``${`` whose body starts at j."""
    depth, prev, n = 1, "{", len(code)
    while j < n and depth:
        ch = code[j]
        if ch in "'\"`":
            j = literal_end(code, j)
            prev = "s"
            continue
        if code.startswith("//", j) or code.startswith("/*", j):
            e = code.find("\n" if code[j + 1] == "/" else "*/", j + 2)
            j = n if e < 0 else e + (0 if code[j + 1] == "/" else 2)
            continue
        if ch == "/" and prev in "(,=:[!&|?{};":
            j = _regex_end(code, j)
            prev = "s"
            continue
        if not ch.isspace():
            prev = ch
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
        j += 1
    return j


def _regex_end(code: str, i: int) -> int:
    j, n, cls = i + 1, len(code), False
    while j < n:
        ch = code[j]
        if ch == "\\":
            j += 2
            continue
        if ch == "[":
            cls = True
        elif ch == "]":
            cls = False
        elif (ch == "/" and not cls) or ch == "\n":
            break
        j += 1
    j += 1
    while j < n and code[j].isalpha():
        j += 1
    return j


def _unescape(s: str) -> str:
    def rep(m):
        e = m.group(1)
        if e[0] == "u":
            return chr(int(e[2:-1] if e[1] == "{" else e[1:], 16))
        if e[0] == "x":
            return chr(int(e[1:], 16))
        return {"n": "\n", "t": "\t", "r": "\r", "0": "\0"}.get(e, e)
    return re.sub(r"\\(u\{[0-9a-fA-F]+\}|u[0-9a-fA-F]{4}|x[0-9a-fA-F]{2}|.)", rep, s, flags=re.S)


def script_parts(path: Path):
    """(offset, code) for each script in a web file."""
    text = path.read_text(encoding="utf-8")
    if path.suffix == ".js":
        return [(0, text)]
    out = []
    for m in re.finditer(r"<script(\s[^>]*)?>(.*?)</script>", text, re.S):
        if m.group(1) and "src=" in m.group(1):
            continue
        out.append((m.start(2), m.group(2)))
    return out


# ---- key usage -------------------------------------------------------------

JS_PLURAL = re.compile(r"\bT\.plural\(\s*([\"'`])((?:web)\.[a-z0-9_.]+)\1\s*,")
DYNAMIC_PREFIXES = ("fmt.", "web.status_", "web.thermal_")


def _js_args(text: str, open_paren: int):
    """[(start, end)] of the top-level arguments of the call at open_paren."""
    args, depth, i, start = [], 0, open_paren, open_paren + 1
    while i < len(text):
        ch = text[i]
        if ch in "\"'`":
            j = i + 1
            while j < len(text) and text[j] != ch:
                j += 2 if text[j] == "\\" else 1
            i = j
        elif ch in "([{":
            depth += 1
        elif ch in ")]}":
            depth -= 1
            if depth == 0:
                args.append((start, i))
                return args
        elif ch == "," and depth == 1:
            args.append((start, i))
            start = i + 1
        i += 1
    return args


JS_CALL = re.compile(r"\bT\(\s*([\"'`])((?:web)\.[a-z0-9_.]+)\1\s*(,\s*\{)?")
HTML_KEY = re.compile(r"\{\{((?:web)\.[a-z0-9_.]+)\}\}")
PY_CALL = re.compile(r"\bT\(\s*\"(cli\.[a-z0-9_.]+)\"")
SH_CALL = re.compile(r"\bS_([a-z0-9_]+)\b")


def _object_segments(code: str, start: int):
    """Split the object literal at code[start] == '{' into top-level segments.

    Returns (segments, index of the closing brace). Skips strings, templates
    and regex literals so a quote inside /[&<>"]/ does not confuse it.
    """
    depth, i, token_start, segs, prev = 0, start, start + 1, [], ""
    while i < len(code):
        ch = code[i]
        if ch in "'\"`":
            i = literal_end(code, i)
            prev = "s"
            continue
        if ch == "/" and prev in "(,=:[!&|?{};" and code[i + 1:i + 2] not in ("/", "*"):
            i = _regex_end(code, i)
            prev = "s"
            continue
        if ch in "([{":
            depth += 1
        elif ch in ")]}":
            depth -= 1
            if depth == 0:
                segs.append(code[token_start:i])
                break
        elif ch == "," and depth == 1:
            segs.append(code[token_start:i])
            token_start = i + 1
        if not ch.isspace():
            prev = ch
        i += 1
    return segs, i


def js_object_names(code: str, start: int) -> list[str]:
    """Property names of the object literal starting at code[start] == '{'."""
    names = []
    for s in _object_segments(code, start)[0]:
        s = s.strip()
        if not s:
            continue
        m = re.match(r"([A-Za-z_$][\w$]*)", s)
        names.append(m.group(1) if m else s)
    return names


def placeholders(text: str) -> set[str]:
    return set(re.findall(r"(?<!\{)\{([A-Za-z_]\w*)(?:![rsa])?(?::[^{}]*)?\}(?!\})", text))


def used_keys():
    """{key: [(file, has_values, names)]} across web, CLI and installer files."""
    uses = {}
    for path in WEB_FILES:
        text = path.read_text(encoding="utf-8")
        for m in HTML_KEY.finditer(text):
            uses.setdefault(m.group(1), []).append((path.name, False, []))
        for m in JS_CALL.finditer(text):
            names = js_object_names(text, m.end() - 1) if m.group(3) else []
            uses.setdefault(m.group(2), []).append((path.name, bool(m.group(3)), names))
    for path in CLI_FILES + SERVER_FILES:
        text = path.read_text(encoding="utf-8")
        for m in re.finditer(r"\bT\(\s*\"(" + PY_KEY + r")\"", text):
            # keyword names: scan the call's arguments
            names = _py_call_names(text, m.start())
            uses.setdefault(m.group(1), []).append((path.name, bool(names), names))
    # Plurals: T.plural("key", count[, {vars}]) uses key_one and key_other,
    # filled with {count} plus the vars (Python: keyword values).
    for path in WEB_FILES:
        text = path.read_text(encoding="utf-8")
        for m in JS_PLURAL.finditer(text):
            args = _js_args(text, text.index("(", m.start()))
            names = ["count"]
            if len(args) > 2 and text[args[2][0]:args[2][1]].lstrip().startswith("{"):
                names += js_object_names(text, text.index("{", args[2][0]))
            for form in ("_one", "_other"):
                uses.setdefault(m.group(2) + form, []).append((path.name, True, names))
    for path in CLI_FILES + SERVER_FILES:
        text = path.read_text(encoding="utf-8")
        for m in re.finditer(r"\bT\.plural\(\s*\"(" + PY_KEY + r")\"", text):
            names = ["count"] + _py_call_names(text, m.start())
            for form in ("_one", "_other"):
                uses.setdefault(m.group(1) + form, []).append((path.name, True, names))
    # Keys built at run time: fmt.* (the number/list helpers), the page's
    # web.status_<status>, and web_picker's notice -> refusal table.
    import ast
    for key, value in en().items():
        if key.startswith(DYNAMIC_PREFIXES):
            uses.setdefault(key, []).append(("(dynamic)", None, []))
    picker = (ROOT / "proxy" / "web_picker.py").read_text(encoding="utf-8")
    table = picker[picker.index("_REFUSALS = {"):]
    table = table[:table.index("}") + 1].split("=", 1)[1]
    for k, v in ast.literal_eval(table.strip()).items():
        for name in (k, v):
            uses.setdefault("server.web_picker." + name, []).append(("web_picker.py", False, []))
    for path in SHELL_FILES:
        text = path.read_text(encoding="utf-8")
        start = text.find(">>> caravan strings")
        end = text.find("<<< caravan strings")
        body = text[:start] + text[end:]
        for m in SH_CALL.finditer(body):
            uses.setdefault("install." + m.group(1), []).append((path.name, False, []))
    return uses


def _py_call_names(text: str, start: int) -> list[str]:
    import ast
    depth, i = 0, text.index("(", start)
    j = i
    while j < len(text):
        ch = text[j]
        if ch in "([{":
            depth += 1
        elif ch in ")]}":
            depth -= 1
            if depth == 0:
                break
        elif ch in "'\"":
            q = text[j:j + 3] if text[j:j + 3] in ('"""', "'''") else ch
            k = text.find(q, j + len(q))
            while k > 0 and text[k - 1] == "\\" and len(q) == 1:
                k = text.find(q, k + 1)
            j = k + len(q) - 1
        j += 1
    call = ast.parse("T" + text[i:j + 1], mode="eval").body
    return [k.arg for k in call.keywords]


# ---- English source for older tests ----------------------------------------

def _js_literal(text: str, quote: str) -> str:
    body = text.replace("\\", "\\\\").replace(quote, "\\" + quote).replace("\n", "\\n")
    return quote + body + quote


def english_source(path) -> str:
    """The file with string lookups replaced by their English text."""
    path = Path(path)
    strings = en()
    text = path.read_text(encoding="utf-8")
    if path.suffix in (".html", ".js") or path.name in ("index.html",):
        import html as H

        def fill(m):
            v = strings.get(m.group(1), m.group(0))
            return v if m.group(1).endswith("_html") else H.escape(v, quote=True).replace("&#x27;", "'")
        text = HTML_KEY.sub(fill, text).replace('lang="{{lang}}"', 'lang="en"')
        return _expand_js(text, strings)
    if path.suffix == ".py":
        out, pos = [], 0
        for m in re.finditer(r"\bT\(\s*\"(" + PY_KEY + r")\"", text):
            if m.start() < pos:
                continue
            value = strings.get(m.group(1))
            if value is None:
                continue
            names = _py_call_names(text, m.start())
            # find the end of the call
            depth, j = 0, text.index("(", m.start())
            k = j
            while k < len(text):
                if text[k] in "([{":
                    depth += 1
                elif text[k] in ")]}":
                    depth -= 1
                    if depth == 0:
                        break
                k += 1
            out.append(text[pos:m.start()])
            if names:
                import ast
                call = ast.parse("T" + text[j:k + 1], mode="eval").body
                exprs = {kw.arg: ast.unparse(kw.value) for kw in call.keywords}
                body = re.sub(r"\{([A-Za-z_]\w*)", lambda pm: "{" + exprs.get(pm.group(1), pm.group(1)), value)
                out.append("f" + repr(body))
            else:
                out.append(repr(value))
            pos = k + 1
        out.append(text[pos:])
        return "".join(out)
    # installer scripts: S_name args -> the English text with $vars
    start, end = text.find("# >>> caravan strings"), text.find("# <<< caravan strings <<<")
    head, block, tail = text[:start], text[start:end], text[end:]

    def sh(m):
        key = "install." + m.group(1)
        value = strings.get(key)
        if value is None:
            return m.group(0)
        args = re.findall(r'"([^"]*)"', m.group(2) or "")
        order = []
        for name in re.findall(r"\{(\w+)\}", value):
            if name not in order:
                order.append(name)
        return re.sub(r"\{(\w+)\}", lambda pm: args[order.index(pm.group(1))] if order.index(pm.group(1)) < len(args) else pm.group(0), value)
    pat = re.compile(r'"\$\(S_([a-z0-9_]+)((?: "[^"]*")*)\)"')
    def quoted(m):
        text = sh(m)
        if not m.group(2) and "'" not in text:
            return "'" + text + "'"
        return '"' + text + '"'
    # The generated strings block is left out so phrase counts match the old script.
    tail = tail[tail.index("\n") + 1:]
    return pat.sub(quoted, head) + pat.sub(quoted, tail)


def _tpl_text(value: str) -> str:
    return value.replace("\\", "\\\\").replace("`", "\\`").replace("${", "\\${")


def _expand_js(text: str, strings: dict) -> str:
    """Replace T("key"[, {vars}]) calls with English literals/templates (nested too)."""
    out, pos = [], 0
    for m in JS_CALL.finditer(text):
        if m.start() < pos:
            continue
        key, quote = m.group(2), m.group(1)
        value = strings.get(key)
        if value is None:
            continue
        if not m.group(3):
            close = text.index(")", m.end() - 1)
            # ${T("key")} inside a template: put the words straight in.
            if text[m.start() - 2:m.start()] == "${" and text[close + 1:close + 2] == "}":
                out.append(text[pos:m.start() - 2])
                out.append(_tpl_text(value))
                pos = close + 2
                continue
            out.append(text[pos:m.start()])
            out.append(_js_literal(value, quote))
            pos = close + 1
            continue
        exprs = _js_object_exprs(text, m.end() - 1)
        obj_end = exprs.pop("__end__")
        close = text.index(")", obj_end)
        tpl, last = "", 0
        for pm in re.finditer(r"\{\{|\}\}|\{([A-Za-z0-9_]+)\}", value):
            tpl += _tpl_text(value[last:pm.start()])
            tok = pm.group(0)
            if tok in ("{{", "}}"):
                tpl += tok[0]
            else:
                tpl += "${" + _expand_js(exprs.get(pm.group(1), pm.group(1)), strings) + "}"
            last = pm.end()
        tpl += _tpl_text(value[last:])
        out.append(text[pos:m.start()])
        out.append("`" + tpl + "`")
        pos = close + 1
    out.append(text[pos:])
    return "".join(out)


def _js_object_exprs(code: str, start: int) -> dict:
    """{name: expression source} for an object literal; '__end__' is the closing brace index."""
    segs, end = _object_segments(code, start)
    out = {"__end__": end}
    for s in segs:
        s = s.strip()
        if not s:
            continue
        m = re.match(r"([A-Za-z_$][\w$]*)\s*:\s*(.*)$", s, re.S)
        if m:
            out[m.group(1)] = m.group(2).strip()
        else:
            out[s] = s
    return out
