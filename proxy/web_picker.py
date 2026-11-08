"""Model picker (ROADMAP): catalog, fit check, disk, download.

Sources:
  * Hugging Face MLX (mlx-community and convertible HF repos)
  * Ollama (= llama.cpp / GGUF) via HF GGUF publishers (bartowski, unsloth,
    lmstudio-community) — one Mini for now; split hook left for later
  * Ollama Cloud — framework only (OLLAMA_API_KEY); labeled CLOUD

Fit uses unload capacity (available + loaded worker footprint, or total minus
an OS baseline) + disk free checked separately. Color: green / yellow / red / gray.
"""
from __future__ import annotations

import json
import os
import re
import shutil
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Optional

# agent/ is on sys.path from web_server
try:
    import memory_guard as MG
except ImportError:  # pragma: no cover
    MG = None

HF_API = "https://huggingface.co/api/models"
OLLAMA_API_KEY = os.environ.get("OLLAMA_API_KEY") or os.environ.get("CARAVAN_OLLAMA_API_KEY")

def _hf_token():
    try:
        from hf_auth import resolve_hf_token
        return resolve_hf_token()
    except Exception:
        return os.environ.get("HF_TOKEN") or os.environ.get("HUGGING_FACE_HUB_TOKEN")

# Back-compat alias (re-resolved on each use via _hf_headers / downloads)
HF_TOKEN = None  # use _hf_token(); kept so older callers don't NameError if they assign
CACHE_TTL_S = float(os.environ.get("CARAVAN_PICKER_CACHE_TTL", "300"))
DEFAULT_CTX = 8192
DEFAULT_SAFETY_GB = float(os.environ.get("CARAVAN_MEMORY_SAFETY_GB", "1.75"))
# macOS + apps baseline when estimating unload capacity on a 24 GB Mini
OS_BASELINE_GB = float(os.environ.get("CARAVAN_OS_BASELINE_GB", "4.0"))
try:
    from web_nodes import MAX_SPLIT_STAGES  # noqa: E402
except ImportError:  # pragma: no cover
    MAX_SPLIT_STAGES = int(os.environ.get("CARAVAN_MAX_SPLIT_STAGES", "2"))
NEW_MODEL_DAYS = int(os.environ.get("CARAVAN_PICKER_NEW_DAYS", "30"))
MLX_MODEL_ROOTS = [
    Path("~/.caravan/mlx-models").expanduser(),
    Path("~/.exo/models").expanduser(),
]
GGUF_ROOTS = [
    Path("~/.caravan/gguf").expanduser(),
    Path("~/.ollama/models").expanduser(),
]

# Quant patterns → bits estimate for KV / display
_QUANT_RE = re.compile(
    r"(?i)(?:[-_]|^)(4bit|6bit|8bit|3bit|2bit|bf16|fp16|fp32|"
    r"q4_k_m|q4_k_s|q5_k_m|q5_k_s|q6_k|q8_0|q3_k_m|q2_k|mxfp4|iq4_xs)(?:[-_]|$)"
)

_FILTER_TAGS = {
    "chat": {"text-generation", "conversational", "chat"},
    "coding": {"code", "coding", "text2code", "code-generation"},
    "reasoning": {"reasoning", "thinking", "chain-of-thought"},
    "vision": {"image-text-to-text", "image-to-text", "visual-question-answering"},
    "image-to-image": {"image-to-image", "text-to-image"},
    "voice": {
        "automatic-speech-recognition", "audio-to-text", "speech-to-text",
        "text-to-speech", "text-to-audio",
    },
    "cloud": {"cloud", "ollama-cloud"},
}

# Category chip → real HF queries (plus name keywords).
_FILTER_SEARCH = {
    "chat": {
        "mlx_search": ["Instruct", "Chat"],
        "hf_search": ["Instruct"],
        "pipeline_tag": None,
    },
    "coding": {
        "mlx_search": ["coder", "code"],
        "hf_search": ["coder", "code instruct"],
        "pipeline_tag": None,
        "name_keys": ("coder", "code-", "-code", "codestral", "deepseek-coder"),
    },
    "reasoning": {
        "mlx_search": ["QwQ", "thinking", "reasoning", "R1"],
        "hf_search": ["QwQ", "DeepSeek-R1", "thinking"],
        "pipeline_tag": None,
        "name_keys": ("qwq", "thinking", "reasoning", "r1-", "-r1", "distill-r1"),
    },
    "vision": {
        "mlx_search": ["VL", "vision"],
        "hf_search": ["VL Instruct"],
        "pipeline_tag": "image-text-to-text",
        "name_keys": ("-vl-", "vl-", "vision", "llava", "pixtral"),
    },
    "image-to-image": {
        "mlx_search": ["image-edit", "flux", "sdxl"],
        "hf_search": [""],
        "pipeline_tag": "image-to-image",
        "name_keys": ("image-edit", "img2img", "flux", "sdxl", "stable-diffusion"),
    },
    "voice": {
        "mlx_search": ["whisper", "tts", "speech"],
        "hf_search": ["whisper"],
        "pipeline_tags": ("automatic-speech-recognition", "text-to-speech"),
        "name_keys": ("whisper", "tts", "asr", "speecht5", "kokoro"),
    },
}

# Static Ollama Cloud catalog (labeled CLOUD; framework only until phase 5).
_OLLAMA_CLOUD = [
    {"id": "gpt-oss:120b-cloud", "name": "gpt-oss 120B Cloud", "note": "Ollama Cloud"},
    {"id": "deepseek-v3.1:671b-cloud", "name": "DeepSeek V3.1 671B Cloud", "note": "Ollama Cloud"},
    {"id": "qwen3-coder:480b-cloud", "name": "Qwen3 Coder 480B Cloud", "note": "Ollama Cloud · coding"},
    {"id": "kimi-k2:1t-cloud", "name": "Kimi K2 1T Cloud", "note": "Ollama Cloud"},
    {"id": "glm-4.6:cloud", "name": "GLM-4.6 Cloud", "note": "Ollama Cloud"},
    {"id": "minimax-m2:cloud", "name": "MiniMax M2 Cloud", "note": "Ollama Cloud"},
]

_cache_lock = threading.Lock()
_cache: dict = {}  # key -> {t, data}


def _cache_get(key: str):
    with _cache_lock:
        e = _cache.get(key)
        if e and time.time() - e["t"] < CACHE_TTL_S:
            return e["data"]
    return None


def _cache_set(key: str, data):
    with _cache_lock:
        _cache[key] = {"t": time.time(), "data": data}


def _hf_headers() -> dict:
    h = {"User-Agent": "caravan-picker/1.0"}
    tok = _hf_token()
    if tok:
        h["Authorization"] = f"Bearer {tok}"
    return h


def _http_json(url: str, timeout: float = 25) -> object:
    req = urllib.request.Request(url, headers=_hf_headers())
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8"))


def _parse_quant(repo_id: str, tags=None) -> Optional[str]:
    blob = repo_id + " " + " ".join(tags or [])
    m = _QUANT_RE.search(blob.replace("-", "_"))
    if not m:
        # mlx-community often ends with -4bit
        m = re.search(r"(?i)(4bit|6bit|8bit|bf16|fp16)$", repo_id)
    return m.group(1).lower() if m else None


def _bits_of_quant(q: Optional[str]) -> float:
    if not q:
        return 4.0
    q = q.lower()
    table = {
        "2bit": 2, "3bit": 3, "4bit": 4, "6bit": 6, "8bit": 8,
        "bf16": 16, "fp16": 16, "fp32": 32,
        "q2_k": 2.5, "q3_k_m": 3.5, "q4_k_m": 4.5, "q4_k_s": 4.0,
        "q5_k_m": 5.5, "q5_k_s": 5.0, "q6_k": 6.5, "q8_0": 8,
        "mxfp4": 4.5, "iq4_xs": 4.25,
    }
    return float(table.get(q, 4.0))


def _base_name(repo_id: str) -> str:
    name = repo_id.split("/")[-1]
    name = re.sub(
        r"(?i)[-_](4bit|6bit|8bit|3bit|2bit|bf16|fp16|fp32|"
        r"q4_k_m|q4_k_s|q5_k_m|q5_k_s|q6_k|q8_0|q3_k_m|q2_k|mxfp4|iq4_xs|"
        r"MLX|GGUF|it-?4bit|Instruct)$",
        "",
        name,
    )
    name = re.sub(r"[-_]+$", "", name)
    return name or repo_id


