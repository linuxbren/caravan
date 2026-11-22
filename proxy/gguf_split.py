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

import re

import os
import shlex
from pathlib import Path
from typing import Optional

from llama_runtime import bin_dir as llama_bin_dir
LLAMA_BIN = str(llama_bin_dir())
RPC_PORT = int(os.environ.get("CARAVAN_GGUF_RPC_PORT", "50052"))
GGUF_CTX = int(os.environ.get("CARAVAN_GGUF_CTX", "8192"))
# Offered Chat window sizes, plus "native" (the model's own trained
# window). Day 30: Auto picks the largest window that fits memory, up to
# the model's trained window, with no fixed cap. 8192 stays the fallback
# when the model or memory cannot be measured.
GGUF_CTX_CHOICES = (4096, 8192, 16384, 32768, 65536, 131072, 262144)
GGUF_CTX_NATIVE = "native"
# Before Day 30 Auto stopped here. Auto never picks less than that old
# rule did (it is the floor), it just no longer stops at it.
GGUF_CTX_LEGACY_AUTO_CAP = 32768
GGUF_CTX_AUTO_CAP = None  # Day 30: no cap; kept so old imports still work.
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


MIB = 1024 * 1024


def helper_overhead_mib(draft_path, total_ctx: int, ubatch: int = GGUF_DEFAULT_UBATCH,
                        kv_type: str = "q8_0", meta_fn=None) -> float:
    """GPU memory the Guess-ahead helper adds: its weights, its own chat
    memory (q8_0, same window as the main model) and its compute buffer.

    Day 28 tuning fix: this was not counted, so a 14B model with a 32k
    window plus its helper ran out of GPU memory on the first reply while
    Caravan said "ready". Unknown layout: weights plus a 1 GiB allowance.
    """
    try:
        size = Path(str(draft_path)).expanduser().stat().st_size / MIB
    except (OSError, TypeError, ValueError):
        return 0.0
    try:
        import gguf_meta
        import kv_auto
        layout = kv_auto.kv_layout((meta_fn or gguf_meta.read_metadata)(draft_path))
        kv = kv_auto.kv_bytes(layout, 1, int(total_ctx), int(ubatch), kv_type, kv_type) / MIB
        return size + kv + kv_auto.compute_reserve_mib(layout, int(ubatch))
    except Exception:  # noqa: BLE001
        return size + 1024.0


def _head_count(model_path, meta_fn=None) -> int:
    """Attention heads from the GGUF header (for the flash-off scratch size)."""
    try:
        import gguf_meta
        meta = (meta_fn or gguf_meta.read_metadata)(model_path)
        arch = meta.get("general.architecture") or ""
        v = meta.get(f"{arch}.attention.head_count")
        if isinstance(v, (list, tuple)):
            v = max(int(x) for x in v) if v else 0
        n = int(v or 0)
        return n if n > 0 else 32
    except Exception:  # noqa: BLE001
        return 32


def attention_scratch_mib(model_path, total_ctx: int, *, ubatch: int = GGUF_DEFAULT_UBATCH,
                          flash_attn: str = "on", n_devices: int = 1, meta_fn=None) -> float:
    """Working memory llama.cpp reserves that grows with the window.

    Day 30: with long windows this is no longer small. llama.cpp reserves
    its compute graph for a full window: the attention mask is window x
    prompt batch (counted at 4 bytes), on every Mac that holds layers. With
    flash attention off it also holds the full score matrix, heads x window
    x prompt batch x 4 bytes, which is many GB at 128K. Kept out of the old
    (pre-Day 30) floor so Auto never picks less than it used to.
    """
    total_ctx = max(0, int(total_ctx))
    ub = max(1, int(ubatch))
    per_device = total_ctx * ub * 4 / MIB
    if flash_attn == "off":
        per_device += _head_count(model_path, meta_fn) * total_ctx * ub * 4 / MIB
    return per_device * max(1, int(n_devices))


