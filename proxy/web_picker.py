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
    "coding": {"code", "coding", "text2code"},
    "reasoning": {"reasoning", "thinking", "chain-of-thought"},
    "vision": {"image-text-to-text", "image-to-text", "visual-question-answering"},
    "image-to-image": {"image-to-image", "text-to-image"},
    "voice": {"automatic-speech-recognition", "audio-to-text", "speech-to-text"},
    "cloud": {"cloud", "ollama-cloud"},
}

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


def _filters_for(pipeline_tag: str, tags) -> list:
    tags = set(t.lower() for t in (tags or []))
    if pipeline_tag:
        tags.add(pipeline_tag.lower())
    out = []
    for filt, keys in _FILTER_TAGS.items():
        if tags & keys:
            out.append(filt)
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
               limit: int = 40) -> list:
    q = {
        "search": query or "",
        "limit": str(limit),
        "full": "true",
        "config": "true",
    }
    if author:
        q["author"] = author
    if filter_gguf:
        q["filter"] = "gguf"
    url = HF_API + "?" + urllib.parse.urlencode(q)
    try:
        data = _http_json(url)
    except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, ValueError) as e:
        return [{"error": f"hf search failed: {e}"}]
    if not isinstance(data, list):
        return []
    return data


def _sibling_safetensors_bytes(model: dict) -> int:
    total = 0
    for s in model.get("siblings") or []:
        name = (s.get("rfilename") or "")
        if name.endswith(".safetensors") or name.endswith(".gguf"):
            total += int(s.get("size") or 0)
    return total


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
    sb = _sibling_safetensors_bytes(m)
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
        "filters": _filters_for(pipeline, tags),
        "likes": m.get("likes") or 0,
        "downloads": m.get("downloads") or 0,
        "weights_gb": round(weights, 2) if weights else None,
        "needs_conversion": needs_conversion,
        "cloud": False,
        "gguf_split_hook": source == "gguf",  # future split
    }