def _filters_for(pipeline_tag: str, tags, repo_id: str = "") -> list:
    tags = set(t.lower() for t in (tags or []))
    if pipeline_tag:
        tags.add(pipeline_tag.lower())
    out = []
    for filt, keys in _FILTER_TAGS.items():
        if tags & keys:
            out.append(filt)
    name = (repo_id or "").lower()
    for filt, spec in _FILTER_SEARCH.items():
        keys = spec.get("name_keys") or ()
        if keys and any(k in name for k in keys):
            if filt not in out:
                out.append(filt)
    if "cloud" in tags or name.startswith("ollama-cloud/"):
        if "cloud" not in out:
            out.append("cloud")
    if not out and (not pipeline_tag or pipeline_tag in ("text-generation",)):
        out.append("chat")
    return out


def _estimate_weights_gb(params_b: Optional[float], quant: Optional[str],
                        siblings_bytes: Optional[int] = None) -> float:
    if siblings_bytes and siblings_bytes > 0:
        return siblings_bytes / 1e9
    if params_b and params_b > 0:
        return params_b * 1e9 * (_bits_of_quant(quant) / 8.0) / 1e9
    return 0.0


def _node_capacity_gb(n: dict) -> float:
    """RAM this Mini would have for a new model once the current worker unloads.

    Prefer available_gb + active/weights footprint (what frees on unload).
    Also consider total - OS_BASELINE_GB. Use the more conservative of the
    two when both look sane, so a busy Mini doesn't look emptier than it is
    after a switch, and an idle Mini doesn't claim the whole stick.
    """
    ram = n.get("ram") or {}
    total = float(ram.get("total_gb") or 0)
    avail = float(ram.get("available_gb") or ram.get("free_gb") or 0)
    footprint = float(n.get("active_gb") or n.get("weights_gb") or 0)
    # If a model is loaded, reclaim its footprint on unload.
    if footprint > 0.25 or n.get("model"):
        reclaim = avail + max(0.0, footprint)
    else:
        reclaim = avail
    by_baseline = (total - OS_BASELINE_GB) if total > 0 else reclaim
    candidates = [c for c in (reclaim, by_baseline) if c > 0]
    if not candidates:
        return max(0.0, avail)
    # More conservative (= smaller) when both are within a sane band.
    cap = min(candidates)
    # If reclaim is clearly measuring "after unload" and baseline is close, fine.
    # If baseline is much larger (idle machine, tiny footprint), prefer baseline.
    if footprint <= 0.25 and by_baseline > reclaim + 1.0:
        cap = by_baseline
    if total > 0:
        cap = min(cap, total - 0.5)
    return round(max(0.0, cap), 2)


def _node_label(n: dict, idx: int) -> str:
    return n.get("label") or n.get("role") or f"Mini{idx+1}"


def fit_check(
    *,
    weights_gb: float,
    nodes: list,
    cfg: Optional[dict] = None,
    n_layers: Optional[int] = None,
    ctx_tokens: int = DEFAULT_CTX,
    safety_gb: float = DEFAULT_SAFETY_GB,
    kv_bits: int = 16,
    split_ok: bool = True,
    max_split_stages: Optional[int] = None,
) -> dict:
    """Return color, nodes_needed, per-node fit, plain-English reasons.

    RAM uses unload capacity (not current free). Disk is checked separately.
    Works for 1..N online nodes (offline/error nodes are ignored). With one
    node, never suggests splitting. `max_split_stages` caps what the *runtime*
    can load today (see web_nodes.MAX_SPLIT_STAGES); fit may still report
    fits_on beyond that with a clear note.
    """
    max_stages = int(max_split_stages if max_split_stages is not None else MAX_SPLIT_STAGES)
    nodes = [
        n for n in (nodes or [])
        if isinstance(n, dict) and not n.get("error") and not n.get("offline")
    ]
    if not nodes:
        return {
            "color": "red", "nodes_needed": None, "fits_on": [],
            "need_gb_1": round(weights_gb + safety_gb, 2),
            "need_gb_split": None,
            "reason": "no online nodes",
            "limit": "unknown",
            "runtime_stages": max_stages,
        }

    caps = [_node_capacity_gb(n) for n in nodes]
    order = sorted(range(len(nodes)), key=lambda i: caps[i], reverse=True)
    caps_sorted = [caps[i] for i in order]
    disks = [float((nodes[i].get("disk") or {}).get("free_gb") or 0) for i in order]
    labels = [_node_label(nodes[i], i) for i in order]
    n_count = len(caps_sorted)

    # Single-node setups cannot split.
    can_split = bool(split_ok) and n_count >= 2

    kv_full = 0.0
    if MG and cfg and n_layers:
        kv_full = MG.estimate_kv_gb(cfg, ctx_tokens, int(n_layers), kv_bits=kv_bits)
    else:
        kv_full = max(0.3, weights_gb * 0.08 * (ctx_tokens / 8192))

    need_1 = weights_gb + kv_full + safety_gb

    def need_each(k: int) -> float:
        return (weights_gb / k) + (kv_full / k) + safety_gb

    def disk_ok_for(k: int):
        share = weights_gb if k == 1 else weights_gb / k
        if k == 1:
            best = max(range(n_count), key=lambda i: disks[i])
            if disks[best] >= share * 0.95:
                return True, None
            return False, (
                f"Not enough disk on {labels[best]} "
                f"(need ~{share:.1f} GB, {disks[best]:.1f} GB free)"
            )
        for i in range(k):
            if disks[i] < share * 0.9:
                return False, (
                    f"Not enough disk on {labels[i]} "
                    f"(need ~{share:.1f} GB each, {labels[i]} has {disks[i]:.1f} GB free)"
                )
        return True, None

    fits_on = []
    disk_block = None
    if caps_sorted[0] >= need_1:
        ok, why = disk_ok_for(1)
        if ok:
            fits_on.append(1)
        else:
            disk_block = why

    if can_split:
        for k in range(2, n_count + 1):
            share_need = need_each(k)
            if all(a >= share_need for a in caps_sorted[:k]):
                ok, why = disk_ok_for(k)
                if ok:
                    fits_on.append(k)
                elif disk_block is None:
                    disk_block = why
            elif (
                k not in fits_on
                and all(a >= share_need * 0.85 for a in caps_sorted[:k])
                and caps_sorted[0] >= share_need * 0.9
            ):
                # Tight but plausible — record as fit with tight flag later
                ok, why = disk_ok_for(k)
                if ok:
                    fits_on.append(k)
                elif disk_block is None:
                    disk_block = why

    # Runtime note when fit wants more stages than mlx_split supports today.
    def runtime_note(k: int) -> str:
        if k <= max_stages:
            return ""
        return f" ({k}-Mini split coming later; runtime loads on {max_stages} today)"

    limit = "ram"
    need_split_each = need_each(2) if n_count >= 2 else None

    if 1 in fits_on:
        margin = caps_sorted[0] - need_1
        if can_split and margin < max(2.5, safety_gb * 1.25):
            color, needed = "yellow", 1
            k2 = 2 if 2 in fits_on else (min(fits_on) if fits_on else 2)
            reason = (
                f"Tight on 1 Mini (~{need_1:.0f} GB RAM; capacity ~{caps_sorted[0]:.0f} GB). "
                f"Fits on {k2}, about {need_each(k2):.0f} GB each"
                + runtime_note(k2)
            )
        else:
            color, needed = "green", 1
            reason = f"Fits on 1 Mini (~{need_1:.0f} GB RAM; capacity ~{caps_sorted[0]:.0f} GB)"
    elif fits_on:
        color, needed = "yellow", min(fits_on)
        ne = need_each(needed)
        # capacity of the poorest of the top-needed
        poor = caps_sorted[needed - 1]
        reason = (
            f"Fits on {needed} Minis, about {ne:.0f} GB RAM each "
            f"(capacity ~{poor:.0f} GB)"
            + runtime_note(needed)
        )
    elif disk_block and (
        caps_sorted[0] >= need_1
        or (can_split and all(a >= need_each(2) for a in caps_sorted[:2]))
    ):
        color, needed = "red", None
        reason = disk_block
        limit = "disk"
    elif can_split:
        # Find largest k that is "almost" — already handled; otherwise red.
        color, needed = "red", None
        # Suggest smallest k that would be needed by RAM alone
        suggest = None
        for k in range(1, n_count + 1):
            if k == 1 and caps_sorted[0] >= need_1:
                suggest = 1
                break
            if k >= 2 and all(a >= need_each(k) for a in caps_sorted[:k]):
                suggest = k
                break
        if suggest is None:
            # compare against full split across all online
            k = n_count
            reason = (
                f"Won't fit: need ~{need_1:.0f} GB RAM on 1 Mini "
                f"(capacity ~{caps_sorted[0]:.0f} GB)"
            )
            if can_split:
                reason += f" or ~{need_each(min(2, n_count)):.0f} GB ×{min(2, n_count)}"
                if n_count > 2:
                    reason += f" (or ~{need_each(n_count):.0f} GB ×{n_count})"
        else:
            reason = f"Won't fit on available capacity (wanted {suggest} Minis)"
    else:
        # Single node — never mention split
        color, needed = "red", None
        reason = (
            f"Won't fit on {labels[0]}: need ~{need_1:.0f} GB RAM "
            f"(capacity ~{caps_sorted[0]:.0f} GB)"
        )
        if disk_block:
            reason = disk_block
            limit = "disk"

    return {
        "color": color,
        "nodes_needed": needed,
        "fits_on": fits_on,
        "need_gb_1": round(need_1, 2),
        "need_gb_split": round(need_split_each, 2) if need_split_each is not None else None,
        "weights_gb": round(weights_gb, 2),
        "kv_gb_1": round(kv_full, 2),
        "reason": reason,
        "limit": limit,
        "capacity_gb": caps_sorted,
        "capacity_labels": labels,
        "online_nodes": n_count,
        "runtime_stages": max_stages,
        "disk_ok": disk_block is None and (
            max(disks) >= weights_gb * 0.9 if disks else False
        ),
        "disk_reason": disk_block,
    }