def ctx_estimate(model_path, ctx: int, *, n_slots: int = 1,
                 ubatch: int = GGUF_DEFAULT_UBATCH, n_devices: int = 1,
                 decide=None, extra_mib_fn=None, cache_type=None,
                 flash_attn=None, meta_fn=None):
    """(need_mib, budget_mib) from kv_auto, or (None, None) if unknown.

    need is for q8_0 chat memory, or f16 when cache_type is pinned to f16,
    plus extra_mib_fn(ctx * n_slots) (the Guess-ahead helper) when given.
    flash_attn ("on"/"off") adds the window-sized attention scratch
    (Day 30); None leaves it out, as before Day 30."""
    try:
        import kv_auto
        fn = decide or kv_auto.decide
        d = fn(
            model_path, n_slots=max(1, int(n_slots)), ctx_per_slot=int(ctx),
            n_ubatch=int(ubatch), n_devices=max(1, int(n_devices)),
        )
        est = d.estimate or {}
        need = est.get("need_f16_mib" if cache_type == "f16" else "need_q8_0_mib")
        budget = est.get("budget_mib")
        if need is None or budget is None:
            return None, None
        need = float(need)
        if extra_mib_fn is not None:
            need += float(extra_mib_fn(int(ctx) * max(1, int(n_slots))) or 0.0)
        if flash_attn in ("on", "off"):
            need += attention_scratch_mib(
                model_path, int(ctx) * max(1, int(n_slots)), ubatch=int(ubatch),
                flash_attn=flash_attn, n_devices=n_devices, meta_fn=meta_fn)
        return need, float(budget)
    except Exception:
        return None, None


def ctx_fits_known(model_path, ctx: int, **kw):
    """True if the lighter memory option fits, False if not, None if unknown."""
    need, budget = ctx_estimate(model_path, ctx, **kw)
    if need is None or budget is None:
        return None
    return need <= budget


def ctx_candidates(trained) -> list:
    """Window sizes Auto may pick for a model trained for `trained` tokens:
    the offered sizes up to it, plus the trained window itself (native)."""
    if not trained:
        return []
    trained = int(trained)
    out = [c for c in GGUF_CTX_CHOICES if c <= trained]
    if trained not in out:
        out.append(trained)
    return sorted(out)


def legacy_auto_ctx(model_path, *, n_slots: int = 1, ubatch: int = GGUF_DEFAULT_UBATCH,
                    n_devices: int = 1, decide=None, meta_fn=None,
                    extra_mib_fn=None, cache_type=None) -> int:
    """The pre-Day 30 Auto rule: start at 8192, grow while known to fit,
    never past 32768. Day 30 Auto never picks less than this."""
    trained = model_context_length(model_path, meta_fn=meta_fn)
    if not trained:
        return GGUF_CTX
    cap = min(int(trained), GGUF_CTX_LEGACY_AUTO_CAP)
    choices = [c for c in GGUF_CTX_CHOICES if c <= cap]
    if not choices:
        return max(1, cap)
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
            extra_mib_fn=extra_mib_fn, cache_type=cache_type,
        )
        if fits is True:
            best = c
        else:
            break
    return best


def auto_ctx(model_path, *, n_slots: int = 1, ubatch: int = GGUF_DEFAULT_UBATCH,
             n_devices: int = 1, decide=None, meta_fn=None,
             extra_mib_fn=None, cache_type=None, flash_attn: str = "on") -> int:
    """Chat window for Auto: as close to the model's trained window as memory allows.

    Day 30 (Brenden: "Context is important"): the largest window that fits
    this model's weights, its chat memory at the given memory compression
    (q8_0 unless cache_type pins f16), the working memory and the safety
    margin, on one Mac or across the split (n_devices), up to the model's
    trained window. No fixed cap. Never less than the pre-Day 30 rule
    (legacy_auto_ctx), and still 8192 when the file or memory cannot be
    measured.
    """
    floor = legacy_auto_ctx(
        model_path, n_slots=n_slots, ubatch=ubatch, n_devices=n_devices,
        decide=decide, meta_fn=meta_fn, extra_mib_fn=extra_mib_fn,
        cache_type=cache_type,
    )
    trained = model_context_length(model_path, meta_fn=meta_fn)
    for c in reversed(ctx_candidates(trained)):
        if c <= floor:
            break
        fits = ctx_fits_known(
            model_path, c, n_slots=n_slots, ubatch=ubatch,
            n_devices=n_devices, decide=decide, extra_mib_fn=extra_mib_fn,
            cache_type=cache_type, flash_attn=flash_attn, meta_fn=meta_fn,
        )
        if fits is True:
            return c
    return floor


