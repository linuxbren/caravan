import subprocess, sys, numpy as np, matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib import font_manager as fm
import os
_FD = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fonts")
for _f in ("InterLab-Regular.ttf", "InterLab-Bold.ttf"): fm.fontManager.addfont(os.path.join(_FD, _f))
plt.rcParams["font.family"] = "InterLab"
W, H, FPS = 1920, 1080, 30
OUT = sys.argv[1]
BG, FG, MUTED, GRID = "#0f1117", "#f2f4f8", "#9aa3b2", "#262b36"
RT = ["llama.cpp", "Ollama", "exo (MLX)"]
COL = ["#4FC3F7", "#FFB74D", "#C084FC"]
MODELS = ["Qwen3-30B-A3B", "Gemma 4 26B-A4B", "GPT-OSS 20B"]
# Real numbers: experiments.md runtime-compare summary (medians, f16 KV)
TG = [[42.9, 45.2, 49.6], [37.0, 37.2, 41.5], [35.8, 36.4, 37.1]]
PP = [[325.4, 367.6, 410.6], [344.5, 375.6, 325.1], [373.6, 420.6, 398.6]]
PP16 = [[123.7, 123, None], [218.8, 216, 147], [247.3, 252, 34]]
TG16 = [[21.2, 21.0, None], [28.1, 25.9, 31.9], [28.6, 28.3, 26.7]]
MEM = [[19.4, 19.3, 20.4], [15.5, 17.3, 18.8], [12.8, 13.0, 15.0]]
METAL = 19.07

from decimal import Decimal, ROUND_HALF_UP
def r0(v): return str(Decimal(str(round(v, 6))).quantize(Decimal("1"), ROUND_HALF_UP))
def ease(t): t = min(max(t, 0), 1); return 1 - (1 - t) ** 3
fig = plt.figure(figsize=(W/100, H/100), dpi=100, facecolor=BG)
proc = subprocess.Popen(["ffmpeg", "-y", "-loglevel", "error", "-f", "rawvideo", "-pix_fmt", "rgba", "-s", f"{W}x{H}", "-r", str(FPS), "-i", "-",
    "-c:v", "libx264", "-preset", "medium", "-crf", "18", "-pix_fmt", "yuv420p", "-r", str(FPS), "-movflags", "+faststart", OUT], stdin=subprocess.PIPE)

def emit(alpha):
    if alpha < 1:
        fig.add_artist(plt.Rectangle((0, 0), 1, 1, transform=fig.transFigure, color=BG, alpha=1 - alpha, zorder=100))
    fig.canvas.draw(); proc.stdin.write(bytes(fig.canvas.buffer_rgba()))

def fade(i, n, f=12): return min(1, (i + 1) / f, (n - i) / f)

def header(title, sub):
    fig.text(0.05, 0.92, title, color=FG, fontsize=44, weight="bold", va="center")
    fig.text(0.05, 0.865, sub, color=MUTED, fontsize=24, va="center")

def legend(y=0.865):
    for x, r, c in zip((0.62, 0.725, 0.815), RT, COL):
        fig.patches.append(plt.Rectangle((x, y - 0.012), 0.016, 0.026, transform=fig.transFigure, color=c, figure=fig))
        fig.text(x + 0.022, y, r, color=FG, fontsize=24, va="center")

def bars(ax, data, t, fmt, ymax, crashed=None, start=0.0):
    ax.set_facecolor(BG); w = 0.26
    for s in ax.spines.values(): s.set_visible(False)
    ax.tick_params(colors=FG, labelsize=24, length=0); ax.yaxis.set_tick_params(labelsize=18, labelcolor=MUTED)
    ax.grid(axis="y", color=GRID, lw=1); ax.set_axisbelow(True)
    ax.set_xticks(range(3)); ax.set_xticklabels(MODELS); ax.set_ylim(0, ymax); ax.set_xlim(-0.6, 2.6)
    for m in range(3):
        for r in range(3):
            v = data[m][r]; x = m + (r - 1) * w
            p = ease((t - start - 0.25 * m - 0.08 * r) / 1.4)
            if v is None:
                if p > 0:
                    ax.bar(x, ymax * 0.06, w * 0.92, color="none", edgecolor="#ff5c5c", lw=2.5, hatch="//", alpha=p)
                    ax.text(x, ymax * 0.08, "crashed", color="#ff5c5c", fontsize=20, weight="bold", ha="center", va="bottom", rotation=90, alpha=p)
                continue
            ax.bar(x, v * p, w * 0.92, color=COL[r])
            if p > 0.02:
                ax.text(x, v * p + ymax * 0.012, fmt(v * p if p < 1 else v), color=FG, fontsize=21, weight="bold", ha="center", va="bottom")

def scene(n, draw):
    for i in range(n):
        fig.clf(); fig.patch.set_facecolor(BG); draw(i / FPS); emit(fade(i, n))

# 1 title (4 s)
def title(t):
    a = ease(t / 0.8)
    fig.text(0.5, 0.60, "llama.cpp vs Ollama vs exo", color=FG, fontsize=78, weight="bold", ha="center", alpha=a)
    fig.text(0.5, 0.49, "on a 24 GB M4 Mac mini", color=FG, fontsize=50, ha="center", alpha=a)
    x0 = 0.5 - 0.18
    for k, c in enumerate(COL):
        fig.patches.append(plt.Rectangle((x0 + k * 0.12, 0.42), 0.12 * ease((t - 0.3 - 0.15 * k) / 0.8), 0.008, transform=fig.transFigure, color=c, figure=fig))
    fig.text(0.5, 0.33, "Oct 30, 2026  ·  Qwen3-30B-A3B  ·  Gemma 4 26B-A4B  ·  GPT-OSS 20B", color=MUTED, fontsize=28, ha="center", alpha=a)
