"""Idea 3 guess-ahead helpers: pairing table, vocab match/remap, download ask,
first-load gate, and per-chat shut-off.

Used by mlx_worker on the split lead. When disabled (--no-split-draft) or when
no pairing matches, behavior is unchanged.
"""
from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path
from typing import Any, Optional

HERE = Path(__file__).resolve().parent
DEFAULT_TABLE = HERE / "guessers.json"
DEFAULT_STATE = Path("~/.caravan/mlx/guess-ahead-state.json").expanduser()


def load_table(path: Optional[Path] = None) -> dict:
    p = Path(path) if path else DEFAULT_TABLE
    return json.loads(p.read_text())


def _norm(s: str) -> str:
    return "".join(ch.lower() if ch.isalnum() else "-" for ch in s).strip("-")


def model_stem(model_dir: Path) -> str:
    name = model_dir.name
    # org--name or plain folder
    if "--" in name:
        name = name.split("--", 1)[-1]
    return name


def find_pairing(model_dir: Path, table: Optional[dict] = None) -> Optional[dict]:
    table = table or load_table()
    stem = model_stem(model_dir)
    stem_n = _norm(stem)
    path_n = _norm(str(model_dir))
    # Pairings win over skips so e.g. DeepSeek-R1-Distill-Qwen is not
    # swallowed by a native DeepSeek-R1 skip entry.
    for pair in table.get("pairings") or []:
        for m in pair.get("match") or []:
            mn = _norm(m)
            if mn in stem_n or stem_n in mn or mn in path_n:
                return dict(pair)
    for skip in table.get("no_pairing") or []:
        for m in skip.get("match") or []:
            if _norm(m) in stem_n or _norm(m) in path_n:
                return {"skip": True, "reason": skip.get("reason"), "match": m}
    return None


def drafts_dir(table: Optional[dict] = None) -> Path:
    table = table or load_table()
    return Path(table.get("drafts_dir") or "~/.caravan/mlx-models/drafts").expanduser()


def state_path(table: Optional[dict] = None) -> Path:
    table = table or load_table()
    return Path(table.get("state_file") or DEFAULT_STATE).expanduser()


def load_state(table: Optional[dict] = None) -> dict:
    p = state_path(table)
    if not p.is_file():
        return {"version": 1, "download_answers": {}, "first_load": {}}
    try:
        return json.loads(p.read_text())
    except Exception:
        return {"version": 1, "download_answers": {}, "first_load": {}}


def save_state(state: dict, table: Optional[dict] = None) -> None:
    p = state_path(table)
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(".tmp")
    tmp.write_text(json.dumps(state, indent=2) + "\n")
    tmp.replace(p)


def env_truthy(name: str) -> bool:
    v = (os.environ.get(name) or "").strip().lower()
    return v in ("1", "true", "yes", "on", "y")


def env_falsey(name: str) -> bool:
    v = (os.environ.get(name) or "").strip().lower()
    return v in ("0", "false", "no", "off", "n")


def ask_download(pairing: dict, *, auto: bool, interactive: Optional[bool] = None,
                 model_label: Optional[str] = None) -> bool:
    """Ask once whether to download the guesser. Honors remembered answers + auto flag."""
    table = load_table()
    st = load_state(table)
    key = pairing["id"]
    answers = st.setdefault("download_answers", {})
    if key in answers:
        return bool(answers[key])
    draft = pairing["draft"]
    size = draft.get("size_mb", "?")
    name = draft.get("name")
    label = model_label or pairing.get("id") or "this model"
    msg = (f"A {size} MB helper can make {label} faster. "
           f"Download {name}? [y/N] ")
    if auto or env_truthy("CARAVAN_MLX_SPLIT_DRAFT_AUTO_DOWNLOAD"):
        answers[key] = True
        save_state(st, table)
        return True
    if interactive is None:
        interactive = sys.stdin.isatty() and sys.stdout.isatty()
    if not interactive:
        # Non-interactive default: do not download; remember decline so we don't spam logs.
        answers[key] = False
        save_state(st, table)
        return False
    try:
        sys.stdout.write(msg)
        sys.stdout.flush()
        line = sys.stdin.readline()
    except Exception:
        answers[key] = False
        save_state(st, table)
        return False
    ok = (line or "").strip().lower() in ("y", "yes")
    answers[key] = ok
    save_state(st, table)
    return ok


