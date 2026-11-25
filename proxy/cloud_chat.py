"""Day 33 (CAR-8): chat with Ollama Cloud models through Caravan.

Picking a cloud model in Models sends the chat to Ollama's cloud API
instead of the Macs. The chat page, streaming, Stop and the message queue
work the same; replies are labeled CLOUD.

Ollama's documented cloud API (https://docs.ollama.com/cloud/api,
https://docs.ollama.com/api/authentication, checked 2026-11-24):

* ``POST https://ollama.com/api/chat`` with ``Authorization: Bearer <key>``.
  Streaming (the default) answers in newline-delimited JSON; each line has
  ``message.content`` (and ``message.thinking`` when thinking is on), and the
  last line has ``done: true``, ``done_reason`` and the token counts and
  durations (nanoseconds). An error mid-stream is a line with ``error``.
* ``GET https://ollama.com/api/tags`` lists the model names to use for
  direct requests, such as ``gpt-oss:120b`` (the ``-cloud`` / ``:cloud``
  names are only for a signed-in local Ollama).
* Errors are JSON ``{"error": "..."}`` with 400, 401/403, 404, 429, 500, 502.

The key comes from ``cloud_keys.resolve`` (environment first, then the
0600 file). It is only ever put in the Authorization header: never logged,
never in an error, never sent to the page, the journal or a saved chat.
"""
from __future__ import annotations

import json
import os
import re
import socket
import tempfile
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Iterable, Iterator, Optional

try:
    from caravan_i18n import T  # noqa: E402
except ImportError:  # run without tools/ on the path
    import sys as _sys
    from pathlib import Path as _Path
    _sys.path.append(str(_Path(__file__).resolve().parents[1] / "tools"))
    from caravan_i18n import T  # noqa: E402

PREFIX = "ollama-cloud/"
PROVIDER = "ollama"
# Tests point this at a local mock server. Never logged with the key.
DEFAULT_BASE = "https://ollama.com"
CONNECT_TIMEOUT_S = float(os.environ.get("CARAVAN_CLOUD_TIMEOUT_S", "60"))
CATALOG_TIMEOUT_S = 4.0
CATALOG_TTL_S = 600.0
_NAME_OK = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:\-/]{0,127}$")
_ROLES = ("system", "user", "assistant", "tool")
_EFFORTS = ("low", "medium", "high")


def base_url() -> str:
    return (os.environ.get("CARAVAN_OLLAMA_CLOUD_URL") or DEFAULT_BASE).rstrip("/")


def is_cloud_id(model_id) -> bool:
    return isinstance(model_id, str) and model_id.startswith(PREFIX)


def direct_name(model_id: str) -> str:
    """``ollama-cloud/gpt-oss:120b-cloud`` -> ``gpt-oss:120b`` (the name the
    direct API wants). Older Day 32 ids carried the local ``-cloud`` /
    ``:cloud`` suffix."""
    name = str(model_id or "")
    if name.startswith(PREFIX):
        name = name[len(PREFIX):]
    if name.endswith(":cloud"):
        name = name[: -len(":cloud")]
    elif name.endswith("-cloud"):
        name = name[: -len("-cloud")]
    return name.strip()


def valid_name(name: str) -> bool:
    return bool(name) and bool(_NAME_OK.match(name)) and ".." not in name


class CloudError(Exception):
    """A plain error for the page. ``status`` is the HTTP code Caravan
    answers with; ``code`` is a stable machine word."""

    def __init__(self, status: int, code: str, message: str):
        super().__init__(message)
        self.status = status
        self.code = code
        self.message = message


def scrub(text, key: Optional[str]) -> str:
    """Never let a key (or most of one) reach a message."""
    s = str(text or "")
    if key:
        for part in {key, key[:-4] if len(key) > 12 else None}:
            if part:
                s = s.replace(part, "…")
    s = re.sub(r"(?i)bearer\s+[A-Za-z0-9._\-:+/=]{8,}", "Bearer …", s)
    return s


def _server_words(raw: bytes, key: Optional[str]) -> str:
    try:
        obj = json.loads(raw.decode("utf-8", errors="replace") or "{}")
        msg = obj.get("error") if isinstance(obj, dict) else None
        if isinstance(msg, dict):
            msg = msg.get("message")
    except ValueError:
        msg = None
    return scrub(str(msg or "").strip()[:200], key)


