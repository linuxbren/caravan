"""Compare a GGUF model to its MLX counterpart.

Prints a compact chart of reading speed, writing speed, and time to
the first token, with a short bar for GGUF and one for MLX at each
prompt size. Bar length follows the printed number, so a shorter
First token bar is sooner (the label is "lower is better"). Full model names are at the top; the bars are labeled
GGUF and MLX. Sizes that were not run are left out. On a terminal
the bars use block characters (█ ▌); with `--ascii`, when output
is not UTF-8, or with NO_COLOR, the bars are plain '#'. Subtle
amber (GGUF) and green (MLX) color is used only on a terminal
without NO_COLOR. `--details` (also `--text`) adds the same wording
as the stats under each reply, and a note about the unique openings.
`--from-averages` draws the same kind of chart without loading a model:
from the last bench run for this pair ("Last bench") when there is
one, otherwise from saved chat averages ("Saved"). A side with no
numbers gets a plain line instead of empty bars.

Does not invent numbers. Pass a plain name (for example
`caravan bench "qwen2.5 coder 7b"`) or both `--gguf` and `--mlx` ids
(`caravan models` lists them). By default it runs five short prompts
and a long-prompt series at about 1k, 4k, and 8k tokens (two prompts
at each size; sizes that will not fit the chat window are skipped).
`--short` or `--long` runs just one of those. Without `--yes` it
shows which two models it would compare and the exact command.
After a live comparison, the model that was loaded before is put
back, even if a measurement failed. On a terminal, a small campfire
animation shows the current step and elapsed time; when output is
piped, or with NO_COLOR or --quiet, that is a plain step line or is
silent. Ctrl-C stops the animation and still puts the original
model back.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "proxy"))
sys.path.insert(0, str(ROOT / "agent"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import web_speed as S  # noqa: E402
import gguf_tune as T  # noqa: E402
import caravan_prompts as P  # noqa: E402
from caravan_progress import (  # noqa: E402
    Progress,
    loading_step,
    long_step,
    restore_step,
    short_step,
)
from caravan_models import (  # noqa: E402
    DEFAULT_PORT,
    fetch_catalog,
    format_line,
    friendly_name,
    kind_of,
    model_id,
    resolve_pair,
)
from caravan_chart import decide_style, render_chart  # noqa: E402


SPEED_STORE = Path("~/.caravan/speed_averages.json").expanduser()
# Last live bench result per GGUF + MLX pair, next to the chat averages.
LAST_BENCH_STORE = Path("~/.caravan/bench_last.json").expanduser()


def _pair_key(gguf_id, mlx_id) -> str:
    return f"{str(gguf_id or '').strip()}|{str(mlx_id or '').strip()}"


def _clean_rows(rows) -> list:
    out = []
    for r in rows or []:
        if isinstance(r, dict) and not r.get("skipped") and r.get("specs"):
            item = {"label": r.get("label") or "", "specs": dict(r["specs"])}
            if r.get("size") is not None:
                item["size"] = r["size"]
            out.append(item)
    return out


def load_last_bench(gguf_id, mlx_id, path=None) -> dict:
    path = Path(path) if path else LAST_BENCH_STORE
    try:
        data = json.loads(path.read_text())
    except (OSError, ValueError):
        return {}
    entry = (data.get("pairs") or {}).get(_pair_key(gguf_id, mlx_id)) if isinstance(data, dict) else None
    return entry if isinstance(entry, dict) else {}


def save_last_bench(gguf_id, mlx_id, gguf_rows, mlx_rows, path=None, now=None) -> dict:
    """Keep the newest numbers for each side; an empty side keeps its last numbers."""
    path = Path(path) if path else LAST_BENCH_STORE
    try:
        data = json.loads(path.read_text())
        if not isinstance(data, dict):
            data = {}
    except (OSError, ValueError):
        data = {}
    pairs = data.setdefault("pairs", {})
    key = _pair_key(gguf_id, mlx_id)
    entry = dict(pairs.get(key) or {})
    g, m = _clean_rows(gguf_rows), _clean_rows(mlx_rows)
    if not g and not m:
        return entry
    when = float(now if now is not None else time.time())
    if g:
        entry["gguf_rows"], entry["gguf_at"] = g, when
    if m:
        entry["mlx_rows"], entry["mlx_at"] = m, when
    pairs[key] = entry
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(data, indent=2))
        tmp.replace(path)
    except OSError:
        pass
    return entry


def _plain_day(ts) -> str:
    try:
        t = time.localtime(float(ts))
    except (TypeError, ValueError):
        return ""
    return time.strftime("%B ", t) + str(t.tm_mday)


def no_numbers_line(kind: str) -> str:
    return f"No saved numbers for the {kind} model yet - chat with it a bit, or run the bench."


def format_side(name: str, specs) -> str:
    """One labeled line in reply-stats wording, or a 'no numbers' note."""
    specs = S.specs_from(specs) if specs else {}
    line = S.format_reply_stats(
        specs.get("write_tok_s"),
        specs.get("ttft_s"),
        prompt_tokens=specs.get("prompt_tokens"),
        read_tok_s=specs.get("read_tok_s"),
        completion_tokens=specs.get("completion_tokens"),
        total_s=specs.get("total_s"),
    )
    if line:
        return f"{name}: {line}"
    return f"{name}: no speed numbers recorded yet."


def _median_specs(samples: list) -> dict:
    out = {}
    for key in ("write_tok_s", "read_tok_s", "ttft_s", "prompt_tokens",
                "completion_tokens", "total_s"):
        vals = [float(s[key]) for s in samples if isinstance(s, dict) and key in s
                and isinstance(s[key], (int, float))]
        if vals:
            med = T._median(vals)
            if med is not None:
                out[key] = med
    return out


def _urlopen(url, data=None, timeout=30, headers=None):
    req = urllib.request.Request(
        url, data=data, headers=headers or {},
        method="POST" if data is not None else "GET",
    )
    if data is not None and "Content-Type" not in (headers or {}):
        req.add_header("Content-Type", "application/json")
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode())


def status(port: int, urlopen=_urlopen) -> dict:
    return urlopen(f"http://127.0.0.1:{int(port)}/api/status", timeout=5)


def load_model(port: int, model_id: str, urlopen=_urlopen, wait=300) -> dict:
    urlopen(
        f"http://127.0.0.1:{int(port)}/api/models/load",
        data=json.dumps({"id": model_id}).encode(),
        timeout=30,
    )
    deadline = time.time() + wait
    last = {}
    while time.time() < deadline:
        last = status(port, urlopen=urlopen)
        worker = (last or {}).get("worker") or last
        if worker.get("status") == "ready" and worker.get("model_id") == model_id:
            return last
        if worker.get("status") in ("error", "stopped") and worker.get("error"):
            raise RuntimeError(worker.get("error") or "load failed")
        time.sleep(1)
    raise TimeoutError("The model did not become ready in time.")


def measure_chat(port: int, prompts=None, max_tokens=192, urlopen=_urlopen,
                 timeout=300, on_prompt=None) -> dict:
    prompts = prompts or T.BENCH_PROMPTS
    samples = []
    n = len(prompts)
    for i, p in enumerate(prompts, 1):
        if on_prompt:
            on_prompt(i, n)
        body = json.dumps({
            "messages": [{"role": "user", "content": p}],
            "max_tokens": int(max_tokens),
            "temperature": 0,
            "stream": False,
        }).encode()
        data = urlopen(
            f"http://127.0.0.1:{int(port)}/api/chat",
            data=body, timeout=timeout,
        )
        web = (data or {}).get("caravan_web") or {}
        stats = web.get("stats") or {}
        specs = T.specs_from_response(data) if isinstance(data, dict) else {}
        # Prefer the same caravan_web stats the page uses under each reply.
        for k, src in (("write_tok_s", "write_tok_s"), ("read_tok_s", "read_tok_s"),
                       ("ttft_s", "ttft_s"), ("prompt_tokens", "prompt_tokens"),
                       ("completion_tokens", "completion_tokens"), ("total_s", "total_s")):
            if k not in specs and src in stats:
                try:
                    specs[k] = float(stats[src])
                except (TypeError, ValueError):
                    pass
        samples.append(specs)
    return _median_specs(samples)


def averages_for(model_id: str, store=None) -> dict:
    """Best-effort saved chat average for this model, across setups."""
    mid = str(model_id or "").strip()
    if not mid:
        return {}
    data = S._load(store)
    slots = ((data.get("models") or {}).get(mid) or {})
    if not isinstance(slots, dict) or not slots:
        return {}
    # Prefer the setup with the most samples.
    best, best_n = {}, -1
    for slot in slots.values():
        if not isinstance(slot, dict):
            continue
        view = S._snapshot(slot)
        n = int(slot.get("n") or slot.get("write_n") or 0)
        if S._has_specs(S.specs_from(view)) and n >= best_n:
            best, best_n = S.specs_from(view), n
    return best


def _side_label(model, fallback_kind=None) -> str:
    if not model:
        return ""
    name = friendly_name(model)
    kind = kind_of(model) if (model.get("source") or model.get("backend") or model.get("id")) else fallback_kind
    kind = kind or fallback_kind or kind_of(model)
    return f"{name} ({kind})"


def _running_window(port, urlopen, st=None):
    if st is None:
        try:
            st = status(port, urlopen=urlopen)
        except Exception:
            st = None
    w = P.chat_window_from(st)
    if w:
        return w
    try:
        s = urlopen(f"http://127.0.0.1:{int(port)}/api/settings", timeout=5)
        w = P.chat_window_from(s)
    except Exception:
        pass
    return w


def measure_series(port, urlopen, *, run_short=True, run_long=True,
                   prompts=None, window=None, timeout=600,
                   progress=None, side="GGUF") -> list:
    """Run the short and/or long series. Returns a list of result rows."""
    rows = []

    def hook_short(i, n):
        if progress:
            progress.set(short_step(side, i, n))

    def hook_long(size):
        def hook(i, n):
            if progress:
                progress.set(long_step(side, size, i, n))
        return hook

    if prompts is not None:
        specs = measure_chat(
            port, prompts=prompts, urlopen=urlopen, on_prompt=hook_short,
        )
        rows.append({
            "label": f"Short prompts ({len(prompts)})",
            "specs": specs, "n": len(prompts),
        })
        return rows
    if run_short:
        shorts = P.short_prompts(tag_prefix="Bench short")
        specs = measure_chat(
            port, prompts=shorts, urlopen=urlopen, on_prompt=hook_short,
        )
        rows.append({
            "label": f"Short prompts ({len(shorts)})",
            "specs": specs, "n": len(shorts),
        })
    if run_long:
        window = window if window is not None else _running_window(port, urlopen)
        for size in P.BENCH_LONG_SIZES:
            label = f"Long prompts (~{P.size_label(size)} tok) (2)"
            if not P.fits_window(size, window):
                rows.append({
                    "label": label, "skipped": True,
                    "reason": P.skip_reason(size, window), "size": size,
                })
                continue
            long_ps = P.long_prompts_for_size(size)
            try:
                specs = measure_chat(
                    port, prompts=long_ps, urlopen=urlopen, timeout=timeout,
                    on_prompt=hook_long(size),
                )
            except KeyboardInterrupt:
                raise
            except Exception as e:
                rows.append({
                    "label": label, "skipped": True,
                    "reason": f"the prompt did not fit or the measurement failed ({e})",
                    "size": size,
                })
                continue
            rows.append({
                "label": label, "specs": specs, "n": 2, "size": size,
            })
    return rows


def format_series(name, rows) -> list:
    lines = [f"{name}:"]
    for r in rows or []:
        if r.get("skipped"):
            lines.append(f"  {r['label']}: skipped — {r['reason']}")
            continue
        specs = r.get("specs") or {}
        line = S.format_reply_stats(
            specs.get("write_tok_s"),
            specs.get("ttft_s"),
            prompt_tokens=specs.get("prompt_tokens"),
            read_tok_s=specs.get("read_tok_s"),
            completion_tokens=specs.get("completion_tokens"),
            total_s=specs.get("total_s"),
        )
        if line:
            lines.append(f"  {r['label']}: {line}")
        else:
            lines.append(f"  {r['label']}: no speed numbers recorded yet.")
    return lines


def _fmt_speed(x) -> str:
    x = float(x)
    if abs(x - round(x)) < 0.05:
        return f"{x:.0f}"
    return f"{x:.1f}"


def _fmt_time(x) -> str:
    x = float(x)
    if x >= 10:
        return f"{x:.1f}s"
    return f"{x:.2f}s"


def _fmt_pct(p) -> str:
    ap = abs(float(p))
    if ap >= 9.5:
        return f"{ap:.0f}%"
    if ap >= 1:
        return f"{ap:.0f}%"
    return f"{ap:.1f}%"


def _pct(fast, slow) -> float:
    return (float(fast) - float(slow)) / abs(float(slow)) * 100.0


def summarize(gguf_rows, mlx_rows, *, gguf_name="GGUF", mlx_name="MLX") -> str:
    """Plain-words comparison from measured numbers only. No invented values."""
    g_map = {r["label"]: r for r in (gguf_rows or []) if r.get("label")}
    m_map = {r["label"]: r for r in (mlx_rows or []) if r.get("label")}
    labels = []
    for r in (gguf_rows or []) + (mlx_rows or []):
        if r.get("label") and r["label"] not in labels:
            labels.append(r["label"])
    paragraphs = []
    for label in labels:
        g, m = g_map.get(label), m_map.get(label)
        head = label.replace(" (5)", "").replace(" (2)", "").replace(" (1)", "")
        head = head[0].lower() + head[1:] if head else label
        if (g or {}).get("skipped") and (m or {}).get("skipped"):
            reason = (g or m).get("reason") or "they would not fit the chat window."
            paragraphs.append(f"On {head}, both sides were skipped — {reason}")
            continue
        if (g or {}).get("skipped") and m and not m.get("skipped") and m.get("specs"):
            paragraphs.append(
                f"On {head}, {gguf_name} was skipped — {g.get('reason')}. "
                f"No comparison at this size."
            )
            continue
        if (m or {}).get("skipped") and g and not g.get("skipped") and g.get("specs"):
            paragraphs.append(
                f"On {head}, {mlx_name} was skipped — {m.get('reason')}. "
                f"No comparison at this size."
            )
            continue
        gs, ms = (g or {}).get("specs") or {}, (m or {}).get("specs") or {}
        if not gs or not ms:
            continue
        bits = []

        def speed_bit(key, word):
            a, b = gs.get(key), ms.get(key)
            if not isinstance(a, (int, float)) or not isinstance(b, (int, float)):
                return
            if a <= 0 or b <= 0:
                return
            rel = abs(a - b) / max(a, b)
            if rel < 0.02:
                bits.append(
                    f"about the same at {word} "
                    f"({_fmt_speed(a)} vs {_fmt_speed(b)} tok/s)"
                )
                return
            if b > a:
                winner, fast, slow = mlx_name, b, a
            else:
                winner, fast, slow = gguf_name, a, b
            bits.append(
                f"{winner} was faster at {word} "
                f"({_fmt_pct(_pct(fast, slow))} faster, "
                f"{_fmt_speed(fast)} vs {_fmt_speed(slow)} tok/s)"
            )

        def time_bit(key, word, unit_fmt=_fmt_time):
            a, b = gs.get(key), ms.get(key)
            if not isinstance(a, (int, float)) or not isinstance(b, (int, float)):
                return
            if a <= 0 or b <= 0:
                return
            rel = abs(a - b) / max(a, b)
            if rel < 0.02:
                bits.append(
                    f"{word} was about the same "
                    f"({unit_fmt(a)} vs {unit_fmt(b)})"
                )
                return
            if a < b:
                winner, fast, slow = gguf_name, a, b
            else:
                winner, fast, slow = mlx_name, b, a
            bits.append(
                f"{winner}'s {word} was sooner "
                f"({_fmt_pct((slow - fast) / slow * 100)} sooner, "
                f"{unit_fmt(fast)} vs {unit_fmt(slow)})"
            )

        speed_bit("read_tok_s", "reading")
        speed_bit("write_tok_s", "writing")
        time_bit("ttft_s", "first token")
        time_bit("total_s", "total time")
        if bits:
            # "On short prompts, X was ... and Y. Z."
            if len(bits) == 1:
                body = bits[0]
            elif len(bits) == 2:
                body = bits[0] + ", and " + bits[1]
            else:
                body = ", ".join(bits[:-1]) + ", and " + bits[-1]
            paragraphs.append(f"On {head}, {body}.")
    if not paragraphs:
        return ""
    return "\n".join(paragraphs) + "\n"


def steps_text(gguf_id: str, mlx_id: str, port: int = DEFAULT_PORT,
               *, gguf=None, mlx=None, query=None,
               run_short=True, run_long=True) -> str:
    """Exact commands Brenden can run. No invented numbers."""
    gid = gguf_id
    mid = mlx_id
    flags = ""
    if run_short and not run_long:
        flags = " --short"
    elif run_long and not run_short:
        flags = " --long"
    series = []
    if run_short:
        series.append("five short prompts")
    if run_long:
        series.append(
            "a long-prompt series at about 1k, 4k, and 8k tokens "
            "(two prompts at each size; sizes that will not fit the "
            "model's chat window are skipped)"
        )
    series_txt = " and ".join(series) if series else "the prompt series"
    header = (
        "This compares a GGUF model to its MLX counterpart and prints\n"
        "a compact chart of reading, writing, and first-token speed.\n"
        f"It runs {series_txt}. Sizes that were not run are left out.\n"
        "Pass --details (or --text) to also print the reply-stats\n"
        "lines. Pass --ascii for plain '#' bars.\n"
    )
    if gguf and mlx:
        header += (
            "\nThis would compare:\n"
            f"  {format_line(gguf)}\n"
            f"  {format_line(mlx)}\n"
        )
    header += (
        "\nWhen the comparison finishes (or if it stops early), Caravan puts\n"
        "the original model back, if one was loaded.\n"
        "\n"
        "On the 1st Mac, with Caravan running and both models already\n"
        "downloaded:\n"
        "\n"
        f"  caravan bench --gguf {gid} --mlx {mid}{flags} --yes\n"
    )
    if query:
        header += (
            "\nOr, using the name:\n"
            "\n"
            f'  caravan bench "{query}"{flags} --yes\n'
        )
    header += (
        "\nTo only print already-saved chat averages, without loading anything:\n"
        "\n"
        f"  caravan bench --gguf {gid} --mlx {mid} --from-averages\n"
        "\n"
        f"Caravan's page is http://127.0.0.1:{int(port)}/\n"
    )
    return header


def run_from_averages(gguf_id: str, mlx_id: str, *, gguf_name=None, mlx_name=None,
                      store=None, details=False, ascii=None, color=None,
                      stream=None, last_store=None) -> list:
    """Chart from the last bench run for this pair, else saved chat averages.

    Each side uses its last bench numbers when there are some ("Last
    bench"), otherwise the saved chat average ("Saved"). A side with no
    numbers gets a plain line instead of empty bars.
    """
    last = load_last_bench(gguf_id, mlx_id, path=last_store)
    g = averages_for(gguf_id, store=store)
    m = averages_for(mlx_id, store=store)
    gname = gguf_name or f"{gguf_id} (GGUF)"
    mname = mlx_name or f"{mlx_id} (MLX)"
    sources = []

    def pick(kind, saved):
        rows = _clean_rows(last.get(f"{kind.lower()}_rows"))
        if rows:
            day = _plain_day(last.get(f"{kind.lower()}_at"))
            sources.append(f"{kind}: Last bench" + (f" ({day})" if day else ""))
            return rows
        if saved:
            sources.append(f"{kind}: Saved chat average")
            return [{"label": "Saved", "specs": saved}]
        return []

    g_rows = pick("GGUF", g)
    m_rows = pick("MLX", m)
    lines = []
    if g_rows or m_rows:
        chart = render_chart(
            g_rows, m_rows, gguf_name=gname, mlx_name=mname,
            ascii=ascii, color=color, stream=stream,
        )
        lines.extend(chart.rstrip("\n").split("\n"))
        lines.append("")
        lines.extend(sources)
    if not g_rows:
        lines.append(no_numbers_line("GGUF"))
    if not m_rows:
        lines.append(no_numbers_line("MLX"))
    if details:
        lines.append("")
        if g_rows and not g:
            lines.extend(format_series(gname, g_rows))
        elif g_rows:
            lines.append(format_side(gname, g))
        if m_rows and not m:
            lines.extend(format_series(mname, m_rows))
        elif m_rows:
            lines.append(format_side(mname, m))
    return lines


def _restore_original(port, original_id, original_name, urlopen, notes,
                      progress=None):
    if progress:
        progress.set(restore_step())
    if not original_id:
        return
    label = original_name or original_id
    notes.append(f"Putting the original model back: {label}.")
    try:
        st = status(port, urlopen=urlopen)
        worker = (st or {}).get("worker") or st or {}
        if worker.get("status") == "ready" and worker.get("model_id") == original_id:
            notes.append("It is already loaded.")
            return
        load_model(port, original_id, urlopen=urlopen)
    except Exception as e:
        notes.append(f"Could not put the original model back: {e}")


def _emit(progress, lines, chunk, *, printed):
    """Append result lines; on a TTY, print them now after clearing the spinner."""
    for line in chunk:
        lines.append(line)
        if progress is not None and progress.mode == "animate":
            progress.println(line)
            printed[0] = True


def run_live(gguf_id: str, mlx_id: str, *, port=DEFAULT_PORT, urlopen=_urlopen,
             gguf_name=None, mlx_name=None, prompts=None,
             run_short=True, run_long=True, progress=None) -> dict:
    try:
        st = status(port, urlopen=urlopen)
    except KeyboardInterrupt:
        raise
    except Exception:
        raise RuntimeError(
            "Caravan is not running. Start it with caravan start, then run this again."
        )
    worker = (st or {}).get("worker") or st or {}
    if not worker and not isinstance(st, dict):
        raise RuntimeError(
            "Caravan is not running. Start it with caravan start, then run this again."
        )
    original_id = None
    original_name = None
    if worker.get("status") == "ready" and worker.get("model_id"):
        original_id = worker.get("model_id")
        original_name = worker.get("model_name") or original_id
    lines = []
    notes = []
    err = None
    g_rows, m_rows = [], []
    printed = [False]
    gname = gguf_name or f"{gguf_id} (GGUF)"
    mname = mlx_name or f"{mlx_id} (MLX)"
    try:
        if progress:
            progress.set(loading_step(gname))
        load_model(port, gguf_id, urlopen=urlopen)
        g_window = _running_window(port, urlopen)
        g_rows = measure_series(
            port, urlopen, run_short=run_short, run_long=run_long,
            prompts=prompts, window=g_window,
            progress=progress, side="GGUF",
        )
        # Collect the reply-stats wording for --details. Default output
        # is the chart, printed once the campfire has stopped.
        lines.extend(format_series(gname, g_rows))
        if progress:
            progress.set(loading_step(mname))
        load_model(port, mlx_id, urlopen=urlopen)
        m_window = _running_window(port, urlopen)
        m_rows = measure_series(
            port, urlopen, run_short=run_short, run_long=run_long,
            prompts=prompts, window=m_window,
            progress=progress, side="MLX",
        )
        lines.extend(format_series(mname, m_rows))
        summary = summarize(
            g_rows, m_rows,
            gguf_name=gguf_name or "GGUF",
            mlx_name=mlx_name or "MLX",
        )
        if summary:
            lines.append("")
            lines.append(summary.rstrip())
        lines.append("")
        lines.append(P.CACHE_NOTE)
    except KeyboardInterrupt:
        err = KeyboardInterrupt()
        notes.append("Stopped.")
    except Exception as e:
        err = e
    finally:
        _restore_original(
            port, original_id, original_name, urlopen, notes,
            progress=progress,
        )
    chart = render_chart(
        g_rows, m_rows, gguf_name=gname, mlx_name=mname,
    )
    return {
        "lines": lines,
        "notes": notes,
        "error": err,
        "original": original_id,
        "gguf_rows": g_rows,
        "mlx_rows": m_rows,
        "chart": chart,
        "printed": printed[0],
    }


def _stub(mid, kind, name=None):
    src = "gguf" if kind == "GGUF" else "mlx"
    return {"id": mid, "name": name or mid, "source": src, "usable": True}


def _resolve(args, models=None):
    query = (args.name or "").strip() or None
    if query or not (args.gguf and args.mlx):
        if models is None:
            cat = fetch_catalog(port=args.port)
            models = cat.get("models") or []
        pair = resolve_pair(
            models, query=query, gguf_id=args.gguf, mlx_id=args.mlx,
        )
        return pair
    return {
        "ok": True,
        "gguf": _stub(args.gguf, "GGUF", args.gguf_name),
        "mlx": _stub(args.mlx, "MLX", args.mlx_name),
        "messages": [],
    }


def _run_flags(args):
    short = bool(getattr(args, "short", False))
    long = bool(getattr(args, "long", False))
    return (short or not long, long or not short)


def main(argv=None, *, models=None):
    p = argparse.ArgumentParser(
        prog="caravan bench",
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p.add_argument(
        "name", nargs="?", default=None,
        help="plain model name, for example 'qwen2.5 coder 7b'; "
             "Caravan finds the matching GGUF and MLX among downloaded models",
    )
    p.add_argument(
        "--gguf", default=None,
        help="GGUF model id (for example gguf/qwen2.5-coder-7b-instruct-q4_k_m); "
             "see caravan models",
    )
    p.add_argument(
        "--mlx", default=None,
        help="MLX model id for the same model (for example "
             "mlx-community/Qwen2.5-Coder-7B-Instruct-4bit); see caravan models",
    )
    p.add_argument(
        "--yes", action="store_true",
        help="load each model and measure; the model that was loaded before "
             "is put back when the comparison finishes",
    )
    p.add_argument(
        "--short", action="store_true",
        help="run only the five short prompts",
    )
    p.add_argument(
        "--long", action="store_true",
        help="run only the long-prompt series (about 1k, 4k, and 8k tokens)",
    )
    p.add_argument(
        "--from-averages", action="store_true",
        help="draw a chart from already-saved chat averages only; "
             "do not load or unload a model",
    )
    p.add_argument(
        "--details", "--text", dest="details", action="store_true",
        help="also print the reply-stats lines and the unique-opening note",
    )
    p.add_argument(
        "--ascii", action="store_true",
        help="use plain '#' bars instead of block characters",
    )
    p.add_argument(
        "--quiet", action="store_true",
        help="no progress animation or step lines; still print the results",
    )
    p.add_argument(
        "--speedups", action="store_true",
        help="measure Prompt lookup and Guess-ahead: Off, Prompt lookup, "
             "Guess-ahead (when a helper is on this Mac) and Auto, on short, "
             "code-edit and long prompts, with how many guesses were kept",
    )
    p.add_argument(
        "--edits", action="store_true",
        help="with --speedups, run only the five code-edit prompts",
    )
    p.add_argument(
        "--only", choices=("gguf", "mlx"), default=None,
        help="with --speedups, measure only one side",
    )
    p.add_argument("--port", type=int, default=DEFAULT_PORT, help=argparse.SUPPRESS)
    p.add_argument("--gguf-name", default=None, help=argparse.SUPPRESS)
    p.add_argument("--mlx-name", default=None, help=argparse.SUPPRESS)
    args = p.parse_args(argv)
    run_short, run_long = _run_flags(args)
    pair = _resolve(args, models=models)
    if not pair.get("ok"):
        text = "\n\n".join(pair.get("messages") or [])
        if not text:
            text = (
                "Need both a GGUF and an MLX model. "
                "Pass a plain name, or both --gguf and --mlx. "
                "Run caravan models to see ids."
            )
        sys.stdout.write(text + "\n")
        return 2
    gguf, mlx = pair["gguf"], pair["mlx"]
    gid, mid = model_id(gguf), model_id(mlx)
    gname = args.gguf_name or _side_label(gguf, "GGUF")
    mname = args.mlx_name or _side_label(mlx, "MLX")
    if args.from_averages:
        for line in run_from_averages(
            gid, mid, gguf_name=gname, mlx_name=mname,
            details=args.details, ascii=args.ascii,
        ):
            print(line)
        return 0
    if args.speedups:
        return _main_speedups(args, gid, mid, gname, mname)
    if not args.yes:
        sys.stdout.write(steps_text(
            gid, mid, port=args.port, gguf=gguf, mlx=mlx, query=args.name,
            run_short=run_short, run_long=run_long,
        ))
        return 0
    progress = Progress(quiet=bool(args.quiet))
    progress.start()
    try:
        result = run_live(
            gid, mid, port=args.port,
            gguf_name=gname, mlx_name=mname,
            run_short=run_short, run_long=run_long,
            progress=progress,
        )
    except KeyboardInterrupt:
        progress.stop()
        sys.stderr.write("Stopped.\n")
        return 130
    except Exception as e:
        progress.stop()
        sys.stderr.write(f"Could not finish the comparison: {e}\n")
        return 1
    progress.stop()
    g_rows = result.get("gguf_rows") or []
    m_rows = result.get("mlx_rows") or []
    if g_rows or m_rows:
        save_last_bench(gid, mid, g_rows, m_rows)
    if g_rows or m_rows:
        chart = render_chart(
            g_rows, m_rows, gguf_name=gname, mlx_name=mname,
            ascii=args.ascii,
        )
        sys.stdout.write(chart if chart.endswith("\n") else chart + "\n")
    if args.details:
        for line in result.get("lines") or []:
            print(line)
    for note in result.get("notes") or []:
        print(note)
    err = result.get("error")
    if isinstance(err, KeyboardInterrupt) or err == "stopped":
        return 130
    if err:
        sys.stderr.write(f"Could not finish the comparison: {err}\n")
        return 1
    return 0


def _main_speedups(args, gid, mid, gname, mname) -> int:
    """caravan bench --speedups: Off / Prompt lookup / Guess-ahead / Auto."""
    import caravan_speedups as SU
    any_only = args.short or args.long or args.edits
    sets_args = {
        "run_short": bool(args.short or not any_only),
        "run_edits": bool(args.edits or not any_only),
        "run_long": bool(args.long or not any_only),
    }
    sides = (args.only,) if args.only else ("gguf", "mlx")
    if not args.yes:
        parts = []
        if sets_args["run_short"]:
            parts.append("the five short prompts")
        if sets_args["run_edits"]:
            parts.append("five code-edit prompts")
        if sets_args["run_long"]:
            parts.append("the long-prompt series")
        names = [n for k, n in (("gguf", gname), ("mlx", mname)) if k in sides]
        flags = " ".join(f for f, on in (("--short", args.short), ("--edits", args.edits),
                                         ("--long", args.long)) if on)
        only = f" --only {args.only}" if args.only else ""
        q = f'"{args.name}" ' if args.name else f"--gguf {gid} --mlx {mid} "
        sys.stdout.write(
            "This measures Prompt lookup and Guess-ahead on "
            + " and ".join(names) + ".\n"
            "Each model is loaded once per mode (Off, Prompt lookup, Guess-ahead "
            "when a helper is on this Mac, Auto) and runs "
            + (", ".join(parts[:-1]) + " and " + parts[-1] if len(parts) > 1 else parts[0]) + ".\n"
            "The model that is loaded now is put back at the end, with its settings.\n\n"
            f"Run: caravan bench {q}--speedups{only}{(' ' + flags) if flags else ''} --yes\n"
        )
        return 0
    progress = Progress(quiet=bool(args.quiet))
    progress.start()
    try:
        result = SU.run_speedups(
            gid, mid, port=args.port, urlopen=_urlopen, status_fn=status,
            window_fn=_running_window, gguf_name=gname, mlx_name=mname,
            sides=sides, sets_args=sets_args, progress=progress,
        )
    except KeyboardInterrupt:
        progress.stop()
        sys.stderr.write("Stopped.\n")
        return 130
    except Exception as e:
        progress.stop()
        sys.stderr.write(f"Could not finish the measurement: {e}\n")
        return 1
    progress.stop()
    if result.get("sides"):
        SU.save(result)
    for line in SU.render(result):
        print(line)
    for note in result.get("notes") or []:
        print(note)
    if result.get("error") == "stopped":
        return 130
    if result.get("error"):
        sys.stderr.write(f"Could not finish the measurement: {result['error']}\n")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