def search_catalog(query: str = "", *, source: str = "all", limit: int = 30) -> dict:
    """Search HF. source: all|hf-mlx|gguf|cloud."""
    key = f"search:{source}:{query}:{limit}"
    hit = _cache_get(key)
    if hit is not None:
        return hit

    rows = []
    errors = []
    q = (query or "").strip()

    if source in ("all", "hf-mlx"):
        for author, lim in (("mlx-community", limit), (None, max(10, limit // 2))):
            qq = q if author else (q or "instruct")
            raw = _hf_search(qq, author=author, limit=lim)
            if raw and isinstance(raw[0], dict) and raw[0].get("error"):
                errors.append(raw[0]["error"])
                continue
            for m in raw:
                n = _normalize_hf_hit(m, source="hf-mlx")
                if n:
                    rows.append(n)
            if author == "mlx-community" and rows:
                break  # enough mlx hits

    if source in ("all", "gguf", "ollama"):
        # Brenden's "Ollama" = GGUF/llama.cpp. Catalog from HF GGUF publishers.
        for author in ("bartowski", "unsloth", "lmstudio-community"):
            raw = _hf_search(q or "Instruct", author=author, filter_gguf=True, limit=max(8, limit // 3))
            if raw and isinstance(raw[0], dict) and raw[0].get("error"):
                errors.append(raw[0]["error"])
                continue
            for m in raw:
                # tag as gguf source
                m = dict(m)
                tags = list(m.get("tags") or [])
                if "gguf" not in tags:
                    tags.append("gguf")
                m["tags"] = tags
                n = _normalize_hf_hit(m, source="gguf")
                if n:
                    n["filters"] = list(set(n["filters"] + ["chat"]))
                    rows.append(n)

    if source in ("all", "cloud"):
        # Framework only — placeholder cloud models (not fetched live yet).
        rows.append({
            "repo_id": "ollama-cloud/placeholder-cloud-model",
            "name": "Ollama Cloud (framework)",
            "base": "Ollama Cloud",
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
            "note": "Framework only — set OLLAMA_API_KEY; untested",
        })

    # Dedupe by repo_id
    seen = set()
    uniq = []
    for r in rows:
        if r["repo_id"] in seen:
            continue
        seen.add(r["repo_id"])
        uniq.append(r)

    # Group by base name for EXO-style expand
    groups: dict = {}
    for r in uniq:
        groups.setdefault(r["base"], []).append(r)
    grouped = []
    for base, quants in groups.items():
        quants.sort(key=lambda x: (_bits_of_quant(x.get("quant")), x["repo_id"]))
        filters = sorted({f for q in quants for f in q.get("filters") or []})
        grouped.append({
            "base": base,
            "source": quants[0]["source"],
            "filters": filters,
            "cloud": any(q.get("cloud") for q in quants),
            "quants": quants,
            "likes": max(q.get("likes") or 0 for q in quants),
        })
    grouped.sort(key=lambda g: (-g["likes"], g["base"].lower()))

    out = {
        "query": q,
        "source": source,
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
                }
            else:
                w = float(qq.get("weights_gb") or 0) or 4.0  # unknown → assume mid
                split_ok = qq.get("source") == "hf-mlx"  # GGUF split later
                qq["fit"] = fit_check(
                    weights_gb=w, nodes=nodes, split_ok=split_ok,
                    safety_gb=DEFAULT_SAFETY_GB,
                )
            quants.append(qq)
        gg = dict(g)
        gg["quants"] = quants
        # group color = best (green > yellow > red)
        order = {"green": 0, "yellow": 1, "red": 2}
        colors = [q["fit"]["color"] for q in quants if q.get("fit")]
        gg["fit_color"] = min(colors, key=lambda c: order.get(c, 9)) if colors else "red"
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


def cancel_job(jid: str) -> dict:
    with _jobs_lock:
        j = _jobs.get(jid)
        if not j:
            return {"ok": False, "error": "unknown job"}
        j["cancel"] = True
        j["status"] = "cancelling"
        return {"ok": True, "job": dict(j)}


def start_download(repo_id: str, *, role_plan: Optional[dict] = None,
                   packer_layers: Optional[int] = None,
                   dest_lead: Optional[str] = None,
                   dest_packer: Optional[str] = None,
                   run_lead: Optional[callable] = None,
                   run_packer: Optional[callable] = None) -> dict:
    """Start async split-aware download. run_* callables do the actual work."""
    import uuid
    jid = uuid.uuid4().hex[:12]
    folder = repo_id.replace("/", "--")
    dest_lead = dest_lead or str(MLX_MODEL_ROOTS[0] / folder)
    dest_packer = dest_packer or f"~/.caravan/mlx-models/{folder}"
    _job_set(jid, status="queued", repo_id=repo_id, progress={
        "lead": {"pct": 0, "msg": "queued"},
        "packer": {"pct": 0, "msg": "queued"},
    }, dest_lead=dest_lead, dest_packer=dest_packer, packer_layers=packer_layers)

    def worker():
        try:
            _job_set(jid, status="running")
            if run_lead:
                def prog(pct, msg):
                    if get_job(jid) and get_job(jid).get("cancel"):
                        raise RuntimeError("cancelled")
                    with _jobs_lock:
                        _jobs[jid]["progress"]["lead"] = {"pct": pct, "msg": msg}
                run_lead(repo_id, dest_lead, packer_layers, prog)
            else:
                _job_set(jid, status="error", error="no lead downloader wired")
                return
            if run_packer:
                def prog2(pct, msg):
                    if get_job(jid) and get_job(jid).get("cancel"):
                        raise RuntimeError("cancelled")
                    with _jobs_lock:
                        _jobs[jid]["progress"]["packer"] = {"pct": pct, "msg": msg}
                run_packer(repo_id, dest_packer, packer_layers, prog2)
            else:
                with _jobs_lock:
                    _jobs[jid]["progress"]["packer"] = {"pct": 100, "msg": "skipped"}
            _job_set(jid, status="done", model_folder=folder)
        except Exception as e:  # noqa: BLE001
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
    # small files first
    for fname in ("config.json", "model.safetensors.index.json"):
        try:
            hf_hub_download(repo_id, fname, local_dir=str(dest_p), token=HF_TOKEN)
        except Exception:
            if fname == "config.json":
                raise
    cfg = json.loads((dest_p / "config.json").read_text())
    idx_path = dest_p / "model.safetensors.index.json"
    if not idx_path.is_file():
        # single-file model
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
    # snapshot_download doesn't give fine progress; approximate
    progress(30, "downloading shards")
    snapshot_download(
        repo_id, local_dir=str(dest_p),
        allow_patterns=patterns, token=HF_TOKEN,
    )
    progress(100, f"done ({len(mine)} shards)")