scene(4 * FPS, title)

def chart(titl, sub, data, fmt, ymax, foot, crashed=None):
    def d(t):
        header(titl, sub); legend()
        ax = fig.add_axes([0.07, 0.13, 0.88, 0.68]); bars(ax, data, t, fmt, ymax)
        fig.text(0.05, 0.045, foot, color=MUTED, fontsize=19)
    return d
scene(8 * FPS, chart("Generation speed (tg128)", "tokens/second, higher is better", TG, lambda v: f"{v:.1f}", 58,
      "Median of 3 runs, f16 KV cache, single Mac mini M4 24 GB. llama.cpp & Ollama: same GGUF files; exo: MLX 4-bit / MXFP4-Q8 conversions."))
scene(8 * FPS, chart("Prompt processing (pp4096)", "tokens/second for a ~4k-token prompt, higher is better", PP, r0, 490,
      "Median of 3 runs, f16 KV. Measured by llama-bench / Ollama server timings / exo bench endpoint, so methods differ slightly."))

# 4 16k depth (10 s)
def deep(t):
    header("At 16k tokens of context", "~550 new prompt tokens on top of a 16k context, then 128 generated")
    legend()
    a1 = fig.add_axes([0.06, 0.25, 0.42, 0.53]); bars(a1, PP16, t, r0, 300)
    a1.set_title("Prompt tok/s @16k", color=FG, fontsize=26, pad=14); a1.tick_params(axis="x", labelsize=19)
    a2 = fig.add_axes([0.55, 0.25, 0.42, 0.53]); bars(a2, TG16, t, lambda v: f"{v:.1f}", 38, start=0.4)
    a2.set_title("Generation tok/s @16k", color=FG, fontsize=26, pad=14); a2.tick_params(axis="x", labelsize=19)
    p = ease((t - 3.0) / 0.8)
    if p > 0:
        fig.text(0.5, 0.135, "GPT-OSS time to first token at 16k:   exo 16.1 s   vs   Ollama 2.2 s", color=FG, fontsize=30, weight="bold",
                 ha="center", alpha=p, bbox=dict(boxstyle="round,pad=0.5", fc="#1b1f2a", ec=COL[2], lw=2, alpha=p))
    fig.text(0.05, 0.03, "exo Qwen3-30B runner crashed before the 16k test.  KV cache: q8_0 for llama.cpp & Ollama, f16 for exo (no KV quant in MLX).\nOllama & exo 16k prompt rates are approximate (derived from timings).",
             color=MUTED, fontsize=18)
scene(10 * FPS, deep)

# 5 memory (8 s)
def mem(t):
    header("Peak memory", "GB, lower is better. 24 GB Mac mini; Metal working-set limit ≈ 19 GB"); legend()
    ax = fig.add_axes([0.07, 0.13, 0.88, 0.68]); bars(ax, MEM, t, lambda v: f"{v:.1f}", 24)
    p = ease((t - 1.8) / 0.8)
    if p > 0:
        ax.axhline(METAL, color="#ff5c5c", lw=3, ls="--", xmax=p)
        ax.text(2.58, METAL + 0.35, "Metal limit ≈ 19 GB", color="#ff5c5c", fontsize=22, weight="bold", ha="right", alpha=p)
    fig.text(0.05, 0.045, "llama.cpp & Ollama: peak process RSS (top of measured range); exo: MLX peak memory. Ollama Gemma f16 read 19.3 GB, likely double-counted.",
             color=MUTED, fontsize=18)
scene(8 * FPS, mem)

# 6 takeaways (7 s)
def take(t):
    fig.text(0.07, 0.86, "Takeaways", color=FG, fontsize=56, weight="bold")
    items = [(COL[1], "Ollama is fastest at prompts on Gemma & GPT-OSS", "It runs a newer llama.cpp underneath: +9–13% pp4096 on the same GGUF files"),
             (COL[2], "exo is fastest at generation on all three models", "Qwen +16%, Gemma +12%, GPT-OSS +4% vs llama.cpp, and best Qwen pp4096 (411)"),
             ("#ff5c5c", "…but exo is the least robust on one 24 GB Mini", "Highest memory use; Qwen & Gemma runners crashed on long prompts")]
    for k, (c, h, s) in enumerate(items):
        p = ease((t - 0.3 - 0.5 * k) / 0.7); y = 0.70 - 0.17 * k
        fig.patches.append(plt.Rectangle((0.07, y - 0.075), 0.008, 0.11, transform=fig.transFigure, color=c, alpha=p, figure=fig))
        fig.text(0.095 - 0.02 * (1 - p), y, h, color=FG, fontsize=38, weight="bold", alpha=p, va="center")
        fig.text(0.095 - 0.02 * (1 - p), y - 0.055, s, color=MUTED, fontsize=26, alpha=p, va="center")
    p = ease((t - 2.0) / 0.7)
    fig.text(0.07, 0.12, "Caveat: exo used MLX quants (4-bit, MXFP4-Q8); llama.cpp & Ollama used identical GGUF files.", color="#d6dbe4", fontsize=26, alpha=p, style="italic")
scene(7 * FPS, take)
proc.stdin.close(); proc.wait(); print("done", proc.returncode)
