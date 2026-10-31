import subprocess, sys, os, numpy as np, matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib import font_manager as fm
_FD = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fonts")
for _f in ("InterLab-Regular.ttf", "InterLab-Bold.ttf"): fm.fontManager.addfont(os.path.join(_FD, _f))
plt.rcParams["font.family"] = "InterLab"
W, H, FPS = 1920, 1080, 30
OUT = sys.argv[1]
BG, FG, MUTED, GRID, RED = "#0f1117", "#f2f4f8", "#9aa3b2", "#262b36", "#ff5c5c"
RT = ["Caravan", "llama.cpp (bare)", "Ollama", "exo (MLX)"]
CARAVAN = "#34D399"
COL = [CARAVAN, "#4FC3F7", "#FFB74D", "#C084FC"]
MODELS = ["Qwen3-30B-A3B", "Gemma 4 26B-A4B", "GPT-OSS 20B"]
# Real numbers: experiments.md "Runtime compare (Caravan)" entry. Order: Caravan, llama.cpp, Ollama, exo
TG = [[40.8, 42.9, 45.2, 49.6], [34.9, 37.0, 37.2, 41.5], [36.3, 35.8, 36.4, 37.1]]
PP = [[336.7, 325.4, 367.6, 410.6], [357.0, 344.5, 375.6, 325.1], [429.5, 373.6, 420.6, 398.6]]
PP16 = [[121.7, 123.7, 123, None], [206.9, 218.8, 216, 147], [253.0, 247.3, 252, 34]]
TG16 = [[20.0, 21.2, 21.0, None], [26.6, 28.1, 25.9, 31.9], [28.9, 28.6, 28.3, 26.7]]
MEM = [[18.7, 19.4, 19.3, 20.4], [16.3, 15.5, 17.3, 18.8], [12.9, 12.8, 13.0, 15.0]]
# resume TTFT (s): cold, warm in memory, after full restart (slot restored from disk)
RES = [[80.0, 1.01, 1.18], [55.6, 0.80, 56.1], [46.2, 0.75, 48.1]]
METAL = 19.07
NR = len(RT)
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
    xs = (0.535, 0.635, 0.775, 0.862)
    for x, r, c in zip(xs, RT, COL):
        fig.patches.append(plt.Rectangle((x, y - 0.012), 0.016, 0.026, transform=fig.transFigure, color=c, figure=fig))
        fig.text(x + 0.022, y, r, color=FG, fontsize=22, va="center", weight="bold" if r == "Caravan" else "normal")
def bars(ax, data, t, fmt, ymax, start=0.0, fs=18):
    ax.set_facecolor(BG); w = 0.2
    for s in ax.spines.values(): s.set_visible(False)
    ax.tick_params(colors=FG, labelsize=24, length=0); ax.yaxis.set_tick_params(labelsize=18, labelcolor=MUTED)
    ax.grid(axis="y", color=GRID, lw=1); ax.set_axisbelow(True)
    ax.set_xticks(range(3)); ax.set_xticklabels(MODELS); ax.set_ylim(0, ymax); ax.set_xlim(-0.6, 2.6)
    for m in range(3):
        for r in range(NR):
            v = data[m][r]; x = m + (r - 1.5) * w
            p = ease((t - start - 0.25 * m - 0.08 * r) / 1.4)
            if v is None:
                if p > 0:
                    ax.bar(x, ymax * 0.06, w * 0.9, color="none", edgecolor=RED, lw=2.5, hatch="//", alpha=p)
                    ax.text(x, ymax * 0.08, "crashed", color=RED, fontsize=18, weight="bold", ha="center", va="bottom", rotation=90, alpha=p)
                continue
            ax.bar(x, v * p, w * 0.9, color=COL[r], edgecolor=FG if r == 0 else "none", lw=1.5 if r == 0 else 0)
            if p > 0.02:
                ax.text(x, v * p + ymax * 0.012, fmt(v * p if p < 1 else v), color=CARAVAN if r == 0 else FG, fontsize=fs, weight="bold", ha="center", va="bottom")
def scene(n, draw):
    for i in range(n):
        fig.clf(); fig.patch.set_facecolor(BG); draw(i / FPS); emit(fade(i, n))
