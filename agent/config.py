"""Tunables for the Caravan agent -- paths, ports, and the current target
model. See docs/ARCHITECTURE.md for why these values are what they are.
"""
import json
import os
from pathlib import Path
from typing import NamedTuple, Optional

# Where each agent instance persists its own identity (see identity.py).
# Deliberately outside the git repo -- this is runtime state, not source.
STATE_DIR = Path.home() / ".caravan" / "agent"

# Optional shared config file (JSON, stdlib only). Read by both the agent
# (this module) and proxy/slot_cleanup.py. Missing file == all defaults.
# Example:
#   {"model": "qwen3:30b",
#    "slot_cleanup": {"mode": "delete", "max_age_days": 30,
#                     "interval_hours": 6,
#                     "archive_dir": "~/.caravan/llama-server/slots-archive"}}
# Override the path with CARAVAN_CONFIG=/path/to/config.json.
CONFIG_FILE = Path(os.environ.get(
    "CARAVAN_CONFIG", str(Path.home() / ".caravan" / "config.json")
)).expanduser()

# The model this cluster serves when nothing else is configured. Kept as
# the default so behavior is unchanged unless you opt in to another model.
# Caravan supports one real conversation identity today (see
# openclaw.json), so one target model at a time is still the right size;
# it's just no longer hardcoded. Any Ollama-store model name works
# ("name", "name:tag", "namespace/name:tag", "hf.co/user/repo:tag").
DEFAULT_TARGET_MODEL = "muse-glimmer"


def load_config_file(path: Optional[Path] = None) -> dict:
    """Parsed CONFIG_FILE (or `path`), or {} if missing/unreadable. Never
    raises -- a broken optional config shouldn't take the agent down."""
    path = Path(path).expanduser() if path is not None else CONFIG_FILE
    try:
        data = json.loads(path.read_text())
    except FileNotFoundError:
        return {}
    except (OSError, ValueError) as e:
        print(f"[caravan] warning: ignoring unreadable config {path}: {e}")
        return {}
    return data if isinstance(data, dict) else {}


def resolve_target_model(cli_value: Optional[str] = None,
                         config_path: Optional[Path] = None) -> str:
    """Target model, by precedence: --model flag > $CARAVAN_MODEL >
    "model" in the config file > DEFAULT_TARGET_MODEL."""
    if cli_value:
        return cli_value
    env_value = os.environ.get("CARAVAN_MODEL", "").strip()
    if env_value:
        return env_value
    file_value = load_config_file(config_path).get("model")
    if isinstance(file_value, str) and file_value.strip():
        return file_value.strip()
    return DEFAULT_TARGET_MODEL


# Back-compat: the resolved value (env > config file > default) at import
# time. New code should call resolve_target_model() so --model wins.
TARGET_MODEL = resolve_target_model()

# llama.cpp binaries -- same paths used by the hand-written launchd
# plists in ../launchd/. Not yet unified with those plists; this agent is
# meant to eventually replace them (see ARCHITECTURE.md, issue #1).
LLAMA_SERVER_BIN = Path.home() / "dev" / "llama.cpp" / "build" / "bin" / "llama-server"
RPC_SERVER_BIN = Path.home() / "dev" / "llama.cpp" / "build" / "bin" / "ggml-rpc-server"

# Ports. RPC_PORT and LLAMA_SERVER_PORT match tonight's proven manual
# setup. AGENT_PORT is a small HTTP surface each agent exposes for peer
# liveness checks (mDNS/Tailscale discovery both need something to
# actually probe) -- see health_server.py.
RPC_PORT = 50052
LLAMA_SERVER_PORT = 8080
AGENT_PORT = 8091

# n_slots x LLAMA_SERVER_CTX_PER_SLOT is llama-server's actual -c value
# (each slot gets a full independent window, not a shared pool split
# n_slots ways) -- see docs/LOG.md, "kv_unified=false" and "The 16K-
# per-slot cap was a real regression" for why this specific shape, not
# just a flat context size. Real sessions have hit 40K+ tokens; a shared/
# split pool silently truncates those.
#
# 2026-10-30: these and the other llama-server tuning flags are now
# configurable -- see resolve_llama_settings() below. The two constants
# stay as the resolved (env > config file > default) values for older
# callers.

