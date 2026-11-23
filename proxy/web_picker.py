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
try:
    from caravan_i18n import T, fmt_date  # noqa: E402  (Day 32: user-facing text, tools/caravan_i18n.py)
except ImportError:  # run without tools/ on the path
    import sys as _sys
    from pathlib import Path as _Path
    _sys.path.append(str(_Path(__file__).resolve().parents[1] / "tools"))
    from caravan_i18n import T  # noqa: E402

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
    "thinking": {"reasoning", "thinking", "chain-of-thought"},
    "tools": {
        "tools", "tool-use", "tool_use", "function-calling",
        "function_calling", "tool-calling", "function-call",
    },
    "vision": {"image-text-to-text", "image-to-text", "visual-question-answering"},
    "embedding": {
        "embedding", "embeddings", "feature-extraction",
        "sentence-similarity", "sentence-transformers",
    },
    "any-to-any": {"any-to-any", "any_to_any"},
    "text-to-image": {"text-to-image", "text-to-img"},
    "text-to-video": {"text-to-video", "text-to-vid", "image-to-video", "text-to-video-synthesis"},
    "text-to-speech": {"text-to-speech", "text-to-audio", "tts"},
    "speech-to-text": {
        "speech-to-text", "automatic-speech-recognition", "asr",
        "speech2text", "audio-to-text",
    },
    "decision": {"decision", "system-one", "systemone"},
    # Kept for API callers; not shown as a default or Advanced chip.
    "image-to-image": {"image-to-image"},
    "cloud": {"cloud", "ollama-cloud"},
}

# Older chip names the page or API may still send.
_FILTER_ALIASES = {
    "reasoning": "thinking",
    "voice": "text-to-speech",
    "asr": "speech-to-text",
    "stt": "speech-to-text",
    "automatic-speech-recognition": "speech-to-text",
}

# Default chips on the Models page (Advanced hides the rest).
FILTER_DEFAULT = ("chat", "coding", "thinking", "tools", "vision")
FILTER_ADVANCED = (
    "embedding", "any-to-any", "text-to-image",
    "text-to-video", "text-to-speech", "speech-to-text", "decision",
)

# Known model-family set for the Models picker. The page only lists
# families that appear in the current catalog results, in this order.
# QwQ counts as Qwen (same family). Mixtral counts as Mistral.
FAMILIES = (
    {"id": "qwen", "label": "Qwen", "needles": ("qwen", "qwq")},
    {"id": "llama", "label": "Llama", "needles": ("llama",)},
    {"id": "gemma", "label": "Gemma", "needles": ("gemma",)},
    {"id": "mistral", "label": "Mistral", "needles": ("mistral", "mixtral", "ministral")},
    {"id": "deepseek", "label": "DeepSeek", "needles": ("deepseek",)},
    {"id": "gpt-oss", "label": "gpt-oss", "needles": ("gpt-oss", "gptoss", "gpt_oss")},
    # "phi" is a short syllable (sophia, graphic), so it needs a start boundary
    # and must not be followed by a letter. Qwen2 / Llama-3 style names are
    # ordinary substrings: "qwen" in "Qwen2.5", "llama" in "CodeLlama".
    {"id": "phi", "label": "Phi", "pattern": r"(?:^|[^a-z0-9])phi(?:\d|[^a-z]|$)"},
)


def family_of(*names):
    """Return {id, label} for the first known family in the given names, or None."""
    blob = " ".join(str(n) for n in names if n).lower()
    if not blob:
        return None
    for fam in FAMILIES:
        needles = fam.get("needles") or ()
        if needles and any(n in blob for n in needles):
            return {"id": fam["id"], "label": fam["label"]}
        pat = fam.get("pattern")
        if pat and re.search(pat, blob):
            return {"id": fam["id"], "label": fam["label"]}
    return None


def group_family(group: dict):
    names = [group.get("base"), group.get("name"), group.get("repo_id")]
    for q in group.get("quants") or []:
        if isinstance(q, dict):
            names += [q.get("repo_id"), q.get("name"), q.get("base")]
        else:
            names.append(q)
    return family_of(*names)


def families_present(groups) -> list:
    """Known families that appear in these catalog groups, in FAMILIES order."""
    found = set()
    for g in groups or []:
        if g.get("family"):
            found.add(g["family"])
        else:
            fam = group_family(g)
            if fam:
                found.add(fam["id"])
    return [{"id": f["id"], "label": f["label"]} for f in FAMILIES if f["id"] in found]

def maker_of(repo_id=None, author=None):
    """Publishing org: explicit author, or the owner half of owner/name."""
    if author and str(author).strip() and str(author).strip().lower() not in ("none", "unknown", "?"):
        return str(author).strip()
    repo = str(repo_id or "").strip()
    if "/" in repo:
        org = repo.split("/", 1)[0].strip()
        if org and org.lower() not in ("ollama-cloud", "unknown", "?"):
            return org
    return None


def release_month(*timestamps):
    """Month and year, e.g. 'October 2025'. Prefers a created date, then last modified."""
    from datetime import datetime, timezone
    for raw in timestamps:
        ts = _parse_hf_time(raw)
        if ts:
            return fmt_date(datetime.fromtimestamp(ts, tz=timezone.utc), "month_year")
    return None


_CONTEXT_KM = re.compile(
    r"(?:^|[^a-z0-9])(?:(?:ctx|context)(?:[_-]?length)?[_-]?)?(\d{1,4})\s*([km])(?:[_-]?(?:ctx|context|tok(?:ens)?)?)?(?:[^a-z0-9]|$)",
    re.I,
)