def download_draft(pairing: dict, *, dry_run: bool = False) -> Path:
    """Download guesser to drafts_dir. dry_run returns the target path without fetching."""
    table = load_table()
    ddir = drafts_dir(table)
    ddir.mkdir(parents=True, exist_ok=True)
    name = pairing["draft"]["name"]
    dest = ddir / name
    if dry_run:
        return dest
    if dest.is_dir() and (dest / "config.json").is_file():
        return dest
    repo = pairing["draft"]["hf_repo"]
    from huggingface_hub import snapshot_download
    snapshot_download(repo, local_dir=str(dest))
    return dest


def _piece_maps_from_tokenizer_json(path: Path) -> tuple[dict[int, str], dict[str, int]]:
    tj = json.loads((path / "tokenizer.json").read_text())
    vocab = (tj.get("model") or {}).get("vocab") or {}
    if not isinstance(vocab, dict):
        return {}, {}
    id_to_piece = {int(i): str(t) for t, i in vocab.items()}
    piece_to_id = {str(t): int(i) for t, i in vocab.items()}
    # added_tokens override / extend
    for a in tj.get("added_tokens") or []:
        pid, content = a.get("id"), a.get("content")
        if pid is None or content is None:
            continue
        id_to_piece[int(pid)] = str(content)
        piece_to_id[str(content)] = int(pid)
    return id_to_piece, piece_to_id


def build_vocab_maps(target_dir: Path, draft_dir: Path) -> dict[str, Any]:
    """Compare target vs draft tokenizers. Returns match info + optional remap tables.

    remap_draft_to_target[draft_id] = target_id (for ids that differ)
    remap_target_to_draft[target_id] = draft_id
    """
    t_id, t_piece = _piece_maps_from_tokenizer_json(target_dir)
    d_id, d_piece = _piece_maps_from_tokenizer_json(draft_dir)
    if not t_id or not d_id:
        # Fall back to vocab_size equality via config
        tc = json.loads((target_dir / "config.json").read_text())
        dc = json.loads((draft_dir / "config.json").read_text())
        tv, dv = tc.get("vocab_size"), dc.get("vocab_size")
        exact = tv is not None and tv == dv
        return {
            "ok": exact,
            "mode": "exact" if exact else "mismatch",
            "reason": None if exact else f"vocab_size {dv} != {tv} (no tokenizer.json vocab)",
            "remap_draft_to_target": {},
            "remap_target_to_draft": {},
            "n_remap": 0,
            "n_same": 0,
        }
    shared = set(t_piece) & set(d_piece)
    remap_d2t: dict[int, int] = {}
    remap_t2d: dict[int, int] = {}
    same = 0
    for piece in shared:
        tid, did = t_piece[piece], d_piece[piece]
        if tid == did:
            same += 1
        else:
            remap_d2t[did] = tid
            remap_t2d[tid] = did
    # Exact if no remaps and same coverage of target ids
    if not remap_d2t and same >= min(len(t_piece), len(d_piece)) * 0.99:
        return {
            "ok": True,
            "mode": "exact",
            "reason": None,
            "remap_draft_to_target": {},
            "remap_target_to_draft": {},
            "n_remap": 0,
            "n_same": same,
        }
    # Compatible if we share a real vocab and most pieces agree (remaps = specials/unused).
    if shared and (
            same >= len(shared) * 0.95
            or (same + len(remap_d2t)) >= len(shared) * 0.99):
        return {
            "ok": True,
            "mode": "compatible_specials_remap",
            "reason": None,
            "remap_draft_to_target": remap_d2t,
            "remap_target_to_draft": remap_t2d,
            "n_remap": len(remap_d2t),
            "n_same": same,
        }
    return {
        "ok": False,
        "mode": "mismatch",
        "reason": f"shared={len(shared)} same_id={same} remap={len(remap_d2t)}",
        "remap_draft_to_target": {},
        "remap_target_to_draft": {},
        "n_remap": len(remap_d2t),
        "n_same": same,
    }


def apply_remap(ids: list[int], table: dict[int, int]) -> list[int]:
    if not table:
        return list(ids)
    return [table.get(i, i) for i in ids]


def first_load_cache_key(model_dir: Path, draft_dir: Path) -> str:
    return f"{model_stem(model_dir)}::{draft_dir.name}"


def get_first_load(model_dir: Path, draft_dir: Path, table: Optional[dict] = None) -> Optional[dict]:
    st = load_state(table)
    return (st.get("first_load") or {}).get(first_load_cache_key(model_dir, draft_dir))


