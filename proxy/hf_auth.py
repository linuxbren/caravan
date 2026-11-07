"""Resolve Hugging Face tokens for Caravan downloads (never echo values).

Order: HF_TOKEN / HUGGING_FACE_HUB_TOKEN env → ~/.caravan/hf_token (Settings)
→ ~/.cache/huggingface/token (huggingface-cli login).
"""
from __future__ import annotations

import os
import hashlib
import json
import threading
import time
import urllib.request
import urllib.error
from pathlib import Path
from typing import Optional

CARAVAN_TOKEN_PATH = Path(os.environ.get(
    "CARAVAN_HF_TOKEN_PATH", str(Path.home() / ".caravan" / "hf_token")
))
HF_CLI_TOKEN_PATH = Path.home() / ".cache" / "huggingface" / "token"


def resolve_hf_token() -> Optional[str]:
    for key in ("HF_TOKEN", "HUGGING_FACE_HUB_TOKEN"):
        v = (os.environ.get(key) or "").strip()
        if v:
            return v
    for p in (CARAVAN_TOKEN_PATH, HF_CLI_TOKEN_PATH):
        try:
            if p.is_file():
                t = p.read_text().strip()
                if t:
                    return t
        except OSError:
            pass
    return None


def token_status() -> dict:
    """Safe status for the Settings page — never includes the secret."""
    env = bool((os.environ.get("HF_TOKEN") or os.environ.get("HUGGING_FACE_HUB_TOKEN") or "").strip())
    caravan = False
    try:
        caravan = CARAVAN_TOKEN_PATH.is_file() and bool(CARAVAN_TOKEN_PATH.read_text().strip())
    except OSError:
        caravan = False
    cli = False
    try:
        cli = HF_CLI_TOKEN_PATH.is_file() and bool(HF_CLI_TOKEN_PATH.read_text().strip())
    except OSError:
        cli = False
    tok = resolve_hf_token()
    source = None
    if env:
        source = "env"
    elif caravan:
        source = "settings"
    elif cli:
        source = "huggingface-cli"
    return {
        "configured": bool(tok),
        "source": source,
        "has_env": env,
        "has_settings": caravan,
        "has_cli": cli,
    }


def save_caravan_token(token: str) -> dict:
    token = (token or "").strip()
    if not token:
        return clear_caravan_token()
    CARAVAN_TOKEN_PATH.parent.mkdir(parents=True, exist_ok=True)
    CARAVAN_TOKEN_PATH.write_text(token + "\n")
    try:
        os.chmod(CARAVAN_TOKEN_PATH, 0o600)
    except OSError:
        pass
    return token_status()


def clear_caravan_token() -> dict:
    try:
        if CARAVAN_TOKEN_PATH.is_file():
            CARAVAN_TOKEN_PATH.unlink()
    except OSError:
        pass
    return token_status()


_validation_cache = {}
_validation_lock = threading.Lock()


def validated_token_status() -> dict:
    """Check whoami server-side; cache only a digest and safe outcome for 60s."""
    status = token_status()
    token = resolve_hf_token()
    if not token:
        return {**status, "validation": "missing"}
    key = hashlib.sha256(token.encode()).hexdigest()
    with _validation_lock:
        cached = _validation_cache.get(key)
        if cached and cached[0] > time.monotonic():
            return {**status, **cached[1]}
        result = {"validation": "unavailable"}
        try:
            request = urllib.request.Request(
                "https://huggingface.co/api/whoami-v2",
                headers={"Authorization": "Bearer " + token},
            )
            with urllib.request.urlopen(request, timeout=5) as response:
                info = json.load(response)
            if isinstance(info, dict) and info.get("name"):
                result = {"validation": "accepted"}
        except urllib.error.HTTPError as exc:
            if exc.code in (401, 403):
                result = {"validation": "rejected"}
        except Exception:
            # Never return exception strings: HTTP clients can include credentials.
            pass
        _validation_cache.clear()
        _validation_cache[key] = (time.monotonic() + 60, result)
        return {**status, **result}