def native_ctx(model_path, meta_fn=None):
    """The model's trained window, or None when the file does not say."""
    return model_context_length(model_path, meta_fn=meta_fn)


def disabled_ctx_values(model_path, *, n_slots: int = 1,
                        ubatch: int = GGUF_DEFAULT_UBATCH, n_devices: int = 1,
                        decide=None, meta_fn=None) -> dict:
    """{value: plain reason} for Chat window sizes that stay listed but unusable.

    Day 30: sizes past the model's trained window, sizes that will not fit
    memory even with the lighter chat memory, and "native" when the file
    does not say its window or the full window will not fit."""
    out = {}
    trained = model_context_length(model_path, meta_fn=meta_fn)
    for c in GGUF_CTX_CHOICES:
        if trained and c > trained:
            out[str(c)] = f"This model was trained for a shorter window ({trained})."
            continue
        fits = ctx_fits_known(
            model_path, c, n_slots=n_slots, ubatch=ubatch,
            n_devices=n_devices, decide=decide, flash_attn="on", meta_fn=meta_fn,
        )
        if fits is False:
            out[str(c)] = "This window will not fit in memory with this model."
    if not trained:
        out[GGUF_CTX_NATIVE] = "This model file does not say how long a window it was trained for."
    else:
        fits = ctx_fits_known(
            model_path, int(trained), n_slots=n_slots, ubatch=ubatch,
            n_devices=n_devices, decide=decide, flash_attn="on", meta_fn=meta_fn,
        )
        if fits is False:
            out[GGUF_CTX_NATIVE] = (f"The full trained window ({trained}) will not fit "
                                    "in memory with this model.")
    return out


# Learned (not pinned) settings that may use more memory, each with the
# lighter value Caravan falls back to when the chat window would not fit.
_LIGHTER = (("flash_attn", "off", "on"), ("cache_type", "f16", "q8_0"),
            ("ubatch", 1024, GGUF_DEFAULT_UBATCH))


def _pins(tune) -> set:
    return set((tune or {}).get("pinned_knobs") or ())