def set_first_load(model_dir: Path, draft_dir: Path, result: dict, table: Optional[dict] = None) -> None:
    st = load_state(table)
    fl = st.setdefault("first_load", {})
    fl[first_load_cache_key(model_dir, draft_dir)] = result
    save_state(st, table)


def derive_break_even(baseline_tps: float, spec_tps: float, k: int, accepted_frac: float) -> float:
    """Minimum accepted_frac (from_draft/n_gen) to beat baseline, with slack.

    If spec was measured faster, use half the observed accepted_frac as floor
    (must stay clearly helpful). Otherwise estimate from k.
    """
    if baseline_tps <= 0 or k < 1:
        return 0.35
    if spec_tps > baseline_tps * 1.05 and accepted_frac > 0:
        # Require at least ~60% of the measured accept rate to keep guessing.
        return max(0.15, min(0.8, accepted_frac * 0.6))
    # No measured win: need roughly >1/k of tokens from draft to amortize a verify.
    return max(0.2, min(0.7, 1.0 / (k + 1)))


class ChatShutoff:
    """Per-chat accepted-guess tracker; disables guessing below break-even."""

    def __init__(self, break_even_frac: float, window: int = 48):
        self.break_even_frac = float(break_even_frac)
        self.window = max(8, int(window))
        self.from_draft = 0
        self.n_gen = 0
        self.disabled = False
        self.reason = None

    def observe(self, from_draft: bool) -> None:
        if self.disabled:
            return
        self.n_gen += 1
        if from_draft:
            self.from_draft += 1
        if self.n_gen >= self.window:
            frac = self.from_draft / max(self.n_gen, 1)
            if frac < self.break_even_frac:
                self.disabled = True
                self.reason = (
                    f"accepted_frac {frac:.3f} < break_even {self.break_even_frac:.3f} "
                    f"over {self.n_gen} tokens; guess-ahead off for this chat"
                )

    def snapshot(self) -> dict:
        return {
            "disabled": self.disabled,
            "reason": self.reason,
            "from_draft": self.from_draft,
            "n_gen": self.n_gen,
            "accepted_frac": round(self.from_draft / max(self.n_gen, 1), 3),
            "break_even_frac": self.break_even_frac,
        }


# Quality prompts for first-load gate (known short answers).
QUALITY_PROBES = [
    ("What is 2+2? Reply with just the number.", ("4", "four")),
    ("Name the capital of France. One word.", ("paris",)),
    ("Is ice cream typically hot or cold? One word.", ("cold",)),
]

# Thinking / scratch channels we never score.
_THOUGHT_CHANNELS = (
    "thought", "thinking", "analysis", "commentary", "scratch", "reason", "reasoning",
)
_FINAL_CHANNELS = ("final", "response", "answer", "output")
_STOP_TOKENS = (
    "<|im_end|>", "<|end|>", "<|end_of_text|>", "<|return|>", "</s>", "<eos>",
)


