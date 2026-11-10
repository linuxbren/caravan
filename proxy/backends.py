"""Backend routing for the Caravan proxy (2026-10-30, MLX step a).

The proxy is the one front door. Each completion request is routed by its
`model` field to a backend:

  * "llama" -- llama-server (GGUF). Everything the proxy did before:
    per-session slot pinning (id_slot), FIFO serialization, disk slot
    save/restore. This is the default for anything not matched below.
  * "mlx"   -- the Caravan MLX worker (agent/mlx_worker.py, step b,
    2026-10-31) on this Mini (MLX safetensors models). Same FIFO and the
    same per-session fingerprint (sent as X-Caravan-Session), no id_slot;
    restore before a session's first turn and save after replies go to
    POST /caravan/cache/{restore,save}. A plain mlx_lm.server upstream
    (mlx.server = "mlx_lm", step a) 404s those calls, logged as
    "cache=mlx-noop" so nobody mistakes it for working persistence.

Which models are MLX (precedence flag > env > ~/.caravan/config.json > default):

    {"mlx": {"enabled": true,
             "host": "127.0.0.1", "port": 8092,
             "model_prefixes": ["mlx-community/"],
             "models": {"qwen3-30b-mlx": "~/.exo/models/mlx-community--Qwen3-30B-A3B-4bit"},
             "model_dirs": ["~/.exo/models", "~/.caravan/models/mlx"]}}

    env: CARAVAN_MLX_ENABLED (0/1), CARAVAN_MLX_HOST, CARAVAN_MLX_PORT,
         CARAVAN_MLX_PREFIXES (comma list), CARAVAN_MLX_MODEL_DIRS (comma list)
    proxy flags: --mlx-host, --mlx-port, --mlx-prefixes, --no-mlx

A request model is MLX if it's a key of "models" (explicit alias -> local
path) or starts with one of "model_prefixes". The proxy rewrites the
body's `model` to the local directory when it can find one (an explicit
mapping, or "<org>--<name>" / "<org>/<name>" under a model_dirs entry --
exo's own download layout), so mlx_lm.server never tries to fetch from
Hugging Face. Discovery GET /v1/models aggregates live MLX and llama backends. Other
non-completion requests (/slots, /health) still go to llama-server.

Step (b), built 2026-10-31 in agent/mlx_worker.py -- the original notes:
  * mlx_lm.models.cache has make_prompt_cache / save_prompt_cache(file,
    cache, metadata) / load_prompt_cache(file, return_metadata=True);
    files are safetensors. The closed PR ml-explore/mlx-lm#1405 sketched
    exactly this for the server (save the LRU prompt cache entry for a
    conversation, reload it on a cache miss).
  * mlx_lm.server has no slot API, so the clean seam is a small Caravan
    shim server (or a patch carried like caravan-patches) exposing
    POST /caravan/cache/{save,restore} {"key": fingerprint}, which the
    MlxBackend.save/restore below would call instead of no-op'ing.
  * Keep the proxy contract identical to llama's: restore before the
    first turn after a restart, save after each completed turn (or idle),
    keyed by the same session fingerprint, files under
    ~/.caravan/mlx/prompt-cache/<fp>.safetensors, cleaned by slot_cleanup.
  * Metadata must record model path + tokenizer hash + cache dtype, and a
    mismatch must mean "cold", never a crash (same lesson as llama's
    q8_0 <-> f16 slot files).
  * Rotating/sliding-window caches (Gemma, GPT-OSS) serialize their
    offset/keep state in the cache meta_state; test those models first,
    since that's exactly where llama.cpp's restore broke.
"""
import json
import os
from pathlib import Path
from typing import NamedTuple, Optional

DEFAULT_MLX_CACHE_DIR = "~/.caravan/mlx/prompt-cache"
DEFAULT_MLX_PORT = 8092
DEFAULT_MLX_PREFIXES = ("mlx-community/",)
DEFAULT_MLX_MODEL_DIRS = ("~/.exo/models", "~/.caravan/models/mlx")


class MlxSettings(NamedTuple):
    enabled: bool
    host: str
    port: int
    model_prefixes: tuple
    models: dict          # alias/id -> local path
    model_dirs: tuple
    cache_dir: str = DEFAULT_MLX_CACHE_DIR   # worker's <fp>.safetensors (slot cleanup scans it)


def _as_bool(v) -> bool:
    if isinstance(v, bool):
        return v
    return str(v).strip().lower() in ("1", "true", "yes", "on")


def _as_list(v) -> tuple:
    if isinstance(v, (list, tuple)):
        return tuple(str(x).strip() for x in v if str(x).strip())
    return tuple(x.strip() for x in str(v).split(",") if x.strip())


