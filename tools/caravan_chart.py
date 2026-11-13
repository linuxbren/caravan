"""ASCII bar chart for `caravan bench` results.

Default output is a compact chart: full model names once at the top,
short labels GGUF and MLX on the bars, one section each for reading,
writing, and first token. Sizes that were not run are omitted. Block
characters (█ ▌) are used when the stream is UTF-8; otherwise '#'.
"""
from __future__ import annotations

import os
import sys

FULL_U, HALF_U = "█", "▌"
FULL_A = "#"
STAR_U, STAR_A = "★", "*"

AMBER = "\033[38;5;214m"
GREEN = "\033[32m"
RESET = "\033[0m"

SECTIONS = (
    ("Reading (tok/s, higher is better)", "read_tok_s", "speed", True),
    ("Writing (tok/s, higher is better)", "write_tok_s", "speed", True),
    ("First token (s, lower is better)", "ttft_s", "time", False),
)

SIZE_ORDER = ("Short", "~1k", "~4k", "~8k", "Saved")
_SIZE_FROM_N = {1024: "~1k", 2048: "~2k", 4096: "~4k", 8192: "~8k"}


def no_color_set() -> bool:
    v = os.environ.get("NO_COLOR")
    return v is not None and v != ""


def is_utf8(stream=None) -> bool:
    stream = sys.stdout if stream is None else stream
    enc = (getattr(stream, "encoding", None) or "").lower()
    if "utf" in enc:
        return True
    if enc:
        return False
    return True


def decide_style(*, ascii=None, color=None, stream=None) -> dict:
    """Pick characters and color from the stream and flags.

    ascii=True forces '#'; ascii=False forces block characters;
    ascii=None follows the stream: not UTF-8, NO_COLOR, or --ascii
    (the caller passes ascii=True) fall back to '#'. Color is on
    only for a TTY without NO_COLOR, unless the caller sets color.
    """
    stream = sys.stdout if stream is None else stream
    nocolor = no_color_set()
    try:
        tty = bool(stream.isatty())
    except Exception:
        tty = False
    if ascii is True:
        force_ascii = True
    elif ascii is False:
        force_ascii = False
    else:
        force_ascii = nocolor or not is_utf8(stream)
    if color is None:
        use_color = (not nocolor) and tty
    else:
        use_color = bool(color) and not nocolor
    return {
        "ascii": force_ascii,
        "color": use_color,
        "full": FULL_A if force_ascii else FULL_U,
        "half": "" if force_ascii else HALF_U,
        "star": STAR_A if force_ascii else STAR_U,
    }


def size_label_of(row) -> str:
    """Short, ~1k, ~4k, ~8k, or Saved — from a measure_series row."""
    if not row:
        return ""
    size = row.get("size")
    if isinstance(size, (int, float)) and int(size) in _SIZE_FROM_N:
        return _SIZE_FROM_N[int(size)]
    lab = str(row.get("label") or "")
    low = lab.lower()
    if "saved" in low:
        return "Saved"
    if "short" in low:
        return "Short"
    for tag in ("8k", "4k", "2k", "1k"):
        if tag in low:
            return f"~{tag}"
    return lab.split()[0] if lab else ""


def _fmt_speed(x) -> str:
    x = float(x)
    if abs(x - round(x)) < 0.05:
        return f"{x:.0f}"
    return f"{x:.1f}"


def _fmt_time(x) -> str:
    """Two decimals, matching the measured figures (0.28s, 20.96s, 52.15s)."""
    return f"{float(x):.2f}s"


def _fmt_pct(p) -> str:
    ap = abs(float(p))
    if ap >= 1:
        return f"{ap:.0f}%"
    return f"{ap:.1f}%"


def _rows_by_size(rows) -> dict:
    out = {}
    for r in rows or []:
        if not isinstance(r, dict) or r.get("skipped"):
            continue
        specs = r.get("specs") or {}
        if not specs:
            continue
        lab = size_label_of(r)
        if lab:
            out[lab] = specs
    return out


def _value(specs, key):
    if not specs:
        return None
    v = specs.get(key)
    if isinstance(v, (int, float)) and v > 0:
        return float(v)
    return None