def final_answer_text(text: str) -> str:
    """Strip thinking/channel blocks; return only the final-answer segment.

    Handles:
    - Qwen ``<think>...</think>``
    - GPT-OSS ``<|channel|>analysis...<|channel|>final<|message|>...``
    - Gemma-4 ``<|channel>thought\n...\n<channel|>ANSWER<turn|>``
      (open token ``<|channel>``, close token ``<channel|>``, answer then
      ``<turn|>`` — there is usually no explicit ``final`` channel)
    - Gemma/Qwen variants that do emit ``<|channel>final`` / ``<|channel|>final``

    If the model only emitted an open thought channel with no closer and
    no final channel, returns empty so the quality gate fails instead of
    matching words inside the scratch pad.
    """
    import re
    t = (text or "")
    for stop in _STOP_TOKENS:
        if stop in t:
            t = t.split(stop)[0]
    # Qwen / generic think fences (closed).
    t = re.sub(r"<think\b[^>]*>.*?</think>", " ", t, flags=re.DOTALL | re.IGNORECASE)
    t = re.sub(r"<\|think\|>.*?(?=<\|/?\w|$)", " ", t, flags=re.DOTALL | re.IGNORECASE)
    m = re.search(r"</think\s*>", t, flags=re.IGNORECASE)
    if m:
        t = t[m.end():]

    # Gemma-4 close-token form: <|channel>NAME ... <channel|>ANSWER[<turn|>...]
    # Prefer the segment after the *last* <channel|> closer.
    if "<channel|>" in t or "<|channel>" in t or "<|channel|>" in t:
        # Walk opens/closes. Content after a closer (and before next open/turn)
        # is the user-visible answer for Gemma.
        gemma_bits: list[str] = []
        # Split keeping delimiters.
        pieces = re.split(r"(<\|channel\|>|<\|channel>|<channel\|>|<\|turn\|>|<turn\|>|<\|turn>)", t)
        mode = "body"  # body | after_open | after_close
        chan = ""
        buf = []
        finals: list[str] = []
        saw_channel = False
        for piece in pieces:
            if piece in ("<|channel|>", "<|channel>"):
                saw_channel = True
                if mode == "after_close" and buf:
                    finals.append("".join(buf))
                mode, chan, buf = "after_open", "", []
                continue
            if piece == "<channel|>":
                saw_channel = True
                # drop thought body in buf; answer follows
                mode, buf = "after_close", []
                continue
            if piece in ("<|turn|>", "<turn|>", "<|turn>"):
                if mode == "after_close" and buf:
                    finals.append("".join(buf))
                mode, buf = "body", []
                continue
            if mode == "after_open":
                if not chan:
                    # first word is channel name; rest is body
                    name_m = re.match(
                        r"\s*([A-Za-z_][A-Za-z0-9_]*)\b(?:\s*<\|message\|>)?\s*",
                        piece)
                    if name_m:
                        chan = name_m.group(1).lower()
                        rest = piece[name_m.end():]
                    else:
                        chan, rest = "", piece
                    if chan in _FINAL_CHANNELS:
                        # GPT-OSS / explicit final: accumulate as final
                        mode = "final_body"
                        if rest:
                            finals.append(rest)
                    else:
                        # thought/analysis: discard
                        buf = []
                else:
                    # still in thought body — discard
                    pass
                continue
            if mode == "final_body":
                finals.append(piece)
                continue
            if mode == "after_close":
                buf.append(piece)
                continue
            # plain body with no channel yet
            buf.append(piece)
        if mode == "after_close" and buf:
            finals.append("".join(buf))
        if finals:
            t = "\n".join(finals)
        elif saw_channel:
            # Had channel markup but never closed / never reached final.
            return ""
        else:
            t = "".join(buf) if buf else t

    # Fallback Final:/Answer: markers for unmarked prose.
    if not any(x in (text or "") for x in ("<|channel", "<channel|>", "</think", "<think")):
        fm = re.search(
            r"\b(?:final(?:\s+answer)?|answer)\s*[:\-]\s*",
            t, flags=re.IGNORECASE)
        if fm:
            t = t[fm.end():]

    t = re.sub(r"<\|/?[^|>]+\|?>", " ", t)
    t = re.sub(r"</?think\b[^>]*>", " ", t, flags=re.IGNORECASE)
    t = re.sub(r"<channel\|>", " ", t)
    t = re.sub(r"<turn\|>", " ", t)
    t = re.sub(r"<\|turn>", " ", t)
    return re.sub(r"\s+", " ", t).strip().lower()


def answer_ok(text: str, expect: tuple[str, ...]) -> bool:
    """True only if an expected answer appears in the *final* answer text.

    Anchors to the last non-empty line (and a short whole-text fallback).
    Uses whole-word matches so a thought that mentions "Paris" cannot
    pass when the final line is "London".
    """
    import re
    t = final_answer_text(text)
    if not t:
        return False
    lines = [ln.strip() for ln in t.splitlines() if ln.strip()]
    # Prefer the last sentence / last line. Long scratch pads without
    # channel markers only score their ending — never the whole blob.
    candidates = []
    if lines:
        last = lines[-1]
        parts = re.split(r"(?<=[.!?])\s+", last)
        if len(last) > 48 and len(parts) > 1:
            candidates.append(parts[-1])
        else:
            candidates.append(last)
            if len(parts) > 1:
                candidates.append(parts[-1])
    if len(t) <= 48:
        candidates.append(t)
    seen = set()
    for c in candidates:
        if not c or c in seen:
            continue
        seen.add(c)
        c_norm = c.strip(" \t\"\'*`")
        for e in expect:
            e = e.lower()
            if c_norm.strip(".!?,:; ") == e:
                return True
            if re.search(rf"(?<![a-z0-9]){re.escape(e)}(?![a-z0-9])", c):
                return True
    return False
