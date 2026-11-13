"""GGUF (llama.cpp) loads for the web UI: one Mini or split across K Minis.

Same mechanism as the CLI split (Sep 5, commit ae838f1, launchd/com.caravan.*):
each peer Mini runs `ggml-rpc-server` (loopback only); the lead reaches each
through an SSH tunnel and runs `llama-server --rpc 127.0.0.1:p1,127.0.0.1:p2,...` and llama.cpp ships each peer its share of the
weights over the network at load. Peers do NOT need the .gguf file -- only
the lead does. The first load copies the peer's share over Thunderbolt; with
`rpc-server -c` the peer keeps a local tensor cache so later loads are faster.

Pure helpers here (placement, commands, parsing) so tests need no Minis.
WorkerManager (web_workers.py) runs the commands and tracks every PID it
starts; Stop kills only those PIDs, after checking the command line.
"""
from __future__ import annotations

import os
import shlex
from pathlib import Path
from typing import Optional

from llama_runtime import bin_dir as llama_bin_dir
LLAMA_BIN = str(llama_bin_dir())
RPC_PORT = int(os.environ.get("CARAVAN_GGUF_RPC_PORT", "50052"))
GGUF_CTX = int(os.environ.get("CARAVAN_GGUF_CTX", "8192"))
# Offered Chat window sizes. Auto never jumps past AUTO_CAP, and never
# to the agent path's much larger window. 8192 stays the fallback when
# the model or memory cannot be measured.
GGUF_CTX_CHOICES = (4096, 8192, 16384, 32768, 65536)
GGUF_CTX_AUTO_CAP = 32768
GGUF_DEFAULT_SLOTS = 1
GGUF_MAX_SLOTS = 2
GGUF_ROOTS = [Path(p).expanduser() for p in os.environ.get(
    "CARAVAN_GGUF_ROOTS", "~/.caravan/models").split(":") if p]
# macOS lets Metal wire ~75% of RAM (recommendedMaxWorkingSetSize); keep
# headroom for KV cache + compute buffers on top of the weights.
GPU_FRACTION = 0.75
HEADROOM_GB = 1.5
GGUF_UBATCH = (256, 512, 1024)
GGUF_DEFAULT_UBATCH = 512
GGUF_DEFAULT_BATCH = 2048
# Only these KV cache types are offered. q4_* is never a trial or a default.
GGUF_KV_TYPES = ("f16", "q8_0")
GGUF_KNOBS = (
    ("flash_attn", ("on", "off")),
    ("ubatch", GGUF_UBATCH),
    ("cache_type", GGUF_KV_TYPES),
)
GGUF_SLOT_ROOT = Path("~/.caravan/web-ui/slots")
RPC_PID = "~/.caravan/web-ui/rpc-server.pid"
RPC_LOG = "~/.caravan/web-ui/rpc-server.log"


def gguf_id(path) -> str:
    return "gguf/" + Path(str(path)).stem


def scan_local(roots=None) -> list:
    """GGUF files on this (lead) Mini. Skips mmproj and shard 2+ files."""
    out = []
    seen = set()
    for root in roots or GGUF_ROOTS:
        if not root.is_dir():
            continue
        for p in sorted(root.rglob("*.gguf")):
            name = p.name.lower()
            if any(part.startswith('.') for part in p.relative_to(root).parts):
                continue
            if "mmproj" in name or ("-of-" in name and "-00001-of-" not in name):
                continue
            try:
                from gguf_sets import members
                nearby = {str(f.relative_to(p.parent)): f.stat().st_size for f in p.parent.glob("*.gguf")}
                parts = members(p.name, nearby)
                size = sum(nearby[n] for n in parts)
                # If downloaded here, insist on the exact verified byte counts too.
                import json
                receipt = p.parent / 'caravan-gguf-source.json'
                expected = json.loads(receipt.read_text()).get('files', {}) if receipt.exists() else {}
                if any(nearby.get(n) != count for n, count in expected.items() if n in parts):
                    continue
            except (OSError, ValueError):
                continue
            if size < 50_000_000:
                continue
            gid = gguf_id(p)
            if gid in seen:
                continue
            seen.add(gid)
            out.append({"id": gid, "name": p.stem, "path": str(p),
                        "size_gb": round(size / 1e9, 2)})
    return out


