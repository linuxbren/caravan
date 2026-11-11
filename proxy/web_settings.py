"""Day 15: optimization toggles the web page can set per model load.

Each option is "auto" (Caravan's learned/default behavior) or a pinned value.
Only real agent/mlx_worker.py flags are used; nothing here is invented.
"""
from __future__ import annotations

import os
import re
from pathlib import Path

# id -> label, plain help, allowed values (first is "auto")
OPTIONS = [
    {"id": "self_tune", "label": "Self-tuning",
     "help": "On by default: Caravan learns from your chats immediately and remembers faster settings for each MLX model. Other Auto settings follow its choices; pinned choices stay yours.",
     "values": ["auto", "off"]},
    {"id": "guess_ahead", "label": "Guess-ahead",
     "help": "A smaller model guesses upcoming words for the main MLX model to check. Needs a matching helper; up to ~33% faster writing one reply on a split model in our tests, but slower with two chats.",
     "values": ["auto", "on", "off", "mtp"]},
    {"id": "prompt_lookup", "label": "Prompt lookup (experimental)",
     "help": "Reuse words from your prompt to help the MLX model write repeated text. Up to ~44% faster in our tests on repeated text, but slower on mixed chats; one chat at a time.",
     "values": ["auto", "off", "adaptive"]},
    {"id": "shared_start", "label": "Shared start (trim / rebuild)",
     "help": "Reuse the beginning of repeated system prompts so the model has less to read. MLX models only.",
     "values": ["auto", "on", "off"]},
    {"id": "pipeline_chats", "label": "Two chats",
     "help": "Let two chats use different Minis at the same time when an MLX model is split. Up to ~70% more combined output in our tests without a helper; no gain on one Mini, and slower with a helper.",
     "values": ["auto", "1", "2"]},
    {"id": "fuse_kernels", "label": "Fused kernels",
     "help": "Combine small GPU steps when running an MLX model. Experimental — no meaningful speed gain in our tests; some models are incompatible.",
     "values": ["auto", "on"]},
    {"id": "kv_bits", "label": "Memory compression",
     "help": "Store MLX chat memory more compactly to save RAM; 16 leaves it uncompressed. May lower quality and slow reading; not supported by every model or Native MTP.",
     "values": ["auto", "16", "8", "4"]},
    {"id": "keepalive", "label": "GPU keep-warm",
     "help": "Keep the main GPU warm while it waits for another Mini. Split MLX models only; up to ~50% faster writing replies in our tests.",
     "values": ["auto", "off"]},
]
_BY_ID = {o["id"]: o for o in OPTIONS}


def normalize(settings) -> dict:
    """Fill defaults, validate. Raises ValueError on unknown keys/values."""
    settings = settings or {}
    if not isinstance(settings, dict):
        raise ValueError("settings must be an object")
    out = {}
    for k, v in settings.items():
        if k not in _BY_ID:
            raise ValueError(f"unknown setting: {k}")
        v = str(v).strip().lower()
        if v not in _BY_ID[k]["values"]:
            raise ValueError(f"{k}: want one of {_BY_ID[k]['values']}, got {v!r}")
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
            raise ValueError("native MTP needs uncompressed 16-bit fresh caches")
        if s["prompt_lookup"] == "adaptive":
            raise ValueError("native MTP and prompt lookup are separate experimental modes")
        lead += ["--native-mtp", "--no-learn"]
    if s["prompt_lookup"] == "adaptive":
        if s["pipeline_chats"] == "2":
            raise ValueError("adaptive prompt lookup currently needs one chat, not two")
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
                raise ValueError(f"line {n}: bad table header")
            parts = re.findall(r'"([^"]*)"|([A-Za-z0-9_\-]+)', m.group(1))
            cur = out
            for q, b in parts:
                cur = cur.setdefault(q or b, {})
            continue
        m = re.match(r'^("?)([A-Za-z0-9_\-.]+)\1\s*=\s*(.+?)\s*$', line)
        if not m:
            raise ValueError(f"line {n}: expected key = value")
        k, v = m.group(2), m.group(3)
        if v.startswith('"'):
            e = v.find('"', 1)
            if e < 0:
                raise ValueError(f"line {n}: unterminated string")
            val = v[1:e]
        else:
            v = v.split("#", 1)[0].strip()
            if v in ("true", "false"):
                val = v == "true"
            else:
                try:
                    val = int(v)
                except ValueError:
                    raise ValueError(f"line {n}: unsupported value {v!r}")
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
                    res["errors"].append(f"{where}.thinking: want one of {list(THINK_VALUES)}")
            elif k in _BY_ID:
                if sv in _BY_ID[k]["values"]:
                    out[k] = sv
                else:
                    res["errors"].append(f"{where}.{k}: want one of {_BY_ID[k]['values']}, got {sv!r}")
            else:
                res["errors"].append(f"{where}: unknown key {k!r}")
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
