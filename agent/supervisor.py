"""Spawns and restarts the local llama.cpp process for whichever role this
node has been assigned -- the piece that eventually replaces the
hand-written launchd plists in ../launchd/ (see docs/ARCHITECTURE.md,
Phase 1 / GitHub issue #1).

Deliberately conservative for now: `supervise()` will restart a crashed
process, but nothing here touches launchd, and nothing runs unless
caravan_agent.py is explicitly told to (--apply). Scaffold stage --
proven correct in caravan_agent.py's dry-run output before this actually
drives the live setup.
"""
from __future__ import annotations

import signal
import subprocess
import sys
import time

import config
import kv_auto


def build_head_command(model_blob_path: str, peer_rpc_addrs: list,
                       settings: "config.LlamaSettings | None" = None) -> list:
    """`peer_rpc_addrs` like ["100.64.0.2:50052"] -- Tailscale IPs
    preferred, per discovery.py and tonight's EHOSTUNREACH findings.

    Flags below match the production config proven live on 2026-09-06
    (docs/LOG.md: "kv_unified=false", "Raising -c to 262144", "Issue #4"):
    --parallel is required for --no-kv-unified to actually take effect
    (server.cpp silently forces kv_unified=true on the n_parallel<0 auto
    path otherwise -- see LOG.md, "no-kv-unified alone was silently
    ignored"), and -c must be n_slots * ctx_per_slot, not a flat
    ctx-per-slot value, or every slot silently gets a much smaller window
    than intended.

    2026-10-30: slot count, per-slot context, -ngl, -fa, -ctk/-ctv,
    --cache-ram and -b/-ub come from `settings` (default:
    config.resolve_llama_settings(), i.e. flag > env > config file >
    default). The launchd plist is rendered from this same function by
    render_llama_plist.py, so the two can't drift.
    """
    if settings is None:
        settings = config.resolve_llama_settings()
    settings = resolve_kv_types(settings, model_blob_path, len(peer_rpc_addrs) + 1)
    tensor_split = ",".join("1" for _ in range(len(peer_rpc_addrs) + 1))
    cmd = [
        str(config.LLAMA_SERVER_BIN),
        "-m", model_blob_path,
    ]
    if peer_rpc_addrs:
        cmd += ["--rpc", ",".join(peer_rpc_addrs)]
        # This node's own device plus one RPC device per peer -- matches
        # tonight's proven `--device MTL0,RPC0` for a single peer. Only
        # correct for Metal-only nodes; revisit once a non-Mac tail
        # exists.
        devices = ["MTL0"] + [f"RPC{i}" for i in range(len(peer_rpc_addrs))]
        cmd += ["--device", ",".join(devices)]
    cmd += [
        "--tensor-split", tensor_split,
        "--port", str(config.LLAMA_SERVER_PORT),
        "-c", str(settings.total_ctx),
        "--slot-save-path", str(config.SLOT_SAVE_DIR) + "/",
        "--parallel", str(settings.n_slots),
        "--no-kv-unified",
        "-ngl", settings.n_gpu_layers,
        "-fa", settings.flash_attn,
        "-ctk", settings.cache_type_k,
        "-ctv", settings.cache_type_v,
        "--cache-ram", str(settings.cache_ram_mib),
        "-b", str(settings.batch_size),
        "-ub", str(settings.ubatch_size),
    ]
    if settings.swa_full:
        cmd += ["--swa-full"]
    return cmd


def resolve_kv_types(settings: "config.LlamaSettings", model_path: str, n_devices: int = 1,
                     log=None) -> "config.LlamaSettings":
    """Turns cache_type_k/v "auto" into f16 or q8_0 (kv_auto.decide) and
    logs the decision with its estimate. Explicit types pass through."""
    if "auto" not in (settings.cache_type_k, settings.cache_type_v):
        return settings
    d = kv_auto.decide(model_path, settings.n_slots, settings.ctx_per_slot, settings.ubatch_size,
                       settings.cache_type_k, settings.cache_type_v, n_devices=n_devices,
                       swa_full=settings.swa_full, cfg=config.kv_auto_config())
    ctk, ctv = d.cache_type_k, d.cache_type_v
    if settings.flash_attn == "off" and ctv not in ("f32", "f16", "bf16"):
        ctv = "f16"  # a quantized V cache needs flash attention
    (log or (lambda m: print(m, file=sys.stderr)))(kv_auto.format_decision(d._replace(cache_type_v=ctv)))
    return settings._replace(cache_type_k=ctk, cache_type_v=ctv)