# --- llama-server tuning (supervisor.build_head_command + the launchd
# plist rendered by render_llama_plist.py) -------------------------------
# Precedence: CLI flag > env var > "llama_server" object in the config
# file > default. Flag names below are the exact ones in the caravan-
# patches fork's common/arg.cpp.
LLAMA_DEFAULTS = {
    # --parallel N and -c N*ctx_per_slot (see comment above). The proxy
    # reads the same n_slots setting (CARAVAN_N_SLOTS) -- keep them equal.
    "n_slots": 4,
    "ctx_per_slot": 65536,
    # -fa on|off|auto. llama.cpp's default is "auto"; explicit "on" makes
    # it deterministic, and a quantized V cache (below) requires it.
    "flash_attn": "on",
    # -ctk/-ctv: q8_0 halves KV memory vs f16 with negligible quality loss
    # -- the difference between 4x64K slots fitting comfortably or not on
    # 24 GB machines. NOTE: changes the on-disk slot-save format, so slot
    # files saved under f16 won't restore after switching (they'll just be
    # reprocessed cold and re-saved).
    "cache_type_k": "q8_0",
    "cache_type_v": "q8_0",
    # --cache-ram MiB. llama.cpp defaults to 8192: a host-RAM prompt cache
    # that, with --cache-idle-slots (also on by default), copies every idle
    # slot's KV into RAM at the start of *every* new task. Caravan already
    # pins sessions to slots and persists them to disk, so that's pure
    # duplicate memory (up to 8 GB on a 24 GB box) plus copy time per
    # request. 0 disables it (and, with it, --cache-idle-slots).
    "cache_ram_mib": 0,
    # -ngl: explicit "all layers on GPU/RPC devices". Setting it also stops
    # llama.cpp's --fit (on by default) from silently picking fewer layers.
    "n_gpu_layers": "999",
    # -b / -ub: llama.cpp defaults (2048 / 512), now passed explicitly and
    # tunable. Larger -ub can speed prompt processing on Metal at the cost
    # of compute-buffer memory -- benchmark before changing (see README).
    "batch_size": 2048,
    "ubatch_size": 512,
    # Fallback --rpc target for the hand-written plist when not derived
    # via discovery: node-b's Thunderbolt-bridge link-local address (en2).
    # Link-local (169.254/16) addresses are self-assigned and CAN change
    # (re-cabling, interface reset) -- prefer render_llama_plist.py --rpc auto.
    "rpc": "169.254.104.38:50052",
}

LLAMA_ENV_VARS = {
    "n_slots": "CARAVAN_N_SLOTS",
    "ctx_per_slot": "CARAVAN_CTX_PER_SLOT",
    "flash_attn": "CARAVAN_FLASH_ATTN",
    "cache_type_k": "CARAVAN_CACHE_TYPE_K",
    "cache_type_v": "CARAVAN_CACHE_TYPE_V",
    "cache_ram_mib": "CARAVAN_CACHE_RAM_MIB",
    "n_gpu_layers": "CARAVAN_N_GPU_LAYERS",
    "batch_size": "CARAVAN_BATCH_SIZE",
    "ubatch_size": "CARAVAN_UBATCH_SIZE",
    "rpc": "CARAVAN_RPC_ADDR",
}

KV_CACHE_TYPES = ("f32", "f16", "bf16", "q8_0", "q4_0", "q4_1", "iq4_nl", "q5_0", "q5_1")
FLASH_ATTN_VALUES = ("on", "off", "auto")


class LlamaSettings(NamedTuple):
    n_slots: int
    ctx_per_slot: int
    flash_attn: str
    cache_type_k: str
    cache_type_v: str
    cache_ram_mib: int
    n_gpu_layers: str
    batch_size: int
    ubatch_size: int
    rpc: str

    @property
    def total_ctx(self) -> int:
        return self.n_slots * self.ctx_per_slot


def resolve_llama_settings(overrides: Optional[dict] = None,
                           config_path: Optional[Path] = None) -> LlamaSettings:
    """llama-server tuning, by precedence: overrides (CLI flags; None
    values ignored) > env var > config file "llama_server" > default.
    Raises ValueError on an invalid value."""
    overrides = {k: v for k, v in (overrides or {}).items() if v is not None}
    section = load_config_file(config_path).get("llama_server")
    file_vals = section if isinstance(section, dict) else {}
    raw = {}
    for key, default in LLAMA_DEFAULTS.items():
        env = os.environ.get(LLAMA_ENV_VARS[key], "").strip()
        if key in overrides:
            raw[key] = overrides[key]
        elif env:
            raw[key] = env
        elif file_vals.get(key) not in (None, ""):
            raw[key] = file_vals[key]
        else:
            raw[key] = default

    def _int(key, minimum):
        try:
            v = int(raw[key])
        except (TypeError, ValueError):
            raise ValueError(f"{key} must be an integer, got {raw[key]!r}")
        if v < minimum:
            raise ValueError(f"{key} must be >= {minimum}, got {v}")
        return v

    fa = str(raw["flash_attn"]).strip().lower()
    if fa not in FLASH_ATTN_VALUES:
        raise ValueError(f"flash_attn must be one of {FLASH_ATTN_VALUES}, got {raw['flash_attn']!r}")
    ctk = str(raw["cache_type_k"]).strip().lower()
    ctv = str(raw["cache_type_v"]).strip().lower()
    for name, v in (("cache_type_k", ctk), ("cache_type_v", ctv)):
        if v not in KV_CACHE_TYPES:
            raise ValueError(f"{name} must be one of {KV_CACHE_TYPES}, got {v!r}")
    if fa == "off" and ctv not in ("f32", "f16", "bf16"):
        raise ValueError("a quantized V cache (cache_type_v) requires flash_attn on/auto")
    ngl = str(raw["n_gpu_layers"]).strip().lower()
    if ngl not in ("all", "auto"):
        try:
            int(ngl)
        except ValueError:
            raise ValueError(f"n_gpu_layers must be an integer, 'all' or 'auto', got {ngl!r}")
    batch, ubatch = _int("batch_size", 32), _int("ubatch_size", 32)
    if ubatch > batch:
        raise ValueError(f"ubatch_size ({ubatch}) must be <= batch_size ({batch})")
    cache_ram = _int("cache_ram_mib", -1)
    return LlamaSettings(
        n_slots=_int("n_slots", 1),
        ctx_per_slot=_int("ctx_per_slot", 512),
        flash_attn=fa,
        cache_type_k=ctk,
        cache_type_v=ctv,
        cache_ram_mib=cache_ram,
        n_gpu_layers=ngl,
        batch_size=batch,
        ubatch_size=ubatch,
        rpc=str(raw["rpc"]).strip(),
    )