def _bar(frac, width, full, half) -> str:
    frac = max(0.0, min(1.0, float(frac)))
    cells = frac * width
    n = int(cells)
    rem = cells - n
    if half and rem >= 0.5 and n < width:
        return full * n + half + " " * (width - n - 1)
    if not half:
        n = int(round(cells))
        n = min(width, max(0, n))
        # A real value that would round to empty still gets one mark,
        # so a tiny bar is visible.
        if n == 0 and frac > 0:
            n = 1
        return full * n + " " * (width - n)
    if n == 0 and frac > 0:
        return (half or full) + " " * (width - 1)
    return full * n + " " * (width - n)


def _paint(text, color_code, enabled) -> str:
    if not enabled or not color_code:
        return text
    return f"{color_code}{text}{RESET}"


def _lead(a, b, *, higher_is_better) -> tuple:
    """(winner_side, pct) or (None, None) if a tie or missing."""
    if a is None or b is None:
        return None, None
    if a <= 0 or b <= 0:
        return None, None
    rel = abs(a - b) / max(a, b)
    if rel < 0.02:
        return None, None
    if higher_is_better:
        if a > b:
            return "GGUF", (a - b) / b * 100.0
        return "MLX", (b - a) / a * 100.0
    if a < b:
        return "GGUF", (b - a) / b * 100.0
    return "MLX", (a - b) / a * 100.0


def _goodness(value, *, higher_is_better):
    if value is None or value <= 0:
        return 0.0
    return float(value) if higher_is_better else 1.0 / float(value)


def render_chart(gguf_rows, mlx_rows, *, gguf_name="GGUF", mlx_name="MLX",
                 ascii=None, color=None, stream=None, width=80) -> str:
    """Render a bar chart from measure_series rows. No invented numbers."""
    style = decide_style(ascii=ascii, color=color, stream=stream)
    width = int(width or 80)
    g_map = _rows_by_size(gguf_rows)
    m_map = _rows_by_size(mlx_rows)
    sizes = [s for s in SIZE_ORDER if s in g_map or s in m_map]
    for lab in list(g_map) + list(m_map):
        if lab not in sizes:
            sizes.append(lab)
    if not sizes:
        return "No speed numbers to chart yet.\n"

    lines = []
    g_title = gguf_name or "GGUF"
    m_title = mlx_name or "MLX"
    # Full names once, with the short labels used on the bars.
    if not g_title.upper().startswith("GGUF"):
        lines.append(f"GGUF  {g_title}")
    else:
        lines.append(g_title)
    if not m_title.upper().startswith("MLX"):
        lines.append(f"MLX   {m_title}")
    else:
        lines.append(m_title)
    lines.append("")

    # "Short  GGUF  " (5+2+4+2=13) + bar + "  " + value(6) + "  " + mark(8)
    size_w, kind_w, val_w, mark_w = 5, 4, 6, 8
    prefix_w = size_w + 2 + kind_w + 2
    suffix_w = 2 + val_w + 2 + mark_w
    bar_w = max(8, width - prefix_w - suffix_w)

    full, half, star = style["full"], style["half"], style["star"]
    use_color = style["color"]

    for title, key, kind, higher in SECTIONS:
        pairs = []
        for size in sizes:
            gv = _value(g_map.get(size), key)
            mv = _value(m_map.get(size), key)
            if gv is None and mv is None:
                continue
            pairs.append((size, gv, mv))
        if not pairs:
            continue
        lines.append(title)
        if higher:
            goodness = [
                _goodness(v, higher_is_better=True)
                for _, gv, mv in pairs
                for v in (gv, mv)
            ]
            section_peak = max(goodness) if goodness else 1.0
            if section_peak <= 0:
                section_peak = 1.0
        else:
            section_peak = None  # first token: scale each size on its own
        fmt = _fmt_speed if kind == "speed" else _fmt_time
        for size, gv, mv in pairs:
            winner, pct = _lead(gv, mv, higher_is_better=higher)
            if section_peak is None:
                peak = max(
                    _goodness(gv, higher_is_better=higher),
                    _goodness(mv, higher_is_better=higher),
                    1e-12,
                )
            else:
                peak = section_peak
            for side, val, paint in (
                ("GGUF", gv, AMBER),
                ("MLX", mv, GREEN),
            ):
                size_cell = size if side == "GGUF" else ""
                prefix = f"{size_cell:<{size_w}}  {side:<{kind_w}}  "
                if val is None:
                    line = prefix + (" " * bar_w) + f"  {'':>{val_w}}"
                    lines.append(line.rstrip())
                    continue
                frac = _goodness(val, higher_is_better=higher) / peak
                body = _paint(_bar(frac, bar_w, full, half), paint, use_color)
                val_s = fmt(val)
                mark = ""
                if winner == side and pct is not None:
                    mark = f"{star} +{_fmt_pct(pct)}"
                line = prefix + body + f"  {val_s:>{val_w}}  {mark:<{mark_w}}"
                lines.append(line.rstrip())
        lines.append("")

    return "\n".join(lines).rstrip() + "\n"