# 1 title (4 s)
def title(t):
    a = ease(t / 0.8)
    fig.text(0.5, 0.62, "Caravan vs llama.cpp vs Ollama vs exo", color=FG, fontsize=72, weight="bold", ha="center", alpha=a)
    fig.text(0.5, 0.51, "on a 24 GB M4 Mac mini", color=FG, fontsize=50, ha="center", alpha=a)
    x0 = 0.5 - 0.20
    for k, c in enumerate(COL):
        fig.patches.append(plt.Rectangle((x0 + k * 0.10, 0.44), 0.10 * ease((t - 0.3 - 0.15 * k) / 0.8), 0.008 if k else 0.014, transform=fig.transFigure, color=c, figure=fig))
    fig.text(0.5, 0.35, "Caravan = its slot-pinning proxy + llama-server, measured end to end through the proxy", color=CARAVAN, fontsize=28, ha="center", alpha=a)
    fig.text(0.5, 0.28, "Oct 30, 2026  ·  Qwen3-30B-A3B  ·  Gemma 4 26B-A4B  ·  GPT-OSS 20B", color=MUTED, fontsize=28, ha="center", alpha=a)
scene(4 * FPS, title)
def chart(titl, sub, data, fmt, ymax, foot):
    def d(t):
        header(titl, sub); legend()
        ax = fig.add_axes([0.07, 0.13, 0.88, 0.68]); bars(ax, data, t, fmt, ymax)
        fig.text(0.05, 0.045, foot, color=MUTED, fontsize=18)
    return d
scene(7 * FPS, chart("Generation speed (tg128)", "tokens/second, higher is better", TG, lambda v: f"{v:.1f}", 58,
      "Median of 3. Caravan: q8_0 KV (its default), via proxy. Others: f16 KV. With q8 KV, Ollama reads 43.8 / 35.0 / 35.6. exo uses MLX conversions."))
scene(7 * FPS, chart("Prompt processing (pp4096)", "tokens/second for a ~4k-token prompt, higher is better", PP, r0, 500,
      "Median of 3. Caravan: llama-server timings through the proxy (ub 1024/2048). llama.cpp: llama-bench. Ollama: server timings. exo: bench endpoint."))
# 4 16k depth (9 s)
def deep(t):
    header("At 16k tokens of context", "~550 new tokens on a cached 16k context, +128 generated")
    legend()
    a1 = fig.add_axes([0.06, 0.2, 0.42, 0.58]); bars(a1, PP16, t, r0, 300, fs=15)
    a1.set_title("Prompt tok/s @16k", color=FG, fontsize=26, pad=14); a1.tick_params(axis="x", labelsize=18)
    a2 = fig.add_axes([0.55, 0.2, 0.42, 0.58]); bars(a2, TG16, t, lambda v: f"{v:.1f}", 38, start=0.4, fs=15)
    a2.set_title("Generation tok/s @16k", color=FG, fontsize=26, pad=14); a2.tick_params(axis="x", labelsize=18)
    fig.text(0.05, 0.035, "q8_0 KV for Caravan, llama.cpp & Ollama; f16 for exo. exo Qwen3-30B runner crashed before the 16k test.\nCaravan Qwen 16k used one 18k slot (two 12k slots ran out of Metal memory). Ollama & exo 16k prompt rates approximate.",
             color=MUTED, fontsize=18)
scene(9 * FPS, deep)
# 5 memory (7 s)
def mem(t):
    header("Peak memory", "GB, lower is better. Metal working-set limit ≈ 19 GB"); legend()
    ax = fig.add_axes([0.07, 0.13, 0.88, 0.68]); bars(ax, MEM, t, lambda v: f"{v:.1f}", 24)
    p = ease((t - 1.8) / 0.8)
    if p > 0:
        ax.axhline(METAL, color=RED, lw=3, ls="--", xmax=p)
        ax.text(2.58, METAL + 0.35, "Metal limit ≈ 19 GB", color=RED, fontsize=22, weight="bold", ha="right", alpha=p)
    fig.text(0.05, 0.045, "Caravan / llama.cpp / Ollama: peak process RSS; exo: MLX peak. Caravan Gemma & GPT-OSS run with two 18k slots allocated.",
             color=MUTED, fontsize=18)
