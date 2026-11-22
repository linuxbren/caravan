"""Cloud model API keys (Day 32). Never echo, never log a key.

Keys typed in Settings are kept in one file, ``~/.caravan/cloud-keys.json``,
readable only by you (0600, written atomically). The page and the API only
ever see whether a key is set and its last 4 characters. An environment
variable (for example ``OPENAI_API_KEY``) still wins, as before, and is
shown as "from the environment"; it cannot be edited from the page.
"""
from __future__ import annotations

import json
import os
import re
import tempfile
from pathlib import Path
from typing import Optional

PROVIDERS = {
    "openai": {"label": "OpenAI", "env": ("OPENAI_API_KEY", "CARAVAN_OPENAI_API_KEY")},
    "anthropic": {"label": "Anthropic", "env": ("ANTHROPIC_API_KEY", "CARAVAN_ANTHROPIC_API_KEY")},
    "openrouter": {"label": "OpenRouter", "env": ("OPENROUTER_API_KEY", "CARAVAN_OPENROUTER_API_KEY")},
    "ollama": {"label": "Ollama Cloud", "env": ("OLLAMA_API_KEY", "CARAVAN_OLLAMA_API_KEY")},
}
ORDER = ("openai", "anthropic", "openrouter", "ollama")

_KEY_OK = re.compile(r"^[A-Za-z0-9._\-:+/=]{8,512}$")


def keys_path(home=None) -> Path:
    env = os.environ.get("CARAVAN_CLOUD_KEYS_PATH")
    if env and home is None:
        return Path(env)
    return Path(home or Path.home()) / ".caravan" / "cloud-keys.json"


def _load(home=None) -> dict:
    try:
        data = json.loads(keys_path(home).read_text())
    except (OSError, ValueError):
        return {}
    if not isinstance(data, dict):
        return {}
    return {k: v for k, v in data.items() if k in PROVIDERS and isinstance(v, str) and v}


def _save(data: dict, home=None) -> None:
    path = keys_path(home)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=".cloud-keys.", dir=str(path.parent))
    try:
        os.fchmod(fd, 0o600)
        with os.fdopen(fd, "w") as f:
            json.dump(data, f, indent=2, sort_keys=True)
            f.write("\n")
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise
    os.chmod(path, 0o600)


def _env_key(provider: str) -> Optional[str]:
    for name in PROVIDERS[provider]["env"]:
        v = (os.environ.get(name) or "").strip()
        if v:
            return v
    return None


def resolve(provider: str, home=None) -> Optional[str]:
    """The key to use (environment first, then Settings), or None."""
    if provider not in PROVIDERS:
        return None
    return _env_key(provider) or _load(home).get(provider) or None


def last4(key: Optional[str]) -> Optional[str]:
    return key[-4:] if key and len(key) >= 8 else None


def status(home=None) -> dict:
    """What the page may see: set or not, where from, last 4 characters."""
    saved = _load(home)
    rows = []
    for pid in ORDER:
        env = _env_key(pid)
        key = env or saved.get(pid)
        rows.append({
            "id": pid,
            "label": PROVIDERS[pid]["label"],
            "set": bool(key),
            "source": "environment" if env else ("settings" if key else None),
            "last4": last4(key),
            "editable": not env,
            "env_name": PROVIDERS[pid]["env"][0],
        })
    return {"providers": rows}


class CloudKeyError(ValueError):
    pass


def save(provider: str, key: str, home=None) -> dict:
    if provider not in PROVIDERS:
        raise CloudKeyError("Unknown provider.")
    key = (key or "").strip()
    if not _KEY_OK.match(key):
        # Never repeat the key in the message.
        raise CloudKeyError("That doesn't look like an API key. Paste the whole key, with no spaces.")
    data = _load(home)
    data[provider] = key
    _save(data, home)
    return status(home)


def remove(provider: str, home=None) -> dict:
    if provider not in PROVIDERS:
        raise CloudKeyError("Unknown provider.")
    data = _load(home)
    if provider in data:
        del data[provider]
        _save(data, home)
    return status(home)
