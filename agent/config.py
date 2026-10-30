"""Tunables for the Caravan agent -- paths, ports, and the current target
model. See docs/ARCHITECTURE.md for why these values are what they are.
"""
import json
import os
from pathlib import Path
from typing import Optional

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
LLAMA_SERVER_N_SLOTS = 4
LLAMA_SERVER_CTX_PER_SLOT = 65536

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