def node_gpu_gb(node: dict) -> Optional[float]:
    ram = (node or {}).get("ram") or {}
    tot = ram.get("total_gb")
    try:
        return float(tot) * GPU_FRACTION if tot else None
    except (TypeError, ValueError):
        return None


def rpc_host(node: dict) -> str:
    """Address the lead dials for this peer's rpc-server (Thunderbolt first)."""
    peer = (node.get("peer") or "").strip()
    if peer:
        return peer.rsplit(":", 1)[0] if ":" in peer else peer
    h = (node.get("ssh") or node.get("host") or "").strip()
    return h.split("@", 1)[-1]


def placement_options(weights_gb: float, nodes: list) -> dict:
    """one-Mini per node, then split across the first K online Minis (lead first).

    Default = the smallest option that fits (one Mini beats a split).
    """
    online = [n for n in nodes or [] if isinstance(n, dict)
              and not n.get("offline") and not n.get("error")]
    lead = [n for n in online if n.get("role") == "lead"][:1]
    ordered = lead + [n for n in online if n not in lead]
    need = float(weights_gb or 0) + HEADROOM_GB
    opts = []
    for n in lead:  # GGUF runs llama-server on the lead; the file lives there
        cap = node_gpu_gb(n)
        ok = cap is None or cap >= need
        opts.append({
            "id": f"one:{n['id']}", "mode": "one", "node_ids": [n["id"]],
            "node_labels": [n.get("label") or n["id"]],
            "label": f"One Mini · {n.get('label') or n['id']}",
            "enabled": ok, "fits": ok,
            "reason": "" if ok else f"needs ~{need:.1f} GB, {n.get('label')} has ~{cap:.1f} GB for the GPU",
        })
    for k in range(2, len(ordered) + 1):
        grp = ordered[:k]
        caps = [node_gpu_gb(n) for n in grp]
        total = sum(c for c in caps if c) if all(caps) else None
        ok = total is None or total >= need
        labels = [n.get("label") or n["id"] for n in grp]
        opts.append({
            "id": "split:" + ",".join(n["id"] for n in grp), "mode": "split",
            "node_ids": [n["id"] for n in grp], "node_labels": labels,
            "label": f"Split across {k} Minis · {' + '.join(labels)}",
            "enabled": ok, "fits": ok,
            "reason": "" if ok else f"needs ~{need:.1f} GB, these Minis have ~{total:.1f} GB together",
        })
    default = next((o["id"] for o in opts if o["enabled"]), None)
    return {"options": opts, "default_id": default, "weights_gb": weights_gb}


def tensor_split(nodes: list) -> list:
    """Share per Mini, proportional to its GPU memory (equal when unknown)."""
    caps = [node_gpu_gb(n) for n in nodes]
    if not all(caps):
        return [1] * len(nodes)
    return [round(c, 1) for c in caps]


def model_context_length(model_path, meta_fn=None):
    """Trained context length from the GGUF header, or None if unknown."""
    try:
        import gguf_meta
        fn = meta_fn or gguf_meta.read_metadata
        meta = fn(model_path)
        arch = meta.get("general.architecture") or ""
        v = meta.get(f"{arch}.context_length")
        if v is None:
            return None
        n = int(v)
        return n if n > 0 else None
    except Exception:
        return None


def ctx_estimate(model_path, ctx: int, *, n_slots: int = 1,
                 ubatch: int = GGUF_DEFAULT_UBATCH, n_devices: int = 1,
                 decide=None):
    """(need_q8_mib, budget_mib) from kv_auto, or (None, None) if unknown."""
    try:
        import kv_auto
        fn = decide or kv_auto.decide
        d = fn(
            model_path, n_slots=max(1, int(n_slots)), ctx_per_slot=int(ctx),
            n_ubatch=int(ubatch), n_devices=max(1, int(n_devices)),
        )
        est = d.estimate or {}
        need = est.get("need_q8_0_mib")
        budget = est.get("budget_mib")
        if need is None or budget is None:
            return None, None
        return float(need), float(budget)
    except Exception:
        return None, None