def resolve_mlx_settings(cfg: dict, overrides: Optional[dict] = None) -> MlxSettings:
    """flag (overrides, None = unset) > env > cfg["mlx"] > default."""
    overrides = {k: v for k, v in (overrides or {}).items() if v is not None}
    sec = cfg.get("mlx") if isinstance(cfg.get("mlx"), dict) else {}

    def pick(key, env, default):
        if key in overrides:
            return overrides[key]
        e = os.environ.get(env, "").strip()
        if e:
            return e
        if sec.get(key) not in (None, ""):
            return sec[key]
        return default

    try:
        port = int(pick("port", "CARAVAN_MLX_PORT", DEFAULT_MLX_PORT))
    except (TypeError, ValueError):
        raise ValueError("mlx port must be an integer")
    if not 0 < port < 65536:
        raise ValueError(f"mlx port out of range: {port}")
    models = sec.get("models") if isinstance(sec.get("models"), dict) else {}
    return MlxSettings(
        enabled=_as_bool(pick("enabled", "CARAVAN_MLX_ENABLED", True)),
        host=str(pick("host", "CARAVAN_MLX_HOST", "127.0.0.1")),
        port=port,
        model_prefixes=_as_list(pick("model_prefixes", "CARAVAN_MLX_PREFIXES", DEFAULT_MLX_PREFIXES)),
        models={str(k): str(v) for k, v in models.items()},
        model_dirs=_as_list(pick("model_dirs", "CARAVAN_MLX_MODEL_DIRS", DEFAULT_MLX_MODEL_DIRS)),
        cache_dir=str(pick("cache_dir", "CARAVAN_MLX_CACHE_DIR", DEFAULT_MLX_CACHE_DIR)),
    )


def is_mlx_model(model: Optional[str], s: MlxSettings) -> bool:
    if not s.enabled or not isinstance(model, str) or not model:
        return False
    if model in s.models:
        return True
    return any(model.startswith(p) for p in s.model_prefixes)


def resolve_mlx_model_path(model: str, s: MlxSettings) -> Optional[str]:
    """Local directory for an MLX model id, or None (then mlx_lm.server
    gets the id as-is). A path that already exists is returned as-is."""
    if model in s.models:
        return str(Path(s.models[model]).expanduser())
    p = Path(model).expanduser()
    if p.is_absolute() and p.is_dir():
        return str(p)
    for d in s.model_dirs:
        base = Path(d).expanduser()
        for cand in (base / model.replace("/", "--"), base / model):
            if (cand / "config.json").is_file():
                return str(cand)
    return None


class Backend:
    """Where a request goes and what the proxy does around it."""
    name = "base"
    supports_slots = False

    def address(self) -> tuple:
        raise NotImplementedError

    def prepare_body(self, data: dict) -> dict:
        return data


class LlamaBackend(Backend):
    """llama-server. host/port are read through callables so the proxy's
    module-level UPSTREAM_HOST/PORT (and tests that patch them) stay the
    single source of truth."""
    name = "llama"
    supports_slots = True

    def __init__(self, host_fn, port_fn):
        self._host, self._port = host_fn, port_fn

    def address(self) -> tuple:
        return self._host(), self._port()


class MlxBackend(Backend):
    name = "mlx"
    supports_slots = False
    # llama-server-only request fields mlx_lm.server doesn't understand.
    _DROP = ("id_slot", "cache_prompt", "n_probs", "slot_id")

    def __init__(self, settings: MlxSettings):
        self.settings = settings

    def address(self) -> tuple:
        return self.settings.host, self.settings.port

    def prepare_body(self, data: dict) -> dict:
        out = {k: v for k, v in data.items() if k not in self._DROP}
        model = data.get("model")
        if isinstance(model, str):
            path = resolve_mlx_model_path(model, self.settings)
            if path:
                out["model"] = path
        return out

    # Step (b) seam: these become real once an MLX prompt-cache save/
    # restore endpoint exists (see module docstring).
    # Step (b), 2026-10-31: Caravan's MLX worker (agent/mlx_worker.py)
    # keeps one prompt cache per session, keyed by the proxy's session
    # fingerprint (sent as X-Caravan-Session), and saves/loads it as
    # <fp>.safetensors -- the llama.cpp <fp>.bin semantics. A plain
    # mlx_lm.server 404s these endpoints, which reads as "mlx-noop".
    SESSION_HEADER = "X-Caravan-Session"
    CACHE_TIMEOUT = 120.0

    def session_headers(self, fingerprint: Optional[str]) -> dict:
        return {self.SESSION_HEADER: fingerprint} if fingerprint else {}

    def _cache_call(self, op: str, payload: dict):
        import http.client
        host, port = self.address()
        try:
            conn = http.client.HTTPConnection(host, port, timeout=self.CACHE_TIMEOUT)
            try:
                body = json.dumps(payload).encode("utf-8")
                conn.request("POST", f"/caravan/cache/{op}", body=body,
                             headers={"Content-Type": "application/json",
                                      "Content-Length": str(len(body))})
                r = conn.getresponse()
                data = r.read()
                if r.status != 200:
                    return None
                return json.loads(data or b"{}")
            finally:
                conn.close()
        except (OSError, ValueError, Exception):
            return None

    def restore(self, fingerprint: Optional[str]) -> str:
        if not fingerprint:
            return "mlx-noop"
        j = self._cache_call("restore", {"key": fingerprint})
        return f"mlx-{j['result']}" if isinstance(j, dict) and j.get("result") else "mlx-noop"

    def save(self, fingerprint: Optional[str]) -> str:
        if not fingerprint:
            return "mlx-noop"
        j = self._cache_call("save", {"key": fingerprint})
        return f"mlx-{j['result']}" if isinstance(j, dict) and j.get("result") else "mlx-noop"

    def drop(self, fingerprints) -> str:
        fps = [f for f in fingerprints if f]
        if not fps:
            return "mlx-noop"
        j = self._cache_call("drop", {"keys": fps})
        return f"mlx-dropped {j.get('dropped')}" if isinstance(j, dict) else "mlx-noop"


class Router:
    def __init__(self, llama: LlamaBackend, mlx_settings: MlxSettings):
        self.llama = llama
        self.mlx = MlxBackend(mlx_settings)

    def for_model(self, model) -> Backend:
        return self.mlx if is_mlx_model(model, self.mlx.settings) else self.llama