def add_llama_cli_args(parser) -> None:
    """The llama-server tuning flags, shared by caravan_agent.py and
    render_llama_plist.py. All default to None == "not set on the CLI"."""
    g = parser.add_argument_group("llama-server tuning (flag > env > config file > default)")
    g.add_argument("--n-slots", type=int, default=None,
                   help="--parallel slots; -c = n_slots * ctx_per_slot (env CARAVAN_N_SLOTS, default 4)")
    g.add_argument("--ctx-per-slot", type=int, default=None,
                   help="context tokens per slot (env CARAVAN_CTX_PER_SLOT, default 65536)")
    g.add_argument("--flash-attn", choices=FLASH_ATTN_VALUES, default=None,
                   help="-fa (env CARAVAN_FLASH_ATTN, default on)")
    g.add_argument("--cache-type-k", default=None,
                   help="-ctk (env CARAVAN_CACHE_TYPE_K, default q8_0)")
    g.add_argument("--cache-type-v", default=None,
                   help="-ctv (env CARAVAN_CACHE_TYPE_V, default q8_0)")
    g.add_argument("--cache-ram", dest="cache_ram_mib", type=int, default=None,
                   help="--cache-ram MiB, 0 = off, -1 = unlimited (env CARAVAN_CACHE_RAM_MIB, default 0)")
    g.add_argument("--n-gpu-layers", default=None,
                   help="-ngl (env CARAVAN_N_GPU_LAYERS, default 999)")
    g.add_argument("--batch-size", type=int, default=None,
                   help="-b (env CARAVAN_BATCH_SIZE, default 2048)")
    g.add_argument("--ubatch-size", type=int, default=None,
                   help="-ub (env CARAVAN_UBATCH_SIZE, default 512)")


def llama_overrides_from_args(args) -> dict:
    return {k: getattr(args, k, None) for k in LLAMA_DEFAULTS if k != "rpc"}


try:
    _resolved_llama = resolve_llama_settings()
except ValueError as _e:  # bad env/config shouldn't break imports
    print(f"[caravan] warning: invalid llama_server setting ({_e}); using defaults")
    _resolved_llama = LlamaSettings(**LLAMA_DEFAULTS)
LLAMA_SERVER_N_SLOTS = _resolved_llama.n_slots
LLAMA_SERVER_CTX_PER_SLOT = _resolved_llama.ctx_per_slot

# Disk-persisted KV cache slots (GitHub issue #4) -- lets a restart reuse
# a session's already-processed prompt instead of reprocessing it cold.
SLOT_SAVE_DIR = Path.home() / ".caravan" / "llama-server" / "slots"

# rpc-server's own on-disk tensor cache (GitHub issue #3) -- turns a
# restart from a 7-11 minute full re-transfer into a ~50-60s warm-cache
# load. Native llama.cpp feature (rpc-server --cache), not something
# Caravan built -- see docs/LOG.md, "Issue #3: solved natively."
RPC_SERVER_USE_CACHE = True

# Where rpc-server --cache actually writes -- matches
# fs_get_cache_directory() in tools/rpc/rpc-server.cpp's macOS branch.
# Only meaningful on a tail node; a head node won't have this directory.
# Used by system_stats.py to report disk headroom, not by supervisor.py
# (the C++ binary derives this path itself from --cache, nothing to pass).
RPC_CACHE_DIR = Path.home() / "Library" / "Caches" / "llama.cpp" / "rpc"

# mDNS/Bonjour service type this agent advertises and browses for.
MDNS_SERVICE_TYPE = "_caravan._tcp"
MDNS_DOMAIN = "local"
