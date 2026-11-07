"""Pure one-option A/B planning and hardware-scoped results (no MLX import)."""
from __future__ import annotations

import hashlib
import json
import math
import time
import tuned_settings as TS

# UI key, worker key, requires a reload. There is no Cartesian-product search.
KNOBS = (("guess_ahead", "guess_ahead", False),
         ("shared_start", "shared_prefix", False),
         ("pipeline_chats", "pipeline_chats", False),
         ("kv_bits", "kv_bits", True),
         ("fuse_kernels", "fuse_kernels", True),
         ("keepalive", "keepalive", True),
         (None, "packer_layers", True))
LIVE = {"guess_ahead", "shared_prefix", "pipeline_chats"}


def validate(name, value):
    """Reject malformed controls before mutating the worker or its store."""
    if name in ("guess_ahead", "shared_prefix", "keepalive"):
        if not isinstance(value, bool):
            raise ValueError(name + " needs a boolean")
    elif name in ("kv_bits", "pipeline_chats", "packer_layers"):
        if isinstance(value, bool) or not isinstance(value, int):
            raise ValueError(name + " needs an integer")
        if (name == "kv_bits" and value not in (16, 8, 4) or
                name == "pipeline_chats" and value not in (1, 2) or
                name == "packer_layers" and value < 1):
            raise ValueError("invalid " + name)
    elif name == "fuse_kernels":
        if value not in ("off", "on"):
            raise ValueError("invalid fuse_kernels")
    else:
        raise ValueError("unknown option " + str(name))
    return value


def fingerprint(nodes, *, split):
    """Stable identity for every participating Mini; never use free RAM/load."""
    if not nodes or any(n.get("offline") or n.get("error") for n in nodes):
        raise ValueError("hardware information unavailable; cannot reuse loss records")
    parts = []
    for n in nodes:
        part = {k: n.get(k) for k in ("id", "host", "role", "peer", "chip", "cpus", "machine")}
        part["ram_gb"] = (n.get("ram") or {}).get("total_gb")
        if not part["chip"] or not part["ram_gb"]:
            raise ValueError("hardware chip/RAM information unavailable")
        parts.append(part)
    payload = {"split": bool(split), "nodes": sorted(parts, key=lambda n: str(n["id"]))}
    return hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()


def baseline(entry, active, settings=None):
    # Explicit user/config flags always win; don't mistake an everyday temporary
    # probe for the best known value when starting a walk-away pass.
    out = {}
    for _, name, _ in KNOBS:
        key = "shared_start" if name == "shared_prefix" else name
        if active.get(key) is not None:
            out[name] = active[key]
    for ui, name, _ in KNOBS:
        winner = ((entry or {}).get("winner") or {}).get(name)
        applicable = name in out
        if name == "guess_ahead" and not active.get("guess_ahead_loaded"):
            applicable = False
        if name in ("shared_prefix", "pipeline_chats") and not active.get("two_chats_available", active.get("keepalive") is not None):
            applicable = False
        if (applicable and winner is not None and name not in (active.get("pinned") or [])
                and (not ui or (settings or {}).get(ui, "auto") == "auto")):
            out[name] = winner
    for name in TS.RELOAD_TRIO:
        if name in out:
            out[name] = TS._norm_reload(name, out[name])
    return out


def schedule(entry, settings, active, fp, *, n_layers=None):
    base = baseline(entry, active, settings)
    losses = (((entry or {}).get("optimize_hardware") or {}).get(fp) or {}).get("losses") or []
    pinned = set(active.get("pinned") or [])
    unavailable = set()
    if not active.get("guess_ahead_loaded") or active.get("guess_ahead_mode") == "native_mtp":
        unavailable.add("guess_ahead")
    if not active.get("two_chats_available", active.get("keepalive") is not None):
        unavailable.update(("shared_prefix", "pipeline_chats", "keepalive", "packer_layers"))
    if not n_layers or not active.get("packer_layers"):
        unavailable.add("packer_layers")
    if not active.get("kv_quant_supported", True):
        unavailable.add("kv_bits")
    items = []
    for ui, name, reload in KNOBS:
        item = dict(name=name, reload=reload, incumbent=base.get(name), challenger=None, state="pending", skip=None)
        if name in unavailable:
            item["skip"] = "unavailable"
        elif name in pinned or ui and settings.get(ui, "auto") != "auto":
            item["skip"] = "pinned"
        elif base.get(name) is None:
            item["skip"] = "no baseline"
        else:
            inc = base[name]
            if name == "kv_bits":
                alternatives = [v for v in (8, 4, 16) if v != inc]
            elif name == "fuse_kernels":
                alternatives = ["on" if inc == "off" else "off"]
            elif name == "keepalive":
                alternatives = [not inc]
            else:
                alternatives = TS.neighbors(name, inc, n_layers=n_layers)
                if name == "packer_layers":
                    alternatives.sort(key=lambda v: (abs(v - inc), v))
            alternatives = [v for v in alternatives if TS.option_id(name, v) not in losses
                            and v not in TS.blocked_values(entry, name)]
            if alternatives:
                item["challenger"] = alternatives[0]
            else:
                item["skip"] = "already lost or blocked"
        if item["skip"]:
            item["state"] = "skipped"
        items.append(item)
    return items


def pick(inc_scores, challenger_scores):
    """Incomplete/invalid arms can never publish a winner or a loss."""
    if (not inc_scores or len(inc_scores) != len(challenger_scores) or
            any(not math.isfinite(x) or x <= 0 for x in inc_scores + challenger_scores)):
        raise ValueError("incomplete or invalid A/B measurements")
    return sum(challenger_scores) >= sum(inc_scores) * TS.SWITCH_MARGIN


def commit(entry, fp, name, winner, lost=None, measurements=None):
    validate(name, winner)
    if lost is not None:
        validate(name, lost)
    if not isinstance(fp, str) or not fp or len(fp) > 128:
        raise ValueError("hardware fingerprint required")
    entry.setdefault("winner", {})[name] = winner
    box = entry.setdefault("optimize_hardware", {}).setdefault(fp, {"losses": [], "results": []})
    if lost is not None:
        oid = TS.option_id(name, lost)
        if oid not in box["losses"]:
            box["losses"].append(oid)
    # If later retested and won, don't keep suppressing it as a loser.
    winner_id = TS.option_id(name, winner)
    box["losses"] = [v for v in box["losses"] if v != winner_id]
    box["results"] = (box["results"] + [dict(name=name, winner=winner, lost=lost,
        measurements=measurements, timestamp=time.time())])[-100:]
    entry.setdefault("pending_reload", {}).pop(name, None)
    entry["reload_trial"] = None
