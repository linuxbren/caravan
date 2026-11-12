"""Apply Memory-compression policy: hide 4 where it can't work, probe 4/8 after load."""
from __future__ import annotations

from typing import Optional


def _kv(settings) -> str:
    if not isinstance(settings, dict):
        return "auto"
    v = settings.get("kv_bits")
    if v in (None, "", "auto"):
        return "auto"
    return str(v).strip().lower()


def record_loss(mgr, kv, reason: str) -> None:
    """Remember this Memory compression value as a loss for the loaded model."""
    try:
        import tuned_settings as TS
        lp = getattr(mgr, "_lead_path", None) or (
            (getattr(mgr, "_loaded_entry", None) or {}).get("lead_path")
        )
        st, entry = mgr._tuned_entry(lp, create=True)
        if entry is not None:
            TS.block_value(entry, "kv_bits", int(kv), reason)
            trial = entry.get("reload_trial") or {}
            if trial.get("name") == "kv_bits" and int(trial.get("value") or 0) == int(kv):
                entry["reload_trial"] = None
            TS.save_store(st, mgr.tuned_path)
    except Exception:
        pass


def write_last_model(mgr, kv="auto") -> None:
    try:
        from web_restore import Store
        store = Store(mgr.state_dir / "last-model.json")
        req = store.read()
        if not req:
            return
        settings = dict(req.get("settings") or {})
        settings["kv_bits"] = kv
        req["settings"] = settings
        store.write(req)
    except Exception:
        pass


def set_page_kv(mgr, kv="auto") -> dict:
    snap = mgr.snapshot() if mgr is not None else {}
    page = dict(snap.get("page_settings") or snap.get("settings") or {})
    page["kv_bits"] = kv
    try:
        mgr._set(page_settings=page)
    except Exception:
        pass
    write_last_model(mgr, kv)
    return page


def apply_saved_4_fallback(mgr, entry, settings) -> tuple:
    """If this model cannot use 4 and settings ask for 4, fall back to Auto.

    Returns (settings, notice_or_None). Does not load or reload.
    """
    import kv_quality as K
    settings = dict(settings or {})
    if _kv(settings) != "4":
        return settings, None
    path = (entry or {}).get("lead_path")
    source = (entry or {}).get("source") or ""
    if source == "gguf" or not K.allows_memory_compression_4(model_dir=path):
        settings["kv_bits"] = "auto"
        return settings, K.FALLBACK_NOTE
    return settings, None


def block_four_if_disallowed(mgr, entry) -> None:
    """Tell Self-tuning and Auto-tune never to try 4 on this model."""
    import kv_quality as K
    path = (entry or {}).get("lead_path")
    if (entry or {}).get("source") == "gguf":
        record_loss(mgr, 4, "GGUF does not offer Memory compression 4")
        return
    if K.allows_memory_compression_4(model_dir=path):
        return
    record_loss(mgr, 4, "Memory compression 4 is not available on this model")


def live_kv_bits(mgr) -> Optional[int]:
    """The Memory compression the loaded worker is actually using."""
    if mgr is None:
        return None
    # Prefer the worker's own report (Auto may have chosen 8).
    try:
        active = mgr.lead_active_settings()
        if isinstance(active, dict) and active.get("kv_bits") is not None:
            n = int(active["kv_bits"])
            if n in (4, 8, 16):
                return n
    except Exception:
        pass
    snap = mgr.snapshot() if mgr is not None else {}
    for src in (snap.get("settings"), snap.get("page_settings")):
        if not isinstance(src, dict):
            continue
        v = src.get("kv_bits")
        if v in (None, "", "auto", "f16"):
            continue
        try:
            n = int(v)
        except (TypeError, ValueError):
            continue
        if n in (4, 8, 16):
            return n
    return 16


def maybe_probe(mgr, *, urlopen=None) -> Optional[dict]:
    """After a successful load at 4 or 8: probe. Does not reload.

    Returns a result dict. When the answer is definitely wrong,
    ``need_reload`` is True and ``notice`` is the plain user-facing
    message. The caller reloads at 16 (never this function), so a
    nested switch cannot start. Skips when already at 16, when a
    probe is already in flight, and on transport errors (not definite).
    """
    import kv_quality as K

    if mgr is None or getattr(mgr, "_kv_probe_guard", False):
        return None
    kv = live_kv_bits(mgr)
    if kv not in (4, 8):
        return None
    snap = mgr.snapshot()
    if snap.get("status") != "ready":
        return None
    port = getattr(mgr, "lead_port", None)
    if not port:
        return None

    mgr._kv_probe_guard = True
    try:
        result = K.run_http_probe(port, urlopen=urlopen)
    except Exception as e:
        result = {
            "ok": False, "definite": False,
            "error": str(e)[:200], "content": "", "elapsed": 0,
        }

    out = {
        "ok": bool(result.get("ok")),
        "kv_bits": kv,
        "definite": bool(result.get("definite")),
        "content": result.get("content") or "",
        "elapsed": result.get("elapsed"),
        "error": result.get("error"),
        "notice": None,
        "need_reload": False,
        "reverted": False,
    }
    if out["ok"] or not out["definite"]:
        mgr._kv_probe = out
        try:
            mgr._set(quality=out, quality_notice=None)
        except Exception:
            pass
        mgr._kv_probe_guard = False
        return out

    notice = K.probe_fail_notice(kv)
    out["notice"] = notice
    out["need_reload"] = True
    record_loss(mgr, kv, "load-time quality probe failed")
    set_page_kv(mgr, "16")
    mgr._kv_probe = out
    try:
        mgr._set(quality=out, quality_notice=notice)
    except Exception:
        pass
    # Leave the guard set so a follow-up load at 16 is not probed.
    # The caller clears it after that load finishes.
    return out


def finish_probe_reload(mgr, result) -> None:
    """Mark a completed revert and drop the no-loop guard."""
    if isinstance(result, dict):
        result["reverted"] = True
        result["need_reload"] = False
        mgr._kv_probe = result
        try:
            mgr._set(quality=result, quality_notice=result.get("notice"))
        except Exception:
            pass
    if mgr is not None:
        mgr._kv_probe_guard = False