def ctx_fits_known(model_path, ctx: int, **kw):
    """True if the lighter memory option fits, False if not, None if unknown."""
    need, budget = ctx_estimate(model_path, ctx, **kw)
    if need is None or budget is None:
        return None
    return need <= budget


def auto_ctx(model_path, *, n_slots: int = 1, ubatch: int = GGUF_DEFAULT_UBATCH,
             n_devices: int = 1, decide=None, meta_fn=None) -> int:
    """Sane Chat window from this model and this Mac's memory.

    Keeps the trusted 8192 default when the file or memory cannot be
    measured. Never returns more than GGUF_CTX_AUTO_CAP, and never the
    agent path's much larger window. May pick a shorter window when the
    model was trained for less, or a longer one (up to the cap) when
    both the model and memory allow it.
    """
    trained = model_context_length(model_path, meta_fn=meta_fn)
    if not trained:
        return GGUF_CTX
    cap = min(int(trained), GGUF_CTX_AUTO_CAP)
    choices = [c for c in GGUF_CTX_CHOICES if c <= cap]
    if not choices:
        return max(1, cap)
    # Start at the trusted default when the model allows it. If the model
    # was trained for less, start at the largest offered size within that
    # window. Grow past the default only when memory is known to fit.
    if GGUF_CTX <= cap and GGUF_CTX in choices:
        best = GGUF_CTX
    else:
        best = choices[-1]
    for c in choices:
        if c <= best:
            continue
        fits = ctx_fits_known(
            model_path, c, n_slots=n_slots, ubatch=ubatch,
            n_devices=n_devices, decide=decide,
        )
        if fits is True:
            best = c
        else:
            # Unknown or too large: do not grow further.
            break
    return best


def disabled_ctx_values(model_path, *, n_slots: int = 1,
                        ubatch: int = GGUF_DEFAULT_UBATCH, n_devices: int = 1,
                        decide=None, meta_fn=None) -> dict:
    """{value: plain reason} for Chat window sizes that stay listed but unusable."""
    out = {}
    trained = model_context_length(model_path, meta_fn=meta_fn)
    for c in GGUF_CTX_CHOICES:
        if trained and c > trained:
            out[str(c)] = "This model was trained for a shorter window."
            continue
        fits = ctx_fits_known(
            model_path, c, n_slots=n_slots, ubatch=ubatch,
            n_devices=n_devices, decide=decide,
        )
        if fits is False:
            out[str(c)] = "This window will not fit in this Mac's memory with this model."
    return out


def resolve_launch(model_path, *, tune=None, ctx=None, decide=None,
                   n_devices: int = 1, ubatch: int = GGUF_DEFAULT_UBATCH,
                   meta_fn=None) -> dict:
    """Resolved per-chat window and slot count for a web llama-server start.

    Pins on the tune win. Auto Chat window uses auto_ctx(). Auto Two chats
    is one slot. -c passed to llama-server is window times slots.
    """
    tune = dict(tune or {})
    try:
        n_slots = int(tune["n_slots"]) if tune.get("n_slots") is not None else GGUF_DEFAULT_SLOTS
    except (TypeError, ValueError):
        n_slots = GGUF_DEFAULT_SLOTS
    n_slots = max(1, min(int(n_slots), GGUF_MAX_SLOTS))
    raw = tune.get("ctx") if tune.get("ctx") is not None else ctx
    if raw is not None:
        try:
            ctx_per = int(raw)
        except (TypeError, ValueError):
            ctx_per = auto_ctx(
                model_path, n_slots=n_slots, ubatch=ubatch,
                n_devices=n_devices, decide=decide, meta_fn=meta_fn,
            )
    else:
        ctx_per = auto_ctx(
            model_path, n_slots=n_slots, ubatch=ubatch,
            n_devices=n_devices, decide=decide, meta_fn=meta_fn,
        )
    if ctx_per < 1:
        ctx_per = GGUF_CTX
    return {
        "ctx": ctx_per,
        "n_slots": n_slots,
        "total_ctx": ctx_per * n_slots,
    }