def _context_tokens(*blobs, config=None):
    """Best-known context window in tokens, or None. Never guesses."""
    if isinstance(config, dict):
        for k in ("max_position_embeddings", "max_sequence_length", "n_positions",
                  "context_length", "max_ctx", "model_max_length"):
            v = config.get(k)
            try:
                n = int(v)
            except (TypeError, ValueError):
                continue
            if n >= 512:
                return n
    text = " ".join(str(b) for b in blobs if b)
    best = None
    for m in _CONTEXT_KM.finditer(text):
        n = int(m.group(1))
        unit = m.group(2).lower()
        tokens = n * (1_000_000 if unit == "m" else 1000)
        if tokens >= 512 and (best is None or tokens > best):
            best = tokens
    return best


def context_phrase(*blobs, config=None, tokens=None):
    """Plain-words context, or None when unknown. No question marks."""
    n = tokens if tokens is not None else _context_tokens(*blobs, config=config)
    if not n:
        return None
    if n >= 1_000_000:
        m = n / 1_000_000
        if abs(m - round(m)) < 0.08:
            m = int(round(m))
        else:
            m = int(round(m, 1)) if isinstance(m, float) else m
        size = T("server.web_picker.about_m_m", m=m)
    elif n >= 1000:
        # "128k" tags are thousands; 32768-token configs are 32 × 1024.
        k = None
        if n % 1000 == 0 or abs(n / 1000 - round(n / 1000)) < 0.02:
            k = int(round(n / 1000))
        elif abs(n / 1024 - round(n / 1024)) < 0.08:
            k = int(round(n / 1024))
        else:
            k = int(round(n / 1000))
        size = T("server.web_picker.about_k_k", k=k)
    else:
        size = T("server.web_picker.about_n", n=n)
    if n >= 32000:
        return T("server.web_picker.handles_long_chats_size", size=size)
    return T("server.web_picker.size_of_chat_history", size=size)


def capability_phrases(tags=None, filters=None, pipeline=None, repo_id=""):
    """Short capability clauses from tags. Speed is never included."""
    filt = list(filters or [])
    if not filt:
        filt = _filters_for(pipeline or "", tags, repo_id)
    blob = set(str(t).lower() for t in list(tags or []) + filt + ([pipeline] if pipeline else []))
    out = []
    if "tools" in filt or blob & {
        "tools", "tool-use", "tool_use", "function-calling",
        "function_calling", "tool-calling", "function-call",
    }:
        out.append(T("server.web_picker.can_use_tools"))
    if "vision" in filt or blob & {
        "image-text-to-text", "image-to-text", "visual-question-answering", "vision",
    }:
        out.append(T("server.web_picker.reads_images"))
    return out


def row_tooltip(group: dict) -> str:
    """One or two lines for a Models-row hover. Omits unknown fields. No speed."""
    quants = [q for q in (group.get("quants") or []) if isinstance(q, dict)]
    makers, created, modified, tags, filts, pipes, blobs, configs = [], [], [], [], [], [], [], []
    blobs.append(group.get("base"))
    for q in quants or [{}]:
        makers.append(maker_of(q.get("repo_id") or group.get("repo_id"), q.get("author") or group.get("author")))
        for key in ("created_at", "createdAt", "created"):
            if q.get(key):
                created.append(q.get(key))
                break
        for key in ("last_modified", "lastModified"):
            if q.get(key):
                modified.append(q.get(key))
                break
        tags += list(q.get("tags") or [])
        filts += list(q.get("filters") or []) + list(group.get("filters") or [])
        if q.get("pipeline_tag"):
            pipes.append(q.get("pipeline_tag"))
        blobs += [q.get("repo_id"), q.get("name"), " ".join(q.get("tags") or [])]
        if q.get("config"):
            configs.append(q.get("config"))
    # Prefer a created date (release); otherwise last modified. Earliest created.
    def _earliest(vals):
        dated = [( _parse_hf_time(v), v) for v in vals]
        dated = [(t, v) for t, v in dated if t]
        if not dated:
            return None
        dated.sort()
        return dated[0][1]
    maker = next((m for m in makers if m), None)
    released = release_month(_earliest(created), _earliest(modified))
    ctx = context_phrase(*blobs, config=configs[0] if configs else (group.get("config") if isinstance(group.get("config"), dict) else None), tokens=group.get("context_tokens"))
    caps = capability_phrases(tags, filts, pipes[0] if pipes else group.get("pipeline_tag"), (quants[0].get("repo_id") if quants else "") or group.get("base") or "")
    line1 = " · ".join(p for p in (maker, released) if p)
    line2_parts = [p for p in [ctx] + caps if p]
    # Capabilities as "Can use tools, reads images." — first clause capitalised.
    line2 = ""
    if line2_parts:
        # "Handles long chats (about 32k). Can use tools, reads images."
        # Day 32: sentence marks come from the strings file; first letters
        # are capitalised (a no-op in scripts without case).
        first_up = lambda x: x[:1].upper() + x[1:]
        if ctx and caps:
            line2 = T("server.web_picker.two_sentences", a=first_up(ctx), b=first_up(T.join(caps)))
        else:
            line2 = first_up(T.join(line2_parts))
            end = T("server.web_picker.sentence_end")
            if not line2.endswith(end):
                line2 += end
    notice = group.get("download_only_note") or serve_notice(
        filts, pipes[0] if pipes else group.get("pipeline_tag"),
        tags, (quants[0].get("repo_id") if quants else "") or group.get("base") or "",
    )
    body = ""
    if line1 and line2:
        body = f"{line1}\n{line2}"
    else:
        body = line1 or line2
    if notice:
        return (body + "\n" + notice) if body else notice
    return body


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
    "thinking": {
        "mlx_search": ["QwQ", "thinking", "reasoning", "R1"],
        "hf_search": ["QwQ", "DeepSeek-R1", "thinking"],
        "pipeline_tag": None,
        "name_keys": ("qwq", "thinking", "reasoning", "r1-", "-r1", "distill-r1"),
    },
    "tools": {
        "mlx_search": ["tool", "function-calling", "tool-use"],
        "hf_search": ["function calling", "tool use"],
        "pipeline_tag": None,
        "name_keys": ("tool-use", "tool_use", "function-calling", "function_calling", "-tools"),
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
    "embedding": {
        "mlx_search": ["embed", "embedding"],
        "hf_search": ["embedding"],
        "pipeline_tag": "feature-extraction",
        "pipeline_tags": ("feature-extraction", "sentence-similarity"),
        "name_keys": ("-embed", "embed-", "embedding", "nomic-embed", "bge-", "e5-"),
    },
    "any-to-any": {
        "mlx_search": ["omni", "any-to-any"],
        "hf_search": ["omni"],
        "pipeline_tag": "any-to-any",
        "name_keys": ("omni", "any-to-any", "any_to_any"),
    },
    "text-to-image": {
        "mlx_search": ["text-to-image", "flux", "sdxl"],
        "hf_search": [""],
        "pipeline_tag": "text-to-image",
        "name_keys": ("text-to-image", "txt2img", "stable-diffusion", "flux"),
    },
    "text-to-video": {
        "mlx_search": ["text-to-video"],
        "hf_search": [""],
        "pipeline_tag": "text-to-video",
        "pipeline_tags": ("text-to-video", "image-to-video"),
        "name_keys": ("text-to-video", "txt2vid", "cogvideox", "ltx-video", "hunyuan-video"),
    },
    "text-to-speech": {
        "mlx_search": ["tts", "speech"],
        "hf_search": ["tts"],
        "pipeline_tag": "text-to-speech",
        "pipeline_tags": ("text-to-speech", "text-to-audio"),
        "name_keys": ("tts", "speecht5", "kokoro", "text-to-speech"),
    },
    "speech-to-text": {
        "mlx_search": ["whisper", "asr", "speech-to-text"],
        "hf_search": ["whisper", "asr"],
        "pipeline_tag": "automatic-speech-recognition",
        "pipeline_tags": ("automatic-speech-recognition", "speech-to-text"),
        "name_keys": ("whisper", "speech-to-text", "speech2text", "-asr-", "asr-"),
    },
    "decision": {
        # Ollama Decision / System One: classify text, yes/no probabilities, rubric scores.
        "mlx_search": ["nimble", "clef", "decision"],
        "hf_search": ["nimble", "clef"],
        "pipeline_tag": None,
        "name_keys": ("nimble", "tev1", "tev-", "clef", "system-one", "decision"),
    },
}

