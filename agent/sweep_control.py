"""Worker-side Optimize now controls. Called on the engine queue, under its lock."""
from __future__ import annotations

import copy
from pathlib import Path
import optimize_schedule as AB
import tuned_settings as TS
try:
    from caravan_i18n import T  # noqa: E402  (Day 32: user-facing text, tools/caravan_i18n.py)
except ImportError:  # run without tools/ on the path
    import sys as _sys
    from pathlib import Path as _Path
    _sys.path.append(str(_Path(__file__).resolve().parents[1] / "tools"))
    from caravan_i18n import T  # noqa: E402


def _live(engine, name, value):
    if name == "guess_ahead":
        engine._learn_guess_override = value
    elif name == "shared_prefix":
        engine._set_shared_prefix(value, reason=T("agent.sweep_control.optimize_now"))
    elif name == "pipeline_chats":
        engine.pipeline_chats = value


def apply(engine, body):
    if not isinstance(body, dict):
        raise ValueError(T("agent.sweep_control.control_must_be_an_object"))
    hold = body.get("hold") or {}
    explicit = getattr(engine, "_learn_explicit", None) or {}
    commit = body.get("commit")
    if not isinstance(hold, dict):
        raise ValueError(T("agent.sweep_control.hold_must_be_an_object"))
    for name, value in hold.items():
        if name not in AB.LIVE:
            raise ValueError(T("agent.sweep_control.hold_only_accepts_live_options"))
        AB.validate(name, value)
        if name in explicit and explicit[name] != value:
            raise ValueError(name + T("agent.sweep_control.is_pinned"))
        if name == "guess_ahead" and value and getattr(engine, "draft_model", None) is None:
            raise ValueError(T("agent.sweep_control.no_helper_loaded"))
        if name in ("shared_prefix", "pipeline_chats") and getattr(engine, "client", None) is None:
            if value not in (False, 1):
                raise ValueError(name + T("agent.sweep_control.needs_a_split_worker"))
    if commit:
        if not isinstance(commit, dict):
            raise ValueError(T("agent.sweep_control.commit_must_be_an_object"))
        AB.validate(commit.get("name"), commit.get("winner"))
        if commit.get("lost") is not None:
            AB.validate(commit["name"], commit["lost"])
        if commit["name"] in explicit and explicit[commit["name"]] != commit["winner"]:
            raise ValueError(commit["name"] + T("agent.sweep_control.is_pinned"))
    with engine._learn_lock:
        if body.get("release"):
            for name, value in (getattr(engine, "_sweep_restore", None) or {}).items():
                _live(engine, name, value)
            engine._sweep_restore = None
            engine._learn_conc_window = []
            engine._sweep_pause = False
        else:
            if getattr(engine, "_sweep_restore", None) is None:
                engine._sweep_restore = {
                    "guess_ahead": engine._learn_guess_override,
                    "pipeline_chats": engine.pipeline_chats,
                    "shared_prefix": bool(engine._shared_prefix_on()),
                }
            # Persist a copy first. A disk error must not publish an in-memory
            # winner or suppress the losing value only until the next restart.
            if commit:
                if engine._learn_entry is None:
                    raise ValueError(T("agent.sweep_control.everyday_learning_is_off_load_with"))
                store = copy.deepcopy(engine._learn_store)
                entry = store["models"][engine._learn_key]
                AB.commit(entry, commit.get("fingerprint"), commit["name"], commit["winner"],
                          commit.get("lost"), commit.get("measurements"))
                path = Path(engine._learn_path).expanduser() if engine._learn_path else None
                TS.save_store(store, path)
                engine._learn_store = store
                engine._learn_entry = entry
                if commit["name"] in AB.LIVE:
                    engine._sweep_restore[commit["name"]] = commit["winner"]
                    hold = dict(hold, **{commit["name"]: commit["winner"]})
            engine._sweep_pause = True
            engine._learn_trial = None
            engine._learn_conc_window = []
            for name, value in hold.items():
                _live(engine, name, value)
        return {"paused": bool(getattr(engine, "_sweep_pause", False)),
                "winner": dict((engine._learn_entry or {}).get("winner") or {})}
