"""Day 15: optimization toggles the web page can set per model load.

Each option is "auto" (Caravan's learned/default behavior) or a pinned value.
Only real agent/mlx_worker.py flags are used; nothing here is invented.
"""
from __future__ import annotations

import os
import re
from pathlib import Path
try:
    from caravan_i18n import T  # noqa: E402  (Day 32: user-facing text, tools/caravan_i18n.py)
except ImportError:  # run without tools/ on the path
    import sys as _sys
    from pathlib import Path as _Path
    _sys.path.append(str(_Path(__file__).resolve().parents[1] / "tools"))
    from caravan_i18n import T  # noqa: E402

# id -> label, plain help, allowed values (first is "auto")
OPTIONS = [
    {"id": "self_tune", "label": T("server.web_settings.self_tuning"),
     "help": T("server.web_settings.caravan_learns_from_your_chats_and"),
     "help_gguf": T("server.web_settings.caravan_learns_from_your_chats_and_2"),
     "values": ["auto", "off"]},
    {"id": "guess_ahead", "label": T("server.web_settings.guess_ahead"),
     "help": T("server.web_settings.a_smaller_model_guesses_upcoming_words"),
     "help_gguf": T("server.web_settings.a_smaller_model_of_the_same"),
     "values": ["auto", "on", "off", "mtp"],
     "values_gguf": ["auto", "off", "on"]},
    {"id": "prompt_lookup", "label": T("server.web_settings.prompt_lookup_experimental"),
     "help": T("server.web_settings.reuse_words_from_your_prompt_to"),
     "help_gguf": T("server.web_settings.reuse_words_from_your_prompt_to_2"),
     "values": ["auto", "off", "adaptive"],
     "values_gguf": ["auto", "off", "on"]},
    {"id": "shared_start", "label": T("server.web_settings.shared_start_trim_rebuild"),
     "help": T("server.web_settings.reuse_the_beginning_of_repeated_system"),
     "help_gguf": T("server.web_settings.reuse_the_start_of_a_chat"),
     "values": ["auto", "on", "off"]},
    {"id": "pipeline_chats", "label": T("server.web_settings.two_chats"),
     "help": T("server.web_settings.let_two_chats_use_different_minis"),
     "help_gguf": T("server.web_settings.let_two_chats_share_the_model"),
     "values": ["auto", "1", "2"]},
    {"id": "chat_window", "label": T("server.web_settings.context"),
     "help": T("server.web_settings.how_much_of_the_conversation_the_2"),
     "values": ["auto", "4096", "8192", "16384", "32768", "65536", "131072", "262144", "native"],
     "backends": ("gguf",)},
    {"id": "fuse_kernels", "label": T("server.web_settings.fused_kernels"),
     "help": T("server.web_settings.combine_small_gpu_steps_when_running"),
     "values": ["auto", "on"],
     "backends": ("mlx",)},
    {"id": "kv_bits", "label": T("server.gguf_self_tune.memory_compression"),
     "help": T("server.web_settings.store_mlx_chat_memory_more_compactly"),
     "help_gguf": T("server.web_settings.store_the_chats_working_memory_more"),
     "values": ["auto", "16", "8", "4"],
     "values_gguf": ["auto", "16", "8"]},
    {"id": "keepalive", "label": T("server.web_settings.gpu_keep_warm"),
     "help": T("server.web_settings.keep_the_main_gpu_warm_while"),
     "values": ["auto", "off"],
     "backends": ("mlx",)},
    {"id": "flash_attn", "label": T("server.gguf_self_tune.flash_attention"),
     "help": T("server.web_settings.a_faster_way_to_read_the"),
     "values": ["auto", "on", "off"],
     "backends": ("gguf",)},
    {"id": "ubatch", "label": T("server.gguf_self_tune.prompt_batch"),
     "help": T("server.web_settings.how_much_of_a_long_question"),
     "values": ["auto", "256", "512", "1024"],
     "backends": ("gguf",)},
]
_BY_ID = {o["id"]: o for o in OPTIONS}


def normalize(settings) -> dict:
    """Fill defaults, validate. Raises ValueError on unknown keys/values."""
    settings = settings or {}
    if not isinstance(settings, dict):
        raise ValueError(T("server.web_settings.settings_must_be_an_object"))
    out = {}
    for k, v in settings.items():
        if k not in _BY_ID:
            raise ValueError(T("server.web_settings.unknown_setting_k", k=k))
        v = str(v).strip().lower()
        allowed = set(_BY_ID[k]["values"]) | set(_BY_ID[k].get("values_gguf") or [])
        if v not in allowed:
            raise ValueError(T("server.web_settings.k_want_one_of_sorted_got", k=k, sorted=sorted(allowed), v=v))
    for o in OPTIONS:
        out[o["id"]] = str(settings.get(o["id"], "auto")).strip().lower()
    return out


