"""Day 27: measure Guess-ahead and Prompt lookup with real prompts.

`caravan bench "qwen2.5 coder 7b" --speedups --yes` loads each side
(GGUF, then MLX) once per mode and runs the same prompts each time:

  Off            Prompt lookup and Guess-ahead both off (the baseline)
  Prompt lookup  reuse words from the prompt (GGUF "On", MLX "Adaptive")
  Guess-ahead    a smaller helper model guesses (only when one is on disk)
  Auto           what Caravan picks on its own

Prompt sets: the five short prompts (ordinary chats), five code-edit
prompts (the reply repeats much of the prompt, the favorable case) and
the long-prompt series (about 1k, 4k and 8k tokens). Each row is the
median of its prompts. "Guesses kept" is how many guessed words the
main model agreed with. A mode counts as faster or slower only when
writing speed moves by at least 3% against Off (the same margin as
Auto-tune). Nothing here invents a number; rows that could not run say
why. The model that was loaded before is put back at the end, with the
settings it had.
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "proxy"))
sys.path.insert(0, str(ROOT / "agent"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import caravan_prompts as P  # noqa: E402
import guess_stats as GS  # noqa: E402
import gguf_tune as GT  # noqa: E402
from caravan_i18n import T  # noqa: E402  (Day 32: user-facing text)

MARGIN = 0.03
STORE = Path("~/.caravan/bench_speedups.json").expanduser()

# (label, settings). Non-Auto rows pin Self-tuning off so a learned
# change cannot reload the model in the middle of a measurement.
MODES = {
    "gguf": (
        (T("cli.speedups.off"), {"prompt_lookup": "off", "guess_ahead": "off", "self_tune": "off"}),
        (T("cli.speedups.prompt_lookup"), {"prompt_lookup": "on", "guess_ahead": "off", "self_tune": "off"}),
        (T("cli.speedups.guess_ahead"), {"prompt_lookup": "off", "guess_ahead": "on", "self_tune": "off"}),
        (T("cli.speedups.auto"), {}),
    ),
    "mlx": (
        (T("cli.speedups.off"), {"prompt_lookup": "off", "guess_ahead": "off", "self_tune": "off"}),
        (T("cli.speedups.prompt_lookup"), {"prompt_lookup": "adaptive", "guess_ahead": "off", "self_tune": "off"}),
        (T("cli.speedups.guess_ahead"), {"prompt_lookup": "off", "guess_ahead": "on", "self_tune": "off"}),
        (T("cli.speedups.auto"), {}),
    ),
}


def prompt_sets(run_short=True, run_edits=True, run_long=True, window=None):
    """[(label, prompts or None, skip_reason)] in run order."""
    out = []
    if run_short:
        out.append((T("cli.speedups.short_5"), P.short_prompts(tag_prefix="Speedups short"), None))
    if run_edits:
        out.append((T("cli.speedups.code_edits_5"), P.edit_prompts(tag_prefix="Speedups edit"), None))
    if run_long:
        for size in P.BENCH_LONG_SIZES:
            label = T("cli.speedups.long_size_label_2", size_label=P.size_label(size))
            if not P.fits_window(size, window):
                out.append((label, None, P.skip_reason(size, window)))
            else:
                out.append((label, P.long_prompts_for_size(size), None))
    return out


def reply_readout(data):
    """Guess readout from one /api/chat reply (new or older Caravan)."""
    data = data if isinstance(data, dict) else {}
    stats = ((data.get("caravan_web") or {}).get("stats") or {})
    if isinstance(stats.get("guess_kept"), dict):
        return stats["guess_kept"]
    r = GS.from_llama_timings(data.get("timings"))
    if r:
        return r
    usage = data.get("usage") or {}
    spec = ((usage.get("caravan") or {}).get("speculate")
            or (data.get("caravan") or {}).get("speculate"))
    return GS.from_speculate(spec, usage.get("completion_tokens"))


def reply_specs(data):
    data = data if isinstance(data, dict) else {}
    specs = GT.specs_from_response(data)
    stats = ((data.get("caravan_web") or {}).get("stats") or {})
    for k in ("write_tok_s", "read_tok_s", "ttft_s", "prompt_tokens",
              "completion_tokens", "total_s"):
        if k not in specs and stats.get(k) is not None:
            try:
                specs[k] = float(stats[k])
            except (TypeError, ValueError):
                pass
    return specs


def median_specs(samples):
    out = {}
    for key in ("write_tok_s", "read_tok_s", "ttft_s", "prompt_tokens",
                "completion_tokens", "total_s"):
        vals = [float(s[key]) for s in samples if isinstance(s, dict)
                and isinstance(s.get(key), (int, float))]
        med = GT._median(vals) if vals else None
        if med is not None:
            out[key] = med
    return out


def run_set(port, urlopen, prompts, *, max_tokens=P.REPLY_TOKENS, timeout=600,
            on_prompt=None):
    samples, readouts = [], []
    for i, p in enumerate(prompts, 1):
        if on_prompt:
            on_prompt(i, len(prompts))
        body = json.dumps({
            "messages": [{"role": "user", "content": p}],
            "max_tokens": int(max_tokens), "temperature": 0, "stream": False,
        }).encode()
        data = urlopen(f"http://127.0.0.1:{int(port)}/api/chat", data=body,
                       timeout=timeout)
        samples.append(reply_specs(data))
        readouts.append(reply_readout(data))
    return {"specs": median_specs(samples), "guess": GS.combine(readouts),
            "n": len(prompts)}


def _active_note(active):
    """What a loaded model reports it is running with, in plain words."""
    a = active if isinstance(active, dict) else {}
    if not a:
        return ""
    pl = a.get("prompt_lookup")
    pl_on = bool(pl.get("enabled")) if isinstance(pl, dict) else bool(pl)
    ga = bool(a.get("guess_ahead"))
    on, off = T("cli.speedups.state_on"), T("cli.speedups.state_off")
    bits = [T("cli.speedups.prompt_lookup_v", v=on if pl_on else off),
            T("cli.speedups.guess_ahead_v", v=on if ga else off)]
    return T.join(bits)


def load_with(port, model_id, settings, urlopen, status_fn, *, wait=420,
              sleep=time.sleep, now=time.time):
    """Load model_id with these settings and wait for a fresh ready worker."""
    before = (status_fn(port, urlopen=urlopen) or {}).get("worker") or {}
    old_pid = before.get("lead_pid")
    same = before.get("model_id") == model_id and before.get("status") == "ready"
    body = {"id": model_id}
    if settings:
        body["settings"] = dict(settings)
    urlopen(f"http://127.0.0.1:{int(port)}/api/models/load",
            data=json.dumps(body).encode(), timeout=30)
    deadline = now() + wait
    last = {}
    while now() < deadline:
        last = status_fn(port, urlopen=urlopen) or {}
        w = last.get("worker") or {}
        if w.get("status") in ("error", "stopped") and w.get("error"):
            raise RuntimeError(w.get("error") or T("cli.bench.load_failed"))
        fresh = (not same) or (w.get("lead_pid") and w.get("lead_pid") != old_pid)
        if (w.get("status") == "ready" and w.get("model_id") == model_id
                and fresh and last.get("lead_healthy", True)):
            return last
        sleep(1)
    raise TimeoutError(T("cli.bench.the_model_did_not_become_ready"))


def run_side(kind, model_id, *, port, urlopen, status_fn, window_fn,
             sets_args, progress=None, name=None):
    """All modes for one side. Returns {"rows": [...], "notes": [...]}."""
    rows, notes = [], []
    for mode, settings in MODES[kind]:
        if progress:
            progress.set(T("cli.speedups.v_mode_loading", v=name or kind.upper(), mode=mode))
        try:
            st = load_with(port, model_id, settings, urlopen, status_fn)
        except KeyboardInterrupt:
            raise
        except Exception as e:
            rows.append({"mode": mode, "skipped": True,
                         "reason": T("cli.speedups.could_not_load_e", e=e)})
            continue
        active = st.get("active") or {}
        note = _active_note(active)
        if mode == T("cli.speedups.guess_ahead") and isinstance(active, dict) and active and not active.get("guess_ahead"):
            rows.append({"mode": mode, "skipped": True, "active": note,
                         "reason": T("cli.speedups.no_helper_model_on_this_mac")})
            continue
        window = window_fn(port, urlopen, st)
        for label, prompts, skip in prompt_sets(window=window, **sets_args):
            if prompts is None:
                rows.append({"mode": mode, "set": label, "skipped": True,
                             "reason": skip})
                continue

            def hook(i, n, _l=label):
                if progress:
                    progress.set(f"{name or kind.upper()} · {mode} · {_l} {i}/{n}")
            try:
                res = run_set(port, urlopen, prompts, on_prompt=hook)
            except KeyboardInterrupt:
                raise
            except Exception as e:
                rows.append({"mode": mode, "set": label, "skipped": True,
                             "reason": T("cli.speedups.the_measurement_failed_e", e=e)})
                continue
            rows.append(dict(res, mode=mode, set=label, active=note))
    return {"rows": rows, "notes": notes}


def verdicts(rows):
    """{mode: {set: "faster"|"slower"|"same"}} against Off, 3% margin."""
    base = {r["set"]: r for r in rows if r.get("mode") == T("cli.speedups.off")
            and not r.get("skipped") and r.get("set")}
    out = {}
    for r in rows:
        if r.get("mode") == T("cli.speedups.off") or r.get("skipped") or not r.get("set"):
            continue
        b = base.get(r["set"])
        a_w = (r.get("specs") or {}).get("write_tok_s")
        b_w = ((b or {}).get("specs") or {}).get("write_tok_s")
        if not a_w or not b_w:
            continue
        rel = (float(a_w) - float(b_w)) / float(b_w)
        word = "faster" if rel >= MARGIN else ("slower" if rel <= -MARGIN else "same")
        item = {"verdict": word, "change_pct": round(rel * 100, 1)}
        a_t = (r.get("specs") or {}).get("ttft_s")
        b_t = ((b or {}).get("specs") or {}).get("ttft_s")
        if a_t and b_t:
            item["ttft_change_pct"] = round((float(a_t) - float(b_t)) / float(b_t) * 100, 1)
        out.setdefault(r["mode"], {})[r["set"]] = item
    return out


def _fmt(x, d=1):
    return "—" if x is None else f"{float(x):.{d}f}"


def format_table(name, rows) -> list:
    v = verdicts(rows)
    lines = [f"{name}", T("cli.speedups.mode_prompts_write_tok_s_vs")]
    for r in rows:
        mode = r.get("mode", "")
        if r.get("skipped"):
            lines.append(T("cli.speedups.mode_set_skipped_reason", mode=mode, set=r.get('set', ''), reason=r.get('reason')))
            continue
        s = r.get("specs") or {}
        g = r.get("guess") or {}
        ch = (v.get(mode) or {}).get(r.get("set")) or {}
        vs = "" if mode == T("cli.speedups.off") else (f"{ch['change_pct']:+.0f}%" if ch else "—")
        kept = ""
        if g.get("kept_pct") is not None:
            kept = T("cli.speedups.kept_pct_kept_of_guessed", kept_pct=g['kept_pct'], kept=g['kept'], guessed=g['guessed'])
        elif g.get("reply_pct") is not None:
            kept = T("cli.speedups.reply_pct_of_words_guessed", reply_pct=g['reply_pct'])
        elif mode != T("cli.speedups.off"):
            kept = T("cli.speedups.no_guesses")
        ttft = s.get("ttft_s")
        lines.append(
            f"  {mode:<14} {r.get('set', ''):<16} {_fmt(s.get('write_tok_s')):>11}  {vs:>6}   "
            f"{(_fmt(ttft, 2) + 's') if ttft is not None else '—':>11}  {kept}"
        )
    autos = sorted({r.get("active") for r in rows if r.get("mode") == T("cli.speedups.auto") and r.get("active")})
    if autos:
        lines.append(T("cli.speedups.auto_ran_with_autos", autos=T.join(autos, "clause")))
    return lines


def summary_lines(name, rows) -> list:
    out = []
    for mode, sets in verdicts(rows).items():
        faster = [f"{k} {d['change_pct']:+.0f}%" for k, d in sets.items() if d["verdict"] == "faster"]
        slower = [f"{k} {d['change_pct']:+.0f}%" for k, d in sets.items() if d["verdict"] == "slower"]
        if faster and not slower:
            out.append(T("cli.speedups.name_mode_faster_on_faster_no", name=name, mode=mode, faster=T.join(faster)))
        elif faster:
            out.append(T("cli.speedups.name_mode_faster_on_faster_slower", name=name, mode=mode, faster=T.join(faster), slower=T.join(slower)))
        elif slower:
            out.append(T("cli.speedups.name_mode_slower_on_slower_keep", name=name, mode=mode, slower=T.join(slower)))
        else:
            out.append(T("cli.speedups.name_mode_about_the_same_as", name=name, mode=mode))
        later = [f"{k} {d['ttft_change_pct']:+.0f}%" for k, d in sets.items()
                 if (d.get("ttft_change_pct") or 0) >= MARGIN * 100]
        if later:
            out.append(T("cli.speedups.first_token_came_later_on_later", later=T.join(later)))
    return out


def save(result, path=None, now=None):
    path = Path(path) if path else STORE
    try:
        data = json.loads(path.read_text())
        if not isinstance(data, dict):
            data = {}
    except (OSError, ValueError):
        data = {}
    runs = data.setdefault("runs", [])
    runs.append(dict(result, at=float(now if now is not None else time.time())))
    data["runs"] = runs[-20:]
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(data, indent=2))
        tmp.replace(path)
    except OSError:
        pass
    return data


def run_speedups(gguf_id, mlx_id, *, port, urlopen, status_fn, window_fn,
                 gguf_name=None, mlx_name=None, sides=("gguf", "mlx"),
                 sets_args=None, progress=None):
    """Both sides, then put the original model back with its settings."""
    sets_args = dict(sets_args or {"run_short": True, "run_edits": True, "run_long": True})
    st = status_fn(port, urlopen=urlopen) or {}
    w = st.get("worker") or {}
    original = None
    if w.get("status") == "ready" and w.get("model_id"):
        page = w.get("page_settings") or w.get("settings") or {}
        pinned = {k: v for k, v in page.items() if v not in (None, "", "auto")}
        original = {"id": w["model_id"], "name": w.get("model_name") or w["model_id"],
                    "settings": pinned}
    result = {"gguf_id": gguf_id, "mlx_id": mlx_id, "sides": {}, "notes": []}
    err = None
    try:
        for kind in sides:
            mid = gguf_id if kind == "gguf" else mlx_id
            if not mid:
                continue
            nm = (gguf_name if kind == "gguf" else mlx_name) or kind.upper()
            result["sides"][kind] = dict(run_side(
                kind, mid, port=port, urlopen=urlopen, status_fn=status_fn,
                window_fn=window_fn, sets_args=sets_args, progress=progress,
                name=nm), name=nm)
    except KeyboardInterrupt:
        err = "stopped"
        result["notes"].append(T("cli.bench.stopped"))
    except Exception as e:
        err = str(e)
    finally:
        if progress:
            progress.set(T("cli.speedups.putting_the_original_model_back"))
        if original:
            result["notes"].append(T("cli.speedups.putting_the_original_model_back_name", name=original['name']))
            try:
                load_with(port, original["id"], original["settings"], urlopen, status_fn)
            except Exception as e:
                result["notes"].append(T("cli.bench.could_not_put_the_original_model", e=e))
    result["error"] = err
    return result


def render(result) -> list:
    lines = []
    for kind in ("gguf", "mlx"):
        side = (result.get("sides") or {}).get(kind)
        if not side:
            continue
        lines += format_table(side.get("name") or kind.upper(), side.get("rows"))
        lines.append("")
    for kind in ("gguf", "mlx"):
        side = (result.get("sides") or {}).get(kind)
        if side:
            lines += summary_lines(side.get("name") or kind.upper(), side.get("rows"))
    if lines and lines[-1] != "":
        lines.append("")
    lines.append(T("cli.speedups.each_row_is_the_median_of", cache_note=P.CACHE_NOTE))
    return lines