def slot_save_dir(cache_type_k: str, cache_type_v: str, root=None,
                  ctx=None, n_slots=None) -> Path:
    """Per-type folder so a memory-compression change starts a fresh (cold) save.

    Old slot files from a different KV type, window, or slot count are not
    required and are not loaded — they live in a different folder. The
    default 8192 window and one slot keep the original folder name so
    existing saves still apply.
    """
    base = Path(root) if root is not None else GGUF_SLOT_ROOT
    name = f"{cache_type_k}_{cache_type_v}"
    if ctx is not None and int(ctx) != GGUF_CTX:
        name += f"_c{int(ctx)}"
    if n_slots is not None and int(n_slots) > 1:
        name += f"_s{int(n_slots)}"
    return Path(str(base)).expanduser() / name


def resolve_web_kv(*, flash_attn: str = "on", cache_type=None,
                   cache_type_k=None, cache_type_v=None,
                   model_path=None, ctx: int = GGUF_CTX, ubatch: int = GGUF_DEFAULT_UBATCH,
                   n_devices: int = 1, n_slots: int = 1, decide=None) -> tuple:
    """Resolve -ctk/-ctv to f16 or q8_0. Never 4-bit. Quantized V needs flash on."""
    allowed = set(GGUF_KV_TYPES)

    def _clean(v, fallback="auto"):
        s = (str(v).strip().lower() if v is not None else fallback) or fallback
        if s in ("q4_0", "q4_1", "iq4_nl", "q4", "4"):
            raise ValueError("GGUF memory compression does not offer 4-bit")
        return s

    if cache_type is not None:
        ct = _clean(cache_type, "")
        if ct not in allowed:
            raise ValueError("cache_type must be f16 or q8_0")
        k = v = ct
    else:
        k = _clean(cache_type_k)
        v = _clean(cache_type_v)
        if k not in allowed | {"auto"} or v not in allowed | {"auto"}:
            raise ValueError("cache type must be auto, f16, or q8_0")
        if k == "auto" or v == "auto":
            decided_k = decided_v = "q8_0"
            try:
                import kv_auto
                fn = decide or kv_auto.decide
                d = fn(
                    model_path, n_slots=max(1, int(n_slots)), ctx_per_slot=int(ctx),
                    n_ubatch=int(ubatch),
                    cache_type_k="auto" if k == "auto" else k,
                    cache_type_v="auto" if v == "auto" else v,
                    n_devices=max(1, int(n_devices)),
                )
                decided_k = d.cache_type_k
                decided_v = d.cache_type_v
            except Exception:
                pass
            if k == "auto":
                k = decided_k if decided_k in allowed else "q8_0"
            if v == "auto":
                v = decided_v if decided_v in allowed else "q8_0"
    if k not in allowed:
        k = "q8_0"
    if v not in allowed:
        v = "q8_0"
    # A quantized V cache needs flash attention (same rule as the agent path).
    if flash_attn == "off" and v not in ("f16", "f32", "bf16"):
        v = "f16"
    return k, v