def _hf_search(query: str, *, author: Optional[str] = None, filter_gguf: bool = False,
               pipeline_tag: Optional[str] = None, limit: int = 40,
               sort: str = "downloads") -> list:
    q = {
        "search": query or "",
        "limit": str(limit),
        "full": "true",
        "config": "true",
        "sort": sort,
        "direction": "-1",
    }
    if author:
        q["author"] = author
    if filter_gguf:
        q["filter"] = "gguf"
    if pipeline_tag:
        q["pipeline_tag"] = pipeline_tag
    url = HF_API + "?" + urllib.parse.urlencode(q)
    try:
        data = _http_json(url)
    except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, ValueError) as e:
        return [{"error": f"hf search failed: {e}"}]
    if not isinstance(data, list):
        return []
    return data


def _sibling_weight_bytes(model: dict) -> int:
    total = 0
    for s in model.get("siblings") or []:
        name = (s.get("rfilename") or "")
        if name.endswith((".safetensors", ".gguf", ".npz", ".bin", ".pt")):
            total += int(s.get("size") or 0)
    return total


def _index_total_size(repo_id: str) -> int:
    """metadata.total_size from model.safetensors.index.json (reliable fallback)."""
    key = f"idxsize:{repo_id}"
    hit = _cache_get(key)
    if hit is not None:
        return int(hit)
    url = f"https://huggingface.co/{repo_id}/resolve/main/model.safetensors.index.json"
    total = 0
    try:
        data = _http_json(url, timeout=20)
        if isinstance(data, dict):
            total = int((data.get("metadata") or {}).get("total_size") or 0)
    except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, ValueError, TypeError):
        total = 0
    _cache_set(key, total)
    return total


def _fetch_repo_blobs(repo_id: str) -> dict:
    """Return {usedStorage, siblings, weight_bytes, gguf_files, size_source}."""
    key = f"blobs:{repo_id}"
    hit = _cache_get(key)
    if hit is not None:
        return hit
    url = f"https://huggingface.co/api/models/{repo_id}?blobs=true"
    out = {"usedStorage": 0, "siblings": [], "weight_bytes": 0, "gguf_files": [], "size_source": None}
    try:
        data = _http_json(url, timeout=20)
    except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, ValueError):
        data = None
    if isinstance(data, dict):
        sibs = data.get("siblings") or []
        weight = 0
        gguf = []
        for s in sibs:
            name = s.get("rfilename") or ""
            size = int(s.get("size") or 0)
            if name.endswith((".safetensors", ".npz", ".bin", ".pt")):
                weight += size
            if name.endswith(".gguf"):
                gguf.append({"rfilename": name, "size": size})
                weight += size
        used = int(data.get("usedStorage") or 0)
        src = "hf-blobs" if weight or used else None
        if not weight and used:
            weight = used
        out = {
            "usedStorage": used,
            "siblings": sibs,
            "weight_bytes": weight,
            "gguf_files": gguf,
            "size_source": src,
        }
    # Fallback: index metadata.total_size (e.g. Qwen3.8-Flash-Next = 111.5 GB)
    if not out.get("weight_bytes"):
        total = _index_total_size(repo_id)
        if total > 0:
            out["weight_bytes"] = total
            out["usedStorage"] = out.get("usedStorage") or total
            out["size_source"] = "index-total_size"
    _cache_set(key, out)
    return out


def _enrich_sizes(rows: list) -> list:
    """Fill weights_gb from HF blobs=true in parallel. Expand multi-GGUF repos."""
    if not rows:
        return rows
    repos = sorted({r["repo_id"] for r in rows if r.get("repo_id") and not r.get("cloud")})
    blobs: dict = {}
    if repos:
        with ThreadPoolExecutor(max_workers=min(12, max(1, len(repos)))) as pool:
            futs = {pool.submit(_fetch_repo_blobs, rid): rid for rid in repos}
            for fut in as_completed(futs):
                rid = futs[fut]
                try:
                    blobs[rid] = fut.result()
                except Exception:
                    blobs[rid] = {"weight_bytes": 0, "gguf_files": [], "usedStorage": 0}

    out = []
    for r in rows:
        if r.get("cloud"):
            out.append(r)
            continue
        rid = r["repo_id"]
        info = blobs.get(rid) or {}
        gguf_files = info.get("gguf_files") or []
        # Multi-file GGUF repo → one row per quant file with its real size.
        if r.get("source") == "gguf" and len(gguf_files) >= 2:
            for gf in gguf_files:
                fname = gf["rfilename"]
                size = int(gf.get("size") or 0)
                quant = _parse_quant(fname) or _parse_quant(rid)
                # skip tiny non-weight shards
                if size and size < 50_000_000:
                    continue
                rr = dict(r)
                rr["name"] = fname
                rr["quant"] = quant
                rr["gguf_file"] = fname
                rr["weights_gb"] = round(size / 1e9, 2) if size else None
                rr["size_source"] = "gguf-file" if size else None
                rr["base"] = _base_name(rid.replace("-GGUF", "").replace("_GGUF", ""))
                out.append(rr)
            continue
        wb = int(info.get("weight_bytes") or 0)
        if not wb and len(gguf_files) == 1:
            wb = int(gguf_files[0].get("size") or 0)
            r = dict(r)
            r["gguf_file"] = gguf_files[0]["rfilename"]
        if not wb:
            wb = int(info.get("usedStorage") or 0)
        rr = dict(r)
        if wb > 0:
            rr["weights_gb"] = round(wb / 1e9, 2)
            rr["size_source"] = info.get("size_source") or "hf-blobs"
        elif rr.get("weights_gb"):
            rr["size_source"] = "estimate"
        else:
            rr["weights_gb"] = None
            rr["size_source"] = None
        out.append(rr)
    return out


def _normalize_hf_hit(m: dict, *, source: str) -> Optional[dict]:
    repo = m.get("id") or m.get("modelId")
    if not repo:
        return None
    tags = list(m.get("tags") or [])
    pipeline = m.get("pipeline_tag") or ""
    quant = _parse_quant(repo, tags)
    # Hide clearly non-convertible junk for MLX source
    if source == "hf-mlx":
        if "gguf" in tags or repo.lower().endswith(".gguf"):
            return None
        # Prefer mlx or safetensors
        libs = set((m.get("library_name") or "",) + tuple(tags))
        has_mlx = "mlx" in libs or "mlx-lm" in tags or "mlx" in repo.lower()
        has_st = any((s.get("rfilename") or "").endswith(".safetensors")
                     for s in (m.get("siblings") or []))
        convertible = has_mlx or has_st or "transformers" in libs or "pytorch" in tags
        if not convertible and "safetensors" not in tags:
            # still allow if downloads suggest weights
            if not m.get("siblings"):
                pass  # keep; size unknown
        needs_conversion = (not has_mlx) and convertible
        if not has_mlx and not convertible:
            return None
    else:
        needs_conversion = False
        has_mlx = False

    params = None
    cfg = m.get("config") or {}
    if isinstance(cfg, dict):
        for k in ("num_parameters", "n_params"):
            if cfg.get(k):
                params = float(cfg[k]) / 1e9
                break
    sb = _sibling_weight_bytes(m)
    # safetensors.index sometimes only in siblings without sizes — ok
    weights = _estimate_weights_gb(params, quant, sb or None)
    return {
        "repo_id": repo,
        "name": repo.split("/")[-1],
        "base": _base_name(repo),
        "source": source,
        "quant": quant,
        "pipeline_tag": pipeline,
        "tags": tags[:40],
        "filters": _filters_for(pipeline, tags, repo),
        "likes": m.get("likes") or 0,
        "downloads": m.get("downloads") or 0,
        "created_at": m.get("createdAt") or m.get("created_at"),
        "last_modified": m.get("lastModified") or m.get("last_modified"),
        "weights_gb": round(weights, 2) if weights else None,
        "needs_conversion": needs_conversion,
        "cloud": False,
        "gguf_split_hook": source == "gguf",  # llama.cpp RPC split (Day 17)
    }


