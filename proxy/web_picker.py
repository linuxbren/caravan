"""Model picker (ROADMAP): catalog, fit check, disk, download.

Sources:
  * Hugging Face MLX (mlx-community and convertible HF repos)
  * Ollama (= llama.cpp / GGUF) via HF GGUF publishers (bartowski, unsloth,
    lmstudio-community) — one Mini for now; split hook left for later
  * Ollama Cloud — framework only (OLLAMA_API_KEY); labeled CLOUD

Fit uses real /api/nodes RAM (available_gb) + disk free, and memory_guard's
KV estimator. Color: green / yellow / red. Capacity = max across nodes.
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
HF_TOKEN = os.environ.get("HF_TOKEN") or os.environ.get("HUGGING_FACE_HUB_TOKEN")
OLLAMA_API_KEY = os.environ.get("OLLAMA_API_KEY") or os.environ.get("CARAVAN_OLLAMA_API_KEY")
CACHE_TTL_S = float(os.environ.get("CARAVAN_PICKER_CACHE_TTL", "300"))
DEFAULT_CTX = 8192
DEFAULT_SAFETY_GB = float(os.environ.get("CARAVAN_MEMORY_SAFETY_GB", "1.75"))
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
    if HF_TOKEN:
        h["Authorization"] = f"Bearer {HF_TOKEN}"
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
) -> dict:
    """Return color, nodes_needed, per-node fit, reasons.

    Capacity rule: a model fits on K Minis if the largest K available_gb
    sum (weights split + KV share + safety) works. For K=1, whole model
    must fit on the roomiest Mini. For K=2, weights split ~half each.
    """
    nodes = [n for n in (nodes or []) if isinstance(n, dict) and not n.get("error")]
    if not nodes:
        return {
            "color": "red", "nodes_needed": None, "fits_on": [],
            "need_gb_1": round(weights_gb + safety_gb, 2),
            "need_gb_split": None, "reason": "no node stats",
        }
    avails = sorted(
        [float((n.get("ram") or {}).get("available_gb")
               or (n.get("ram") or {}).get("free_gb") or 0) for n in nodes],
        reverse=True,
    )
    disks = [float((n.get("disk") or {}).get("free_gb") or 0) for n in nodes]
    n_count = len(avails)

    # KV estimate (full model layers for 1-node; half for split share)
    kv_full = 0.0
    kv_half = 0.0
    if MG and cfg and n_layers:
        kv_full = MG.estimate_kv_gb(cfg, ctx_tokens, int(n_layers), kv_bits=kv_bits)
        kv_half = MG.estimate_kv_gb(cfg, ctx_tokens, max(1, int(n_layers) // 2), kv_bits=kv_bits)
    else:
        # Rough fallback: ~0.5 GB KV per 8k at 7B-ish; scale by weights
        kv_full = max(0.3, weights_gb * 0.08 * (ctx_tokens / 8192))
        kv_half = kv_full * 0.55

    need_1 = weights_gb + kv_full + safety_gb
    need_split_each = (weights_gb / 2.0) + kv_half + safety_gb

    fits_on = []
    # 1 node
    if avails[0] >= need_1 and max(disks) >= weights_gb * 0.95:
        fits_on.append(1)
    # 2..N nodes (split)
    if split_ok and n_count >= 2:
        for k in range(2, n_count + 1):
            # each of top-k must hold its share; disk each needs ~weights/k
            share_w = weights_gb / k
            share_need = share_w + (kv_full / k) + safety_gb
            if all(a >= share_need for a in avails[:k]) and all(
                    d >= share_w * 0.9 for d in sorted(disks, reverse=True)[:k]):
                fits_on.append(k)

    if 1 in fits_on:
        color, needed = "green", 1
        reason = f"fits on 1 Mini (~{need_1:.1f} GB)"
    elif fits_on:
        color, needed = "yellow", min(fits_on)
        reason = f"needs {needed} Minis (~{need_split_each:.1f} GB each)"
    elif split_ok and n_count >= 2 and avails[0] >= need_split_each * 0.85:
        color, needed = "yellow", 2
        reason = "tight on 2 Minis"
        fits_on = [2]
    else:
        color, needed = "red", None
        reason = f"won't fit (need ~{need_1:.1f} GB on 1 or ~{need_split_each:.1f} GB ×2)"

    return {
        "color": color,
        "nodes_needed": needed,
        "fits_on": fits_on,
        "need_gb_1": round(need_1, 2),
        "need_gb_split": round(need_split_each, 2),
        "weights_gb": round(weights_gb, 2),
        "kv_gb_1": round(kv_full, 2),
        "reason": reason,
        "disk_ok": max(disks) >= weights_gb * 0.9 if disks else False,
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
        "weights_gb": round(weights, 2) if weights else None,
        "needs_conversion": needs_conversion,
        "cloud": False,
        "gguf_split_hook": source == "gguf",  # future split
    }


def search_catalog(query: str = "", *, source: str = "all", limit: int = 30,
                  filt: str = "") -> dict:
    """Search HF. source: all|hf-mlx|gguf|cloud. filt: chat|coding|… chip."""
    filt = (filt or "").strip().lower()
    if filt in ("fits-on-1", "fits-on-2", ""):
        filt_key = ""
    else:
        filt_key = filt
    key = f"search:{source}:{query}:{limit}:{filt_key}"
    hit = _cache_get(key)
    if hit is not None:
        return hit

    rows = []
    errors = []
    q = (query or "").strip()

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
                raw = _hf_search(term, author="mlx-community", limit=max(12, limit // 2))
                _ingest(raw, "hf-mlx", extra_filters=[filt_key])
            for ptag in ([spec["pipeline_tag"]] if spec.get("pipeline_tag") else []) + list(spec.get("pipeline_tags") or []):
                raw = _hf_search(q or "", pipeline_tag=ptag, limit=max(8, limit // 3))
                _ingest(raw, "hf-mlx", extra_filters=[filt_key])
            if not rows:
                for term in spec.get("hf_search") or []:
                    raw = _hf_search((q + " " + term).strip() if q else term, limit=max(10, limit // 2))
                    _ingest(raw, "hf-mlx", extra_filters=[filt_key])
        if want_gguf and filt_key in ("chat", "coding", "reasoning", "vision"):
            gq = q or (spec.get("mlx_search") or ["Instruct"])[0]
            for author in ("bartowski", "unsloth", "lmstudio-community"):
                raw = _hf_search(gq, author=author, filter_gguf=True, limit=max(6, limit // 4))
                _ingest(raw, "gguf", extra_filters=[filt_key, "chat"])
        if filt_key == "image-to-image":
            raw = _hf_search(q or "", pipeline_tag="image-to-image", limit=limit)
            _ingest(raw, "hf-mlx", extra_filters=["image-to-image"])
        if filt_key == "voice":
            for ptag in ("automatic-speech-recognition", "text-to-speech"):
                raw = _hf_search(q or "whisper", pipeline_tag=ptag, limit=max(8, limit // 2))
                _ingest(raw, "hf-mlx", extra_filters=["voice"])

    else:
        # Default / free-text search
        if source in ("all", "hf-mlx"):
            for author, lim in (("mlx-community", limit), (None, max(10, limit // 2))):
                qq = q if author else (q or "instruct")
                raw = _hf_search(qq, author=author, limit=lim)
                _ingest(raw, "hf-mlx")
                if author == "mlx-community" and rows:
                    break
        if source in ("all", "gguf", "ollama"):
            for author in ("bartowski", "unsloth", "lmstudio-community"):
                raw = _hf_search(q or "Instruct", author=author, filter_gguf=True,
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
    grouped.sort(key=lambda g: (_src_rank(g), -g["likes"], g["base"].lower()))

    out = {
        "query": q,
        "source": source,
        "filter": filt_key,
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
                split_ok = qq.get("source") == "hf-mlx"  # GGUF split later
                qq["fit"] = fit_check(
                    weights_gb=w, nodes=nodes, split_ok=split_ok,
                    safety_gb=DEFAULT_SAFETY_GB,
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
    """Bytes on disk for a local_dir download: finished shards + .incomplete."""
    dest_p = Path(dest).expanduser()
    done = 0
    incomplete = 0
    n_incomplete = 0
    if not dest_p.exists():
        return {"done_bytes": 0, "incomplete_bytes": 0, "have_bytes": 0, "n_incomplete": 0}
    try:
        for p in dest_p.glob("*.safetensors"):
            try:
                done += p.stat().st_size
            except OSError:
                pass
        for p in dest_p.glob("*.gguf"):
            try:
                done += p.stat().st_size
            except OSError:
                pass
        cache_dl = dest_p / ".cache" / "huggingface" / "download"
        if cache_dl.is_dir():
            for p in cache_dl.rglob("*"):
                if not p.is_file():
                    continue
                name = p.name
                try:
                    sz = p.stat().st_size
                except OSError:
                    continue
                if name.endswith(".incomplete"):
                    incomplete += sz
                    n_incomplete += 1
    except OSError:
        pass
    return {
        "done_bytes": done,
        "incomplete_bytes": incomplete,
        "have_bytes": done + incomplete,
        "n_incomplete": n_incomplete,
    }


def _fmt_eta(seconds: Optional[float]) -> str:
    if seconds is None or seconds < 0 or seconds != seconds:  # noqa: PLR0124
        return "—"
    seconds = int(seconds)
    if seconds < 60:
        return f"{seconds}s"
    if seconds < 3600:
        return f"{seconds // 60}m {seconds % 60}s"
    return f"{seconds // 3600}h {(seconds % 3600) // 60}m"


def progress_snapshot(dest: str, total_bytes: Optional[int], prev: Optional[dict] = None) -> dict:
    """Build a progress dict with pct, MB/s, ETA from byte counts."""
    m = measure_download_bytes(dest)
    have = m["have_bytes"]
    total = int(total_bytes or 0)
    now = time.time()
    speed = 0.0
    if prev and prev.get("t") and prev.get("have_bytes") is not None:
        dt = max(0.001, now - float(prev["t"]))
        speed = max(0.0, (have - int(prev["have_bytes"])) / dt)
    pct = 0
    if total > 0:
        pct = max(0, min(99, int(have * 100 / total)))
        if have >= total and m["n_incomplete"] == 0 and m["done_bytes"] > 0:
            pct = 100
    elif m["done_bytes"] > 0 and m["n_incomplete"] == 0:
        pct = 100
    eta_s = None
    if speed > 0 and total > have:
        eta_s = (total - have) / speed
    mb_s = speed / 1e6
    have_gb = have / 1e9
    total_gb = total / 1e9 if total else None
    if total_gb:
        msg = f"{have_gb:.2f}/{total_gb:.2f} GB · {mb_s:.1f} MB/s · ETA {_fmt_eta(eta_s)}"
    else:
        msg = f"{have_gb:.2f} GB · {mb_s:.1f} MB/s"
    if m["n_incomplete"]:
        msg += f" · {m['n_incomplete']} active"
    return {
        "pct": pct,
        "msg": msg,
        "have_bytes": have,
        "total_bytes": total or None,
        "speed_bps": speed,
        "mb_s": round(mb_s, 2),
        "eta_s": None if eta_s is None else int(eta_s),
        "t": now,
        "n_incomplete": m["n_incomplete"],
    }


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


def start_download(repo_id: str, *, role_plan: Optional[dict] = None,
                   packer_layers: Optional[int] = None,
                   dest_lead: Optional[str] = None,
                   dest_packer: Optional[str] = None,
                   run_lead: Optional[callable] = None,
                   run_packer: Optional[callable] = None,
                   total_bytes_lead: Optional[int] = None,
                   total_bytes_packer: Optional[int] = None,
                   measure_packer: Optional[callable] = None) -> dict:
    """Start async split-aware download. Lead + packer run in PARALLEL.

    measure_packer() -> {have_bytes, n_incomplete} for EXO2 (SSH); optional.
    """
    import uuid
    jid = uuid.uuid4().hex[:12]
    folder = repo_id.replace("/", "--")
    dest_lead = dest_lead or str(MLX_MODEL_ROOTS[0] / folder)
    dest_packer = dest_packer or f"~/.caravan/mlx-models/{folder}"
    _job_set(jid, status="queued", repo_id=repo_id, progress={
        "lead": {"pct": 0, "msg": "queued", "have_bytes": 0, "t": time.time()},
        "packer": {"pct": 0, "msg": "queued", "have_bytes": 0, "t": time.time()},
    }, dest_lead=dest_lead, dest_packer=dest_packer, packer_layers=packer_layers,
        total_bytes_lead=total_bytes_lead, total_bytes_packer=total_bytes_packer)

    def _watch(role: str, dest: str, total_b: Optional[int], stop_evt: threading.Event,
               measure: Optional[callable] = None):
        prev = None
        while not stop_evt.wait(0.8):
            if get_job(jid) and get_job(jid).get("cancel"):
                break
            # Refresh total if dry-run filled it in later.
            job_now = get_job(jid) or {}
            if role == "lead":
                total_b = job_now.get("total_bytes_lead") or total_b
            else:
                total_b = job_now.get("total_bytes_packer") or total_b
            if measure:
                try:
                    m = measure() or {}
                    have = int(m.get("have_bytes") or 0)
                    n_inc = int(m.get("n_incomplete") or 0)
                    fake_prev = prev
                    # synthesize snapshot from remote counts
                    now = time.time()
                    speed = 0.0
                    if fake_prev and fake_prev.get("t") and fake_prev.get("have_bytes") is not None:
                        dt = max(0.001, now - float(fake_prev["t"]))
                        speed = max(0.0, (have - int(fake_prev["have_bytes"])) / dt)
                    total = int(total_b or 0)
                    pct = max(0, min(99, int(have * 100 / total))) if total else 0
                    eta_s = ((total - have) / speed) if (speed > 0 and total > have) else None
                    mb_s = speed / 1e6
                    if total:
                        msg = f"{have/1e9:.2f}/{total/1e9:.2f} GB · {mb_s:.1f} MB/s · ETA {_fmt_eta(eta_s)}"
                    else:
                        msg = f"{have/1e9:.2f} GB · {mb_s:.1f} MB/s"
                    if n_inc:
                        msg += f" · {n_inc} active"
                    snap = {
                        "pct": pct, "msg": msg, "have_bytes": have,
                        "total_bytes": total or None, "speed_bps": speed,
                        "mb_s": round(mb_s, 2),
                        "eta_s": None if eta_s is None else int(eta_s),
                        "t": now, "n_incomplete": n_inc,
                    }
                except Exception as e:  # noqa: BLE001
                    snap = {"pct": 0, "msg": f"measure error: {e}", "t": time.time()}
            else:
                snap = progress_snapshot(dest, total_b, prev)
            prev = snap
            with _jobs_lock:
                if jid in _jobs:
                    _jobs[jid]["progress"][role] = snap
                    _jobs[jid]["updated"] = time.time()

    def worker():
        stop_lead = threading.Event()
        stop_pack = threading.Event()
        errors = []
        try:
            _job_set(jid, status="running")
            watchers = []
            if run_lead:
                watchers.append(threading.Thread(
                    target=_watch, args=("lead", dest_lead, total_bytes_lead, stop_lead, None),
                    daemon=True, name=f"pick-watch-lead-{jid}"))
            if run_packer:
                watchers.append(threading.Thread(
                    target=_watch, args=("packer", dest_packer, total_bytes_packer, stop_pack, measure_packer),
                    daemon=True, name=f"pick-watch-pack-{jid}"))
            for w in watchers:
                w.start()

            def run_one(label, fn, dest, pk, stop_evt):
                def prog(pct, msg):
                    if get_job(jid) and get_job(jid).get("cancel"):
                        raise RuntimeError("cancelled")
                    with _jobs_lock:
                        cur = dict(_jobs[jid]["progress"].get(label) or {})
                        cur.update({"pct": pct, "msg": msg})
                        _jobs[jid]["progress"][label] = cur
                try:
                    fn(repo_id, dest, pk, prog)
                except Exception as e:  # noqa: BLE001
                    errors.append(f"{label}: {e}")
                finally:
                    stop_evt.set()

            threads = []
            if run_lead:
                threads.append(threading.Thread(
                    target=run_one, args=("lead", run_lead, dest_lead, packer_layers, stop_lead),
                    daemon=True, name=f"pick-lead-{jid}"))
            else:
                errors.append("no lead downloader wired")
            if run_packer:
                threads.append(threading.Thread(
                    target=run_one, args=("packer", run_packer, dest_packer, packer_layers, stop_pack),
                    daemon=True, name=f"pick-pack-{jid}"))
            else:
                with _jobs_lock:
                    _jobs[jid]["progress"]["packer"] = {"pct": 100, "msg": "skipped"}
                stop_pack.set()

            for t in threads:
                t.start()
            for t in threads:
                t.join()
            stop_lead.set(); stop_pack.set()

            if get_job(jid) and get_job(jid).get("cancel"):
                _job_set(jid, status="cancelled", error="stopped by user")
                return
            if errors:
                _job_set(jid, status="error", error="; ".join(errors))
                return
            # final 100%
            with _jobs_lock:
                for role in ("lead", "packer"):
                    p = dict(_jobs[jid]["progress"].get(role) or {})
                    if p.get("msg") != "skipped":
                        p["pct"] = 100
                        p["msg"] = (p.get("msg") or "done") + " · done"
                        _jobs[jid]["progress"][role] = p
            _job_set(jid, status="done", model_folder=folder)
        except Exception as e:  # noqa: BLE001
            stop_lead.set(); stop_pack.set()
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
            hf_hub_download(repo_id, fname, local_dir=str(dest_p), token=HF_TOKEN)
        except Exception:
            if fname == "config.json":
                raise
    cfg = json.loads((dest_p / "config.json").read_text())
    idx_path = dest_p / "model.safetensors.index.json"
    if not idx_path.is_file():
        progress(20, "single-file snapshot")
        snapshot_download(repo_id, local_dir=str(dest_p), token=HF_TOKEN)
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
        allow_patterns=patterns, token=HF_TOKEN,
    )
    progress(100, f"done ({len(mine)} shards)")
