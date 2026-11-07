"""Worker-side Optimize now controls. Called on the engine queue, under its lock."""
from __future__ import annotations

import copy
from pathlib import Path
import optimize_schedule as AB
import tuned_settings as TS


def _live(engine, name, value):
    if name == "guess_ahead":
        engine._learn_guess_override = value
    elif name == "shared_prefix":
        engine._set_shared_prefix(value, reason="optimize now")
    elif name == "pipeline_chats":
        engine.pipeline_chats = value


def apply(engine, body):
    if not isinstance(body, dict):
        raise ValueError("control must be an object")
    hold = body.get("hold") or {}
    explicit = getattr(engine, "_learn_explicit", None) or {}
    commit = body.get("commit")
    if not isinstance(hold, dict):
        raise ValueError("hold must be an object")
    for name, value in hold.items():
        if name not in AB.LIVE:
            raise ValueError("hold only accepts live options")
        AB.validate(name, value)
        if name in explicit and explicit[name] != value:
            raise ValueError(name + " is pinned")
        if name == "guess_ahead" and value and getattr(engine, "draft_model", None) is None:
            raise ValueError("no helper loaded")
        if name in ("shared_prefix", "pipeline_chats") and getattr(engine, "client", None) is None:
            if value not in (False, 1):
                raise ValueError(name + " needs a split worker")
    if commit:
        if not isinstance(commit, dict):
            raise ValueError("commit must be an object")
        AB.validate(commit.get("name"), commit.get("winner"))
        if commit.get("lost") is not None:
            AB.validate(commit["name"], commit["lost"])
        if commit["name"] in explicit and explicit[commit["name"]] != commit["winner"]:
            raise ValueError(commit["name"] + " is pinned")
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
                    raise ValueError("everyday learning is off; load with Auto first")
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