scene(7 * FPS, mem)
# 6 resume headline (11 s)
RL = ["Turn 1, cold", "Warm, in memory", "After full restart"]
RC = ["#5b6475", "#7dd3fc", CARAVAN]
def resume(t):
    header("Resume a 16k conversation after a restart", "Caravan only · time to first token, seconds, lower is better")
    for k, (lab, c) in enumerate(zip(RL, RC)):
        x = (0.53, 0.66, 0.82)[k]
        fig.patches.append(plt.Rectangle((x, 0.853), 0.016, 0.026, transform=fig.transFigure, color=c, figure=fig))
        fig.text(x + 0.022, 0.865, lab, color=FG, fontsize=22, va="center")
    ax = fig.add_axes([0.2, 0.25, 0.72, 0.56]); ax.set_facecolor(BG)
    for s in ax.spines.values(): s.set_visible(False)
    ax.tick_params(colors=FG, labelsize=24, length=0); ax.xaxis.set_tick_params(labelsize=18, labelcolor=MUTED)
    ax.grid(axis="x", color=GRID, lw=1); ax.set_axisbelow(True); ax.set_xlim(0, 92); ax.set_ylim(2.6, -0.6)
    ax.set_yticks(range(3)); ax.set_yticklabels(MODELS)
    h = 0.26
    for m in range(3):
        for k in range(3):
            v = RES[m][k]; y = m + (k - 1) * h
            p = ease((t - 0.3 - 0.35 * m - 0.12 * k) / 1.3)
            bad = (k == 2 and m > 0)
            ax.barh(y, v * p, h * 0.88, color=RED if bad else RC[k])
            if p > 0.02:
                val = v * p if p < 1 else v
                lbl = f"{val:.1f} s" if val >= 10 else f"{val:.2f} s"
                if bad and p >= 1: lbl += "   restored, but re-prefilled"
                ax.text(v * p + 0.8, y, lbl, color=(RED if bad else (CARAVAN if k == 2 else FG)), fontsize=20, weight="bold", va="center")
    p = ease((t - 2.6) / 0.8)
    if p > 0:
        ax.text(14, -0.02, "68× faster: slot restored from disk", color=CARAVAN, fontsize=24, weight="bold", va="center", alpha=p)
    p2 = ease((t - 4.5) / 0.8)
    if p2 > 0:
        fig.text(0.5, 0.135, "Works for Qwen. Gemma 4 & GPT-OSS use sliding-window layers: llama-server discards the restored cache.",
                 color=FG, fontsize=26, weight="bold", ha="center", alpha=p2, bbox=dict(boxstyle="round,pad=0.5", fc="#1b1f2a", ec=CARAVAN, lw=2, alpha=p2))
    fig.text(0.05, 0.035, "Restart = stop & restart llama-server + proxy (1.5–2.1 s, files in page cache). Qwen slot file 852 MB, save 0.18 s / restore 0.26 s.\nWarm-cache reference, no restart (earlier runs): GPT-OSS @16k, Ollama 2.2 s vs exo 16.1 s. Ollama & exo were not tested after a restart.",
             color=MUTED, fontsize=18)
scene(11 * FPS, resume)
# 7 takeaways (8 s)
def take(t):
    fig.text(0.07, 0.86, "Takeaways", color=FG, fontsize=56, weight="bold")
    items = [(CARAVAN, "Caravan resumes a 16k Qwen chat in 1.2 s after a restart, not 80 s", "Its saved slots work, but not yet for Gemma 4 / GPT-OSS (sliding-window layers re-prefill)"),
             (COL[1], "Through the proxy, Caravan runs at about bare llama.cpp speed", "Generation −6% to +1%; best pp4096 on GPT-OSS (430), higher than llama-bench on all three"),
             (COL[2], "Caravan is not the fastest runtime", "Ollama is faster at short prompts on every model; exo/MLX is fastest at generation"),
             (RED, "Qwen3-30B barely fits on a 24 GB Mini", "Two 12k slots ran out of Metal memory; two 8k or one 18k slot is the limit")]
    for k, (c, h, s) in enumerate(items):
        p = ease((t - 0.3 - 0.5 * k) / 0.7); y = 0.72 - 0.155 * k
        fig.patches.append(plt.Rectangle((0.07, y - 0.07), 0.008, 0.1, transform=fig.transFigure, color=c, alpha=p, figure=fig))
        fig.text(0.095 - 0.02 * (1 - p), y, h, color=FG, fontsize=34, weight="bold", alpha=p, va="center")
        fig.text(0.095 - 0.02 * (1 - p), y - 0.05, s, color=MUTED, fontsize=24, alpha=p, va="center")
    p = ease((t - 2.5) / 0.7)
    fig.text(0.07, 0.07, "Caveats: Caravan used q8_0 KV (others f16 in tg/pp charts); exo used MLX quants; one Mac mini, single node.", color="#d6dbe4", fontsize=24, alpha=p, style="italic")
scene(8 * FPS, take)
proc.stdin.close(); proc.wait(); print("done", proc.returncode)