def _parse_hf_time(s) -> float:
    if not s:
        return 0.0
    try:
        # 2025-10-01T12:00:00.000Z
        from datetime import datetime, timezone
        ss = str(s).replace("Z", "+00:00")
        return datetime.fromisoformat(ss).timestamp()
    except Exception:
        return 0.0


def search_catalog(query: str = "", *, source: str = "all", limit: int = 30,
                  filt: str = "", newer: bool = False) -> dict:
    """Search HF. source: all|hf-mlx|gguf|cloud. filt: chat|coding|new|… chip."""
    filt = (filt or "").strip().lower()
    if filt == "new":
        newer = True
        filt_key = ""
    elif filt in ("fits-on-1", "fits-on-2", ""):
        filt_key = ""
    else:
        filt_key = filt
    key = f"search:{source}:{query}:{limit}:{filt_key}:new={int(bool(newer))}"
    hit = _cache_get(key)
    if hit is not None:
        return hit

    rows = []
    errors = []
    q = (query or "").strip()
    sort = "createdAt" if newer else "downloads"

    def _search(term, **kw):
        kw.setdefault("sort", sort)
        return _hf_search(term, **kw)


    def _ingest(raw, src, extra_filters=None):
        if raw and isinstance(raw[0], dict) and raw[0].get("error"):
            errors.append(raw[0]["error"])
            return
        for m in raw or []:
            if src == "gguf":
                m = dict(m)
                tags = list(m.get("tags") or [])
                if "gguf" not in tags:
                    tags.append("gguf")
                m["tags"] = tags
            n = _normalize_hf_hit(m, source=src)
            if not n:
                continue
            if extra_filters:
                n["filters"] = sorted(set(n["filters"] + list(extra_filters)))
            rows.append(n)

    # Cloud chip / cloud source — static labeled list.
    if source == "cloud" or filt_key == "cloud":
        for c in _OLLAMA_CLOUD:
            filters = ["cloud"]
            note = (c.get("note") or "").lower()
            if "coding" in note:
                filters.append("coding")
            else:
                filters.append("chat")
            rows.append({
                "repo_id": f"ollama-cloud/{c['id']}",
                "name": c["name"],
                "base": c["name"],
                "source": "cloud",
                "quant": None,
                "pipeline_tag": "text-generation",
                "tags": ["cloud", "ollama-cloud"],
                "filters": filters,
                "likes": 0,
                "downloads": 0,
                "weights_gb": None,
                "needs_conversion": False,
                "cloud": True,
                "cloud_label": "CLOUD",
                "api_key_configured": bool(OLLAMA_API_KEY),
                "note": c.get("note") or "Ollama Cloud · framework only",
            })
        # cloud-only short-circuit
        source = "cloud"

    elif filt_key in _FILTER_SEARCH and source in ("all", "hf-mlx", "gguf", "ollama"):
        spec = _FILTER_SEARCH[filt_key]
        want_mlx = source in ("all", "hf-mlx")
        want_gguf = source in ("all", "gguf", "ollama")
        if want_mlx:
            for term in spec.get("mlx_search") or [q or ""]:
                term = (q + " " + term).strip() if q else term
                raw = _search(term, author="mlx-community", limit=max(12, limit // 2))
                _ingest(raw, "hf-mlx", extra_filters=[filt_key])
            for ptag in ([spec["pipeline_tag"]] if spec.get("pipeline_tag") else []) + list(spec.get("pipeline_tags") or []):
                raw = _search(q or "", pipeline_tag=ptag, limit=max(8, limit // 3))
                _ingest(raw, "hf-mlx", extra_filters=[filt_key])
            if not rows:
                for term in spec.get("hf_search") or []:
                    raw = _search((q + " " + term).strip() if q else term, limit=max(10, limit // 2))
                    _ingest(raw, "hf-mlx", extra_filters=[filt_key])
        if want_gguf and filt_key in ("chat", "coding", "reasoning", "vision"):
            gq = q or (spec.get("mlx_search") or ["Instruct"])[0]
            for author in ("bartowski", "unsloth", "lmstudio-community"):
                raw = _search(gq, author=author, filter_gguf=True, limit=max(6, limit // 4))
                _ingest(raw, "gguf", extra_filters=[filt_key, "chat"])
        if filt_key == "image-to-image":
            raw = _search(q or "", pipeline_tag="image-to-image", limit=limit)
            _ingest(raw, "hf-mlx", extra_filters=["image-to-image"])
        if filt_key == "voice":
            for ptag in ("automatic-speech-recognition", "text-to-speech"):
                raw = _search(q or "whisper", pipeline_tag=ptag, limit=max(8, limit // 2))
                _ingest(raw, "hf-mlx", extra_filters=["voice"])

    else:
        # Default / free-text search
        if source in ("all", "hf-mlx"):
            for author, lim in (("mlx-community", limit), (None, max(10, limit // 2))):
                qq = q if author else (q or "instruct")
                raw = _search(qq, author=author, limit=lim)
                _ingest(raw, "hf-mlx")
                if author == "mlx-community" and rows:
                    break
        if source in ("all", "gguf", "ollama"):
            for author in ("bartowski", "unsloth", "lmstudio-community"):
                raw = _search(q or "Instruct", author=author, filter_gguf=True,
                                 limit=max(8, limit // 3))
                _ingest(raw, "gguf", extra_filters=["chat"])
        if source in ("all", "cloud") and not filt_key:
            for c in _OLLAMA_CLOUD[:3]:
                rows.append({
                    "repo_id": f"ollama-cloud/{c['id']}",
                    "name": c["name"],
                    "base": c["name"],
                    "source": "cloud",
                    "quant": None,
                    "pipeline_tag": "text-generation",
                    "tags": ["cloud", "ollama-cloud"],
                    "filters": ["cloud", "chat"],
                    "likes": 0,
                    "downloads": 0,
                    "weights_gb": None,
                    "needs_conversion": False,
                    "cloud": True,
                    "cloud_label": "CLOUD",
                    "api_key_configured": bool(OLLAMA_API_KEY),
                    "note": c.get("note") or "Ollama Cloud · framework only",
                })

    # Real sizes (blobs=true, index total_size fallback). No 4 GB guess.
    rows = _enrich_sizes(rows)

    if newer:
        import time as _time
        cutoff = _time.time() - NEW_MODEL_DAYS * 86400
        kept = []
        for r in rows:
            ts = _parse_hf_time(r.get("created_at")) or _parse_hf_time(r.get("last_modified"))
            if ts >= cutoff or r.get("cloud"):
                r = dict(r)
                if "new" not in (r.get("filters") or []):
                    r["filters"] = list(r.get("filters") or []) + ["new"]
                kept.append(r)
        rows = kept

    # Dedupe — prefer rows with size / more specific quant file
    seen = set()
    uniq = []
    for r in rows:
        key_id = r.get("gguf_file") or r["repo_id"]
        if key_id in seen:
            continue
        seen.add(key_id)
        if filt_key and filt_key not in (r.get("filters") or []) and not r.get("cloud"):
            # keep if name keys match
            name = (r.get("repo_id") or "").lower() + " " + (r.get("name") or "").lower()
            keys = (_FILTER_SEARCH.get(filt_key) or {}).get("name_keys") or ()
            if keys and not any(k in name for k in keys):
                if filt_key not in (r.get("pipeline_tag") or "",):
                    # still keep pipeline-matched voice/i2i already tagged
                    if filt_key not in (r.get("filters") or []):
                        continue
        uniq.append(r)

    groups: dict = {}
    for r in uniq:
        groups.setdefault(r["base"], []).append(r)
    grouped = []
    for base, quants in groups.items():
        quants.sort(key=lambda x: (_bits_of_quant(x.get("quant")), x.get("weights_gb") or 0, x["repo_id"]))
        filters = sorted({f for q in quants for f in q.get("filters") or []})
        sizes = [q.get("weights_gb") for q in quants if q.get("weights_gb")]
        grouped.append({
            "base": base,
            "source": quants[0]["source"],
            "filters": filters,
            "cloud": any(q.get("cloud") for q in quants),
            "quants": quants,
            "likes": max(q.get("likes") or 0 for q in quants),
            "size_gb_min": min(sizes) if sizes else None,
            "size_gb_max": max(sizes) if sizes else None,
        })
    def _src_rank(g):
        s = g.get("source") or ""
        if s == "hf-mlx":
            return 0
        if s == "cloud":
            return 2
        return 1  # gguf
    def _newest(g):
        times = []
        for q in g.get("quants") or []:
            times.append(_parse_hf_time(q.get("created_at")) or _parse_hf_time(q.get("last_modified")))
        return max(times) if times else 0.0
    if newer:
        grouped.sort(key=lambda g: (-_newest(g), _src_rank(g), g["base"].lower()))
    else:
        grouped.sort(key=lambda g: (_src_rank(g), -g["likes"], g["base"].lower()))

    out = {
        "query": q,
        "source": source,
        "filter": filt_key,
        "newer": bool(newer),
        "groups": grouped[: max(limit, 1)],
        "errors": errors,
        "gguf_catalog": "huggingface (bartowski / unsloth / lmstudio-community)",
        "cached": False,
    }
    _cache_set(key, {**out, "cached": True})
    return out


def attach_fit(groups: list, nodes: list) -> list:
    out = []
    for g in groups:
        quants = []
        for q in g.get("quants") or []:
            qq = dict(q)
            if qq.get("cloud"):
                qq["fit"] = {
                    "color": "green", "nodes_needed": 0, "fits_on": [],
                    "reason": "cloud — token usage, not node RAM",
                    "weights_gb": None,
                }
            elif not qq.get("weights_gb"):
                qq["fit"] = {
                    "color": "gray", "nodes_needed": None, "fits_on": [],
                    "reason": "size unknown — not marked OK",
                    "weights_gb": None,
                }
            else:
                w = float(qq["weights_gb"])
                gguf = qq.get("source") == "gguf"
                split_ok = qq.get("source") == "hf-mlx" or gguf
                qq["fit"] = fit_check(
                    weights_gb=w, nodes=nodes, split_ok=split_ok,
                    safety_gb=DEFAULT_SAFETY_GB,
                    # llama.cpp RPC splits across any number of Minis.
                    max_split_stages=(max(len(nodes), 1) if gguf else MAX_SPLIT_STAGES),
                )
            quants.append(qq)
        gg = dict(g)
        gg["quants"] = quants
        # best color: green > yellow > gray > red
        order = {"green": 0, "yellow": 1, "gray": 2, "red": 3}
        colors = [q["fit"]["color"] for q in quants if q.get("fit")]
        gg["fit_color"] = min(colors, key=lambda c: order.get(c, 9)) if colors else "gray"
        sizes = [q.get("weights_gb") for q in quants if q.get("weights_gb")]
        gg["size_gb_min"] = min(sizes) if sizes else None
        gg["size_gb_max"] = max(sizes) if sizes else None
        out.append(gg)
    return out


def _dir_size_gb(path: Path) -> float:
    total = 0
    try:
        for root, _dirs, files in os.walk(path):
            for f in files:
                try:
                    total += (Path(root) / f).stat().st_size
                except OSError:
                    pass
    except OSError:
        return 0.0
    return total / 1e9


def list_installed(*, packer_sizes: Optional[dict] = None) -> list:
    """Models on this Mini's disk. packer_sizes maps repo_folder -> gb on EXO2."""
    packer_sizes = packer_sizes or {}
    found = {}
    for root in MLX_MODEL_ROOTS:
        if not root.is_dir():
            continue
        for p in root.iterdir():
            if not p.is_dir():
                continue
            if p.name == "drafts":
                continue  # shown as cleanup row
            key = p.name
            repo = key.replace("--", "/")
            e = found.setdefault(repo, {
                "id": repo,
                "name": repo.split("/")[-1],
                "source": "hf-mlx",
                "paths": {},
                "size_gb": {},
            })
            e["paths"]["lead"] = str(p)
            e["size_gb"]["lead"] = round(_dir_size_gb(p), 2)
    for root in GGUF_ROOTS:
        if not root.is_dir():
            continue
        for p in root.rglob("*.gguf"):
            repo = f"gguf/{p.stem}"
            e = found.setdefault(repo, {
                "id": repo,
                "name": p.name,
                "source": "gguf",
                "paths": {},
                "size_gb": {},
            })
            e["paths"]["lead"] = str(p)
            e["size_gb"]["lead"] = round(p.stat().st_size / 1e9, 2)
    for repo, gb in packer_sizes.items():
        e = found.setdefault(repo, {
            "id": repo, "name": repo.split("/")[-1], "source": "hf-mlx",
            "paths": {}, "size_gb": {},
        })
        e["size_gb"]["packer"] = round(float(gb), 2)
    return sorted(found.values(), key=lambda x: x["name"].lower())


def delete_model(repo_or_path: str, *, current_model_id: Optional[str],
                 ssh_delete: Optional[callable] = None) -> dict:
    """Delete from ALL Minis. Refuses if currently loaded."""
    rid = (repo_or_path or "").strip()
    if not rid:
        return {"ok": False, "error": "missing id"}
    cur = (current_model_id or "").lower()
    folder = rid.replace("/", "--")
    if cur and (cur == rid.lower() or cur in rid.lower() or folder.lower() in cur):
        return {"ok": False, "error": "refuse: model is currently loaded"}
    removed = []
    for root in MLX_MODEL_ROOTS:
        p = root / folder
        if p.is_dir():
            shutil.rmtree(p)
            removed.append(str(p))
    # loose path
    ep = Path(rid).expanduser()
    if ep.is_dir() and ("mlx-models" in str(ep) or "exo/models" in str(ep)):
        shutil.rmtree(ep)
        removed.append(str(ep))
    remote = None
    if ssh_delete:
        try:
            remote = ssh_delete(folder)
        except Exception as e:  # noqa: BLE001
            remote = {"error": str(e)}
    if not removed and not (isinstance(remote, dict) and remote.get("removed")):
        return {"ok": False, "error": "not found on disk", "remote": remote}
    return {"ok": True, "removed": removed, "remote": remote}



def _path_size_gb(path: Path) -> float:
    if not path.exists():
        return 0.0
    if path.is_file():
        try:
            return path.stat().st_size / 1e9
        except OSError:
            return 0.0
    return _dir_size_gb(path)


def list_cleanup_targets(*, packer: Optional[dict] = None,
                         current_model_id: Optional[str] = None) -> list:
    """Special on-disk rows: HF download cache + guess-ahead drafts."""
    packer = packer or {}
    cur = (current_model_id or "").lower()
    hub = Path("~/.cache/huggingface/hub").expanduser()
    drafts = Path("~/.caravan/mlx-models/drafts").expanduser()
    # Leftover per-model .cache/huggingface under mlx-models (exclude drafts + loaded)
    leftover = 0.0
    for root in MLX_MODEL_ROOTS:
        if not root.is_dir():
            continue
        for p in root.iterdir():
            if not p.is_dir() or p.name == "drafts":
                continue
            repo = p.name.replace("--", "/").lower()
            if cur and (cur in repo or repo in cur or p.name.lower() in cur):
                continue
            c = p / ".cache" / "huggingface"
            if c.is_dir():
                leftover += _path_size_gb(c)
    lead_hub = round(_path_size_gb(hub) + leftover, 2)
    rows = [
        {
            "id": "cleanup:hf-cache",
            "kind": "hf-cache",
            "name": "Download cache (Hugging Face)",
            "note": "Hub cache plus leftover .cache folders under mlx-models (skips the loaded model)",
            "size_gb": {
                "lead": lead_hub,
                "packer": packer.get("hf-cache"),
            },
            "deletable": True,
        },
        {
            "id": "cleanup:drafts",
            "kind": "drafts",
            "name": "Guess-ahead helper models",
            "note": "Small drafts under mlx-models/drafts — guess-ahead re-downloads when needed",
            "size_gb": {
                "lead": round(_path_size_gb(drafts), 2),
                "packer": packer.get("drafts"),
            },
            "deletable": True,
        },
    ]
    return rows


def delete_cleanup(kind: str, *, current_model_id: Optional[str] = None,
                   ssh_cleanup: Optional[callable] = None) -> dict:
    """Delete HF hub cache or drafts on all Minis. Never touches the loaded model."""
    kind = (kind or "").strip().lower().replace("cleanup:", "")
    cur = (current_model_id or "").lower()
    removed = []
    if kind in ("hf-cache", "hf_cache", "cache"):
        hub = Path("~/.cache/huggingface/hub").expanduser()
        if hub.is_dir():
            # Remove model blobs except anything matching the loaded id.
            for p in list(hub.iterdir()):
                name = p.name.lower()
                if cur and cur.replace("/", "--") in name:
                    continue
                if p.is_dir():
                    shutil.rmtree(p, ignore_errors=True)
                    removed.append(str(p))
                elif p.is_file() and p.name != "CACHEDIR.TAG":
                    try:
                        p.unlink()
                        removed.append(str(p))
                    except OSError:
                        pass
        # leftover .cache under mlx-models (not the loaded model, not drafts)
        for root in MLX_MODEL_ROOTS:
            if not root.is_dir():
                continue
            for p in root.iterdir():
                if not p.is_dir() or p.name == "drafts":
                    continue
                repo = p.name.replace("--", "/").lower()
                if cur and (cur in repo or repo in cur or p.name.lower() in cur):
                    continue
                c = p / ".cache"
                if c.is_dir():
                    shutil.rmtree(c, ignore_errors=True)
                    removed.append(str(c))
    elif kind == "drafts":
        drafts = Path("~/.caravan/mlx-models/drafts").expanduser()
        if drafts.is_dir():
            for p in list(drafts.iterdir()):
                if p.is_dir():
                    shutil.rmtree(p, ignore_errors=True)
                    removed.append(str(p))
                elif p.is_file():
                    try:
                        p.unlink(); removed.append(str(p))
                    except OSError:
                        pass
    else:
        return {"ok": False, "error": f"unknown cleanup kind: {kind}"}

    remote = None
    if ssh_cleanup:
        try:
            remote = ssh_cleanup(kind)
        except Exception as e:  # noqa: BLE001
            remote = {"error": str(e)}
    return {"ok": True, "kind": kind, "removed": removed, "remote": remote}


# ---- download jobs (phase 2) --------------------------------------------
_jobs_lock = threading.Lock()
_jobs: dict = {}


def _job_set(jid: str, **kw):
    with _jobs_lock:
        j = _jobs.setdefault(jid, {"id": jid, "t": time.time()})
        j.update(kw)
        j["updated"] = time.time()
        return dict(j)


def get_job(jid: str) -> Optional[dict]:
    with _jobs_lock:
        j = _jobs.get(jid)
        return dict(j) if j else None


def list_jobs() -> list:
    with _jobs_lock:
        return [dict(j) for j in _jobs.values()]


def measure_download_bytes(dest: str) -> dict:
    """Bytes on disk for a local_dir download: finished shards + .incomplete (+ xet)."""
    try:
        from download_progress import measure_disk
        return measure_disk(dest)
    except Exception:
        dest_p = Path(dest).expanduser()
        return {"done_bytes": 0, "incomplete_bytes": 0, "have_bytes": 0, "n_incomplete": 0,
                "source": "disk"} if not dest_p.exists() else {"done_bytes": 0, "incomplete_bytes": 0,
                "have_bytes": 0, "n_incomplete": 0, "source": "disk"}


def _fmt_eta(seconds: Optional[float]) -> str:
    try:
        from download_progress import fmt_eta
        return fmt_eta(seconds)
    except Exception:
        if seconds is None or seconds < 0 or seconds != seconds:  # noqa: PLR0124
            return "—"
        seconds = int(seconds)
        if seconds < 60:
            return f"{seconds}s"
        if seconds < 3600:
            return f"{seconds // 60}m {seconds % 60}s"
        return f"{seconds // 3600}h {(seconds % 3600) // 60}m"


def progress_snapshot(dest: str, total_bytes: Optional[int], prev: Optional[dict] = None,
                      *, repo_id: Optional[str] = None, pid: Optional[int] = None) -> dict:
    """Truthful progress: hook → disk → nettop (hf_xet-safe)."""
    try:
        from download_progress import combine_progress
        return combine_progress(
            dest=dest or "",
            repo_id=repo_id or Path(dest or ".").name.replace("--", "/"),
            total_bytes=total_bytes,
            pid=pid,
            prev=prev,
        )
    except Exception as e:  # noqa: BLE001
        return {"pct": 0, "msg": f"progress error: {e}", "have_bytes": 0, "t": time.time(),
                "source": "starting", "stalled": False}


def kill_local_fetch(repo_id: str) -> dict:
    """SIGTERM/SIGKILL any local mlx_split_fetch for this repo."""
    import subprocess
    pattern = f"mlx_split_fetch.py {repo_id}"
    killed = []
    try:
        r = subprocess.run(["pgrep", "-f", pattern], capture_output=True, text=True)
        pids = [p.strip() for p in (r.stdout or "").splitlines() if p.strip()]
        for pid in pids:
            try:
                subprocess.run(["kill", "-TERM", pid], check=False)
                killed.append(pid)
            except OSError:
                pass
        if pids:
            time.sleep(0.6)
            r2 = subprocess.run(["pgrep", "-f", pattern], capture_output=True, text=True)
            left = [p.strip() for p in (r2.stdout or "").splitlines() if p.strip()]
            for pid in left:
                subprocess.run(["kill", "-KILL", pid], check=False)
                if pid not in killed:
                    killed.append(pid)
    except OSError as e:
        return {"ok": False, "error": str(e), "killed": killed}
    return {"ok": True, "killed": killed, "pattern": pattern}


def cancel_job(jid: str, *, kill_procs: Optional[callable] = None) -> dict:
    """Mark cancelled and kill fetch processes (lead + packer)."""
    with _jobs_lock:
        j = _jobs.get(jid)
        if not j:
            return {"ok": False, "error": "unknown job"}
        j["cancel"] = True
        j["status"] = "cancelling"
        repo = j.get("repo_id")
        job = dict(j)
    killed = {"lead": None, "packer": None}
    # Kill any tracked local Popen
    proc = job.get("lead_proc")
    if proc is not None:
        try:
            proc.terminate()
        except Exception:
            pass
    if repo:
        killed["lead"] = kill_local_fetch(repo)
    if kill_procs:
        try:
            killed["packer"] = kill_procs(repo, job)
        except Exception as e:  # noqa: BLE001
            killed["packer"] = {"ok": False, "error": str(e)}
    _job_set(jid, status="cancelled", error="stopped by user", kill=killed)
    return {"ok": True, "job": get_job(jid), "killed": killed}


def stop_jobs_for_repo(repo_id: str, *, kill_procs: Optional[callable] = None) -> list:
    """Cancel every active job for repo_id (used by Delete)."""
    rid = (repo_id or "").strip()
    out = []
    for j in list_jobs():
        if (j.get("repo_id") or "") != rid:
            continue
        if j.get("status") in ("queued", "running", "cancelling"):
            out.append(cancel_job(j["id"], kill_procs=kill_procs))
    # Even with no job record (e.g. web UI restarted), kill stray fetches.
    if rid:
        stray = kill_local_fetch(rid)
        if kill_procs:
            try:
                stray_p = kill_procs(rid, {"repo_id": rid})
            except Exception as e:  # noqa: BLE001
                stray_p = {"ok": False, "error": str(e)}
        else:
            stray_p = None
        out.append({"stray_lead": stray, "stray_packer": stray_p})
    return out


def monotonic_snap(prev: dict, snap: dict) -> dict:
    """Progress never goes backwards: have_bytes and pct only grow (pct < 100 until done)."""
    out = dict(snap)
    ph = int((prev or {}).get("have_bytes") or 0)
    if int(out.get("have_bytes") or 0) < ph:
        out["have_bytes"] = ph
    pp = int((prev or {}).get("pct") or 0)
    pct = int(out.get("pct") or 0)
    tot = int(out.get("total_bytes") or (prev or {}).get("total_bytes") or 0)
    if tot and out.get("have_bytes"):
        pct = max(pct, min(99, int(int(out["have_bytes"]) * 100 / tot)))
    out["pct"] = max(0, min(99, max(pct, pp if pp < 100 else 99)))
    if tot:
        out["total_bytes"] = tot
    return out


RETRY_MAX = 3
RETRY_BACKOFF_S = (5, 15, 45)
_NET_ERR_WORDS = ("timed out", "timeout", "connection", "reset by peer", "temporarily",
                  "incompleteread", "remote end closed", "502", "503", "504", "429",
                  "network", "ssl", "eof occurred", "name resolution", "broken pipe")


def is_network_error(e) -> bool:
    """Retry only transport-ish failures; auth/404/disk errors fail at once."""
    s = str(e).lower()
    if any(w in s for w in ("401", "403", "404", "gated", "unauthorized", "no space", "cancelled")):
        return False
    return any(w in s for w in _NET_ERR_WORDS)


def _sleep_unless_cancel(jid: str, secs: float) -> bool:
    end = time.time() + secs
    while time.time() < end:
        if (get_job(jid) or {}).get("cancel"):
            return True
        time.sleep(0.5)
    return False


def accumulate_net(prev: Optional[dict], net_raw) -> int:
    """Monotonic network byte count from nettop's per-process sum.

    nettop only sums open flows, so the raw number drops whenever a connection
    closes (Nov 6: 969 MB -> 836 MB mid-download). Add positive deltas only.
    """
    acc = int((prev or {}).get("net_acc") or 0)
    last = (prev or {}).get("net_last")
    if net_raw is None:
        return acc
    net_raw = int(net_raw)
    if last is None:
        return acc + net_raw  # first reading for this process: all of it is new
    return acc + max(0, net_raw - int(last))


def apply_reported_total(repo_id: str, node_id: str, line: str) -> Optional[int]:
    """Day 18: the fetcher's first line says what THIS Mini really downloads
    ({"my_gb": ...}, every shard including shared ones). Use it as the Mini's
    total so progress can't read 17.62/11.77 GB."""
    try:
        rep = json.loads((line or "").strip())
        tb = int(float(rep["my_gb"]) * 1e9)
    except (ValueError, TypeError, KeyError, AttributeError):
        return None
    if tb <= 0:
        return None
    for j in list_jobs():
        if j.get("repo_id") == repo_id and j.get("status") in ("running", "queued"):
            totals = dict(j.get("totals") or {})
            if totals.get(node_id) != tb:
                totals[node_id] = tb
                _job_set(j["id"], totals=totals)
            return tb
    return None


def start_download(repo_id: str, *, role_plan: Optional[dict] = None,
                   packer_layers: Optional[int] = None,
                   dest_lead: Optional[str] = None,
                   dest_packer: Optional[str] = None,
                   run_lead: Optional[callable] = None,
                   run_packer: Optional[callable] = None,
                   total_bytes_lead: Optional[int] = None,
                   total_bytes_packer: Optional[int] = None,
                   measure_packer: Optional[callable] = None,
                   runners: Optional[list] = None,
                   note: Optional[str] = None,
                   placement: Optional[dict] = None) -> dict:
    """Start async download across one or more nodes in PARALLEL.

    Prefer `runners`: list of dicts
      {id, label, role, dest, run(repo, dest, packer_layers, prog), measure?, total_bytes?}
    Legacy run_lead/run_packer still work for the 2-Mini default.
    """
    import uuid
    jid = uuid.uuid4().hex[:12]
    folder = repo_id.replace("/", "--")

    if not runners:
        runners = []
        dest_lead = dest_lead or str(MLX_MODEL_ROOTS[0] / folder)
        if run_lead:
            runners.append({
                "id": "lead", "label": "EXO1", "role": "lead",
                "dest": dest_lead, "run": run_lead,
                "total_bytes": total_bytes_lead, "measure": None,
            })
        dest_packer = dest_packer or f"~/.caravan/mlx-models/{folder}"
        if run_packer:
            runners.append({
                "id": "packer", "label": "EXO2", "role": "packer",
                "dest": dest_packer, "run": run_packer,
                "total_bytes": total_bytes_packer, "measure": measure_packer,
            })

    progress = {}
    for r in runners:
        rid = r.get("id") or r.get("label") or "node"
        progress[rid] = {"pct": 0, "msg": "starting…", "have_bytes": 0, "t": time.time(),
                         "label": r.get("label") or rid, "role": r.get("role"),
                         "source": "starting", "stalled": False}
        # legacy aliases
        if r.get("role") == "lead":
            progress.setdefault("lead", progress[rid])
        if r.get("role") == "packer" and "packer" not in progress:
            progress.setdefault("packer", progress[rid])

    _job_set(jid, status="queued", repo_id=repo_id, progress=progress,
             runners=[{"id": r.get("id"), "label": r.get("label"), "role": r.get("role"),
                       "dest": r.get("dest")} for r in runners],
             packer_layers=packer_layers, note=note or "",
             placement=placement or {},
             dest_lead=next((r["dest"] for r in runners if r.get("role") == "lead"), None),
             dest_packer=next((r["dest"] for r in runners if r.get("role") != "lead"), None),
             total_bytes_lead=total_bytes_lead, total_bytes_packer=total_bytes_packer)

    def _watch(role_id: str, dest: str, total_b: Optional[int], stop_evt: threading.Event,
               measure: Optional[callable] = None):
        prev = None
        while not stop_evt.wait(0.8):
            if get_job(jid) and get_job(jid).get("cancel"):
                break
            job_now = get_job(jid) or {}
            if measure:
                try:
                    m = measure() or {}
                    # Remote measure may already be a full progress snap (source/msg/stalled)
                    # Only a snapshot that already carries pct/msg is "full"; a raw remote
                    # measure ({have_bytes, source, ...}) must be folded for pct/speed/ETA.
                    if m.get("msg") is not None and m.get("pct") is not None:
                        snap = dict(m)
                        snap.setdefault("t", time.time())
                        if not snap.get("total_bytes") and total_b:
                            snap["total_bytes"] = int(total_b)
                    else:
                        # Raw have_bytes — fold through combine with prev for speed/stall
                        have = int(m.get("have_bytes") or 0)
                        net_acc = accumulate_net(prev, m.get("net_raw"))
                        disk0 = (prev or {}).get("disk0")
                        if disk0 is None:
                            disk0 = int(m.get("disk_have") or 0)  # already on disk (resume)
                        disk_now = int(m.get("disk_have") or 0)
                        # hf_xet buffers whole files: disk sits still while the network moves.
                        # Bytes = what was on disk at start + bytes received since, or disk if more.
                        have = max(have, disk_now, int(disk0) + net_acc)
                        n_inc = int(m.get("n_incomplete") or 0)
                        now = time.time()
                        speed = 0.0
                        if prev and prev.get("t") and prev.get("have_bytes") is not None:
                            dt = max(0.001, now - float(prev["t"]))
                            speed = max(0.0, (have - int(prev["have_bytes"])) / dt)
                        totals = job_now.get("totals") or {}
                        total = int(totals.get(role_id) or total_b or 0)
                        if total and have > total * 1.5:
                            # implausible counter (wrong process / scaled nettop): ignore it
                            have = int((prev or {}).get("have_bytes") or 0)
                        if total:
                            have = min(have, total)  # Day 18: never above this Mini's total
                        from download_progress import grew as _grew
                        last_byte_t = float((prev or {}).get("last_byte_t") or now)
                        if _grew(prev, have, disk_now, m.get("net_raw")):
                            last_byte_t = now
                        stalled = (have > 0 or (prev and prev.get("have_bytes"))) and (now - last_byte_t) >= 30
                        pct = 0
                        if total > 0 and have > 0:
                            pct = max(0, min(99, int(have * 100 / total)))
                        mb_s = speed / 1e6
                        eta_s = ((total - have) / speed) if (speed > 0 and total > have) else None
                        if have == 0:
                            msg = ("can't read progress: " + str(m["measure_error"])) if m.get("measure_error") else "starting…"
                            pct = 0
                        elif total:
                            msg = f"{have/1e9:.2f}/{total/1e9:.2f} GB · {mb_s:.1f} MB/s · ETA {_fmt_eta(eta_s)}"
                        else:
                            msg = f"{have/1e9:.2f} GB · {mb_s:.1f} MB/s"
                        if m.get("source") == "nettop":
                            msg += " · via network"
                        if n_inc:
                            msg += f" · {n_inc} active"
                        if stalled:
                            msg += " · stalled?"
                        snap = {
                            "pct": pct, "msg": msg, "have_bytes": have,
                            "total_bytes": total or None, "speed_bps": speed,
                            "mb_s": round(mb_s, 2),
                            "eta_s": None if eta_s is None else int(eta_s),
                            "t": now, "n_incomplete": n_inc,
                            "last_byte_t": last_byte_t, "stalled": stalled,
                            "source": m.get("source") or ("starting" if have == 0 else "disk"),
                            "net_baseline": m.get("net_baseline") or (prev or {}).get("net_baseline"),
                            "pid": m.get("pid") or (prev or {}).get("pid"),
                            "net_acc": net_acc, "net_last": m.get("net_raw"),
                            "net_seen": bool((prev or {}).get("net_seen") or m.get("net_raw") is not None),
                            "disk0": int(disk0), "resume_base": int(disk0),
                            "disk_have": disk_now,
                        }
                except Exception as e:  # noqa: BLE001
                    snap = {"pct": 0, "msg": f"measure error: {e}", "t": time.time(),
                            "source": "starting", "stalled": False}
            else:
                totals = (get_job(jid) or {}).get("totals") or {}
                tb = int(totals.get(role_id) or total_b or 0)
                job_now2 = get_job(jid) or {}
                snap = progress_snapshot(
                    dest, tb, prev,
                    repo_id=job_now2.get("repo_id"),
                    pid=(prev or {}).get("pid") or job_now2.get("pids", {}).get(role_id),
                )
            # keep label/role; never go backwards
            with _jobs_lock:
                if jid in _jobs:
                    prev_p = dict(_jobs[jid]["progress"].get(role_id) or {})
                    if prev_p.get("state") in ("done", "stopped", "failed"):
                        break  # final state is sticky; a late measure must not reopen it
                    snap = monotonic_snap(prev_p, snap)
                    snap["label"] = prev_p.get("label")
                    snap["role"] = prev_p.get("role")
                    if prev_p.get("retry"):
                        snap["retry"] = prev_p["retry"]
                    if prev_p.get("stage") and not (
                            snap.get("have_bytes") and str(prev_p["stage"]).startswith("starting")):
                        snap["stage"] = prev_p.get("stage")
                    _jobs[jid]["progress"][role_id] = snap
                    # mirror legacy keys
                    if snap.get("role") == "lead":
                        _jobs[jid]["progress"]["lead"] = snap
                    if snap.get("role") == "packer":
                        _jobs[jid]["progress"]["packer"] = snap
                    _jobs[jid]["updated"] = time.time()
            prev = snap

    def worker():
        stops = { (r.get("id") or r.get("label")): threading.Event() for r in runners }
        errors = []
        try:
            _job_set(jid, status="running")
            # stash totals
            totals = { (r.get("id") or r.get("label")): r.get("total_bytes") for r in runners }
            _job_set(jid, totals=totals)

            watchers = []
            for r in runners:
                rid = r.get("id") or r.get("label")
                watchers.append(threading.Thread(
                    target=_watch,
                    args=(rid, r.get("dest") or "", r.get("total_bytes"), stops[rid], r.get("measure")),
                    daemon=True, name=f"pick-watch-{rid}-{jid}"))
            for w in watchers:
                w.start()

            def run_one(r):
                rid = r.get("id") or r.get("label")
                fn = r.get("run")
                dest = r.get("dest")
                stop_evt = stops[rid]
                def prog(pct, msg):
                    if get_job(jid) and get_job(jid).get("cancel"):
                        raise RuntimeError("cancelled")
                    with _jobs_lock:
                        cur = dict(_jobs[jid]["progress"].get(rid) or {})
                        # Runner milestones are coarse (5/15/30/100). Keep them as a
                        # stage label; byte-based pct from the watcher stays in charge.
                        cur["stage"] = msg
                        _jobs[jid]["progress"][rid] = cur
                        if cur.get("role") == "lead":
                            _jobs[jid]["progress"]["lead"] = cur
                        if cur.get("role") == "packer":
                            _jobs[jid]["progress"]["packer"] = cur
                try:
                    if not fn:
                        raise RuntimeError(f"no runner for {rid}")
                    attempt = 0
                    while True:
                        try:
                            fn(repo_id, dest, packer_layers, prog)
                            break
                        except Exception as e:  # noqa: BLE001
                            j_now = get_job(jid) or {}
                            if j_now.get("cancel") or attempt >= RETRY_MAX or not is_network_error(e):
                                raise
                            attempt += 1
                            wait = RETRY_BACKOFF_S[min(attempt - 1, len(RETRY_BACKOFF_S) - 1)]
                            with _jobs_lock:
                                cur = dict(_jobs[jid]["progress"].get(rid) or {})
                                cur["retry"] = {"n": attempt, "of": RETRY_MAX, "wait_s": wait,
                                                "error": str(e)[-160:]}
                                cur["stage"] = f"network error, retry {attempt}/{RETRY_MAX} in {wait}s"
                                _jobs[jid]["progress"][rid] = cur
                            if stop_evt.wait(0) or _sleep_unless_cancel(jid, wait):
                                raise
                except Exception as e:  # noqa: BLE001
                    errors.append(f"{rid}: {e}")
                finally:
                    stop_evt.set()

            threads = [threading.Thread(target=run_one, args=(r,), daemon=True,
                                        name=f"pick-{r.get('id')}-{jid}") for r in runners]
            if not threads:
                _job_set(jid, status="error", error="no download runners")
                return
            for t in threads:
                t.start()
            for t in threads:
                t.join()
            for e in stops.values():
                e.set()

            def _mark(state):
                with _jobs_lock:
                    for rid, pg in list(_jobs[jid]["progress"].items()):
                        if isinstance(pg, dict):
                            pp = dict(pg); pp["state"] = state; pp["speed_bps"] = 0; pp["eta_s"] = None
                            _jobs[jid]["progress"][rid] = pp
            if get_job(jid) and get_job(jid).get("cancel"):
                _mark("stopped")
                _job_set(jid, status="cancelled", error="stopped by user")
                return
            if errors:
                _mark("failed")
                _job_set(jid, status="error", error="; ".join(errors))
                return
            with _jobs_lock:
                for rid, p in list(_jobs[jid]["progress"].items()):
                    if isinstance(p, dict) and p.get("msg") != "skipped":
                        pp = dict(p)
                        pp["pct"] = 100
                        if not pp.get("total_bytes"):
                            # Finished before the first measure (e.g. a resumed Mini whose
                            # files were all on disk already): fall back to the planned size.
                            rt = next((r.get("total_bytes") for r in runners
                                       if (r.get("id") or r.get("label")) == rid), None)
                            if rt:
                                pp["total_bytes"] = int(rt)
                        if pp.get("total_bytes"):
                            pp["have_bytes"] = max(int(pp.get("have_bytes") or 0), int(pp["total_bytes"]))
                        pp["speed_bps"] = 0; pp["eta_s"] = None; pp["stalled"] = False
                        pp["state"] = "done"
                        pp["msg"] = "done" + (f" · {pp['have_bytes']/1e9:.2f} GB" if pp.get("have_bytes") else "")
                        _jobs[jid]["progress"][rid] = pp
            # Persist placement next to each dest so Settings/load respect it.
            place = (get_job(jid) or {}).get("placement") or placement or {}
            if place:
                try:
                    from placement import write_placement
                    blob = {**place, "repo_id": repo_id}
                    if packer_layers is not None and not place.get("full_copy"):
                        blob["packer_layers"] = int(packer_layers)
                        blob["n_stages"] = len(runners)
                    for r in runners:
                        dest = r.get("dest")
                        if not dest:
                            continue
                        try:
                            # Remote runners save on their own Mini; writing locally left
                            # placement-only folders on EXO1 and none next to the weights.
                            if callable(r.get("save_placement")):
                                r["save_placement"](blob)
                            else:
                                write_placement(dest, blob)
                        except Exception:
                            pass
                except Exception:
                    pass
            _job_set(jid, status="done", model_folder=folder)
        except Exception as e:  # noqa: BLE001
            for e2 in stops.values():
                e2.set()
            _job_set(jid, status="error", error=str(e))

    threading.Thread(target=worker, name=f"picker-dl-{jid}", daemon=True).start()
    return get_job(jid)



def local_download_mlx(repo_id: str, dest: str, packer_layers: Optional[int],
                       progress, *, role: str = "lead") -> None:
    """Download only this role's shards using mlx_split_fetch.plan_files."""
    from huggingface_hub import snapshot_download, hf_hub_download
    dest_p = Path(dest).expanduser()
    dest_p.mkdir(parents=True, exist_ok=True)
    progress(5, "fetching index")
    for fname in ("config.json", "model.safetensors.index.json"):
        try:
            hf_hub_download(repo_id, fname, local_dir=str(dest_p), token=_hf_token())
        except Exception:
            if fname == "config.json":
                raise
    cfg = json.loads((dest_p / "config.json").read_text())
    idx_path = dest_p / "model.safetensors.index.json"
    if not idx_path.is_file():
        progress(20, "single-file snapshot")
        snapshot_download(repo_id, local_dir=str(dest_p), token=_hf_token())
        progress(100, "done")
        return
    index = json.loads(idx_path.read_text())
    import mlx_split_fetch as MSF
    plan = MSF.plan_files(cfg, index, front_layers=packer_layers)
    role_key = "head" if role == "lead" else "front"
    mine = sorted(plan[role_key])
    progress(15, f"{len(mine)} shards for {role}")
    small = list(MSF.SMALL)
    patterns = small + mine
    progress(30, "downloading shards")
    snapshot_download(
        repo_id, local_dir=str(dest_p),
        allow_patterns=patterns, token=_hf_token(),
    )
    progress(100, f"done ({len(mine)} shards)")