def resolve_launch(model_path, *, tune=None, ctx=None, decide=None,
                   n_devices: int = 1, ubatch: int = GGUF_DEFAULT_UBATCH,
                   meta_fn=None) -> dict:
    """Resolved per-chat window and slot count for a web llama-server start.

    Pins on the tune win. Auto Chat window uses auto_ctx(). Auto Two chats
    is one slot. -c passed to llama-server is window times slots.

    Day 30: the window comes first. Auto sizes the window with only the
    settings you pinned (tune["pinned_knobs"]); learned speed choices
    (16-bit chat memory, flash attention off, a bigger prompt batch, the
    Guess-ahead helper) never make Auto pick a shorter window. A learned
    choice that does not fit with the chosen window falls back to the
    lighter one ("lighter" lists what changed); the helper is left off.
    "native" is the model's trained window.
    """
    tune = dict(tune or {})
    pins = _pins(tune)
    try:
        n_slots = int(tune["n_slots"]) if tune.get("n_slots") is not None else GGUF_DEFAULT_SLOTS
    except (TypeError, ValueError):
        n_slots = GGUF_DEFAULT_SLOTS
    n_slots = max(1, min(int(n_slots), GGUF_MAX_SLOTS))
    draft = (_existing_draft_path(tune.get("draft_path"))
             if tune.get("guess_ahead") == "on" else None)
    extra = None
    if draft:
        def extra(total_ctx, _d=draft, _ub=ubatch):
            return helper_overhead_mib(_d, total_ctx, _ub)
    fa = tune.get("flash_attn") if tune.get("flash_attn") in ("on", "off") else "on"
    ct = tune.get("cache_type")
    # Settings Auto sizes the window with: pins as they are, learned
    # choices at their lightest.
    size_fa = fa if "flash_attn" in pins else "on"
    size_ct = ct if "cache_type" in pins else None
    size_ub = int(ubatch) if "ubatch" in pins else min(int(ubatch), GGUF_DEFAULT_UBATCH)
    size_extra = extra if "guess_ahead" in pins else None

    def _auto():
        return auto_ctx(
            model_path, n_slots=n_slots, ubatch=size_ub,
            n_devices=n_devices, decide=decide, meta_fn=meta_fn,
            extra_mib_fn=size_extra, cache_type=size_ct, flash_attn=size_fa,
        )
    raw = tune.get("ctx") if tune.get("ctx") is not None else ctx
    ctx_auto = False
    if raw is not None and str(raw).strip().lower() == GGUF_CTX_NATIVE:
        ctx_per = native_ctx(model_path, meta_fn=meta_fn) or _auto()
    elif raw is not None and not tune.get("ctx_auto"):
        try:
            ctx_per = int(raw)
        except (TypeError, ValueError):
            ctx_per, ctx_auto = _auto(), True
    else:
        ctx_per, ctx_auto = _auto(), True
    if ctx_per < 1:
        ctx_per = GGUF_CTX
    out = {
        "ctx": ctx_per,
        "n_slots": n_slots,
        "total_ctx": ctx_per * n_slots,
        "ctx_auto": ctx_auto,
    }
    # Learned heavier choices fall back to lighter ones until this window
    # fits (pins stay as they are). Unknown memory changes nothing.
    eff = {"flash_attn": fa, "cache_type": ct, "ubatch": int(ubatch)}

    def _fits(with_extra=None):
        return ctx_fits_known(
            model_path, ctx_per, n_slots=n_slots, ubatch=eff["ubatch"],
            n_devices=n_devices, decide=decide, extra_mib_fn=with_extra,
            cache_type=eff["cache_type"] if eff["cache_type"] == "f16" else None,
            flash_attn=eff["flash_attn"], meta_fn=meta_fn,
        )
    lighter = {}
    if _fits() is False:
        for name, heavy, light in _LIGHTER:
            if name in pins or eff.get(name) != heavy:
                continue
            eff[name] = light
            lighter[name] = light
            if _fits() is not False:
                break
    if lighter:
        out["lighter"] = lighter
        out.update({k: eff[k] for k in lighter})
    if draft:
        # A window that leaves no room for the helper: run without it
        # (llama_args drops the helper flags) instead of failing replies.
        fits = _fits(extra)
        out["helper_fits"] = fits is not False
    return out


def window_blockers(model_path, *, n_slots: int = 1, n_devices: int = 1,
                    pins=(), decide=None, meta_fn=None) -> set:
    """Heavier settings ("name=value") that would not fit with the Auto
    window. Day 30: Auto-tune and Self-tuning skip those trials, because
    keeping such a win would need a shorter chat window."""
    pins = set(pins or ())
    try:
        w = auto_ctx(model_path, n_slots=n_slots, n_devices=n_devices,
                     decide=decide, meta_fn=meta_fn)
    except Exception:  # noqa: BLE001
        return set()
    out = set()
    for name, heavy, _light in _LIGHTER:
        if name in pins:
            continue
        kw = {"flash_attn": "on", "cache_type": None, "ubatch": GGUF_DEFAULT_UBATCH}
        kw[name] = heavy
        fits = ctx_fits_known(
            model_path, w, n_slots=n_slots, n_devices=n_devices, decide=decide,
            meta_fn=meta_fn, ubatch=int(kw["ubatch"]), flash_attn=kw["flash_attn"],
            cache_type=kw["cache_type"],
        )
        if fits is False:
            out.add(f"{name}={heavy}")
    return out