def to_args(settings) -> tuple[list, list]:
    """Return (lead_args, packer_args) for mlx_worker.py."""
    s = normalize(settings)
    lead, packer = [], []
    if s["guess_ahead"] == "off":
        lead.append("--no-split-draft")
    elif s["guess_ahead"] == "on":
        lead.append("--pin-guess-ahead")
    if s["guess_ahead"] == "mtp":
        if s["kv_bits"] in ("8", "4"):
            raise ValueError(T("server.web_settings.native_mtp_needs_uncompressed_16_bit"))
        if s["prompt_lookup"] == "adaptive":
            raise ValueError(T("server.web_settings.native_mtp_and_prompt_lookup_are"))
        lead += ["--native-mtp", "--no-learn"]
    if s["prompt_lookup"] == "adaptive":
        if s["pipeline_chats"] == "2":
            raise ValueError(T("server.web_settings.adaptive_prompt_lookup_currently_needs_one"))
        lead += ["--split-prompt-lookup", "3", "--split-prompt-lookup-adaptive", "--no-learn"]
    if s["self_tune"] == "off":
        lead.append("--no-learn")
    if s["shared_start"] == "on":
        lead.append("--split-shared-prefix-cache")
    elif s["shared_start"] == "off":
        lead.append("--no-split-shared-prefix-cache")
    if s["pipeline_chats"] in ("1", "2"):
        lead += ["--split-pipeline-chats", s["pipeline_chats"]]
    if s["prompt_lookup"] == "adaptive":
        lead += ["--split-pipeline-chats", "1"]
    if s["fuse_kernels"] == "on":
        lead += ["--fuse-kernels", "all"]
        packer += ["--fuse-kernels", "all"]
    if s["kv_bits"] in ("8", "4"):   # "16" = uncompressed, the worker default
        lead += ["--kv-bits", s["kv_bits"]]
        packer += ["--kv-bits", s["kv_bits"]]
    if s["keepalive"] == "off":
        lead.append("--no-split-keepalive")
    return lead, packer


def lead_omits_no_learn(settings) -> bool:
    """True when the lead should learn: Self-tuning is on, no experimental mode.

    A split start builds its command from a shared default that includes
    ``--no-learn`` so packers never record. The lead must drop that flag
    when Self-tuning is on, or the worker starts with learning off and
    Settings shows a contradictory "now: off" next to On.
    """
    s = normalize(settings or {})
    return (s.get("self_tune") != "off"
            and s.get("guess_ahead") != "mtp"
            and s.get("prompt_lookup") != "adaptive")


def drop_no_learn_for_lead(args, settings) -> list:
    """Remove a default ``--no-learn`` from lead argv when learning should be on."""
    args = list(args or [])
    if lead_omits_no_learn(settings):
        return [a for a in args if a != "--no-learn"]
    return args


def from_args(cmd: str) -> dict:
    """Best-effort inverse of to_args() for a running lead's command line."""
    a = f" {cmd} "
    out = normalize({})
    if " --native-mtp " in a:
        out["guess_ahead"] = "mtp"
    elif " --no-split-draft " in a:
        out["guess_ahead"] = "off"
    elif " --pin-guess-ahead " in a:
        out["guess_ahead"] = "on"
    if " --split-prompt-lookup-adaptive " in a:
        out["prompt_lookup"] = "adaptive"
    if " --no-learn " in a:
        out["self_tune"] = "off"
    if " --split-shared-prefix-cache " in a:
        out["shared_start"] = "on"
    elif " --no-split-shared-prefix-cache " in a:
        out["shared_start"] = "off"
    for n in ("1", "2"):
        if f" --split-pipeline-chats {n} " in a:
            out["pipeline_chats"] = n
    learned = ""
    if " --learn-reload-auto " in a:
        learned = a.split(" --learn-reload-auto ", 1)[1].split(" ", 1)[0]
    if "fuse_kernels" not in learned and " --fuse-kernels all " in a:
        out["fuse_kernels"] = "on"
    if "kv_bits" not in learned:
        for n in ("8", "4"):
            if f" --kv-bits {n} " in a:
                out["kv_bits"] = n
    if "keepalive" not in learned and " --no-split-keepalive " in a:
        out["keepalive"] = "off"
    return out


