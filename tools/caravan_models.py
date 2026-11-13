"""List downloaded models and match a plain name to a GGUF/MLX pair.

Used by `caravan models` and `caravan bench`. Talks to a running Caravan
page when it is up; otherwise falls back to what is on this Mac's disk.
"""
from __future__ import annotations

import json
import re
import sys
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "proxy"))
sys.path.insert(0, str(ROOT / "agent"))

DEFAULT_PORT = int(__import__("os").environ.get("CARAVAN_WEB_PORT", "8190"))

# Quant and format tokens, not model names (never "7b", "instruct", "coder").
_QUANT_PATTERNS = (
    r"q[2-8]_k_[sml]",
    r"q[2-8]_k",
    r"q[2-8]_[01]",
    r"q[2-8]k[sml]?",
    r"iq[1-4][_\-]\w+",
    r"[2-8][_\-]?bit",
    r"mxfp\d+",
    r"\bbf16\b",
    r"\bfp?16\b",
    r"\bfp?32\b",
    r"\bgguf\b",
    r"\bmlx\b",
)


def kind_of(model) -> str:
    src = str((model or {}).get("source") or "").lower()
    backend = str((model or {}).get("backend") or "").lower()
    mid = str((model or {}).get("id") or "")
    if src == "gguf" or backend == "llama" or mid.startswith("gguf/"):
        return "GGUF"
    return "MLX"


def friendly_name(model) -> str:
    name = str((model or {}).get("name") or (model or {}).get("id") or "").strip()
    if name.endswith(" (GGUF)"):
        name = name[: -len(" (GGUF)")].strip()
    return name or str((model or {}).get("id") or "")


def model_id(model) -> str:
    return str((model or {}).get("id") or (model or {}).get("hf") or "").strip()


def is_current(model, current) -> bool:
    if not current:
        return False
    cur = str(current)
    return model_id(model) == cur or str((model or {}).get("hf") or "") == cur


def format_line(model, current=None) -> str:
    name = friendly_name(model)
    kind = kind_of(model)
    mid = model_id(model)
    mark = "  (currently loaded)" if is_current(model, current) else ""
    ready = "" if (model or {}).get("usable", True) else "  — not ready to load"
    return f"{name}  ({kind})  {mid}{mark}{ready}"


def format_list(models, current=None, *, running=True) -> str:
    lines = []
    if not running:
        lines.append(
            "Caravan is not running. These are the models on this Mac. "
            "Run caravan start to see which one is loaded, and to compare them."
        )
        lines.append("")
    rows = [m for m in (models or []) if isinstance(m, dict) and model_id(m)]
    if not rows:
        lines.append("No models are downloaded on this Mac yet.")
        return "\n".join(lines) + "\n"
    for m in rows:
        lines.append(format_line(m, current if running else None))
    return "\n".join(lines) + "\n"


def _urlopen(url, data=None, timeout=30, headers=None):
    req = urllib.request.Request(
        url, data=data, headers=headers or {},
        method="POST" if data is not None else "GET",
    )
    if data is not None and "Content-Type" not in (headers or {}):
        req.add_header("Content-Type", "application/json")
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode())


def resolve_port(default=DEFAULT_PORT) -> int:
    try:
        import caravan_service as service
        return int(service.stored("web", Path.home())["port"])
    except Exception:
        return int(default)


def disk_models() -> list:
    """Loadable models on this Mac, without talking to the page."""
    import web_catalog as C
    import gguf_split as G
    rows = list(C.list_models() or [])
    seen = {model_id(m) for m in rows}
    for g in G.scan_local() or []:
        gid = g.get("id")
        if not gid or gid in seen:
            continue
        rows.append({
            "id": gid,
            "name": (g.get("name") or gid),
            "source": "gguf",
            "backend": "llama",
            "lead_path": g.get("path"),
            "usable": True,
        })
        seen.add(gid)
    try:
        import web_gguf_shares
        for e in web_gguf_shares.entries([], None) or []:
            if model_id(e) and model_id(e) not in seen:
                rows.append(e)
                seen.add(model_id(e))
    except Exception:
        pass
    return rows


def merge_local_gguf(models) -> list:
    """Add GGUF files from this Mac's disk if the running page omitted them.

    `caravan models` talks to /api/models first. If that list is MLX-only
    (an older page, or a scan that skipped a file the disk still has),
    local GGUF ids would be missing from the list while `caravan bench`
    name matching might still see them from a later disk look, or the
    other way around. Merging makes both commands show the same GGUF.
    """
    rows = [m for m in (models or []) if isinstance(m, dict)]
    seen = {model_id(m) for m in rows if model_id(m)}
    # Also treat a leading "gguf/" as matching a bare stem, and vice versa.
    def aliases(mid):
        mid = str(mid or "")
        out = {mid, mid.lower()}
        if mid.lower().startswith("gguf/"):
            out.add(mid[5:])
            out.add(mid[5:].lower())
        else:
            out.add("gguf/" + mid)
            out.add("gguf/" + mid.lower())
        return out
    all_seen = set()
    for s in seen:
        all_seen |= aliases(s)
    try:
        extra = disk_models()
    except Exception:
        extra = []
    for m in extra:
        if kind_of(m) != "GGUF":
            continue
        mid = model_id(m)
        if not mid or all_seen & aliases(mid):
            continue
        rows.append(m)
        seen.add(mid)
        all_seen |= aliases(mid)
    return rows