WINDOW_SKIP = "needs a shorter chat window"


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
           "slot_save": bool, "ctx": int, "n_slots": 1|2,
           "prompt_lookup": "on"|"off", "guess_ahead": "on"|"off",
           "draft_path": str}.
    Prompt lookup adds --spec-type ngram-simple (llama.cpp b12283; Day 27
    measured it well ahead of ngram-mod on code edits and no worse on
    short chats, see docs/DAY27.md). Guess-ahead
    adds --spec-draft-model and --spec-type draft-simple only when draft_path
    is a file already on disk; this never downloads a helper, and never
    passes --spec-draft-hf or --fim-qwen-*-spec. Use resolve_launch() for
    the resolved ctx, n_slots, and total_ctx.
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
    # Day 30: a learned heavier choice that does not fit this window was
    # swapped for the lighter one (the window wins).
    lighter = launch.get("lighter") or {}
    if lighter:
        tune = dict(tune, **lighter)
        if "flash_attn" in lighter:
            fa = lighter["flash_attn"]
        if "ubatch" in lighter:
            ub = int(lighter["ubatch"])
            batch = max(ub, GGUF_DEFAULT_BATCH)
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
    else:
        # Day 28 tuning fix 2: one chat means one slot. Without --parallel,
        # llama-server opens 4 slots sharing one memory pool; long prompts
        # then rotate through slots, the pool fills with old prompts, and on
        # 2 Macs the 2nd Mac's rpc-server hit a GPU address fault on an 8k
        # prompt (reply failed, then HTTP 502). Stock llama.cpp runs used -np 1.
        args += ["--parallel", "1"]
    if tune.get("slot_save", True) is not False:
        sp = slot_save_dir(ctk, ctv, root=slot_root, ctx=ctx_per, n_slots=n_slots)
        args += ["--slot-save-path", str(sp) + "/"]
    if peers:
        devs = ["MTL0"] + [f"RPC{i}" for i in range(len(peers))]
        args += ["--rpc", ",".join(peers), "--device", ",".join(devs),
                 "--tensor-split", ",".join(str(s) for s in shares)]
    if launch.get("helper_fits") is False:
        tune = dict(tune, guess_ahead="off")
    args += _speculative_args(tune, split=bool(peers), flash_attn=fa)
    return args


def _speculative_args(tune: Optional[dict], *, split: bool = False,
                      flash_attn: str = "on") -> list:
    """llama-server speculative flags. Never a download, never a missing file.

    Day 28 tuning fix: the helper keeps its chat memory in q8_0 (half of
    f16; it was the same size as the main model's f16 memory), runs fully
    on the GPU, and on a split it stays on this Mac's GPU (MTL0) so its
    many small steps never cross the network.
    """
    tune = dict(tune or {})
    want_lookup = tune.get("prompt_lookup") == "on"
    draft = _existing_draft_path(tune.get("draft_path"))
    want_draft = tune.get("guess_ahead") == "on" and draft is not None
    if not want_lookup and not want_draft:
        return []
    kinds = []
    if want_lookup:
        kinds.append("ngram-simple")
    if want_draft:
        kinds.append("draft-simple")
    out = ["--spec-type", ",".join(kinds)]
    if want_draft:
        out += ["--spec-draft-model", draft,
                "--spec-draft-ngl", "999",
                "-ctkd", "q8_0", "-ctvd", "q8_0" if flash_attn == "on" else "f16"]
        if split:
            out += ["--spec-draft-device", "MTL0"]
    return out


def _existing_draft_path(path) -> Optional[str]:
    """Absolute path of a GGUF file already on disk, or None. Never a URL."""
    if not path:
        return None
    s = str(path).strip()
    if not s or "://" in s or s.startswith("-"):
        return None
    p = Path(s).expanduser()
    try:
        if p.is_file() and p.suffix.lower() == ".gguf" and p.stat().st_size > 0:
            return str(p.resolve())
    except OSError:
        return None
    return None