# Fixture from Brenden's first full-series run on the 1st Mac,
# Qwen2.5 Coder 7B (five short prompts plus the long-prompt series).
# Used in tests and in the docs sample. Do not invent other figures.
FIXTURE_GGUF_NAME = "Qwen2.5 Coder 7B (GGUF Q4_K_M)"
FIXTURE_MLX_NAME = "Qwen2.5 Coder 7B (MLX 4bit)"
FIXTURE_GGUF = [
    {"label": "Short prompts (5)", "specs": {
        "read_tok_s": 182, "write_tok_s": 22.2, "ttft_s": 0.28,
        "prompt_tokens": 77, "completion_tokens": 145, "total_s": 6.76,
    }},
    {"label": "Long prompts (~1k tok) (2)", "size": 1024, "specs": {
        "read_tok_s": 239, "write_tok_s": 21.5, "ttft_s": 5.30,
        "prompt_tokens": 1265, "completion_tokens": 149, "total_s": 12.20,
    }},
    {"label": "Long prompts (~4k tok) (2)", "size": 4096, "specs": {
        "read_tok_s": 215, "write_tok_s": 19.1, "ttft_s": 23.40,
        "prompt_tokens": 5035, "completion_tokens": 161, "total_s": 31.83,
    }},
    {"label": "Long prompts (~8k tok) (2)", "size": 8192, "specs": {
        "read_tok_s": 195, "write_tok_s": 16.7, "ttft_s": 52.15,
        "prompt_tokens": 10102, "completion_tokens": 146, "total_s": 61.04,
    }},
]
FIXTURE_MLX = [
    {"label": "Short prompts (5)", "specs": {
        "read_tok_s": 204, "write_tok_s": 23.4, "ttft_s": 0.46,
        "prompt_tokens": 77, "completion_tokens": 141, "total_s": 6.45,
    }},
    {"label": "Long prompts (~1k tok) (2)", "size": 1024, "specs": {
        "read_tok_s": 257, "write_tok_s": 22.9, "ttft_s": 5.01,
        "prompt_tokens": 1265, "completion_tokens": 148, "total_s": 11.44,
    }},
    {"label": "Long prompts (~4k tok) (2)", "size": 4096, "specs": {
        "read_tok_s": 242, "write_tok_s": 21.8, "ttft_s": 20.96,
        "prompt_tokens": 5035, "completion_tokens": 167, "total_s": 28.57,
    }},
    {"label": "Long prompts (~8k tok) (2)", "size": 8192, "specs": {
        "read_tok_s": 218, "write_tok_s": 20.4, "ttft_s": 46.74,
        "prompt_tokens": 10102, "completion_tokens": 89, "total_s": 51.08,
    }},
]


def fixture_chart(*, ascii=True, color=False, width=80) -> str:
    return render_chart(
        FIXTURE_GGUF, FIXTURE_MLX,
        gguf_name=FIXTURE_GGUF_NAME, mlx_name=FIXTURE_MLX_NAME,
        ascii=ascii, color=color, width=width,
    )


if __name__ == "__main__":
    sys.stdout.write(fixture_chart(ascii=True))
    print("--- utf-8 ---")
    sys.stdout.write(fixture_chart(ascii=False, color=False))
