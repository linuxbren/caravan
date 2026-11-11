"""Obsidian-style Markdown archive + BM25 recall for trimmed chat turns.

Notes live under memory_dir (default ~/.caravan/memory) as
<YYYY-MM-DD>/<session>.md. Trimmed turns are appended, never discarded.
Before each reply we search the session's archive (optionally all) and
inject top snippets. Notes live only on the lead Mac (1st node).
"""
from __future__ import annotations

import math
import os
import re
import time
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

DEFAULT_MEMORY_DIR = "~/.caravan/memory"
DEFAULT_RECALL_TOKEN_CAP = 500
_TOKEN = re.compile(r"[a-z0-9_]{2,}", re.I)
_TURN_RE = re.compile(r"(?m)^## turn (\d+)\s*$")


def default_memory_dir() -> Path:
    raw = os.environ.get("CARAVAN_MEMORY_DIR") or DEFAULT_MEMORY_DIR
    return Path(raw).expanduser()


def _safe_session(session: str) -> str:
    s = re.sub(r"[^A-Za-z0-9._-]+", "_", str(session or "anon"))[:64]
    return s or "anon"


def _today() -> str:
    return datetime.now().strftime("%Y-%m-%d")


def note_path(memory_dir: Path, session: str, day: Optional[str] = None) -> Path:
    return memory_dir / (day or _today()) / f"{_safe_session(session)}.md"


def _frontmatter(session: str, model: str, created: str) -> str:
    return (
        "---\n"
        f"session: {session}\n"
        f"model: {model or ''}\n"
        f"created: {created}\n"
        f"updated: {created}\n"
        "caravan: memory\n"
        "---\n\n"
        f"# Caravan session `{session}`\n\n"
    )


def _next_turn_index(text: str) -> int:
    nums = [int(m.group(1)) for m in _TURN_RE.finditer(text or "")]
    return (max(nums) + 1) if nums else 1


def append_turns(
    memory_dir: Path,
    session: str,
    turns: list,
    *,
    model: str = "",
) -> dict:
    """Append trimmed turns to today's note. Returns {path, turns, turn_from, turn_to}."""
    memory_dir = Path(memory_dir).expanduser()
    path = note_path(memory_dir, session)
    path.parent.mkdir(parents=True, exist_ok=True)
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    existing = path.read_text() if path.is_file() else ""
    if not existing:
        existing = _frontmatter(_safe_session(session), model, now)
    else:
        # bump updated
        existing = re.sub(
            r"(?m)^updated:.*$", f"updated: {now}", existing, count=1)
    start = _next_turn_index(existing)
    chunks = []
    n = 0
    for m in turns or []:
        role = str(m.get("role") or "unknown")
        if role == "system":
            continue
        content = str(m.get("content") or "").rstrip()
        if not content:
            continue
        chunks.append(f"## turn {start + n}\n\n**{role}:**\n\n{content}\n\n")
        n += 1
    if not chunks:
        return {"path": str(path), "turns": 0, "turn_from": start, "turn_to": start - 1}
    path.write_text(existing + "".join(chunks))
    return {
        "path": str(path),
        "turns": n,
        "turn_from": start,
        "turn_to": start + n - 1,
        "day": path.parent.name,
        "session": _safe_session(session),
    }


def _tokenize(text: str) -> list:
    return [t.lower() for t in _TOKEN.findall(text or "")]


def _parse_turns(text: str) -> list:
    """Return [{n, role, content, text}] from a note body."""
    parts = _TURN_RE.split(text or "")
    # split gives [pre, n1, body1, n2, body2, ...]
    out = []
    if len(parts) < 3:
        return out
    for i in range(1, len(parts), 2):
        n = int(parts[i])
        body = parts[i + 1] if i + 1 < len(parts) else ""
        role = "unknown"
        m = re.search(r"\*\*([^*]+):\*\*", body)
        if m:
            role = m.group(1).strip()
        content = re.sub(r"^\s*\*\*[^*]+:\*\*\s*", "", body.strip(), count=1)
        out.append({"n": n, "role": role, "content": content.strip(), "text": body.strip()})
    return out