def _param_b(name: str):
    """Parameter count in billions from a file or model name, or None."""
    blob = str(name or "")
    m = re.search(r'(?i)(\d+(?:\.\d+)?)\s*b\b', blob)
    if m:
        return float(m.group(1))
    m = re.search(r'(?i)(\d+(?:\.\d+)?)\s*m\b', blob)
    if m:
        return float(m.group(1)) / 1000.0
    return None


def _family_id(*names) -> Optional[str]:
    try:
        from web_picker import family_of
        fam = family_of(*names)
        if fam and fam.get("id"):
            return fam["id"]
    except Exception:
        pass
    blob = " ".join(str(n) for n in names if n).lower().replace("_", "-")
    for key in ("qwen", "llama", "gemma", "mistral", "deepseek", "phi",
                "gpt-oss", "gptoss"):
        if key in blob:
            return "gpt-oss" if key in ("gpt-oss", "gptoss") else key
    return None


_GENERATIONS = (
    ("qwen3", r"qwen[-_ ]?3"),
    ("qwen2.5", r"qwen[-_ ]?2\.5"),
    ("qwen2", r"qwen[-_ ]?2(?![.\d])"),
    ("llama3", r"llama[-_ ]?3"),
    ("llama2", r"llama[-_ ]?2"),
    ("gemma3", r"gemma[-_ ]?3"),
    ("gemma2", r"gemma[-_ ]?2"),
)


def _generation(*names) -> Optional[str]:
    """Model generation from a name ("qwen2.5", "qwen3", "llama3"...), or None.

    Day 27: a helper must share the main model's tokenizer. Same family is
    not enough (Qwen2.5 and Qwen3 are both "qwen"), so when both names say
    their generation, the generations must match.
    """
    blob = " ".join(str(n) for n in names if n).lower()
    for gen, pat in _GENERATIONS:
        if re.search(pat, blob):
            return gen
    return None


def find_gguf_draft(main_path, *, inventory=None) -> Optional[dict]:
    """A smaller same-family GGUF already on this Mac, or None.

    Never downloads. The helper must be a real file, the same family as
    the main model, and clearly smaller (fewer parameters when the names
    say so, otherwise a smaller file, at most half the main model's size).
    The main model itself is never picked.
    """
    main = Path(str(main_path)).expanduser()
    try:
        main_res = main.resolve() if main.is_file() else main
        main_size = main.stat().st_size if main.is_file() else 0
    except OSError:
        main_res, main_size = main, 0
    main_fam = _family_id(main.name, main.stem, str(main))
    if not main_fam:
        return None
    main_params = _param_b(main.name) or _param_b(main.stem)
    main_gen = _generation(main.name)
    cands = list(inventory or [])
    if not cands:
        try:
            cands = scan_local()
        except Exception:
            cands = []
        # Also look next to the main file (same folder, other GGUFs).
        try:
            if main.parent.is_dir():
                for p in sorted(main.parent.glob("*.gguf")):
                    cands.append({"path": str(p), "name": p.stem,
                                  "size_gb": round(p.stat().st_size / 1e9, 2)})
        except OSError:
            pass
    best = None
    best_size = None
    for item in cands:
        if not isinstance(item, dict):
            continue
        raw = item.get("path") or item.get("lead_path")
        path = _existing_draft_path(raw)
        if not path:
            continue
        p = Path(path)
        try:
            if p.resolve() == main_res:
                continue
            size = p.stat().st_size
        except OSError:
            continue
        if size < 50_000_000:
            continue
        if main_size and size >= main_size * 0.5:
            continue
        fam = _family_id(p.name, p.stem, item.get("name"), item.get("id"), path)
        if fam != main_fam:
            continue
        gen = _generation(p.name)
        if main_gen and gen and gen != main_gen:
            continue
        params = _param_b(p.name) or _param_b(p.stem) or _param_b(item.get("name") or "")
        if main_params and params is not None and not (params < main_params):
            continue
        if main_params and params is None:
            # Name does not say the size; only accept a clearly smaller file.
            if not main_size or size >= main_size * 0.35:
                continue
        if best is None or size < best_size:
            best = {
                "path": path,
                "name": p.stem,
                "family": main_fam,
                "size_gb": round(size / 1e9, 2),
            }
            best_size = size
    return best


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
    # Day 27: how many guessed words were kept (Prompt lookup / Guess-ahead).
    if "draft_n" in timings or "draft_n_accepted" in timings:
        dn_ = timings.get("draft_n")
        da_ = timings.get("draft_n_accepted")
        spec = {"proposed": dn_, "accepted": da_, "from_draft": da_, "n_gen": dn}
        if isinstance(da_, (int, float)) and isinstance(dn, (int, float)) and dn:
            spec["accepted_frac"] = round(float(da_) / float(dn), 3)
        cv.setdefault("speculate", spec)
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


