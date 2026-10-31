"""Starting the MLX server for an MLX model (2026-10-30 step a: mlx_lm.server;
2026-10-31 step b: the Caravan MLX worker, agent/mlx_worker.py, is the
default -- mlx.server / CARAVAN_MLX_SERVER = "mlx_lm" for the old one).

The proxy (proxy/slot_pin_proxy.py + proxy/backends.py) routes requests
whose model is an MLX id to an mlx_lm.server on this Mini; this module is
the matching launch side. Same precedence as everything else:
flag > env > ~/.caravan/config.json "mlx" > default.

    "mlx": {
      "python": "~/.caravan/venvs/mlx/bin/python",   # CARAVAN_MLX_PYTHON
      "port": 8092, "host": "127.0.0.1",             # CARAVAN_MLX_PORT / _HOST
      "models": {"qwen3-mlx": "~/.exo/models/mlx-community--Qwen3-30B-A3B-4bit"},
      "extra_args": ["--prompt-cache-size", "4"],    # CARAVAN_MLX_EXTRA_ARGS (space separated)
      "server": "caravan"                            # CARAVAN_MLX_SERVER: caravan | mlx_lm
    }

v2 (2026-10-31): the default server is Caravan's own MLX worker
(agent/mlx_worker.py): same OpenAI API as mlx_lm.server, plus a prompt
cache per proxy session that is reused turn to turn (also for Gemma 4 and
gpt-oss, whose sliding-window caches mlx_lm.server 0.32.2 can't reuse)
and saved to / loaded from mlx.cache_dir across restarts. "mlx_lm" keeps
the plain mlx_lm.server (step a behaviour).

Used two ways:
  * caravan_agent.py --model mlx-community/<name> [--apply]  -> role MLX,
    supervises mlx_lm.server instead of llama-server;
  * render_mlx_plist.py -> launchd/com.caravan.mlx-server.plist for a
    hand-managed launchd job (rendered only, never loaded by Caravan).
"""
import os
import shlex
import sys
from pathlib import Path
from typing import Optional

_PROXY_DIR = Path(__file__).resolve().parent.parent / "proxy"
if str(_PROXY_DIR) not in sys.path:
    sys.path.insert(0, str(_PROXY_DIR))
import backends  # noqa: E402  (proxy/backends.py: one definition of MLX settings)

DEFAULT_MLX_PYTHON = "~/.caravan/venvs/mlx/bin/python"
SERVERS = ("caravan", "mlx_lm")
WORKER = Path(__file__).resolve().parent / "mlx_worker.py"
is_mlx_model = backends.is_mlx_model


def resolve(cfg: dict, overrides: Optional[dict] = None):
    """(MlxSettings, python, extra_args)."""
    overrides = {k: v for k, v in (overrides or {}).items() if v is not None}
    s = backends.resolve_mlx_settings(cfg, {k: overrides[k] for k in ("host", "port") if k in overrides})
    sec = cfg.get("mlx") if isinstance(cfg.get("mlx"), dict) else {}
    python = (overrides.get("python") or os.environ.get("CARAVAN_MLX_PYTHON", "").strip()
              or sec.get("python") or DEFAULT_MLX_PYTHON)
    env_extra = os.environ.get("CARAVAN_MLX_EXTRA_ARGS", "").strip()
    extra = (list(overrides["extra_args"]) if "extra_args" in overrides
             else shlex.split(env_extra) if env_extra else list(sec.get("extra_args") or []))
    return s, str(Path(python).expanduser()), [str(x) for x in extra]


def resolve_server(cfg: dict, overrides: Optional[dict] = None) -> str:
    overrides = {k: v for k, v in (overrides or {}).items() if v is not None}
    sec = cfg.get("mlx") if isinstance(cfg.get("mlx"), dict) else {}
    server = str(overrides.get("server") or os.environ.get("CARAVAN_MLX_SERVER", "").strip()
                 or sec.get("server") or "caravan").strip().lower().replace("-", "_")
    if server not in SERVERS:
        raise ValueError(f"mlx server must be one of {SERVERS}, got {server!r}")
    return server


def build_mlx_command(model: str, cfg: dict, overrides: Optional[dict] = None) -> list:
    """mlx_lm.server command for `model` (an MLX id, alias, or local dir).
    Raises FileNotFoundError when there's no local copy -- Caravan never
    lets mlx_lm download a model on its own."""
    s, python, extra = resolve(cfg, overrides)
    path = backends.resolve_mlx_model_path(model, s)
    if path is None:
        raise FileNotFoundError(
            f"no local MLX model for {model!r} (looked in {', '.join(s.model_dirs)} "
            "and config mlx.models)")
    if resolve_server(cfg, overrides) == "mlx_lm":
        return [python, "-m", "mlx_lm", "server", "--model", path,
                "--host", s.host, "--port", str(s.port)] + extra
    return [python, str(WORKER), "--model", path, "--host", s.host, "--port", str(s.port),
            "--cache-dir", str(Path(s.cache_dir).expanduser())] + extra
