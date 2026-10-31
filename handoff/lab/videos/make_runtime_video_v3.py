import subprocess, sys, os, json, numpy as np, matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib import font_manager as fm
_FD = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fonts")
for _f in ("InterLab-Regular.ttf", "InterLab-Bold.ttf"): fm.fontManager.addfont(os.path.join(_FD, _f))
plt.rcParams["font.family"] = "InterLab"
W, H, FPS = 1920, 1080, 30
OUT = sys.argv[1]; D = json.load(open(sys.argv[2]))
BG, FG, MUTED, GRID, RED = "#0f1117", "#f2f4f8", "#9aa3b2", "#262b36", "#ff5c5c"
RT = ["Caravan", "LocalAI", "llama.cpp", "exo"]
CARAVAN, LOCALAI = "#34D399", "#F472B6"
COL = [CARAVAN, LOCALAI, "#4FC3F7", "#C084FC"]
MODELS = ["Qwen3 30B", "Gemma 4 26B", "GPT-OSS 20B"]
# Order: Caravan, LocalAI, llama.cpp, exo. Numbers: experiments.md runtime-compare entries (Caravan, LocalAI).
TG, PP, PP16, TG16, MEM = D["TG"], D["PP"], D["PP16"], D["TG16"], D["MEM"]
RES = D["RES"]          # Caravan: cold, warm, after restart
LRES = D["LRES"]        # LocalAI after restart (or None)
METAL = 19.07
NR = len(RT)
from decimal import Decimal, ROUND_HALF_UP
def f1(v): return f"{v:,.1f}"
APPROX = set(map(tuple, D.get("approx", [])))
def r0(v): return f"{int(Decimal(str(round(v, 6))).quantize(Decimal('1'), ROUND_HALF_UP)):,}"
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
    xs = (0.60, 0.695, 0.79, 0.885)
    for x, r, c in zip(xs, RT, COL):
        fig.patches.append(plt.Rectangle((x, y - 0.012), 0.016, 0.026, transform=fig.transFigure, color=c, figure=fig))
        fig.text(x + 0.022, y, r, color=FG, fontsize=22, va="center", weight="bold" if r == "Caravan" else "normal")
def bars(ax, data, t, fmt, ymax, start=0.0, fs=18, approx=()):
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
                ax.text(x, v * p + ymax * 0.012, ("~" + r0(v) if (m, r) in approx and p >= 1 else fmt(v * p if p < 1 else v)), color=CARAVAN if r == 0 else FG, fontsize=fs, weight="bold", ha="center", va="bottom")
def scene(n, draw):
    for i in range(n):
        fig.clf(); fig.patch.set_facecolor(BG); draw(i / FPS); emit(fade(i, n))
def title(t):
    a = ease(t / 0.8)
    fig.text(0.5, 0.62, "Caravan vs LocalAI vs llama.cpp vs exo", color=FG, fontsize=72, weight="bold", ha="center", alpha=a)
    fig.text(0.5, 0.51, "Running AI models at home on a 24 GB Mac mini", color=FG, fontsize=50, ha="center", alpha=a)
    x0 = 0.5 - 0.20
    for k, c in enumerate(COL):
        fig.patches.append(plt.Rectangle((x0 + k * 0.10, 0.44), 0.10 * ease((t - 0.3 - 0.15 * k) / 0.8), 0.008 if k else 0.014, transform=fig.transFigure, color=c, figure=fig))
    fig.text(0.5, 0.35, "Same Mac, same three models, four ways to run them", color=CARAVAN, fontsize=30, ha="center", alpha=a)
    fig.text(0.5, 0.28, "Oct 30, 2026  ·  Qwen3 30B  ·  Gemma 4 26B  ·  GPT-OSS 20B", color=MUTED, fontsize=28, ha="center", alpha=a)
scene(4 * FPS, title)
def chart(titl, sub, data, fmt, ymax, foot, note=None):
    def d(t):
        header(titl, sub); legend()
        ax = fig.add_axes([0.07, 0.15, 0.88, 0.66]); bars(ax, data, t, fmt, ymax)
        if note:
            p = ease((t - 1.0) / 0.8)
            fig.text(0.95, 0.785, note, color=FG, fontsize=22, ha="right", alpha=p,
                     bbox=dict(boxstyle="round,pad=0.45", fc="#1b1f2a", ec=MUTED, lw=1.5, alpha=p))
        fig.text(0.05, 0.05, foot, color=MUTED, fontsize=19)
    return d
scene(8 * FPS, chart("Writing speed", "tokens per second while the model writes, higher is better", TG, lambda v: f"{v:.1f}", 58,
      "Middle result of 3 runs. exo uses a different model format (MLX), so its models are not byte-for-byte the same.",
      note="What's a token? About ¾ of a word."))
scene(7 * FPS, chart("Reading a long prompt", "a ~4,000-token prompt (about 3,000 words), tokens/s, higher is better", PP, f1, 500,
      "Middle result of 3 runs. Caravan and LocalAI both run llama.cpp underneath, with slightly different settings."))