def http_error(code: int, raw: bytes, model: str, key: Optional[str]) -> CloudError:
    said = _server_words(raw, key)
    if code in (401, 403):
        return CloudError(401, "cloud_key_rejected", T("server.cloud_chat.ollama_cloud_did_not_accept_the_key"))
    if code == 404:
        return CloudError(404, "cloud_model_not_found", T("server.cloud_chat.ollama_cloud_has_no_model_named", model=model))
    if code == 429:
        return CloudError(429, "cloud_rate_limited", T("server.cloud_chat.ollama_cloud_says_too_many_requests"))
    if code >= 500:
        return CloudError(502, "cloud_unavailable", T("server.cloud_chat.ollama_cloud_could_not_answer_right", code=code))
    if said:
        return CloudError(400, "cloud_bad_request", T("server.cloud_chat.ollama_cloud_refused_the_request_said", code=code, said=said))
    return CloudError(400, "cloud_bad_request", T("server.cloud_chat.ollama_cloud_refused_the_request", code=code))


def network_error(e: BaseException) -> CloudError:
    if isinstance(e, (socket.timeout, TimeoutError)) or "timed out" in str(e).lower():
        return CloudError(504, "cloud_timeout", T("server.cloud_chat.ollama_cloud_did_not_answer_in_time"))
    return CloudError(502, "cloud_unreachable", T("server.cloud_chat.could_not_reach_ollama_cloud_check"))


def build_payload(body: dict, model: str, stream: bool, *, with_think: bool = True) -> dict:
    """The page's OpenAI-shaped chat body -> Ollama /api/chat body."""
    msgs = []
    for m in body.get("messages") or []:
        if not isinstance(m, dict):
            continue
        role = m.get("role")
        content = m.get("content")
        if isinstance(content, list):  # OpenAI content parts: keep the text
            content = "".join(p.get("text", "") for p in content
                              if isinstance(p, dict) and p.get("type") == "text")
        if role not in _ROLES or not isinstance(content, str):
            continue
        msgs.append({"role": role, "content": content})
    out = {"model": model, "messages": msgs, "stream": bool(stream)}
    opts = {}
    for src, dst in (("temperature", "temperature"), ("top_p", "top_p"), ("top_k", "top_k"),
                     ("seed", "seed"), ("max_tokens", "num_predict"),
                     ("max_completion_tokens", "num_predict")):
        v = body.get(src)
        if isinstance(v, (int, float)) and not isinstance(v, bool):
            opts[dst] = v
    if isinstance(body.get("stop"), (list, str)):
        opts["stop"] = body["stop"] if isinstance(body["stop"], list) else [body["stop"]]
    if opts:
        out["options"] = opts
    if with_think:
        kw = body.get("chat_template_kwargs") if isinstance(body.get("chat_template_kwargs"), dict) else {}
        effort = kw.get("reasoning_effort") or body.get("reasoning_effort")
        if effort in _EFFORTS:
            out["think"] = effort
        elif isinstance(body.get("thinking"), bool):
            out["think"] = body["thinking"]
        elif isinstance(kw.get("enable_thinking"), bool):
            out["think"] = kw["enable_thinking"]
    return out


def _request(path: str, key: Optional[str], data: Optional[dict] = None, method: str = "GET"):
    headers = {"User-Agent": "caravan-cloud/1.0", "Accept": "application/json, application/x-ndjson"}
    if data is not None:
        headers["Content-Type"] = "application/json"
    if key:
        headers["Authorization"] = "Bearer " + key
    raw = json.dumps(data).encode() if data is not None else None
    return urllib.request.Request(base_url() + path, data=raw, headers=headers, method=method)


def open_chat(body: dict, model: str, key: str, *, stream: bool = True, opener=None, timeout=None):
    """Open ``POST /api/chat``. Returns the open HTTP response.

    A model that does not support the thinking switch answers 400 about
    ``think``; then the request is sent once more without it. Raises
    ``CloudError`` with a plain message (never the key)."""
    if not key:
        raise CloudError(400, "cloud_key_missing", T("server.cloud_chat.add_your_ollama_cloud_key_in"))
    if not valid_name(model):
        raise CloudError(400, "cloud_bad_model", T("server.cloud_chat.that_cloud_model_name_doesnt_look"))
    opener = opener or urllib.request.urlopen
    timeout = CONNECT_TIMEOUT_S if timeout is None else timeout
    payload = build_payload(body, model, stream)
    for attempt in (0, 1):
        try:
            return opener(_request("/api/chat", key, payload, "POST"), timeout=timeout)
        except urllib.error.HTTPError as e:
            try:
                raw = e.read() or b""
            except Exception:  # noqa: BLE001
                raw = b""
            if (attempt == 0 and e.code == 400 and "think" in payload
                    and "think" in _server_words(raw, key).lower()):
                payload = build_payload(body, model, stream, with_think=False)
                continue
            raise http_error(e.code, raw, model, key) from None
        except (urllib.error.URLError, OSError, ValueError) as e:
            raise network_error(e) from None
    raise CloudError(502, "cloud_unavailable", T("server.cloud_chat.could_not_reach_ollama_cloud_check"))