def llama_args(model_path: str, *, port: int, peers: list, shares: list,
               ctx: int = None, bin_dir: str = LLAMA_BIN,
               tune: Optional[dict] = None, decide=None, slot_root=None,
               meta_fn=None) -> list:
    """llama-server argv. peers = ["host:port", ...] (empty for one Mini).

    Always passes the flags Caravan already trusts on the agent path: flash
    attention, auto KV (f16 or q8_0 only), default prompt batch, saved slots,
    and --cache-ram 0. Chat window defaults to a size that fits this model
    and this Mac, falling back to 8192 when that cannot be measured, and
    never jumping to the agent path's much larger window. Two chats adds
    --parallel and --no-kv-unified, and -c is the per-chat window times
    the number of slots.

    tune: {"flash_attn": "on"|"off", "ubatch": int, "cache_type": "f16"|"q8_0",
           "slot_save": bool, "ctx": int, "n_slots": 1|2}.
    Use resolve_launch() for the resolved ctx, n_slots, and total_ctx.
    """
    tune = dict(tune or {})
    fa = tune.get("flash_attn", "on")
    if fa not in ("on", "off"):
        raise ValueError("flash_attn must be on or off")
    ub = int(tune["ubatch"]) if tune.get("ubatch") is not None else GGUF_DEFAULT_UBATCH
    if ub not in GGUF_UBATCH:
        raise ValueError("ubatch must be one of %s" % (GGUF_UBATCH,))
    batch = max(ub, GGUF_DEFAULT_BATCH)
    n_devices = 1 + len(peers or [])
    launch = resolve_launch(
        model_path, tune=tune, ctx=ctx, decide=decide,
        n_devices=n_devices, ubatch=ub, meta_fn=meta_fn,
    )
    ctx_per, n_slots, total_c = launch["ctx"], launch["n_slots"], launch["total_ctx"]
    ctk, ctv = resolve_web_kv(
        flash_attn=fa, cache_type=tune.get("cache_type"),
        cache_type_k=tune.get("cache_type_k"), cache_type_v=tune.get("cache_type_v"),
        model_path=model_path, ctx=ctx_per, ubatch=ub,
        n_devices=n_devices, n_slots=n_slots, decide=decide,
    )
    args = [str(Path(bin_dir).expanduser() / "llama-server"),
            "-m", str(Path(model_path).expanduser()),
            "--host", "127.0.0.1", "--port", str(int(port)),
            "-c", str(int(total_c)), "-ngl", "999", "-fa", fa,
            "-ctk", ctk, "-ctv", ctv,
            "-b", str(batch), "-ub", str(ub),
            "--cache-ram", "0", "--jinja"]
    if n_slots > 1:
        args += ["--parallel", str(n_slots), "--no-kv-unified"]
    if tune.get("slot_save", True) is not False:
        sp = slot_save_dir(ctk, ctv, root=slot_root, ctx=ctx_per, n_slots=n_slots)
        args += ["--slot-save-path", str(sp) + "/"]
    if peers:
        devs = ["MTL0"] + [f"RPC{i}" for i in range(len(peers))]
        args += ["--rpc", ",".join(peers), "--device", ",".join(devs),
                 "--tensor-split", ",".join(str(s) for s in shares)]
    return args


def _rpath(p: str) -> str:
    return ('"$HOME"/' + shlex.quote(p[2:])) if p.startswith("~/") else shlex.quote(p)


def rpc_start_command(*, port: int = RPC_PORT, bin_dir: str = LLAMA_BIN) -> str:
    """Remote shell: stop our tracked rpc-server, start one on 127.0.0.1, print PID.

    Security: ggml-rpc-server has no auth, so on a peer it listens on
    loopback ONLY. The lead reaches it through an SSH local forward
    (ssh_tunnel_args), so only machines holding Caravan's SSH key -- the
    topology Minis -- can talk to it, over an encrypted channel. No network
    listener, no sudo/pf, any number of Minis. (Also sidesteps macOS Local
    Network privacy, which made llama-server's direct dials fail with
    "Failed to connect" when launched under the web server.)
    `-d MTL0` gives one RPC device per Mini, so RPC<i> maps to peer i.
    Exit 3 = port busy by something we don't own; 4 = died / not listening.
    """
    from llama_runtime import PIN
    remote = "~/.caravan/runtime/llama/" + PIN["version"] + "/ggml-rpc-server"
    fallback = _rpath(bin_dir.rstrip("/") + "/ggml-rpc-server")
    binp = '"$CARAVAN_RPC_BIN"'
    return (
        f"CARAVAN_RPC_BIN={_rpath(remote)}; [ -x \"$CARAVAN_RPC_BIN\" ] || CARAVAN_RPC_BIN={fallback}; "
        "mkdir -p ~/.caravan/web-ui; "
        + rpc_stop_command() + "; "
        + f"if lsof -nP -iTCP:{int(port)} -sTCP:LISTEN >/dev/null 2>&1; then echo PORT_BUSY; exit 3; fi; "
        f"nohup {binp} -d MTL0 -H 127.0.0.1 -p {int(port)} -c "
        f"> {RPC_LOG} 2>&1 & echo $! > {RPC_PID}; "
        f"p=$(cat {RPC_PID}); "
        f"for i in $(seq 1 60); do kill -0 $p 2>/dev/null || break; "
        f"lsof -nP -iTCP:{int(port)} -sTCP:LISTEN >/dev/null 2>&1 && break; sleep 0.25; done; "
        f"kill -0 $p 2>/dev/null || {{ tail -5 {RPC_LOG}; echo DIED; exit 4; }}; "
        f"lsof -nP -iTCP:{int(port)} -sTCP:LISTEN >/dev/null 2>&1 || {{ tail -5 {RPC_LOG}; echo NOT_LISTENING; exit 4; }}; "
        "echo PID:$p"
    )