def deep(t):
    header("Long chat (16,000 tokens of history)", "a new ~550-token message on a 16,000-token chat")
    legend()
    a1 = fig.add_axes([0.06, 0.2, 0.42, 0.58]); bars(a1, PP16, t, f1, 300, fs=12, approx=APPROX)
    a1.set_title("Reading speed, tokens/s", color=FG, fontsize=26, pad=14); a1.tick_params(axis="x", labelsize=18)
    a2 = fig.add_axes([0.55, 0.2, 0.42, 0.58]); bars(a2, TG16, t, lambda v: f"{v:.1f}", 38, start=0.4, fs=14)
    a2.set_title("Writing speed, tokens/s", color=FG, fontsize=26, pad=14); a2.tick_params(axis="x", labelsize=18)
    fig.text(0.05, 0.035, D["deep_foot"], color=MUTED, fontsize=18)
scene(9 * FPS, deep)
def mem(t):
    header("Memory used", "GB at the peak, lower is better. This Mac lets the GPU use about 19 GB"); legend()
    ax = fig.add_axes([0.07, 0.13, 0.88, 0.68]); bars(ax, MEM, t, lambda v: f"{v:.1f}", 24)
    p = ease((t - 1.8) / 0.8)
    if p > 0:
        ax.axhline(METAL, color=RED, lw=3, ls="--", xmax=p, zorder=1)
        ax.text(2.58, METAL + 0.35, "GPU memory limit ≈ 19 GB", color=RED, fontsize=22, weight="bold", ha="right", alpha=p)
    fig.text(0.05, 0.045, D["mem_foot"], color=MUTED, fontsize=18)
scene(7 * FPS, mem)
RL = ["First message (cold)", "Next message", "Caravan after restart", "LocalAI after restart"]
RC = ["#5b6475", "#7dd3fc", CARAVAN, LOCALAI]
def resume(t):
    header("Picking a chat back up after a restart", "wait before the first word, seconds, lower is better · 16,000-token chat")
    for k, (lab, c) in enumerate(zip(RL, RC)):
        x = (0.05, 0.25, 0.42, 0.62)[k]
        fig.patches.append(plt.Rectangle((x, 0.793), 0.016, 0.026, transform=fig.transFigure, color=c, figure=fig))
        fig.text(x + 0.022, 0.805, lab, color=FG, fontsize=22, va="center")
    ax = fig.add_axes([0.17, 0.22, 0.76, 0.54]); ax.set_facecolor(BG)
    for s in ax.spines.values(): s.set_visible(False)
    ax.tick_params(colors=FG, labelsize=24, length=0); ax.xaxis.set_tick_params(labelsize=18, labelcolor=MUTED)
    ax.grid(axis="x", color=GRID, lw=1); ax.set_axisbelow(True); ax.set_xlim(0, D["res_xmax"]); ax.set_ylim(2.65, -0.65)
    ax.set_yticks(range(3)); ax.set_yticklabels(MODELS)
    h = 0.21
    for m in range(3):
        vals = RES[m] + [LRES[m]]
        for k in range(4):
            v = vals[k]
            if v is None: continue
            y = m + (k - 1.5) * h
            p = ease((t - 0.3 - 0.35 * m - 0.12 * k) / 1.3)
            bad = (k == 2 and m > 0)
            ax.barh(y, v * p, h * 0.88, color=RED if bad else RC[k])
            if p > 0.02:
                val = v * p if p < 1 else v
                lbl = f"{val:.1f} s" if val >= 10 else f"{val:.2f} s"
                if bad and p >= 1: lbl += "   saved, but re-read from scratch"
                if k == 3 and p >= 1: lbl += "   re-reads the chat"
                ax.text(v * p + 0.8, y, lbl, color=(RED if bad else (CARAVAN if k == 2 else FG)), fontsize=19, weight="bold", va="center")
    p = ease((t - 2.6) / 0.8)
    if p > 0:
        ax.text(9, 0.105, D["res_callout"], color=CARAVAN, fontsize=24, weight="bold", va="center", alpha=p)
    p2 = ease((t - 4.5) / 0.8)
    if p2 > 0:
        fig.text(0.5, 0.125, D["res_box"], color=FG, fontsize=25, weight="bold", ha="center", alpha=p2,
                 bbox=dict(boxstyle="round,pad=0.5", fc="#1b1f2a", ec=CARAVAN, lw=2, alpha=p2))
    fig.text(0.05, 0.035, D["res_foot"], color=MUTED, fontsize=18)
scene(12 * FPS, resume)
def take(t):
    fig.text(0.07, 0.86, "Takeaways", color=FG, fontsize=56, weight="bold")
    for k, (ci, h, s) in enumerate(D["take"]):
        c = {"caravan": CARAVAN, "localai": LOCALAI, "llama": COL[2], "exo": COL[3], "red": RED}[ci]
        p = ease((t - 0.3 - 0.5 * k) / 0.7); y = 0.72 - 0.155 * k
        fig.patches.append(plt.Rectangle((0.07, y - 0.07), 0.008, 0.1, transform=fig.transFigure, color=c, alpha=p, figure=fig))
        fig.text(0.095 - 0.02 * (1 - p), y, h, color=FG, fontsize=34, weight="bold", alpha=p, va="center")
        fig.text(0.095 - 0.02 * (1 - p), y - 0.05, s, color=MUTED, fontsize=24, alpha=p, va="center")
    p = ease((t - 2.5) / 0.7)
    fig.text(0.07, 0.09, D["caveat"], color="#d6dbe4", fontsize=22, va="center", alpha=p, style="italic")
scene(9 * FPS, take)
proc.stdin.close(); proc.wait(); print("done", proc.returncode)