def iter_events(lines: Iterable[bytes]) -> Iterator[dict]:
    """NDJSON lines -> dict events. Blank or broken lines are skipped."""
    for line in lines:
        line = (line or b"").strip()
        if not line:
            continue
        try:
            obj = json.loads(line.decode("utf-8", errors="replace"))
        except ValueError:
            continue
        if isinstance(obj, dict):
            yield obj


def chunk(model: str, rid: str, delta: dict, finish=None, usage=None) -> dict:
    """One OpenAI-shaped stream chunk, so the page reads it like a Mac reply."""
    out = {"id": rid, "object": "chat.completion.chunk", "created": int(time.time()), "model": model,
           "choices": [{"index": 0, "delta": delta, "finish_reason": finish}]}
    if usage is not None:
        out["usage"] = usage
    return out


def usage_from_done(done: dict, *, ttft_s=None, total_s=None) -> dict:
    """Token counts from Ollama's last event; times measured at Caravan,
    plus Ollama's own read/write durations when it sends them. Missing
    values stay missing (never made up)."""
    def num(k):
        v = done.get(k)
        return v if isinstance(v, (int, float)) and not isinstance(v, bool) and v >= 0 else None
    pt, ct = num("prompt_eval_count"), num("eval_count")
    cav = {"cloud": True}
    if ttft_s is not None:
        cav["ttft_s"] = round(float(ttft_s), 6)
    if total_s is not None:
        cav["total_s"] = round(float(total_s), 6)
    ped, ed = num("prompt_eval_duration"), num("eval_duration")
    if ped:
        cav["prefill_s"] = round(ped / 1e9, 6)
    if ct is not None and ed:
        cav["write_tok_s"] = round(ct / (ed / 1e9), 2)
    usage = {"caravan": cav}
    if pt is not None:
        usage["prompt_tokens"] = int(pt)
    if ct is not None:
        usage["completion_tokens"] = int(ct)
    if pt is not None and ct is not None:
        usage["total_tokens"] = int(pt + ct)
    cached = num("prompt_eval_cached_count")
    if cached is not None:
        usage["prompt_tokens_details"] = {"cached_tokens": int(cached)}
    return usage


def to_completion(data: dict, model: str, rid: str) -> dict:
    msg = data.get("message") if isinstance(data.get("message"), dict) else {}
    out_msg = {"role": "assistant", "content": msg.get("content") or ""}
    if msg.get("thinking"):
        out_msg["reasoning_content"] = msg["thinking"]
    return {"id": rid, "object": "chat.completion", "created": int(time.time()), "model": model,
            "choices": [{"index": 0, "finish_reason": data.get("done_reason") or "stop", "message": out_msg}]}


# ---- which cloud model chats go to (kept across a restart)

CHOICE_FILE = "cloud-choice.json"