def fetch_catalog(port: int = None, urlopen=_urlopen) -> dict:
    """{models, current, running, source} from the page, merged with local GGUF."""
    port = int(port or resolve_port())
    try:
        data = urlopen(f"http://127.0.0.1:{port}/api/models", timeout=5)
        models = list((data or {}).get("models") or [])
        models = merge_local_gguf(models)
        return {
            "models": models,
            "current": (data or {}).get("current"),
            "running": True,
            "source": "api",
            "port": port,
        }
    except Exception:
        try:
            models = disk_models()
        except Exception:
            models = []
        return {
            "models": models,
            "current": None,
            "running": False,
            "source": "disk",
            "port": port,
        }


def name_tokens(text: str) -> list:
    """Plain tokens for matching: case-insensitive, no punctuation, no quants."""
    s = str(text or "").lower()
    for pat in _QUANT_PATTERNS:
        s = re.sub(pat, " ", s, flags=re.I)
    s = re.sub(r"[^a-z0-9.]+", " ", s)
    out = []
    for t in s.split():
        t = t.strip(".")
        if not t:
            continue
        out.append(t.replace(".", ""))
    return out


def _match_score(query_toks: list, model_toks: list):
    """Lower is better. None if this model does not match the query."""
    if not query_toks or not model_toks:
        return None
    qi = 0
    for t in model_toks:
        if qi < len(query_toks) and t == query_toks[qi]:
            qi += 1
    if qi == len(query_toks):
        return (0, len(model_toks) - len(query_toks))
    if set(query_toks) <= set(model_toks):
        return (1, len(model_toks) - len(query_toks))
    return None


def match_side(query: str, models, kind: str) -> list:
    """Models of this kind (GGUF or MLX) that match the plain name, best first."""
    q = name_tokens(query)
    scored = []
    for m in models or []:
        if kind_of(m) != kind:
            continue
        text = " ".join(filter(None, [
            friendly_name(m), model_id(m), str((m or {}).get("hf") or ""),
        ]))
        score = _match_score(q, name_tokens(text))
        if score is not None:
            scored.append((score, m))
    scored.sort(key=lambda x: (x[0], friendly_name(x[1]).lower()))
    # Unique by id, keep best.
    out, seen = [], set()
    for _, m in scored:
        mid = model_id(m)
        if mid in seen:
            continue
        seen.add(mid)
        out.append(m)
    return out


def find_in_catalog(mid: str, models) -> dict | None:
    if not mid:
        return None
    want = str(mid).strip()
    want_l = want.lower()
    for m in models or []:
        if model_id(m) == want or str((m or {}).get("hf") or "") == want:
            return m
        if model_id(m).lower() == want_l or str((m or {}).get("hf") or "").lower() == want_l:
            return m
    return {"id": want, "name": want, "source": "gguf" if want.lower().startswith("gguf/") else "mlx",
            "usable": True}


def _candidates_message(kind: str, query: str, found: list) -> str:
    if not found:
        return (
            f"No {kind} model matches {query!r}. "
            "Run caravan models to see what is downloaded, and pick one with "
            f"--{kind.lower()} <id>."
        )
    lines = [
        f"Several {kind} models match {query!r}. Pick one with "
        f"--{kind.lower()} and its id:"
    ]
    for m in found:
        lines.append("  " + format_line(m))
    return "\n".join(lines)


def resolve_pair(models, *, query=None, gguf_id=None, mlx_id=None) -> dict:
    """Pick one GGUF and one MLX. Ambiguous or missing sides are reported, not guessed."""
    messages = []
    g_found, m_found = [], []
    if gguf_id:
        gguf = find_in_catalog(gguf_id, models)
    elif query:
        g_found = match_side(query, models, "GGUF")
        if len(g_found) == 1:
            gguf = g_found[0]
        else:
            gguf = None
            messages.append(_candidates_message("GGUF", query, g_found))
    else:
        gguf = None
    if mlx_id:
        mlx = find_in_catalog(mlx_id, models)
    elif query:
        m_found = match_side(query, models, "MLX")
        if len(m_found) == 1:
            mlx = m_found[0]
        else:
            mlx = None
            messages.append(_candidates_message("MLX", query, m_found))
    else:
        mlx = None
    if not query and not gguf_id and not mlx_id:
        messages.append(
            "Say which model to compare, for example:  caravan bench \"qwen2.5 coder 7b\"\n"
            "Or pass both ids:  caravan bench --gguf <id> --mlx <id>\n"
            "See downloaded models and their ids:  caravan models"
        )
    blocked = any(s.startswith("No ") or s.startswith("Several") for s in messages)
    return {
        "ok": bool(gguf and mlx) and not blocked,
        "gguf": gguf,
        "mlx": mlx,
        "messages": messages,
        "gguf_candidates": g_found,
        "mlx_candidates": m_found,
    }


def main(argv=None):
    import argparse
    p = argparse.ArgumentParser(
        prog="caravan models",
        description="List downloaded models and the id to copy for each one.",
    )
    p.add_argument("--port", type=int, default=None, help=argparse.SUPPRESS)
    args = p.parse_args(argv)
    cat = fetch_catalog(port=args.port)
    sys.stdout.write(format_list(
        cat.get("models"), cat.get("current"), running=bool(cat.get("running")),
    ))
    return 0


if __name__ == "__main__":
    sys.exit(main())