def ssh_tunnel_args(ssh_target: str, local_port: int, remote_port: int = RPC_PORT) -> list:
    """ssh -L lead 127.0.0.1:<local_port> → peer 127.0.0.1:<remote_port>."""
    return ["ssh", "-o", "BatchMode=yes", "-o", "ExitOnForwardFailure=yes",
            "-o", "ServerAliveInterval=15", "-o", "ConnectTimeout=10",
            "-c", "aes128-gcm@openssh.com,chacha20-poly1305@openssh.com", "-N",
            "-L", f"127.0.0.1:{int(local_port)}:127.0.0.1:{int(remote_port)}", ssh_target]


def tunnel_port(i: int) -> int:
    return RPC_PORT + 10 + int(i)


def rpc_stop_command() -> str:
    """Kill only the PID we recorded, and only if it is ggml-rpc-server."""
    return (
        f"if [ -f {RPC_PID} ]; then p=$(cat {RPC_PID}); "
        "if ps -p \"$p\" -o command= 2>/dev/null | grep -q ggml-rpc-server; then "
        "kill \"$p\"; for i in 1 2 3 4 5 6 7 8 9 10; do kill -0 \"$p\" 2>/dev/null || break; sleep 0.3; done; "
        "kill -0 \"$p\" 2>/dev/null && kill -9 \"$p\"; fi; "
        f"rm -f {RPC_PID}; fi"
    )


def parse_pid(stdout: str) -> Optional[int]:
    for line in (stdout or "").splitlines():
        line = line.strip()
        if line.startswith("PID:") and line[4:].isdigit():
            return int(line[4:])
    return None


def usage_from_timings(usage: Optional[dict], timings: Optional[dict]) -> Optional[dict]:
    """llama-server streams `timings` (ms); map them onto usage.caravan seconds
    so the stats line reads the same as MLX: Read (prefill) / Write (decode)."""
    if not timings:
        return usage
    u = dict(usage or {})
    pn = timings.get("prompt_n")
    pms = timings.get("prompt_ms")
    dn = timings.get("predicted_n")
    dms = timings.get("predicted_ms")
    u.setdefault("prompt_tokens", pn)
    u.setdefault("completion_tokens", dn)
    cv = dict(u.get("caravan") or {})
    if pms is not None:
        cv.setdefault("prefill_s", round(pms / 1000.0, 4))
        cv.setdefault("ttft_s", round(pms / 1000.0, 4))
    if pms is not None and dms is not None:
        cv.setdefault("total_s", round((pms + dms) / 1000.0, 4))
    cv.setdefault("how", "llama.cpp")
    # Native decode excludes the first token's prefill interval; warm prompt
    # rates count only uncached tokens. Dividing total usage by these times
    # inflates short/warm runs, so preserve llama.cpp's measured rates.
    import math
    for key, source in (("read_tok_s", "prompt_per_second"),
                        ("write_tok_s", "predicted_per_second")):
        value = timings.get(source)
        if isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value) and value >= 0:
            cv.setdefault(key, round(value, 2))
    u["caravan"] = cv
    return u


# ----- shared by the web UI and the CLI (one mechanism: SSH tunnels) -----