def _cloud_key_set(provider):
    """Day 32: a key saved in Settings or set in the environment."""
    try:
        import cloud_keys
        return bool(cloud_keys.resolve(provider))
    except Exception:
        return bool(OLLAMA_API_KEY) if provider == "ollama" else False


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


def fetch_config(repo_id: str, *, opener=None) -> Optional[dict]:
    """A model's config.json from the download source (cached), or None.

    Day 31: the picker, placement and download checks size the chat memory
    from the real config (layers, key/value heads, head size, trained
    window), not a guess from the file size."""
    if not repo_id or ".." in str(repo_id):
        return None
    key = f"config:{repo_id}"
    hit = _cache_get(key)
    if hit is not None:
        return hit or None
    url = "https://huggingface.co/%s/resolve/main/config.json" % repo_id
    try:
        req = urllib.request.Request(url, headers=_hf_headers())
        with (opener or urllib.request.urlopen)(req, timeout=15) as r:
            blob = json.loads(r.read().decode("utf-8"))
    except Exception:  # noqa: BLE001 - unknown config means the old estimate
        blob = None
    blob = blob if isinstance(blob, dict) else None
    _cache_set(key, blob or {})
    return blob


def local_config(model_dir) -> Optional[dict]:
    """config.json of a downloaded MLX model folder, or None."""
    try:
        blob = json.loads((Path(model_dir).expanduser() / "config.json").read_text())
    except (OSError, ValueError, TypeError):
        return None
    return blob if isinstance(blob, dict) else None


def trained_ctx(cfg: Optional[dict]) -> Optional[int]:
    """Trained window from an MLX/HF config, including wrapped decoders
    (Qwen3.5 and other multimodal models keep it in text_config)."""
    if not isinstance(cfg, dict):
        return None
    for blob in (cfg, cfg.get("text_config") if isinstance(cfg.get("text_config"), dict) else None):
        if not blob:
            continue
        for k in ("max_position_embeddings", "max_sequence_length", "n_positions",
                  "seq_length", "n_ctx"):
            try:
                n = int(blob.get(k) or 0)
            except (TypeError, ValueError):
                continue
            if n >= 512:
                return n
    return None


GGUF_HEADER_READS = (4 << 20, 16 << 20, 64 << 20)


def fetch_gguf_header(repo_id: str, filename: str, *, opener=None) -> Optional[dict]:
    """Header keys of a GGUF file at the download source, read from its first
    few MB (never the weights), or None. Day 31: lets placement size the
    chat window before the model is downloaded."""
    if not repo_id or not filename or ".." in filename or filename.startswith("/") \
            or not filename.endswith(".gguf"):
        return None
    key = f"gguf-header:{repo_id}:{filename}"
    hit = _cache_get(key)
    if hit is not None:
        return hit or None
    try:
        import io
        import gguf_meta
    except ImportError:
        return None
    url = "https://huggingface.co/%s/resolve/main/%s" % (repo_id, urllib.parse.quote(filename))
    meta = None
    for n in GGUF_HEADER_READS:
        try:
            req = urllib.request.Request(url, headers=dict(_hf_headers(), Range=f"bytes=0-{n - 1}"))
            with (opener or urllib.request.urlopen)(req, timeout=30) as r:
                data = r.read(n)
        except Exception:  # noqa: BLE001
            break
        try:
            meta = gguf_meta.read_metadata_from(io.BytesIO(data), name=filename)
            break
        except gguf_meta.GGUFError as e:
            if "truncated" in str(e) and len(data) >= n:
                continue
            break
        except Exception:  # noqa: BLE001
            break
    _cache_set(key, meta or {})
    return meta


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



