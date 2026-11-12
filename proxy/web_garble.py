"""Apply a safe-settings fix after a garbled chat reply."""
from __future__ import annotations

from typing import Optional


def _optimizer_running(optimizer) -> bool:
    if optimizer is None:
        return False
    try:
        if callable(getattr(optimizer, "inflight", None)) and optimizer.inflight() > 0:
            return True
    except Exception:
        pass
    snap = None
    try:
        if callable(getattr(optimizer, "snapshot", None)):
            snap = optimizer.snapshot()
    except Exception:
        snap = None
    if isinstance(snap, dict):
        if snap.get("running") or snap.get("phase") in ("running", "A/B", "reloading"):
            # "running" is the usual flag; phase strings vary.
            if snap.get("running") is True or (
                snap.get("running") is not False and snap.get("phase") and
                snap.get("phase") not in ("idle", "done", None, "")
                and snap.get("running")
            ):
                return bool(snap.get("running"))
        if snap.get("running"):
            return True
    return bool(getattr(optimizer, "running", False))


def _record_losses(mgr, settings) -> None:
    try:
        import garble
        import tuned_settings as TS
    except ImportError:
        return
    losses = garble.losses_from_used(settings)
    if not losses:
        return
    lp = getattr(mgr, "_lead_path", None)
    try:
        st, entry = mgr._tuned_entry(lp)
    except Exception:
        return
    if not entry:
        return
    for name, val in losses:
        try:
            TS.block_value(entry, name, val, "garbled reply")
        except Exception:
            pass
    try:
        TS.save_store(st, mgr.tuned_path)
    except Exception:
        pass


def _clear_last_model_kv(mgr, new_settings) -> None:
    try:
        from web_restore import Store
        store = Store(mgr.state_dir / "last-model.json")
        req = store.read()
        if not req:
            return
        settings = dict(req.get("settings") or {})
        if "kv_bits" in new_settings:
            settings["kv_bits"] = new_settings["kv_bits"]
        for key in ("guess_ahead", "prompt_lookup", "fuse_kernels", "shared_start", "cache_type"):
            if key in new_settings:
                settings[key] = new_settings[key]
        req["settings"] = settings
        store.write(req)
    except Exception:
        pass


def handle_garbled_reply(mgr, text, *, raw=None, optimizer=None) -> Optional[dict]:
    """If the reply is garbled, record a loss and move to safe settings.

    Returns a dict with a user-facing ``message`` (and whether a reload
    happened), or None if the reply was fine. Does not loop: when settings
    are already safe, only the notice is returned.
    """
    import garble
    if not garble.is_garbled(text, raw=raw):
        return None
    snap = mgr.snapshot() if mgr is not None else {}
    settings = dict(snap.get("settings") or snap.get("page_settings") or {})
    backend = "gguf" if snap.get("backend") == "llama" else "mlx"
    plan = garble.plan_garble_fix(settings, backend=backend)
    _record_losses(mgr, settings)
    result = {
        "message": plan["message"],
        "changed": False,
        "already_safe": plan["already_safe"],
        "reload": False,
        "changes": plan["changes"],
    }
    if plan["already_safe"]:
        return result
    if _optimizer_running(optimizer):
        result["deferred"] = True
        return result
    mid = snap.get("model_id")
    if not mid:
        return result
    page = dict(snap.get("page_settings") or settings)
    for key, val in plan["changes"]:
        page[key] = val
    if any(k == "kv_bits" for k, _ in plan["changes"]):
        page["kv_bits"] = "16"
    try:
        mgr.switch(mid, wait=True, settings=page)
    except Exception as e:
        result["error"] = str(e)[:200]
        return result
    _clear_last_model_kv(mgr, page)
    result["changed"] = True
    result["reload"] = True
    return result


def attach_garble(app, raw_text, meta, *, cancelled=False):
    """Maybe run the auto-fix and put the notice on a chat meta payload."""
    if cancelled or meta is None:
        return meta
    try:
        import garble
        if not garble.is_garbled(raw_text):
            return meta
        opt = getattr(app, "optimizer", None)
        result = handle_garbled_reply(app.mgr, raw_text, optimizer=opt)
        if result:
            meta["garble"] = {
                "message": result["message"],
                "changed": result.get("changed"),
                "already_safe": result.get("already_safe"),
            }
            # Refresh settings so the page shows what is live now.
            try:
                meta["settings"] = app.mgr.snapshot().get("settings")
            except Exception:
                pass
    except Exception:
        pass
    return meta