FREE_RAM_CMD = ("sysctl -n hw.pagesize; vm_stat | awk '/Pages free|Pages inactive|Pages speculative|Pages purgeable/ "
                "{gsub(\"\\\\.\",\"\",$NF); s+=$NF} END {print s}'")


def parse_free_gb(out: str) -> Optional[float]:
    """stdout of FREE_RAM_CMD → GB the next model could use (free+inactive+speculative+purgeable)."""
    try:
        lines = [l.strip() for l in (out or "").splitlines() if l.strip()]
        page, pages = int(lines[0]), int(lines[1])
        return round(page * pages / 1e9, 2)
    except (IndexError, ValueError):
        return None


def shares_from_free(free: list) -> list:
    """--tensor-split weights from live free RAM per Mini; equal if any unknown."""
    if not free or any((f is None or f <= 0) for f in free):
        return [1] * len(free or [])
    return [round(f, 1) for f in free]


def wait_port(port: int, *, proc=None, timeout: float = 10.0) -> bool:
    import socket
    import time
    end = time.time() + timeout
    while time.time() < end:
        if proc is not None and proc.poll() is not None:
            return False
        try:
            socket.create_connection(("127.0.0.1", int(port)), timeout=1).close()
            return True
        except OSError:
            time.sleep(0.25)
    return False


def pid_cmdline(pid) -> str:
    import subprocess
    try:
        return subprocess.run(["ps", "-p", str(int(pid)), "-o", "command="],
                              capture_output=True, text=True, timeout=5).stdout.strip()
    except (OSError, ValueError, Exception):
        return ""


def is_tunnel_cmd(cmd: str) -> bool:
    return cmd.startswith("ssh ") and " -L 127.0.0.1:" in cmd and ":127.0.0.1:" in cmd


def seed_command(model_name: str, size: int, shares: list, index: int,
                 repo: str = "~/cv3") -> str:
    """Remote shell (GGUF stage 2, Day 18): if this peer has its own copy of the
    same GGUF (same name and size) under ~/.caravan/models, fill its rpc-server
    cache for its share so the lead sends only hashes. Prints the seeder's JSON
    line, or NO_LOCAL_COPY. Never fails the load."""
    name = shlex.quote(Path(model_name).name)
    sh = ",".join(str(x) for x in shares)
    py = _rpath("~/.caravan/venvs/mlx/bin/python")
    seeder = _rpath(repo.rstrip("/") + "/agent/gguf_rpc_seed.py")
    return (
        f"f=$(find \"$HOME\"/.caravan/models -maxdepth 3 -name {name} 2>/dev/null | head -1); "
        f"if [ -n \"$f\" ] && [ \"$(stat -f %z \"$f\" 2>/dev/null || stat -c %s \"$f\")\" = {int(size)} ]; then "
        f"{py} {seeder} \"$f\" --shares {shlex.quote(sh)} --index {int(index)} 2>&1 | tail -1; "
        "else echo NO_LOCAL_COPY; fi"
    )


def parse_seed(stdout: str) -> Optional[dict]:
    import json
    for line in reversed((stdout or "").strip().splitlines()):
        if line.startswith("{"):
            try:
                return json.loads(line)
            except ValueError:
                return None
    return None


def gguf_schedule(best: dict, losses: list) -> list:
    """GGUF Optimize now plan: one llama-server option at a time (each needs a
    reload), skipping recorded losers ("name=value"), same 3% margin as MLX."""
    items = []
    for name, values in GGUF_KNOBS:
        if name == "flash_attn":
            inc = best.get(name, "on")
        elif name == "ubatch":
            inc = best.get(name, GGUF_DEFAULT_UBATCH)
        else:
            inc = best.get(name, "f16")
        alts = [v for v in values if v != inc and f"{name}={v}" not in losses]
        if name == "ubatch":
            alts.sort(key=lambda v: abs(v - inc))
        items.append({"name": name, "incumbent": inc, "challenger": alts[0] if alts else None,
                      "skip": None if alts else "already lost", "reload": True})
    return items