# ---- ROADMAP #13c: optional ~/.caravan/config.toml ------------------------
# Global [defaults] plus [models."<web model id or model dir name>"] tables.
# Keys are the option ids above, plus thinking = "on" | "off" | "low" |
# "medium" | "high" (the page's Thinking button default). Precedence:
# a choice made on the web page (anything not Auto) > the file > Auto.
# Python 3.9 has no tomllib, so this reads the small TOML subset we need
# (tables, key = "string" | number | true/false, # comments); tomllib is
# used instead when it exists.
CONFIG_PATH = Path(os.environ.get("CARAVAN_CONFIG_TOML",
                                  str(Path.home() / ".caravan" / "config.toml"))).expanduser()
THINK_VALUES = ("on", "off", "low", "medium", "high")


def _parse_toml_subset(text: str) -> dict:
    out: dict = {}
    cur = out
    for n, raw in enumerate(text.splitlines(), 1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("["):
            m = re.match(r'^\[\s*(.+?)\s*\]\s*(#.*)?$', line)
            if not m:
                raise ValueError(T("server.web_settings.line_n_bad_table_header", n=n))
            parts = re.findall(r'"([^"]*)"|([A-Za-z0-9_\-]+)', m.group(1))
            cur = out
            for q, b in parts:
                cur = cur.setdefault(q or b, {})
            continue
        m = re.match(r'^("?)([A-Za-z0-9_\-.]+)\1\s*=\s*(.+?)\s*$', line)
        if not m:
            raise ValueError(T("server.web_settings.line_n_expected_key_value", n=n))
        k, v = m.group(2), m.group(3)
        if v.startswith('"'):
            e = v.find('"', 1)
            if e < 0:
                raise ValueError(T("server.web_settings.line_n_unterminated_string", n=n))
            val = v[1:e]
        else:
            v = v.split("#", 1)[0].strip()
            if v in ("true", "false"):
                val = v == "true"
            else:
                try:
                    val = int(v)
                except ValueError:
                    raise ValueError(T("server.web_settings.line_n_unsupported_value_v", n=n, v=v))
        cur[k] = val
    return out


def _cfg_value(k, v) -> str:
    if isinstance(v, bool):
        if k == "thinking":
            return "on" if v else "off"
        return "on" if v else "off"
    return str(v).strip().lower()


def load_config(path=None) -> dict:
    """{"defaults": {...}, "models": {id: {...}}, "errors": [...], "path": str}.

    Missing file -> empty. Bad keys/values are dropped and listed in errors
    (never fatal: a typo in the file must not stop a model load).
    """
    p = Path(path) if path else CONFIG_PATH
    res = {"defaults": {}, "models": {}, "errors": [], "path": str(p), "exists": p.is_file()}
    if not res["exists"]:
        return res
    try:
        text = p.read_text()
        try:
            import tomllib  # Python 3.11+
            raw = tomllib.loads(text)
        except ImportError:
            raw = _parse_toml_subset(text)
    except Exception as e:  # noqa: BLE001
        res["errors"].append(f"{p}: {e}")
        return res

    def clean(tbl, where):
        out = {}
        for k, v in (tbl or {}).items():
            if isinstance(v, dict):
                continue
            sv = _cfg_value(k, v)
            if k == "thinking":
                if sv in THINK_VALUES:
                    out[k] = sv
                else:
                    res["errors"].append(T("server.web_settings.where_thinking_want_one_of_list", where=where, list=list(THINK_VALUES)))
            elif k in _BY_ID:
                if sv in _BY_ID[k]["values"]:
                    out[k] = sv
                else:
                    res["errors"].append(T("server.web_settings.where_k_want_one_of_values", where=where, k=k, values=_BY_ID[k]['values'], sv=sv))
            else:
                res["errors"].append(T("server.web_settings.where_unknown_key_k", where=where, k=k))
        return out

    res["defaults"] = clean(raw.get("defaults"), "defaults")
    for mid, tbl in (raw.get("models") or {}).items():
        if isinstance(tbl, dict):
            res["models"][str(mid)] = clean(tbl, f'models."{mid}"')
    return res


def file_settings(model_id=None, model_dir=None, cfg=None) -> dict:
    """Settings the file pins for one model: defaults, then its own table.

    Matches the web model id or the model folder name. Auto values in the
    file are dropped (they pin nothing).
    """
    cfg = cfg if cfg is not None else load_config()
    out = dict(cfg.get("defaults") or {})
    names = [n for n in (model_id, Path(str(model_dir)).name if model_dir else None) if n]
    for n in names:
        out.update((cfg.get("models") or {}).get(n) or {})
    return {k: v for k, v in out.items() if v != "auto"}


def merge_with_file(page: dict, fsets: dict):
    """Page choices (non-Auto) win; the file fills Auto. Returns (settings, from_file)."""
    s = normalize(page)
    used = {}
    for k, v in (fsets or {}).items():
        if k in s and s[k] == "auto":
            s[k] = v
            used[k] = v
    return s, used


def options_for(source="mlx", model_dir=None, config=None, n_minis=1) -> list:
    """Settings rows for this model type, with the matching help and values.

    GGUF hides Fused kernels and GPU keep-warm, and drops 4-bit memory
    compression. Guess-ahead and Prompt lookup are Auto/Off/On, with
    Auto meaning off until a test finds a winner. Guess-ahead On is
    offered only when a smaller same-family GGUF is already on this
    Mac; Caravan will not download one. Two chats and Chat window are
    offered. On MLX, Memory
    compression 4 is still listed but marked disabled when this model's
    chat memory is too compact for 4 to work well.
    """
    src = "gguf" if (source or "").lower() == "gguf" else "mlx"
    disabled = {}
    if src == "mlx":
        try:
            import kv_quality as K
            disabled = K.disabled_values_for(config, model_dir=model_dir, source=src)
        except Exception:
            disabled = {}
    ctx_disabled = {}
    ctx_auto = None
    if src == "gguf" and model_dir:
        try:
            import gguf_split as G
            ctx_disabled = G.disabled_ctx_values(
                model_dir, n_slots=1, n_devices=max(1, int(n_minis or 1)))
            ctx_auto = G.auto_ctx(
                model_dir, n_slots=1, n_devices=max(1, int(n_minis or 1)))
        except Exception:
            ctx_disabled, ctx_auto = {}, None
    out = []
    for o in OPTIONS:
        backends = o.get("backends") or ("mlx", "gguf")
        if src not in backends:
            continue
        item = {k: v for k, v in o.items()
                if k not in ("backends", "help_gguf", "values_gguf", "locked_for_gguf")}
        if src == "gguf" and o.get("help_gguf"):
            item["help"] = o["help_gguf"]
        if src == "gguf" and o.get("values_gguf"):
            item["values"] = list(o["values_gguf"])
        if src == "gguf" and o.get("locked_for_gguf"):
            item["locked"] = True
            item["forced"] = o["locked_for_gguf"]
        if o.get("id") == "kv_bits" and disabled:
            item["disabled_values"] = dict(disabled)
        if o.get("id") == "chat_window":
            if ctx_disabled:
                item["disabled_values"] = dict(ctx_disabled)
            if ctx_auto:
                item["auto_value"] = int(ctx_auto)
                trained = None
                try:
                    trained = G.native_ctx(model_dir)
                except Exception:  # noqa: BLE001
                    trained = None
                if trained and int(ctx_auto) >= int(trained):
                    tail = T("server.web_settings.auto_is_ctx_auto_for_this", ctx_auto=ctx_auto)
                elif trained:
                    tail = (T("server.web_settings.auto_is_ctx_auto_for_this_2", ctx_auto=ctx_auto, trained=trained))
                else:
                    tail = T("server.web_settings.auto_is_ctx_auto_for_this_3", ctx_auto=ctx_auto)
                item["help"] = (
                    T("server.web_settings.how_much_of_the_conversation_the", tail=tail)
                )
                if trained:
                    item["native_value"] = int(trained)
        if src == "gguf" and o.get("id") == "guess_ahead":
            draft = None
            if model_dir:
                try:
                    import gguf_split as G
                    draft = G.find_gguf_draft(model_dir)
                except Exception:
                    draft = None
            if not draft:
                item["disabled_values"] = {
                    "on": T("server.web_settings.needs_a_smaller_model_of_the"),
                }
            else:
                item["draft"] = {"name": draft.get("name"), "path": draft.get("path"),
                                 "size_gb": draft.get("size_gb")}
        out.append(item)
    return out


def apply_gguf_settings(tune: dict, settings, *, model_path=None) -> dict:
    """Merge page Settings (pins) onto a learned GGUF tune. Pins win.

    Auto leaves the learned/default value. Prompt lookup On or Off is
    applied as a pin; Auto leaves a learned result (or off). Guess-ahead
    On is applied only together with a draft_path already on disk;
    this never downloads a helper. Chat window and Two chats pins
    become ctx and n_slots; Auto leaves them unset so the loader picks
    a sane window and one slot. Auto-tune and Self-tuning do not flip
    Chat window or Two chats.
    """
    out = dict(tune or {})
    try:
        s = normalize(settings)
    except (ValueError, TypeError):
        return out
    fa = s.get("flash_attn")
    if fa in ("on", "off"):
        out["flash_attn"] = fa
    ub = s.get("ubatch")
    if ub in ("256", "512", "1024"):
        out["ubatch"] = int(ub)
    kv = s.get("kv_bits")
    if kv == "16":
        out["cache_type"] = "f16"
    elif kv == "8":
        out["cache_type"] = "q8_0"
    elif kv == "4":
        raise ValueError(T("server.gguf_split.gguf_memory_compression_does_not_offer"))
    ss = s.get("shared_start")
    if ss == "off":
        out["slot_save"] = False
    elif ss == "on":
        out["slot_save"] = True
    cw = s.get("chat_window")
    if cw in ("4096", "8192", "16384", "32768", "65536", "131072", "262144"):
        out["ctx"] = int(cw)
        out.pop("ctx_auto", None)
    elif cw == "native":
        # Day 30: the model's own trained window; Auto when the file does not say.
        trained = None
        if model_path:
            try:
                import gguf_split as G
                trained = G.native_ctx(model_path)
            except Exception:  # noqa: BLE001
                trained = None
        if trained:
            out["ctx"] = int(trained)
            out.pop("ctx_auto", None)
        else:
            out.pop("ctx", None)
    elif cw == "auto":
        out.pop("ctx", None)
    pc = s.get("pipeline_chats")
    if pc in ("1", "2"):
        out["n_slots"] = int(pc)
    elif pc == "auto":
        out.pop("n_slots", None)
    pl = s.get("prompt_lookup")
    if pl == "on":
        out["prompt_lookup"] = "on"
    elif pl == "off":
        out["prompt_lookup"] = "off"
    # Auto leaves a learned value already in out, or stays off.
    ga = s.get("guess_ahead")
    if ga == "off":
        out["guess_ahead"] = "off"
        out.pop("draft_path", None)
    elif ga == "on":
        draft = None
        raw = out.get("draft_path") or (out.get("draft") or {}).get("path")
        try:
            import gguf_split as G
            draft = G._existing_draft_path(raw)
            if not draft and model_path:
                found = G.find_gguf_draft(model_path)
                draft = (found or {}).get("path") if found else None
        except Exception:
            draft = None
        if draft:
            out["guess_ahead"] = "on"
            out["draft_path"] = draft
        else:
            # On without a helper on disk is treated as off, never a download.
            out["guess_ahead"] = "off"
            out.pop("draft_path", None)
    return out


def gguf_active_settings(tune=None, settings=None, *, launch=None, model_path=None) -> dict:
    """Chip-facing 'active' dict for a loaded GGUF model (no /caravan/settings).

    Day 33 (v0.9.15): "guesser" says which helper is in use and why
    (Caravan's paired helper, or another same-family file on this Mac).
    """
    tune = dict(tune or {})
    try:
        s = normalize(settings or {})
    except (ValueError, TypeError):
        s = {}
    launch = dict(launch or {})
    ctx = launch.get("ctx") or tune.get("ctx")
    n_slots = launch.get("n_slots") or tune.get("n_slots") or 1
    ct = tune.get("cache_type") or launch.get("cache_type")
    if ct == "f16":
        kv = 16
    elif ct == "q8_0":
        kv = 8
    else:
        kv = None
    on = tune.get("guess_ahead") == "on" and bool(tune.get("draft_path"))
    guesser = None
    try:
        try:
            import guesser_choice as GC
        except ImportError:
            import sys as _sys
            _sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "agent"))
            import guesser_choice as GC
        if on:
            guesser = GC.gguf_source(tune.get("draft_path"),
                                     main_name=Path(str(model_path)).name if model_path else "")
        elif s.get("guess_ahead") == "off":
            guesser = GC.choice(GC.NONE, "off", "off")
    except Exception:  # noqa: BLE001  (a label never breaks the chips)
        guesser = None
    return {
        "backend": "llama",
        "guesser": guesser,
        "self_tune": s.get("self_tune") != "off",
        "guess_ahead": tune.get("guess_ahead") == "on" and bool(tune.get("draft_path")),
        "guess_ahead_loaded": tune.get("guess_ahead") == "on" and bool(tune.get("draft_path")),
        "prompt_lookup": {"enabled": tune.get("prompt_lookup") == "on"},
        "shared_start": tune.get("slot_save", True) is not False,
        "pipeline_chats": int(n_slots),
        "two_chats_available": True,
        "kv_bits": kv,
        "flash_attn": tune.get("flash_attn") or "on",
        "ubatch": tune.get("ubatch") or 512,
        "chat_window": int(ctx) if ctx else None,
        "pinned": [k for k, v in s.items() if v not in (None, "", "auto")],
    }

