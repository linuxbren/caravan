"""Opt-in model-warning ping (Day 18).

Off unless CARAVAN_ALERT_WEBHOOK_URL is set. When on, the web server POSTs
{model, warnings, mini, caravan_version} once per (model, warning set) the
first time it sees a model with warnings. Dedupe lives in
~/.caravan/alert-sent.json. Runs in a background thread with a short timeout,
so it never blocks the UI. Nothing is ever sent for users who don't set it.
Optional CARAVAN_ALERT_WEBHOOK_KEY is sent as both `Authorization: Bearer`
and `X-Webhook-Key`.
"""
from __future__ import annotations

import hashlib
import json
import os
import socket
import subprocess
import threading
from pathlib import Path
from urllib.request import Request, urlopen

TIMEOUT_S = 5.0
_lock = threading.Lock()
_VERSION = None


def caravan_version() -> str:
    """Short commit (or VERSION file / 'unknown'). No paths, no hostnames."""
    global _VERSION
    if _VERSION:
        return _VERSION
    root = Path(__file__).resolve().parent.parent
    v = os.environ.get("CARAVAN_VERSION", "").strip()
    if not v:
        try:
            v = subprocess.run(["git", "-C", str(root), "rev-parse", "--short", "HEAD"],
                               capture_output=True, text=True, timeout=3).stdout.strip()
        except Exception:  # noqa: BLE001
            v = ""
    if not v and (root / "VERSION").is_file():
        v = (root / "VERSION").read_text().strip()
    _VERSION = v or "unknown"
    return _VERSION


def config(env=None) -> dict:
    env = os.environ if env is None else env
    return {"url": (env.get("CARAVAN_ALERT_WEBHOOK_URL") or "").strip(),
            "key": (env.get("CARAVAN_ALERT_WEBHOOK_KEY") or "").strip()}


def state_path() -> Path:
    return Path(os.path.expanduser("~/.caravan/alert-sent.json"))


def alert_key(model: str, warnings) -> str:
    h = hashlib.sha256("\n".join(sorted(warnings)).encode()).hexdigest()[:16]
    return f"{model}|{h}"


def build_payload(model: str, warnings, mini: str = None, version: str = None) -> dict:
    return {"model": model, "warnings": sorted(warnings),
            "mini": mini or socket.gethostname().split(".")[0],
            "caravan_version": version or caravan_version()}


def _load(p: Path) -> dict:
    try:
        d = json.loads(p.read_text())
        return d if isinstance(d, dict) else {}
    except Exception:  # noqa: BLE001
        return {}


def pending(rows, sent: dict) -> list:
    out = []
    for r in rows or []:
        w = [x for x in (r.get("warnings") or []) if x]
        m = r.get("hf") or r.get("id")
        if not w or not m:
            continue
        k = alert_key(m, w)
        if k not in sent and k not in {alert_key(*x) for x in out}:
            out.append((m, w))
    return out


def _post(url: str, key: str, payload: dict) -> bool:
    hdr = {"Content-Type": "application/json", "User-Agent": "caravan-alert"}
    if key:
        hdr["Authorization"] = f"Bearer {key}"
        hdr["X-Webhook-Key"] = key
    try:
        with urlopen(Request(url, data=json.dumps(payload).encode(), headers=hdr, method="POST"),
                     timeout=TIMEOUT_S) as r:
            return 200 <= r.status < 300
    except Exception:  # noqa: BLE001
        return False


def check_and_send(rows, env=None, path: Path = None, post=_post, mini=None, version=None) -> list:
    """Synchronous core (tests call this). Returns payloads successfully sent."""
    cfg = config(env)
    if not cfg["url"]:
        return []
    p = path or state_path()
    with _lock:
        sent = _load(p)
        todo = pending(rows, sent)
        done = []
        for m, w in todo:
            pl = build_payload(m, w, mini, version)
            if post(cfg["url"], cfg["key"], pl):
                sent[alert_key(m, w)] = True
                done.append(pl)
        if done:
            try:
                p.parent.mkdir(parents=True, exist_ok=True)
                p.write_text(json.dumps(sent, indent=1))
            except OSError:
                pass
        return done


def maybe_alert_async(rows) -> None:
    """Fire-and-forget; no-op (no thread) when the env var is unset."""
    if not config()["url"]:
        return
    rows = [{"hf": r.get("hf"), "id": r.get("id"), "warnings": list(r.get("warnings") or [])}
            for r in rows or [] if r.get("warnings")]
    if rows:
        threading.Thread(target=check_and_send, args=(rows,), daemon=True).start()