def iter_session_notes(memory_dir: Path, session: str, *, all_sessions: bool = False):
    memory_dir = Path(memory_dir).expanduser()
    if not memory_dir.is_dir():
        return
    sid = _safe_session(session)
    for day_dir in sorted(memory_dir.iterdir()):
        if not day_dir.is_dir() or day_dir.name.startswith("."):
            continue
        if all_sessions:
            for f in sorted(day_dir.glob("*.md")):
                yield f
        else:
            f = day_dir / f"{sid}.md"
            if f.is_file():
                yield f


def bm25_recall(
    memory_dir: Path,
    session: str,
    query: str,
    *,
    top_k: int = 3,
    token_cap: int = DEFAULT_RECALL_TOKEN_CAP,
    all_sessions: bool = False,
) -> list:
    """Cheap BM25-ish ranking over archived turns. Returns snippet dicts."""
    q = _tokenize(query)
    if not q:
        return []
    docs = []
    for path in iter_session_notes(memory_dir, session, all_sessions=all_sessions):
        try:
            text = path.read_text()
        except OSError:
            continue
        for turn in _parse_turns(text):
            toks = _tokenize(turn["content"])
            if not toks:
                continue
            docs.append({**turn, "path": str(path), "toks": toks})
    if not docs:
        return []
    N = len(docs)
    df = Counter()
    for d in docs:
        df.update(set(d["toks"]))
    avgdl = sum(len(d["toks"]) for d in docs) / N
    k1, b = 1.4, 0.75
    scored = []
    qset = set(q)
    for d in docs:
        tf = Counter(d["toks"])
        dl = len(d["toks"])
        score = 0.0
        for term in qset:
            if term not in tf:
                continue
            n_qi = df.get(term, 0)
            idf = math.log(1 + (N - n_qi + 0.5) / (n_qi + 0.5))
            f = tf[term]
            score += idf * (f * (k1 + 1)) / (f + k1 * (1 - b + b * dl / avgdl))
        if score > 0:
            scored.append((score, d))
    scored.sort(key=lambda x: -x[0])
    out, used = [], 0
    for score, d in scored[: max(top_k * 3, top_k)]:
        approx = max(1, len(d["content"]) // 4)
        if used and used + approx > token_cap:
            continue
        snippet = d["content"]
        if len(snippet) > 800:
            snippet = snippet[:800].rstrip() + "…"
        out.append({
            "score": round(score, 3),
            "turn": d["n"],
            "role": d["role"],
            "text": snippet,
            "path": d["path"],
            "approx_tokens": approx,
        })
        used += approx
        if len(out) >= top_k or used >= token_cap:
            break
    return out


def count_archived_turns(memory_dir: Path, session: str) -> int:
    """Total ## turn N headings across this session's archive files."""
    n = 0
    for path in iter_session_notes(memory_dir, session, all_sessions=False):
        try:
            text = Path(path).read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        n += len(_TURN_RE.findall(text))
    return n


_GUARD_NOTE_PREFIXES = (
    "Note: ",
    "Earlier in this conversation",
)


def is_memory_guard_note(content: str) -> bool:
    s = str(content or "").lstrip()
    return any(s.startswith(p) for p in _GUARD_NOTE_PREFIXES)


def format_recall_note(snippets: list, archived_turns: int = 0) -> str:
    """One system note: archive-awareness (when N>0) plus optional BM25 snippets.

    Always tell the model when turns were moved, even if recall finds nothing.
    """
    n = int(archived_turns or 0)
    snippets = list(snippets or [])
    if n <= 0 and not snippets:
        return ""
    lines = []
    if n > 0:
        lines.append(
            f"Note: {n} earlier turns of this conversation were moved to notes "
            "to save memory. If the user refers to something you can't see here, "
            "say you don't have it in view and ask them to restate it, rather "
            "than guessing."
        )
    if snippets:
        lines.append("Relevant bits from those notes:" if n > 0 else
                     "Earlier in this conversation (from notes):")
        for s in snippets:
            lines.append(f"- (turn {s['turn']}, {s['role']}) {s['text']}")
    return "\n".join(lines)
