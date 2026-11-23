"""Cloud model API keys (Day 32). Never echo, never log a key.

Keys typed in Settings are kept in one file, ``~/.caravan/cloud-keys.json``,
readable only by you (0600, written atomically). The page and the API only
ever see whether a key is set and its last 4 characters. An environment
variable (``OLLAMA_API_KEY``) still wins, as before, and is shown as
"from the environment"; it cannot be edited from the page.

Only Ollama Cloud for now: it is the only cloud source the Models picker
can search. To add a provider later, add one entry to PROVIDERS (label and
env names); Settings shows one row per entry, in this order.
"""
from __future__ import annotations

import json
import os
import re
import tempfile
from pathlib import Path
from typing import Optional
try:
    from caravan_i18n import T  # noqa: E402  (Day 32: user-facing text, tools/caravan_i18n.py)
except ImportError:  # run without tools/ on the path
    import sys as _sys
    from pathlib import Path as _Path
    _sys.path.append(str(_Path(__file__).resolve().parents[1] / "tools"))
    from caravan_i18n import T  # noqa: E402

PROVIDERS = {
    "ollama": {"label": T("server.cloud_keys.ollama_cloud"), "env": ("OLLAMA_API_KEY", "CARAVAN_OLLAMA_API_KEY")},
}
ORDER = tuple(PROVIDERS)

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
        raise CloudKeyError(T("server.cloud_keys.unknown_provider"))
    key = (key or "").strip()
    if not _KEY_OK.match(key):
        # Never repeat the key in the message.
        raise CloudKeyError(T("server.cloud_keys.that_doesnt_look_like_an_api"))
    data = _load(home)
    data[provider] = key
    _save(data, home)
    return status(home)


def remove(provider: str, home=None) -> dict:
    if provider not in PROVIDERS:
        raise CloudKeyError(T("server.cloud_keys.unknown_provider"))
    data = _load(home)
    if provider in data:
        del data[provider]
        _save(data, home)
    return status(home)
