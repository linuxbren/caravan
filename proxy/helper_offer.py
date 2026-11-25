"""Day 27: offer a missing Guess-ahead helper, with the user's OK.

When a loaded model has a known small helper (same tokenizer) that is
not on this Mac, the page shows one short line under the model:
"Download helper for faster replies?" with Download / Not now. Nothing is
downloaded without an explicit yes. "Not now" is remembered per model in
~/.caravan/helper-offers.json and never asks again for that model.

GGUF helpers come from HELPERS below (a GGUF helper for a GGUF model).
MLX helpers come from agent/guessers.json through web_helpers.offer(),
for a split MLX model or an MLX model on one Mac (a Balance split still
does not use a helper). Day 33 (v0.9.15): no helper is offered while the
model uses its own shipped guesser. After a yes, Guess-ahead goes to Auto if it
was Off; Auto still decides by measurement (Auto-tune keeps the helper
only when it is at least 3% faster).
"""
from __future__ import annotations

import json
import re
import time
from pathlib import Path
from typing import Optional
try:
    from caravan_i18n import T  # noqa: E402  (Day 32: user-facing text, tools/caravan_i18n.py)
except ImportError:  # run without tools/ on the path
    import sys as _sys
    from pathlib import Path as _Path
    _sys.path.append(str(_Path(__file__).resolve().parents[1] / "tools"))
    from caravan_i18n import T  # noqa: E402

STORE = Path("~/.caravan/helper-offers.json").expanduser()
LINE = T("server.helper_offer.download_helper_for_faster_replies")

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
               store_path=None, ignore_declined=False) -> Optional[dict]:
    """Offer for a GGUF model, or None (no known helper, already on disk,
    downloading, or Not now). ignore_declined: the user asked for it now
    (Helper download button), so an earlier Not now does not hide it."""
    if not model_id or not lead_path:
        return None
    if not ignore_declined and declined(model_id, store_path):
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


def uses_shipped_guesser(active: Optional[dict]) -> bool:
    """True when the running worker uses a guesser shipped for this model
    (Day 33, v0.9.15). A helper is then not needed, so it is not offered."""
    g = (active or {}).get("guesser") or {}
    return g.get("kind") == "native_mtp"


def mlx_offer(snapshot: dict, store_path=None, active=None) -> Optional[dict]:
    """Offer for an MLX model (existing pairing table), or None.

    None while the model uses its own shipped guesser (Day 33, v0.9.15)."""
    if uses_shipped_guesser(active):
        return None
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


def _is_gguf(snap: dict, entry: dict) -> bool:
    if entry.get("source") == "gguf":
        return True
    if entry.get("source"):
        return False
    # No catalog source: the page's GGUF id, or the loaded model on llama.cpp.
    mid = str(entry.get("id") or snap.get("model_id") or "")
    if mid.lower().startswith("gguf/"):
        return True
    return snap.get("backend") == "llama" and (not entry or mid == snap.get("model_id"))


def offer_for(snapshot: dict, entry: Optional[dict], *, jobs=None, store_path=None,
              find_draft=None, ignore_declined=False, active=None) -> Optional[dict]:
    """The one offer for the loaded (or named) model, or None."""
    snap = snapshot or {}
    entry = entry or {}
    mid = entry.get("id") or snap.get("model_id")
    if _is_gguf(snap, entry):
        return gguf_offer(mid, entry.get("lead_path"), find_draft=find_draft,
                          jobs=jobs, store_path=store_path,
                          ignore_declined=ignore_declined)
    if snap.get("model_id") == mid:
        return mlx_offer(snap, store_path=store_path, active=active)
    return None


def helper_status(snapshot: dict, entry: Optional[dict], *, find_draft=None,
                  active=None) -> dict:
    """What the Helper download button says for the loaded (or named) model.

    GGUF: whether a helper is already on this Mac (and its name), or which
    known helper could be downloaded. MLX: the same, for a model on one
    Mac or a split (a Balance split still does not use a helper).
    """
    snap = snapshot or {}
    entry = entry or {}
    mid = entry.get("id") or snap.get("model_id")
    if not mid:
        return {"kind": None, "model": None}
    if not _is_gguf(snap, entry):
        out = {"kind": "mlx", "model": mid, "split": bool(snap.get("split"))}
        if snap.get("model_id") == mid and uses_shipped_guesser(active):
            # Day 33 (v0.9.15): the model's own guesser is in use.
            out["shipped"] = True
            out["message"] = T("server.helper_offer.this_model_uses_its_built_in")
            return out
        try:
            import web_helpers
            if web_helpers.balance_split(snap):
                out["balance"] = True
                out["message"] = web_helpers.BALANCE_NO_HELPER
                return out
        except Exception:  # noqa: BLE001
            pass
        try:
            import web_helpers as _WH  # noqa: F401
            import guess_ahead as G
            p = G.find_pairing(Path(str(mid).replace("/", "--")))
            d = (p or {}).get("draft") or {}
            if p and not p.get("skip") and d.get("vocab") not in ("mismatch", "incompatible"):
                present = (G.drafts_dir() / d["name"] / "config.json").is_file()
                out["present"] = present
                out["present_name"] = d["name"] if present else None
                out["known_id"] = p["id"]
                out["known_name"] = d["name"]
                out["known_size_mb"] = d.get("size_mb")
                if present:
                    out["message"] = (T("server.helper_offer.the_guess_ahead_helper_is_already",
                                        present_name=out["present_name"]))
        except Exception:  # noqa: BLE001
            pass
        return out
    path = entry.get("lead_path")
    known = (match_gguf(Path(str(path)).name) if path else None) or match_gguf(mid)
    present = None
    if path:
        if find_draft is None:
            import gguf_split as G
            find_draft = G.find_gguf_draft
        try:
            present = find_draft(path)
        except Exception:
            present = None
    out = {"kind": "gguf", "model": mid,
           "present": bool(present),
           "present_name": (present or {}).get("name"),
           "known_id": known["id"] if known else None,
           "known_name": known["gguf_file"][:-len(".gguf")] if known else None,
           "known_size_mb": _mb(known["bytes"]) if known else None}
    if present:
        out["message"] = (T("server.helper_offer.the_guess_ahead_helper_is_already", present_name=out['present_name']))
    elif known:
        out["message"] = T("server.helper_offer.a_known_size_mb_mb_helper", known_size_mb=out['known_size_mb'], known_name=out['known_name'])
    else:
        out["message"] = T("server.helper_offer.there_is_no_known_guess_ahead")
    return out


def download_body(offer: dict) -> dict:
    """Body for the normal download endpoint (same jobs and progress)."""
    if offer.get("kind") == "gguf":
        return {"repo_id": offer["repo_id"], "source": "gguf",
                "gguf_file": offer["gguf_file"]}
    return {"repo_id": offer["repo_id"], "helper_id": offer["id"]}