def build_tail_command() -> list[str]:
    """--cache (GitHub issue #3, "solved natively") turns a restart from
    a 7-11 minute full re-transfer into a ~50-60s warm-cache load -- see
    docs/LOG.md. Only reason to ever pass RPC_SERVER_USE_CACHE=False is
    disk space on a node too small to hold a cached copy of its shard.

    Security (Day 17, docs/SECURITY.md): ggml-rpc-server has no auth, so it
    binds 127.0.0.1 only -- never 0.0.0.0. The lead reaches it through an
    SSH tunnel (open_rpc_tunnels), the same mechanism as the web UI: only
    machines holding Caravan's SSH key can connect.
    """
    cmd = [
        str(config.RPC_SERVER_BIN),
        "-d", "MTL0",
        "-H", "127.0.0.1",
        "-p", str(config.RPC_PORT),
    ]
    if config.RPC_SERVER_USE_CACHE:
        cmd += ["--cache"]
    return cmd


def rpc_tunnel_plan(rpc_addrs: list[str], user: str | None = None) -> list[tuple[list[str], str]]:
    """For each peer "host:port", the ssh -L command and the local address
    llama-server should use instead. Local ports RPC_PORT+10+i."""
    import os
    import getpass
    user = user or os.environ.get("CARAVAN_RPC_SSH_USER") or getpass.getuser()
    plan = []
    for i, addr in enumerate(rpc_addrs):
        host, _, port = addr.rpartition(":")
        lp = config.RPC_PORT + 10 + i
        cmd = ["ssh", "-o", "BatchMode=yes", "-o", "ExitOnForwardFailure=yes",
               "-o", "ServerAliveInterval=15", "-o", "ConnectTimeout=10", "-N",
               "-L", f"127.0.0.1:{lp}:127.0.0.1:{port or config.RPC_PORT}", f"{user}@{host}"]
        plan.append((cmd, f"127.0.0.1:{lp}"))
    return plan


def open_rpc_tunnels(rpc_addrs: list[str]) -> tuple[list, list[str]]:
    """Start the SSH tunnels; returns (procs, local rpc addrs). Raises if one fails."""
    procs, local = [], []
    for cmd, addr in rpc_tunnel_plan(rpc_addrs):
        p = subprocess.Popen(cmd, stdin=subprocess.DEVNULL, start_new_session=True)
        time.sleep(1.0)
        if p.poll() is not None:
            for q in procs:
                q.terminate()
            raise RuntimeError(f"SSH tunnel failed: {' '.join(cmd)}")
        procs.append(p)
        local.append(addr)
    return procs, local


def supervise(cmd: list[str], log_path, restart_delay: float = 10.0,
              stop_timeout: float = 15.0):
    """Runs `cmd`, restarting it if it exits, forever. Blocking -- run in
    its own thread/process. `log_path`: where stdout+stderr go (append
    mode), matching the launchd plists' StandardOutPath/StandardErrorPath
    convention so logs stay in a familiar place.

    Deliberately simple: no crash-loop backoff beyond the fixed
    `restart_delay`, no health checking beyond "did the process exit".
    Good enough to replace launchd's KeepAlive for phase 1; a smarter
    policy can come later if a real crash-loop shows up in practice.

    Handles SIGTERM/SIGINT explicitly and forwards them to the child --
    without this, launchd stopping *this* process (e.g. a plain
    `bootout`, the routine operation this whole thing exists to make
    safe) would kill the agent but leave `cmd`'s process orphaned and
    still running, invisible to launchd and likely blocking the port on
    next start. `stop_timeout` should stay comfortably under the plist's
    own `ExitTimeOut` so the graceful path has time to finish before
    launchd SIGKILLs the whole process group itself.
    """
    log_path.parent.mkdir(parents=True, exist_ok=True)
    stopping = False

    def _request_stop(signum, frame):
        nonlocal stopping
        stopping = True

    signal.signal(signal.SIGTERM, _request_stop)
    signal.signal(signal.SIGINT, _request_stop)

    while not stopping:
        with open(log_path, "a") as log_file:
            proc = subprocess.Popen(cmd, stdout=log_file, stderr=subprocess.STDOUT)
            while proc.poll() is None and not stopping:
                time.sleep(0.5)
            if stopping and proc.poll() is None:
                proc.terminate()
                try:
                    proc.wait(timeout=stop_timeout)
                except subprocess.TimeoutExpired:
                    proc.kill()
                    proc.wait()
        if stopping:
            break
        time.sleep(restart_delay)