class Choice:
    """The picked cloud model. Saved next to ``last-model.json`` in the web
    state folder (``cloud-choice.json``: schema 1, 0600, written
    atomically), so a restart goes back to how it was: cloud if it was
    cloud, the Macs if it was the Macs. Only the provider and model name
    are saved, never the key."""

    def __init__(self, path=None):
        self._lock = threading.Lock()
        self._cur = None
        self.path = Path(path) if path else None
        self.restored = False
        if self.path is not None:
            saved = self._read()
            if saved:
                self._cur = self._row(saved["model"], saved["label"], saved["provider"])
                self.restored = True

    @staticmethod
    def _row(model: str, label: str, provider: str = PROVIDER) -> dict:
        return {"provider": provider, "label": label, "model": model,
                "model_id": PREFIX + model, "name": model, "cloud": True, "cloud_label": "CLOUD"}

    def _read(self) -> Optional[dict]:
        try:
            if self.path.stat().st_size > 64 * 1024:
                return None
            blob = json.loads(self.path.read_text())
        except (OSError, ValueError):
            return None
        if not isinstance(blob, dict) or blob.get("schema") != 1:
            return None
        ch = blob.get("choice")
        if not isinstance(ch, dict):
            return None
        provider, model = ch.get("provider"), ch.get("model")
        if provider != PROVIDER or not isinstance(model, str) or not valid_name(model):
            return None
        label = ch.get("label") if isinstance(ch.get("label"), str) and ch.get("label") else T("server.cloud_keys.ollama_cloud")
        return {"provider": provider, "model": model, "label": label}

    def _write(self, cur: Optional[dict]) -> None:
        if self.path is None:
            return
        choice = None if not cur else {k: cur[k] for k in ("provider", "model", "label")}
        self.path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(prefix=".cloud-choice.", dir=str(self.path.parent))
        try:
            os.fchmod(fd, 0o600)
            with os.fdopen(fd, "w") as f:
                json.dump({"schema": 1, "saved_at": time.time(), "choice": choice}, f, indent=2)
                f.flush()
                os.fsync(f.fileno())
            os.replace(tmp, self.path)
        except BaseException:
            try:
                os.unlink(tmp)
            except OSError:
                pass
            raise

    def get(self) -> Optional[dict]:
        with self._lock:
            return dict(self._cur) if self._cur else None

    def set(self, model: str, label: str) -> dict:
        cur = self._row(model, label)
        with self._lock:
            self._write(cur)
            self._cur = cur
            self.restored = False
        return dict(cur)

    def clear(self) -> bool:
        with self._lock:
            had = self._cur is not None
            if had or (self.path is not None and self.path.exists()):
                self._write(None)
            self._cur = None
            self.restored = False
        return had


# ---- model list (GET /api/tags is public; cached)

# Shown when the live list can't be read. Names from https://ollama.com/api/tags
# on 2026-11-24; a stale name answers "Ollama Cloud has no model named …".
FALLBACK_MODELS = ("gpt-oss:120b", "gpt-oss:20b", "gemma4:31b")
_PREFERRED = ("gpt-oss:120b", "gpt-oss:20b", "gemma4:31b")
_cat_lock = threading.Lock()
_cat = {"t": 0.0, "rows": None}


def live_catalog_enabled() -> bool:
    return (os.environ.get("CARAVAN_OLLAMA_CLOUD_CATALOG") or "live").strip().lower() != "static"


def list_models(*, opener=None, timeout=CATALOG_TIMEOUT_S) -> list:
    """Model rows from ``GET /api/tags``: [{name, capabilities}]. Raises
    ``CloudError`` on any failure."""
    opener = opener or urllib.request.urlopen
    try:
        with opener(_request("/api/tags", None), timeout=timeout) as r:
            data = json.loads(r.read().decode("utf-8", errors="replace"))
    except urllib.error.HTTPError as e:
        raise http_error(e.code, b"", "", None) from None
    except (urllib.error.URLError, OSError, ValueError) as e:
        raise network_error(e) from None
    rows = []
    for m in (data.get("models") if isinstance(data, dict) else None) or []:
        if not isinstance(m, dict):
            continue
        name = str(m.get("name") or m.get("model") or "").strip()
        if not valid_name(name):
            continue
        caps = [c for c in (m.get("capabilities") or []) if isinstance(c, str)]
        rows.append({"name": name, "capabilities": caps})
    rank = {n: i for i, n in enumerate(_PREFERRED)}
    rows.sort(key=lambda r: (rank.get(r["name"], len(rank)), r["name"]))
    return rows


def catalog(*, opener=None) -> tuple:
    """(rows, live: bool). Live list when it can be read (cached), else the
    short fallback list."""
    now = time.time()
    with _cat_lock:
        if _cat["rows"] is not None and now - _cat["t"] < CATALOG_TTL_S:
            return list(_cat["rows"]), True
    if live_catalog_enabled():
        try:
            rows = list_models(opener=opener)
        except CloudError:
            rows = []
        if rows:
            with _cat_lock:
                _cat.update(t=now, rows=rows)
            return list(rows), True
    return [{"name": n, "capabilities": []} for n in FALLBACK_MODELS], False


def clear_catalog_cache() -> None:
    with _cat_lock:
        _cat.update(t=0.0, rows=None)
