"""Day 27: offer a missing Guess-ahead helper, with the user's OK.

When a loaded model has a known small helper (same tokenizer) that is
not on this Mac, the page shows one short line under the model:
"Download helper for faster replies?" with Download / Not now. Nothing is
downloaded without an explicit yes. "Not now" is remembered per model in
~/.caravan/helper-offers.json and never asks again for that model.

GGUF helpers come from HELPERS below (a GGUF helper for a GGUF model).
MLX helpers come from agent/guessers.json through web_helpers.offer(),
which only offers one for a split MLX model (on one Mac an MLX model
does not use a helper yet). After a yes, Guess-ahead goes to Auto if it
was Off; Auto still decides by measurement (Auto-tune keeps the helper
only when it is at least 3% faster).
"""
from __future__ import annotations

import json
import re
import time
from pathlib import Path
from typing import Optional

STORE = Path("~/.caravan/helper-offers.json").expanduser()
LINE = "Download helper for faster replies?"

# id, pattern on the main GGUF file name, helper repo/file, size, and
# what we know. Only same-tokenizer pairs. "measured" names a real
# result in docs/DAY27.md; the others share the tokenizer but are not
# measured yet, and Auto-tune decides.
HELPERS = (
    {"id": "gguf-qwen2.5-coder",
     "pattern": r"qwen[-_ ]?2\.5[-_ ]coder[-_ ](1\.5|3|7|14|32)b",
     "repo_id": "bartowski/Qwen2.5-Coder-0.5B-Instruct-GGUF",
     "gguf_file": "Qwen2.5-Coder-0.5B-Instruct-Q8_0.gguf",
     "bytes": 531068576, "measured": True},
    {"id": "gguf-qwen2.5",
     "pattern": r"qwen[-_ ]?2\.5[-_ ](?!coder)(?:\w+[-_ ])?(3|7|14|32|72)b",
     "repo_id": "bartowski/Qwen2.5-0.5B-Instruct-GGUF",
     "gguf_file": "Qwen2.5-0.5B-Instruct-Q8_0.gguf",
     "bytes": 531068480, "measured": False},
    {"id": "gguf-qwen3",
     "pattern": r"qwen[-_ ]?3[-_ ](4|8|14|32)b",
     "repo_id": "bartowski/Qwen_Qwen3-0.6B-GGUF",
     "gguf_file": "Qwen_Qwen3-0.6B-Q8_0.gguf",
     "bytes": 804753824, "measured": False},
    {"id": "gguf-llama3",
     "pattern": r"llama[-_ ]?3\.[13][-_ ](8|70)b",
     "repo_id": "bartowski/Llama-3.2-1B-Instruct-GGUF",
     "gguf_file": "Llama-3.2-1B-Instruct-Q8_0.gguf",
     "bytes": 1321083008, "measured": False},
)


def match_gguf(name: str) -> Optional[dict]:
    blob = str(name or "").lower()
    for h in HELPERS:
        if re.search(h["pattern"], blob):
            return dict(h)
    return None


def load_store(path=None) -> dict:
    p = Path(path) if path else STORE
    try:
        d = json.loads(p.read_text())
        return d if isinstance(d, dict) else {}
    except (OSError, ValueError):
        return {}


def not_now(model_id: str, path=None, now=None) -> dict:
    """Remember Not now for this model. Never asks again for it."""
    p = Path(path) if path else STORE
    d = load_store(p)
    d.setdefault("not_now", {})[str(model_id)] = float(now if now is not None else time.time())
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(".tmp")
    tmp.write_text(json.dumps(d, indent=2))
    tmp.replace(p)
    return d


def declined(model_id: str, path=None) -> bool:
    return str(model_id) in (load_store(path).get("not_now") or {})


def _mb(n) -> int:
    return int(round(float(n) / 1e6))


def gguf_offer(model_id: str, lead_path, *, find_draft=None, jobs=None,
               store_path=None) -> Optional[dict]:
    """Offer for a GGUF model, or None (no known helper, already on disk,
    downloading, or Not now)."""
    if not model_id or not lead_path:
        return None
    if declined(model_id, store_path):
        return None
    h = match_gguf(Path(str(lead_path)).name) or match_gguf(model_id)
    if not h:
        return None
    if find_draft is None:
        import gguf_split as G
        find_draft = G.find_gguf_draft
    try:
        if find_draft(lead_path):
            return None
    except Exception:
        return None
    for j in jobs or []:
        if j.get("repo_id") == h["repo_id"] and j.get("status") in ("queued", "running", "cancelling"):
            return None
    return {"id": h["id"], "kind": "gguf", "model": model_id,
            "repo_id": h["repo_id"], "gguf_file": h["gguf_file"],
            "size_mb": _mb(h["bytes"]), "measured": bool(h["measured"]),
            "message": LINE}


def mlx_offer(snapshot: dict, store_path=None) -> Optional[dict]:
    """Offer for a split MLX model (existing pairing table), or None."""
    try:
        import web_helpers
        o = web_helpers.offer(snapshot or {})
    except Exception:
        o = None
    if not o:
        return None
    mid = (snapshot or {}).get("model_id") or o.get("model")
    if declined(mid, store_path):
        return None
    return {"id": o["id"], "kind": "mlx", "model": mid, "repo_id": o["repo_id"],
            "size_mb": o.get("size_mb"), "measured": False, "message": LINE}


def offer_for(snapshot: dict, entry: Optional[dict], *, jobs=None, store_path=None,
              find_draft=None) -> Optional[dict]:
    """The one offer for the loaded (or named) model, or None."""
    snap = snapshot or {}
    entry = entry or {}
    mid = entry.get("id") or snap.get("model_id")
    if (entry.get("source") == "gguf") or (snap.get("backend") == "llama" and not entry):
        return gguf_offer(mid, entry.get("lead_path"), find_draft=find_draft,
                          jobs=jobs, store_path=store_path)
    if snap.get("model_id") == mid:
        return mlx_offer(snap, store_path=store_path)
    return None


def download_body(offer: dict) -> dict:
    """Body for the normal download endpoint (same jobs and progress)."""
    if offer.get("kind") == "gguf":
        return {"repo_id": offer["repo_id"], "source": "gguf",
                "gguf_file": offer["gguf_file"]}
    return {"repo_id": offer["repo_id"], "helper_id": offer["id"]}