def gguf_schedule(best: dict, losses: list, *, n_slots: int = 1,
                  pinned=None, draft_path=None, blocked=None) -> list:
    """GGUF Optimize now plan: one llama-server option at a time (each needs a
    reload), skipping recorded losers ("name=value"), same 3% margin as MLX.

    Prompt lookup is tried last, only when it is safe: one chat (not Two
    chats), and the row is not pinned Off or On.

    Day 27: when draft_path names a smaller same-family helper already on
    this Mac, Guess-ahead is tried after Prompt lookup with the same
    gates (one chat, not pinned) and the same 3% margin, so Auto keeps
    it only when it measured faster on the Auto-tune prompts. Nothing is
    downloaded; with no helper there is no Guess-ahead step at all.
    Self-tuning does not use these extra options (it reads GGUF_KNOBS
    only).

    Day 30: blocked lists heavier values ("cache_type=f16") that would not
    fit with the full Auto chat window (window_blockers); a trial of or
    against one is skipped, because keeping it would shorten the window.
    """
    defaults = {
        "flash_attn": "on",
        "ubatch": GGUF_DEFAULT_UBATCH,
        "cache_type": "f16",
        "prompt_lookup": "off",
    }
    items = []
    blocked = set(blocked or ())
    for name, values in GGUF_KNOBS:
        inc = best.get(name, defaults[name])
        alts = [v for v in values if v != inc and f"{name}={v}" not in losses
                and f"{name}={v}" not in blocked]
        if name == "ubatch":
            alts.sort(key=lambda v: abs(v - inc))
        skip = None if alts else "already lost"
        if f"{name}={inc}" in blocked:
            skip = WINDOW_SKIP
        elif not alts and any(f"{name}={v}" in blocked for v in values if v != inc):
            skip = WINDOW_SKIP
        items.append({"name": name, "incumbent": inc,
                      "challenger": alts[0] if alts and not skip else None,
                      "skip": skip, "reload": True})
    # Prompt lookup last, and only when it is safe.
    inc = best.get("prompt_lookup", "off")
    pinned_set = set(pinned or [])
    skip = None
    challenger = None
    if int(n_slots or 1) > 1:
        skip = "two chats"
    elif "prompt_lookup" in pinned_set:
        skip = "pinned"
    else:
        alts = [v for v in ("on", "off") if v != inc and f"prompt_lookup={v}" not in (losses or [])]
        # We only ever trial turning it on (the default is off).
        if inc == "off" and "on" in alts:
            challenger = "on"
        elif inc == "on" and "off" in alts:
            challenger = "off"
        else:
            skip = "already lost"
    items.append({"name": "prompt_lookup", "incumbent": inc,
                  "challenger": challenger, "skip": skip, "reload": True})
    draft = _existing_draft_path(draft_path)
    if draft:
        inc = best.get("guess_ahead", "off")
        if inc not in ("on", "off"):
            inc = "off"
        skip = None
        challenger = None
        if int(n_slots or 1) > 1:
            skip = "two chats"
        elif "guess_ahead" in pinned_set:
            skip = "pinned"
        else:
            other = "on" if inc == "off" else "off"
            if f"guess_ahead={other}" in (losses or []):
                skip = "already lost"
            else:
                challenger = other
        items.append({"name": "guess_ahead", "incumbent": inc,
                      "challenger": challenger, "skip": skip, "reload": True,
                      "draft_path": draft})
    return items
