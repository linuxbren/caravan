"""Memory-compression quality: when 4 is unsafe, and a short load-time probe.

4-bit Memory compression is unreliable on models that share chat memory
across many query heads (few key/value heads). Qwen2.5 Coder 1.5B
(2 heads) and 7B (4 heads) both fall under that rule. The page hides
4 for those models, and a short known-answer probe after any load at
4 or 8 catches the rest.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Optional

# User-facing. No jargon, no hostnames, no model architecture names.
DISABLED_4_REASON = (
    "4 is not available on this model. This model's chat memory is too "
    "compact for 4 to work well."
)
FALLBACK_NOTE = (
    "Memory compression 4 is not available on this model, so it was "
    "turned back to Auto."
)
PROBE_PROMPT = "Reply with just: OK"
PROBE_EXPECT = "OK"
PROBE_MAX_TOKENS = 16
# First request after a load can pay for a compile; keep this bounded.
PROBE_TIMEOUT = 20.0

# num_key_value_heads at or below this cannot use 4 reliably.
MAX_KV_HEADS_FOR_4 = 4


def read_model_config(model_dir) -> dict:
    """Load a model's config.json. Empty dict if it is missing or unreadable."""
    if not model_dir:
        return {}
    path = Path(model_dir) / "config.json"
    try:
        raw = json.loads(path.read_text())
    except (OSError, ValueError, TypeError):
        return {}
    return raw if isinstance(raw, dict) else {}


def _as_int_min(value):
    """A single count, or the smallest of a list (sliding-window models)."""
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, (list, tuple)):
        nums = []
        for x in value:
            try:
                nums.append(int(x))
            except (TypeError, ValueError):
                continue
        return min(nums) if nums else None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def key_value_heads(config) -> Optional[int]:
    """How many key/value heads the model uses for chat memory.

    Looks at the usual config keys, including a nested text/language
    config, and takes the smallest value when a model lists several.
    """
    if not isinstance(config, dict):
        return None
    keys = (
        "num_key_value_heads",
        "num_kv_heads",
        "n_kv_heads",
        "num_key_value_head",
    )
    for k in keys:
        n = _as_int_min(config.get(k))
        if n is not None:
            return n
    for nest in ("text_config", "language_config", "llm_config", "model_config", "decoder_config"):
        sub = config.get(nest)
        if isinstance(sub, dict):
            n = key_value_heads(sub)
            if n is not None:
                return n
    return None


def allows_memory_compression_4(config=None, *, model_dir=None) -> bool:
    """True when Memory compression 4 may be offered for this model.

    Unknown configs (no head count) are allowed; the load-time probe
    still checks 4 and 8 after a load.
    """
    cfg = config if isinstance(config, dict) else read_model_config(model_dir)
    n = key_value_heads(cfg)
    if n is None:
        return True
    return n > MAX_KV_HEADS_FOR_4


def disabled_values_for(config=None, *, model_dir=None, source="mlx") -> dict:
    """Map of Memory compression values the page should show as disabled."""
    src = (source or "mlx").lower()
    if src == "gguf":
        return {}  # 4 is already omitted from the GGUF value list
    if allows_memory_compression_4(config, model_dir=model_dir):
        return {}
    return {"4": DISABLED_4_REASON}


def probe_fail_notice(kv) -> str:
    label = str(kv if kv is not None else "").strip() or "this setting"
    return (
        f"Memory compression {label} gave wrong answers on this model, "
        "so it was turned back to 16."
    )


def probe_answer_ok(text: Optional[str]) -> bool:
    """True only when the reply is essentially the known answer (OK)."""
    import re
    try:
        from garble import is_garbled, strip_special_markers
        raw = text or ""
        if is_garbled(raw):
            return False
        vis = strip_special_markers(raw)
    except Exception:
        vis = text or ""
    vis = (vis or "").strip()
    if not vis:
        return False
    # Letters/digits only: "OK.", '"OK"', and "OK" all count as the one
    # word OK. A ramble that merely contains OK does not.
    words = re.findall(r"[A-Za-z0-9]+", vis)
    if not words:
        return False
    return all(w.upper() == PROBE_EXPECT for w in words) and len(words) <= 2


def run_http_probe(port: int, *, timeout: float = PROBE_TIMEOUT, urlopen=None) -> dict:
    """Ask the local worker the known prompt. Does not apply a fix."""
    import time
    import urllib.request
    from urllib.error import HTTPError, URLError

    urlopen = urlopen or urllib.request.urlopen
    body = json.dumps({
        "messages": [{"role": "user", "content": PROBE_PROMPT}],
        "max_tokens": PROBE_MAX_TOKENS,
        "temperature": 0,
        "stream": False,
        "thinking": False,
    }).encode()
    req = urllib.request.Request(
        f"http://127.0.0.1:{int(port)}/v1/chat/completions",
        data=body,
        headers={
            "Content-Type": "application/json",
            "X-Caravan-Session": "kv-probe",
        },
        method="POST",
    )
    t0 = time.monotonic()
    content = ""
    error = None
    try:
        with urlopen(req, timeout=timeout) as resp:
            data = json.loads(resp.read())
        for ch in (data.get("choices") or []):
            msg = ch.get("message") or {}
            if isinstance(msg.get("content"), str):
                content += msg["content"]
    except (HTTPError, URLError, OSError, TimeoutError, ValueError, TypeError) as exc:
        error = f"{type(exc).__name__}: {exc}"[:200]
        data = None
    elapsed = time.monotonic() - t0
    ok = False if error else probe_answer_ok(content)
    return {
        "ok": ok,
        "content": content,
        "elapsed": round(elapsed, 3),
        "error": error,
        # A transport failure is not a definite wrong answer.
        "definite": error is None,
    }