# Types Caravan can load into the chat worker (MLX LM / GGUF). The Advanced
# types stay in the picker so Caravan can sit between an agent app and a
# model, but these cannot be served for chat yet.
DOWNLOAD_ONLY_NOTES = {
    "text-to-image": T("server.web_picker.download_only_caravan_cant_run_image"),
    "image-to-image": T("server.web_picker.download_only_caravan_cant_run_image"),
    "text-to-video": T("server.web_picker.download_only_caravan_cant_run_video"),
    "text-to-speech": T("server.web_picker.download_only_caravan_cant_run_speech"),
    "speech-to-text": T("server.web_picker.download_only_caravan_cant_run_speech"),
    "embedding": T("server.web_picker.download_only_caravan_cant_run_embedding"),
    "decision": T("server.web_picker.download_only_caravan_cant_run_decision"),
    "any-to-any": T("server.web_picker.download_only_caravan_cant_run_this"),
}
SERVEABLE_FILTERS = {"chat", "coding", "thinking", "tools", "vision", "cloud"}


def serve_notice(filters=None, pipeline_tag: str = "", tags=None, repo_id: str = "") -> str:
    """Plain line when Caravan cannot load this model for chat, or empty."""
    filts = list(filters or [])
    if not filts:
        filts = _filters_for(pipeline_tag or "", tags, repo_id)
    if any(f in SERVEABLE_FILTERS for f in filts):
        return ""
    for f in filts:
        if f in DOWNLOAD_ONLY_NOTES:
            return DOWNLOAD_ONLY_NOTES[f]
    return ""


def serve_notice_for_folder(path) -> str:
    """Detect a non-chat tree already on disk (for Load)."""
    d = Path(path).expanduser() if path else None
    if not d or not d.is_dir():
        return ""
    try:
        from placement import read_placement
        place = read_placement(d) or {}
        note = serve_notice(
            place.get("filters") or place.get("serve_filters"),
            place.get("pipeline_tag") or "",
            repo_id=place.get("repo_id") or "",
        )
        if note:
            return note
        if place.get("download_only_note"):
            return place["download_only_note"]
    except Exception:
        pass
    # Diffusers-style image or video trees ship model_index.json and usually
    # have no top-level LLM config (or a non-language one).
    if (d / "model_index.json").is_file():
        try:
            idx_text = (d / "model_index.json").read_text().lower()
        except OSError:
            idx_text = ""
        videoish = "video" in idx_text
        note = (
            DOWNLOAD_ONLY_NOTES["text-to-video"] if videoish
            else DOWNLOAD_ONLY_NOTES["text-to-image"]
        )
        cfg = d / "config.json"
        if not cfg.is_file():
            return note
        try:
            blob = json.loads(cfg.read_text())
        except (OSError, ValueError):
            blob = {}
        if not isinstance(blob, dict) or not (
            blob.get("model_type") or blob.get("architectures") or blob.get("num_hidden_layers")
        ):
            return note
    # Voice, video, and other non-chat trees often have no top-level
    # config.json at all. Refuse Load with a plain line.
    if not (d / "config.json").is_file():
        return T("server.web_picker.download_only_caravan_cant_run_this_2")
    return ""


# Day 32: each download-only notice has its own Load refusal line, so the
# refusal is looked up instead of cut out of the notice's words.
_REFUSALS = {
    "download_only_caravan_cant_run_image": "refuse_image",
    "download_only_caravan_cant_run_video": "refuse_video",
    "download_only_caravan_cant_run_speech": "refuse_speech",
    "download_only_caravan_cant_run_embedding": "refuse_embedding",
    "download_only_caravan_cant_run_decision": "refuse_decision",
    "download_only_caravan_cant_run_this": "refuse_this_kind",
    "download_only_caravan_cant_run_this_2": "caravan_cant_run_this_kind_of",
}


def load_refusal(notice: str) -> str:
    """One-line Load error from a download-only notice."""
    s = (notice or "").strip()
    for nkey, rkey in _REFUSALS.items():
        if s == T("server.web_picker." + nkey):
            return T("server.web_picker." + rkey)
    if s.lower().startswith("download only, "):  # an English notice from an older catalog
        s = s[len("Download only, "):]
        if s:
            s = s[0].upper() + s[1:]
    return s or T("server.web_picker.caravan_cant_run_this_kind_of")

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
    return n.get("label") or n.get("role") or T("server.web_picker.mini_v", v=idx+1)


_WINDOW_SIZES = (4096, 8192, 16384, 32768, 65536, 131072, 262144)


def _window_candidates(target: int) -> list:
    """Window sizes a placement may hold: the usual sizes up to the target,
    plus the target itself (same list Chat window Auto picks from)."""
    out = [c for c in _WINDOW_SIZES if c <= int(target)]
    if int(target) not in out:
        out.append(int(target))
    return sorted(out)


def _fmt_window(tokens) -> str:
    n = int(tokens or 0)
    return f"{n // 1024}K" if n >= 1024 else str(n)


def fit_check(
    *,
    weights_gb: float,
    nodes: list,
    cfg: Optional[dict] = None,
    n_layers: Optional[int] = None,
    ctx_tokens: Optional[int] = None,
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
    max_stages = min(max_stages, max(1, len(nodes)))
    if not nodes:
        return {
            "color": "red", "nodes_needed": None, "fits_on": [],
            "need_gb_1": round(weights_gb + safety_gb, 2),
            "need_gb_split": None,
            "reason": T("server.placement.no_online_nodes"),
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

    # Day 31: the model's own window. With a real config the chat memory
    # comes from its layers / key-value heads / head size (memory_guard,
    # the same estimate the worker trims chats with) at its trained window
    # (max_position_embeddings, including text_config). Unknown config:
    # the old 8K window and 8%-of-weights estimate. `ctx_tokens` still
    # overrides the window.
    trained = trained_ctx(cfg)
    target = int(ctx_tokens) if ctx_tokens else int(trained or DEFAULT_CTX)
    if MG and cfg and not n_layers:
        try:
            n_layers = MG.model_layer_count(cfg) or None
        except Exception:  # noqa: BLE001
            n_layers = None
    real_kv = bool(MG and cfg and n_layers and MG.kv_elems_per_token(cfg) > 0)

    def kv_at(tokens: int) -> float:
        if real_kv:
            return MG.estimate_kv_gb(cfg, int(tokens), int(n_layers), kv_bits=kv_bits)
        return max(0.3, weights_gb * 0.08 * (int(tokens) / 8192))

    # Fitting at all needs the short window (8K, or the whole trained window
    # when shorter). The full window decides the recommendation.
    short_ctx = min(DEFAULT_CTX, target)
    kv_full = kv_at(short_ctx)
    kv_target = kv_at(target)

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
                T("server.web_picker.not_enough_disk_on_labels_need", labels=labels[best], share=share, disks=disks[best])
            )
        for i in range(k):
            if disks[i] < share * 0.9:
                return False, (
                    T("server.web_picker.not_enough_disk_on_labels_need_2", labels=labels[i], share=share, labels2=labels[i], disks=disks[i])
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
        return T("server.web_picker.k_mini_split_coming_later_runtime", k=k, max_stages=max_stages)

    limit = "ram"
    need_split_each = need_each(2) if n_count >= 2 else None

    if 1 in fits_on:
        margin = caps_sorted[0] - need_1
        if can_split and margin < max(2.5, safety_gb * 1.25):
            color, needed = "yellow", 1
            k2 = 2 if 2 in fits_on else (min(fits_on) if fits_on else 2)
            reason = (
                T("server.web_picker.tight_on_1_mini_need_1", need_1=need_1, caps_sorted=caps_sorted[0], k2=k2, need_each=need_each(k2), runtime_note=runtime_note(k2))
            )
        else:
            color, needed = "green", 1
            reason = T("server.web_picker.fits_on_1_mini_need_1", need_1=need_1, caps_sorted=caps_sorted[0])
    elif fits_on:
        color, needed = "yellow", min(fits_on)
        ne = need_each(needed)
        # capacity of the poorest of the top-needed
        poor = caps_sorted[needed - 1]
        reason = (
            T("server.web_picker.fits_on_needed_minis_about_ne", needed=needed, ne=ne, poor=poor, runtime_note=runtime_note(needed))
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
                T("server.web_picker.wont_fit_need_need_1_gb", need_1=need_1, caps_sorted=caps_sorted[0])
            )
            if can_split:
                reason += T("server.web_picker.or_need_each_gb_min", need_each=need_each(min(2, n_count)), min=min(2, n_count))
                if n_count > 2:
                    reason += T("server.web_picker.or_need_each_gb_n_count", need_each=need_each(n_count), n_count=n_count)
        else:
            reason = T("server.web_picker.wont_fit_on_available_capacity_wanted", suggest=suggest)
    else:
        # Single node — never mention split
        color, needed = "red", None
        reason = (
            T("server.web_picker.wont_fit_on_labels_need_need", labels=labels[0], need_1=need_1, caps_sorted=caps_sorted[0])
        )
        if disk_block:
            reason = disk_block
            limit = "disk"

    # Day 31: the window each placement holds, and the recommendation: the
    # smallest placement that holds the full window (one Mac when it does).
    windows = {}
    for k in fits_on:
        if k > max_stages:
            continue
        best = None
        for t in _window_candidates(target):
            if all(a >= weights_gb / k + kv_at(t) / k + safety_gb for a in caps_sorted[:k]):
                best = t
        if best:
            windows[k] = best
    recommended = needed
    if windows:
        full = [k for k in sorted(windows) if windows[k] >= target]
        if full:
            recommended = full[0]
        else:
            top = max(windows.values())
            recommended = min(k for k in windows if windows[k] == top)
    if windows and (real_kv and (trained or ctx_tokens)) and color != "red":
        w_rec = windows[recommended]
        size = _fmt_window(target)
        if recommended == 1:
            reason = (T("server.web_picker.fits_on_1_mac_with_the", size=size) if w_rec >= target
                      else T("server.web_picker.fits_on_1_mac_with_a", fmt_window=_fmt_window(w_rec)))
            color = "green" if w_rec >= target else "yellow"
        else:
            tail = (T("server.web_picker.for_the_full_size_context", size=size) if w_rec >= target
                    else T("server.web_picker.for_a_fmt_window_context", fmt_window=_fmt_window(w_rec)))
            if 1 in windows:
                reason = (T("server.web_picker.fits_on_1_mac_with_a_2", fmt_window=_fmt_window(windows[1]), recommended=recommended, tail=tail))
            else:
                reason = T("server.web_picker.split_across_recommended_macs_tail", recommended=recommended, tail=tail)
            color = "yellow"

    return {
        "color": color,
        "nodes_needed": needed,
        "recommended_nodes": recommended,
        "window_ctx": {str(k): v for k, v in sorted(windows.items())},
        "trained_ctx": trained,
        "target_ctx": target,
        "kv_gb_full": round(kv_target, 2),
        "kv_source": "config" if real_kv else "estimate",
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
        return [{"error": T("server.web_picker.hf_search_failed_e", e=e)}]
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
        from gguf_sets import groups
        gguf_files = groups(info.get("gguf_files") or [])
        # Multi-file GGUF repo → one row per quant file with its real size.
        if r.get("source") == "gguf" and len(gguf_files) >= 1:
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
        "author": m.get("author") or (repo.split("/")[0] if "/" in repo else None),
        "config": cfg if cfg else None,
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


def _fresh_cloud_keys(out):
    """Day 32: a cached search must not show an old "no key" for cloud rows."""
    for g in out.get("groups") or []:
        for row in [g] + list(g.get("quants") or []):
            if isinstance(row, dict) and row.get("cloud") and row.get("provider"):
                row["api_key_configured"] = _cloud_key_set(row["provider"])
    return out


def search_catalog(query: str = "", *, source: str = "all", limit: int = 30,
                  filt: str = "", newer: bool = False) -> dict:
    """Search HF. source: all|hf-mlx|gguf|cloud. filt: chat|coding|new|… chip."""
    filt = (filt or "").strip().lower()
    filt = _FILTER_ALIASES.get(filt, filt)
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
        return _fresh_cloud_keys(hit)

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
                "api_key_configured": _cloud_key_set("ollama"),
                "provider": "ollama",
                "note": c.get("note") or T("server.web_picker.ollama_cloud_framework_only"),
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
        if want_gguf and filt_key in ("chat", "coding", "thinking", "tools", "vision"):
            gq = q or (spec.get("mlx_search") or ["Instruct"])[0]
            for author in ("bartowski", "unsloth", "lmstudio-community"):
                raw = _search(gq, author=author, filter_gguf=True, limit=max(6, limit // 4))
                _ingest(raw, "gguf", extra_filters=[filt_key, "chat"])
        if filt_key == "image-to-image":
            raw = _search(q or "", pipeline_tag="image-to-image", limit=limit)
            _ingest(raw, "hf-mlx", extra_filters=["image-to-image"])
        if filt_key == "text-to-speech":
            for ptag in ("text-to-speech", "text-to-audio"):
                raw = _search(q or "tts", pipeline_tag=ptag, limit=max(8, limit // 2))
                _ingest(raw, "hf-mlx", extra_filters=["text-to-speech"])
        if filt_key == "speech-to-text":
            for ptag in ("automatic-speech-recognition", "speech-to-text"):
                raw = _search(q or "whisper", pipeline_tag=ptag, limit=max(8, limit // 2))
                _ingest(raw, "hf-mlx", extra_filters=["speech-to-text"])

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
                    "api_key_configured": _cloud_key_set("ollama"),
                    "provider": "ollama",
                    "note": c.get("note") or T("server.web_picker.ollama_cloud_framework_only"),
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
        fam = group_family({"base": base, "quants": quants})
        grouped.append({
            "base": base,
            "source": quants[0]["source"],
            "filters": filters,
            "cloud": any(q.get("cloud") for q in quants),
            "quants": quants,
            "likes": max(q.get("likes") or 0 for q in quants),
            "size_gb_min": min(sizes) if sizes else None,
            "size_gb_max": max(sizes) if sizes else None,
            "family": fam["id"] if fam else None,
            "family_label": fam["label"] if fam else None,
        })
        grouped[-1]["download_only_note"] = serve_notice(
            filters, (quants[0].get("pipeline_tag") if quants else "") or "",
            repo_id=base,
        )
        grouped[-1]["download_only"] = bool(grouped[-1]["download_only_note"])
        for qq in quants:
            if "download_only_note" not in qq:
                qq["download_only_note"] = serve_notice(
                    qq.get("filters") or filters,
                    qq.get("pipeline_tag") or "",
                    repo_id=qq.get("repo_id") or base,
                )
                qq["download_only"] = bool(qq["download_only_note"])
        grouped[-1]["tooltip"] = row_tooltip(grouped[-1])
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
        "families": families_present(grouped[: max(limit, 1)]),
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
                    "reason": T("server.web_picker.cloud_token_usage_not_node_ram"),
                    "weights_gb": None,
                }
            elif not qq.get("weights_gb"):
                qq["fit"] = {
                    "color": "gray", "nodes_needed": None, "fits_on": [],
                    "reason": T("server.web_picker.size_unknown_not_marked_ok"),
                    "weights_gb": None,
                }
            else:
                w = float(qq["weights_gb"])
                gguf = qq.get("source") == "gguf"
                split_ok = qq.get("source") == "hf-mlx" or gguf
                # Day 31: a config already fetched for this repo (placement
                # step, download) sizes the full window; search never waits
                # on one fetch per row.
                cached = None if gguf else _cache_get(f"config:{qq.get('repo_id')}")
                qq["fit"] = fit_check(
                    weights_gb=w, nodes=nodes, split_ok=split_ok,
                    cfg=cached or None,
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
    """Models on this Mini's disk. packer_sizes maps repo_folder -> gb on the helper Mac."""
    packer_sizes = packer_sizes or {}
    found = {}
    from picker_disk_sizes import _looks_like_model
    for root in MLX_MODEL_ROOTS:
        if not root.is_dir():
            continue
        for p in root.iterdir():
            # Day 31 part C: only model folders (not exo's caches/, drafts/
            # or empty leftovers), the same test as each Mac's disk scan.
            if not _looks_like_model(p):
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
    # Day 31 part C: GGUF files come from the same scan as the Settings
    # list (~/.caravan/models, all parts, finished downloads only). The old
    # roots here (~/.caravan/gguf, ~/.ollama/models) are not where Caravan
    # downloads, so Topology showed none of the GGUF models Settings did.
    import gguf_split
    for g in gguf_split.scan_local():
        found.setdefault(g["id"], {
            "id": g["id"],
            "name": Path(g["path"]).name,
            "source": "gguf",
            "paths": {"lead": g["path"]},
            "size_gb": {"lead": g["size_gb"]},
        })
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
        return {"ok": False, "error": T("server.web_picker.missing_id")}
    cur = (current_model_id or "").lower()
    folder = rid.replace("/", "--")
    if cur and (cur == rid.lower() or cur in rid.lower() or folder.lower() in cur):
        return {"ok": False, "error": T("server.web_picker.refuse_model_is_currently_loaded")}
    if rid.startswith("gguf/"):
        return delete_gguf(rid)
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
        return {"ok": False, "error": T("server.web_picker.not_found_on_disk"), "remote": remote}
    return {"ok": True, "removed": removed, "remote": remote}



def delete_gguf(rid: str) -> dict:
    """Day 31 part C: delete one GGUF model (every part) from this Mac.

    GGUF files live only on the 1st Mac; llama.cpp sends each Mac its share
    at load. Only files the Settings scan lists can be deleted, and only
    inside Caravan's GGUF folder. The caller refuses the loaded model."""
    import gguf_split
    from gguf_sets import members
    hit = next((g for g in gguf_split.scan_local() if g["id"] == rid), None)
    if not hit:
        return {"ok": False, "error": T("server.web_picker.not_found_on_disk")}
    p = Path(hit["path"])
    roots = [r.resolve() for r in gguf_split.GGUF_ROOTS]
    if not any(p.resolve().is_relative_to(r) and p.resolve() != r for r in roots) or p.is_symlink():
        return {"ok": False, "error": T("server.web_picker.refuse_not_in_caravans_gguf_folder")}
    folder = p.parent
    nearby = {f.name: f.stat().st_size for f in folder.glob("*.gguf")}
    removed = []
    for name in members(p.name, nearby):
        (folder / name).unlink()
        removed.append(str(folder / name))
    if not any(folder.glob("*.gguf")) and folder.resolve() not in roots:
        for extra in ("caravan-gguf-source.json", "caravan-placement.json"):
            if (folder / extra).is_file():
                (folder / extra).unlink()
        shutil.rmtree(folder / ".cache", ignore_errors=True)
        try:
            folder.rmdir()
        except OSError:
            pass  # something else lives here; leave it
    return {"ok": True, "removed": removed, "remote": None}


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
            "name": T("server.web_picker.download_cache_hugging_face"),
            "note": T("server.web_picker.hub_cache_plus_leftover_cache_folders"),
            "size_gb": {
                "lead": lead_hub,
                "packer": packer.get("hf-cache"),
            },
            "deletable": True,
        },
        {
            "id": "cleanup:drafts",
            "kind": "drafts",
            "name": T("server.web_picker.guess_ahead_helper_models"),
            "note": T("server.web_picker.small_drafts_under_mlx_models_drafts"),
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
        return {"ok": False, "error": T("server.web_picker.unknown_cleanup_kind_kind", kind=kind)}

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
        return {"pct": 0, "msg": T("server.web_picker.progress_error_e", e=e), "have_bytes": 0, "t": time.time(),
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
            return {"ok": False, "error": T("server.web_picker.unknown_job")}
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
    if repo and not job.get('file_mode'):
        killed["lead"] = kill_local_fetch(repo)
    if kill_procs:
        try:
            killed["packer"] = kill_procs(repo, job)
        except Exception as e:  # noqa: BLE001
            killed["packer"] = {"ok": False, "error": str(e)}
    unconfirmed = bool(job.get('file_mode') and not (killed.get('packer') or {}).get('ok'))
    _job_set(jid, status="error" if unconfirmed else "cancelled",
             error="Could not confirm transfer stop; it may still be running. Check the transfer log/network." if unconfirmed else "stopped by user",
             kill=killed, stop_unconfirmed=unconfirmed)
    return {"ok": not unconfirmed, "job": get_job(jid), "killed": killed}


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
                "id": "lead", "label": T("server.web_nodes.1st_mac"), "role": "lead",
                "dest": dest_lead, "run": run_lead,
                "total_bytes": total_bytes_lead, "measure": None,
            })
        dest_packer = dest_packer or f"~/.caravan/mlx-models/{folder}"
        if run_packer:
            runners.append({
                "id": "packer", "label": T("server.web_nodes.2nd_mac"), "role": "packer",
                "dest": dest_packer, "run": run_packer,
                "total_bytes": total_bytes_packer, "measure": measure_packer,
            })

    progress = {}
    for r in runners:
        rid = r.get("id") or r.get("label") or "node"
        progress[rid] = {"pct": 0, "msg": T("server.download_progress.starting"), "have_bytes": 0, "t": time.time(),
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
                            msg = (T("server.web_picker.cant_read_progress_measure_error", measure_error=str(m["measure_error"]))) if m.get("measure_error") else T("server.download_progress.starting")
                            pct = 0
                        elif total:
                            msg = T("server.download_progress.v_v2_gb_mb_s_mb", v=have/1e9, v2=total/1e9, mb_s=mb_s, fmt_eta=_fmt_eta(eta_s))
                        else:
                            msg = T("server.download_progress.v_gb_mb_s_mb_s", v=have/1e9, mb_s=mb_s)
                        if m.get("source") == "nettop":
                            msg += T("server.download_progress.via_network")
                        if n_inc:
                            msg += T("server.web_picker.n_inc_active", n_inc=n_inc)
                        if stalled:
                            msg += T("server.download_progress.stalled")
                        snap = {
                            "pct": pct, "msg": msg, "have_bytes": have,
                            # Day 32: stable code, so the page need not match the words.
                            "msg_code": "cant_read" if (have == 0 and m.get("measure_error")) else None,
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
                    snap = {"pct": 0, "msg": T("server.web_picker.measure_error_e", e=e), "t": time.time(),
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
                            snap.get("have_bytes") and prev_p.get("stage_code") == "starting"):
                        snap["stage"] = prev_p.get("stage")
                        snap["stage_code"] = prev_p.get("stage_code")
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
                def prog(pct, msg, code=None):
                    if get_job(jid) and get_job(jid).get("cancel"):
                        raise RuntimeError("cancelled")
                    with _jobs_lock:
                        cur = dict(_jobs[jid]["progress"].get(rid) or {})
                        # Runner milestones are coarse (5/15/30/100). Keep them as a
                        # stage label; byte-based pct from the watcher stays in charge.
                        cur["stage"] = msg
                        # Day 32: "starting" etc. as a code, not by its words.
                        cur["stage_code"] = code
                        _jobs[jid]["progress"][rid] = cur
                        if cur.get("role") == "lead":
                            _jobs[jid]["progress"]["lead"] = cur
                        if cur.get("role") == "packer":
                            _jobs[jid]["progress"]["packer"] = cur
                try:
                    if not fn:
                        raise RuntimeError(T("server.web_picker.no_runner_for_rid", rid=rid))
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
                                                "error": T("server.web_picker.network_error")}
                                cur["stage"] = T("server.web_picker.network_error_retry_attempt_retry_max", attempt=attempt, retry_max=RETRY_MAX, wait=wait)
                                cur["stage_code"] = "network_retry"
                                _jobs[jid]["progress"][rid] = cur
                            if stop_evt.wait(0) or _sleep_unless_cancel(jid, wait):
                                raise
                except Exception as e:  # noqa: BLE001
                    import logging
                    logging.getLogger("caravan.download").exception(
                        "Download failed on %s: %s", rid, e)
                    from web_nodes import plain_download_error
                    errors.append(plain_download_error(e, log=False))
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
                unconfirmed = bool((get_job(jid) or {}).get('stop_unconfirmed'))
                _mark("failed" if unconfirmed else "stopped")
                _job_set(jid, status="error" if unconfirmed else "cancelled",
                         error="Could not confirm transfer stop; it may still be running. Check transfer logs/network." if unconfirmed else "stopped by user")
                return
            if errors:
                _mark("failed")
                seen = []
                for e in errors:
                    if e not in seen:
                        seen.append(e)
                _job_set(jid, status="error", error=T.join(seen, "clause"))
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
                        pp["msg"] = "done" + (T("server.web_picker.v_gb", v=pp['have_bytes']/1e9) if pp.get("have_bytes") else "")
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
                            # placement-only folders on the lead and none next to the actual weights.
                            if callable(r.get("save_placement")):
                                r["save_placement"](blob)
                            else:
                                write_placement(dest, blob)
                        except Exception as exc:
                            raise RuntimeError(T("server.web_picker.downloaded_files_but_could_not_save", id=r.get('id'), exc=exc)) from exc
                except Exception:
                    raise
            _job_set(jid, status="done", model_folder=folder)
        except Exception as e:  # noqa: BLE001
            for e2 in stops.values():
                e2.set()
            import logging
            logging.getLogger("caravan.download").exception("Download failed: %s", e)
            from web_nodes import plain_download_error
            _job_set(jid, status="error", error=plain_download_error(e, log=False))

    threading.Thread(target=worker, name=f"picker-dl-{jid}", daemon=True).start()
    return get_job(jid)



def local_download_mlx(repo_id: str, dest: str, packer_layers: Optional[int],
                       progress, *, role: str = "lead") -> None:
    """Download only this role's shards using mlx_split_fetch.plan_files."""
    from huggingface_hub import snapshot_download, hf_hub_download
    dest_p = Path(dest).expanduser()
    dest_p.mkdir(parents=True, exist_ok=True)
    progress(5, T("server.web_picker.fetching_index"))
    for fname in ("config.json", "model.safetensors.index.json"):
        try:
            hf_hub_download(repo_id, fname, local_dir=str(dest_p), token=_hf_token())
        except Exception:
            pass
    cfg_path = dest_p / "config.json"
    idx_path = dest_p / "model.safetensors.index.json"
    if not cfg_path.is_file() or not idx_path.is_file():
        # Not an LLM shard layout (diffusion trees, single-file repos, …).
        progress(20, T("server.web_picker.full_snapshot"))
        snapshot_download(repo_id, local_dir=str(dest_p), token=_hf_token())
        progress(100, "done")
        return
    cfg = json.loads(cfg_path.read_text())
    index = json.loads(idx_path.read_text())
    import mlx_split_fetch as MSF
    plan = MSF.plan_files(cfg, index, front_layers=packer_layers)
    role_key = "head" if role == "lead" else "front"
    mine = sorted(plan[role_key])
    progress(15, T("server.web_picker.mine_shards_for_role", mine=len(mine), role=role))
    small = list(MSF.SMALL)
    patterns = small + mine
    progress(30, T("server.web_picker.downloading_shards"))
    snapshot_download(
        repo_id, local_dir=str(dest_p),
        allow_patterns=patterns, token=_hf_token(),
    )
    progress(100, T("server.web_picker.done_mine_shards", mine=len(mine)))
