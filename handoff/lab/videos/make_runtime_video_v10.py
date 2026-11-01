# v10: Caravan v3 idea 1 — several chats at once (pipeline overlap).
# Usage: make_runtime_video_v10.py out.mp4 v10_data.json --day "Day 6" [--stills dir]
import subprocess, sys, os, json, matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib import font_manager as fm
_FD = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fonts")
for _f in ("InterLab-Regular.ttf", "InterLab-Bold.ttf"):
    fm.fontManager.addfont(os.path.join(_FD, _f))
plt.rcParams["font.family"] = "InterLab"
W, H, FPS = 1920, 1080, 30
OUT = sys.argv[1]; D = json.load(open(sys.argv[2]))
STILLS = sys.argv[sys.argv.index("--stills") + 1] if "--stills" in sys.argv else None
import datetime as _dt
DAY1 = _dt.date(2026, 10, 30)
def day_label(date_str):
    return f"Day {(_dt.date.fromisoformat(date_str) - DAY1).days + 1}"
if "--day" in sys.argv:
    DAY = sys.argv[sys.argv.index("--day") + 1]
elif "--day-of" in sys.argv:
    DAY = day_label(sys.argv[sys.argv.index("--day-of") + 1])
elif D.get("_day"):
    DAY = D["_day"]
else:
    sys.exit("give a day label: --day 'Day 6' or --day-of YYYY-MM-DD")
STILL_AT = set(D.get("_stills", []))
BG, FG, MUTED, GRID, RED, PANEL = "#0f1117", "#f2f4f8", "#9aa3b2", "#262b36", "#ff5c5c", "#1b1f2a"
N1, N2, N3 = "#94A3B8", "#FACC15", "#34D399"
BEFORE, AFTER = "#F87171", "#34D399"
LLAMA = "#4FC3F7"
MODELS = ["Qwen3 30B", "Gemma 4 26B", "GPT-OSS 20B"]
SHORT = ["Qwen3", "Gemma 4", "GPT-OSS"]
def ease(t):
    t = min(max(t, 0), 1); return 1 - (1 - t) ** 3
fig = plt.figure(figsize=(W / 100, H / 100), dpi=100, facecolor=BG)
proc = subprocess.Popen(
    ["ffmpeg", "-y", "-loglevel", "error", "-f", "rawvideo", "-pix_fmt", "rgba",
     "-s", f"{W}x{H}", "-r", str(FPS), "-i", "-",
     "-c:v", "libx264", "-preset", "medium", "-crf", "18", "-pix_fmt", "yuv420p",
     "-r", str(FPS), "-movflags", "+faststart", OUT],
    stdin=subprocess.PIPE)
FRAME = [0]
def emit(alpha):
    if alpha < 1:
        fig.add_artist(plt.Rectangle((0, 0), 1, 1, transform=fig.transFigure, color=BG, alpha=1 - alpha, zorder=100))
    fig.canvas.draw(); proc.stdin.write(bytes(fig.canvas.buffer_rgba()))
    t = FRAME[0] / FPS
    if STILLS and any(abs(t - s) < 0.5 / FPS for s in STILL_AT):
        fig.savefig(os.path.join(STILLS, f"v10_t{t:04.1f}.png"), facecolor=BG)
    FRAME[0] += 1
def fade(i, n, f=12):
    return min(1, (i + 1) / f, (n - i) / f)
def scene(n, draw):
    for i in range(n):
        fig.clf(); fig.patch.set_facecolor(BG); draw(i / FPS); emit(fade(i, n))
def header(title, sub):
    fig.text(0.05, 0.925, title, color=FG, fontsize=44, weight="bold", va="center")
    fig.text(0.05, 0.87, sub, color=MUTED, fontsize=24, va="center")
def legend(items, y=0.815, xs=None):
    x = 0.05
    for k, (lab, c) in enumerate(items):
        if xs: x = xs[k]
        fig.patches.append(plt.Rectangle((x, y - 0.012), 0.016, 0.026, transform=fig.transFigure, color=c, figure=fig))
        bold = "2 chats" in lab.lower() or "after" in lab.lower()
        fig.text(x + 0.022, y, lab, color=FG, fontsize=20, va="center", weight="bold" if bold else "normal")
        if not xs: x += 0.035 + 0.0105 * len(lab)
from decimal import Decimal, ROUND_HALF_UP
def rh(v, nd):
    return str(Decimal(str(round(v, 6))).quantize(Decimal(1).scaleb(-nd), ROUND_HALF_UP))
def tps(v): return f"{v:.1f}"
def secs(v): return f"{rh(v, 2)} s" if v < 10 else f"{rh(v, 1)} s"
def box(x, y, w, h, ec, a, fc=PANEL, lw=2.5):
    fig.patches.append(plt.Rectangle((x, y), w, h, transform=fig.transFigure, fc=fc, ec=ec, lw=lw, alpha=a, figure=fig))
def vbars(ax, series, t, fmt, ymax, start=0.0, fs=16, labels=SHORT):
    ax.set_facecolor(BG); n = len(series); w = 0.8 / n
    for s in ax.spines.values(): s.set_visible(False)
    ax.tick_params(colors=FG, labelsize=22, length=0); ax.yaxis.set_tick_params(labelsize=17, labelcolor=MUTED)
    ax.grid(axis="y", color=GRID, lw=1); ax.set_axisbelow(True)
    ax.set_xticks(range(3)); ax.set_xticklabels(labels); ax.set_ylim(0, ymax); ax.set_xlim(-0.55, 2.55)
    for m in range(3):
        for r, (vals, c, faint) in enumerate(series):
            v = vals[m]; x = m + (r - (n - 1) / 2) * w
            if v is None: continue
            p = ease((t - start - 0.25 * m - 0.07 * r) / 1.4)
            hl = (c == N2) or (c == AFTER)
            ax.bar(x, v * p, w * 0.9, color=c, alpha=0.55 if faint else 1,
                   edgecolor=FG if hl else "none", lw=1.5 if hl else 0)
            if p > 0.02:
                ax.text(x, v * p + ymax * 0.012, fmt(v * p if p < 1 else v),
                        color=N2 if hl else (MUTED if faint else FG),
                        fontsize=fs, weight="bold", ha="center", va="bottom")

# 1. Title (~4s)
def title(t):
    a = ease(t / 0.8)
    fig.text(0.5, 0.64, "Several chats at once", color=FG, fontsize=68, weight="bold", ha="center", alpha=a)
    fig.text(0.5, 0.545, "Caravan v3 · overlap Packer 1 and the lead across chats", color=FG, fontsize=36, ha="center", alpha=a)
    x0 = 0.5 - 0.12
    for k, c in enumerate([N1, N2, N3]):
        fig.patches.append(plt.Rectangle((x0 + k * 0.08, 0.47), 0.08 * ease((t - 0.3 - 0.15 * k) / 0.8), 0.014,
                                         transform=fig.transFigure, color=c, figure=fig))
    fig.text(0.5, 0.38,
             "latest = 2 chats  ·  before = 1 chat  ·  also = 3 chats (fair schedule)",
             color=N2, fontsize=26, ha="center", alpha=a)
    fig.text(0.5, 0.30,
             f"{DAY} of building Caravan  ·  two 24 GB Mac minis  ·  Qwen3 30B  ·  Gemma 4 26B  ·  GPT-OSS 20B",
             color=MUTED, fontsize=26, ha="center", alpha=a)
scene(4 * FPS, title)

# 2. Problem (~7s)
def problem(t):
    header("One chat still takes turns", "Packer 1 and the lead each sit idle about half the time")
    p0 = ease((t - 0.2) / 0.7)
    box(0.07, 0.48, 0.38, 0.28, N1, p0)
    fig.text(0.26, 0.70, "Packer 1", color=N1, fontsize=28, weight="bold", ha="center", alpha=p0)
    fig.text(0.26, 0.62, "first half of the layers", color=FG, fontsize=22, ha="center", alpha=p0)
    fig.text(0.26, 0.55, "then waits on the lead", color=MUTED, fontsize=22, ha="center", alpha=p0)
    box(0.55, 0.48, 0.38, 0.28, N2, p0)
    fig.text(0.74, 0.70, "Lead", color=N2, fontsize=28, weight="bold", ha="center", alpha=p0)
    fig.text(0.74, 0.62, "second half, picks the word", color=FG, fontsize=22, ha="center", alpha=p0)
    fig.text(0.74, 0.55, "then waits on Packer 1", color=MUTED, fontsize=22, ha="center", alpha=p0)
    p1 = ease((t - 1.4) / 0.7)
    if p1 > 0:
        fig.patches.append(plt.Rectangle((0.45, 0.605), 0.10 * p1, 0.012, transform=fig.transFigure, color=LLAMA, figure=fig))
        fig.text(0.50, 0.66, "Thunderbolt", color=LLAMA, fontsize=20, ha="center", weight="bold", alpha=p1)
    p2 = ease((t - 2.2) / 0.8)
    if p2 > 0:
        fig.text(0.5, 0.28,
                 "A single chat is no faster. To raise total tokens/s, keep both Minis busy\n"
                 "by overlapping chat B's Packer 1 work with chat A's lead work.",
                 color=FG, fontsize=26, weight="bold", ha="center", va="center", alpha=p2, linespacing=1.4,
                 bbox=dict(boxstyle="round,pad=0.55", fc=PANEL, ec=N2, lw=2, alpha=p2))
    fig.text(0.05, 0.04, "Off by default (--split-pipeline-chats N). Flag off keeps the old single-chat path.",
             color=MUTED, fontsize=18)
scene(7 * FPS, problem)

# 3. How (~7s)
def how(t):
    header("How the overlap works", "same string, two (or three) chats in flight")
    rows = [
        ("Chat A on the lead", "Packer 1 already starts chat B's next half"),
        ("They swap", "Packer 1 does A while the lead does B"),
        ("Both Minis stay busy", "total writing across chats rises; each chat shares the halves"),
    ]
    for k, (h, d) in enumerate(rows):
        p = ease((t - 0.3 - 0.55 * k) / 0.6); y = 0.68 - 0.12 * k
        fig.text(0.10, y, f"{k + 1}.", color=N2, fontsize=32, weight="bold", va="center", alpha=p)
        fig.text(0.18, y + 0.025, h, color=FG, fontsize=30, weight="bold", va="center", alpha=p)
        fig.text(0.18, y - 0.035, d, color=MUTED, fontsize=24, va="center", alpha=p)
    p = ease((t - 2.4) / 0.7)
    if p > 0:
        fig.text(0.5, 0.22,
                 "Idea-5 balanced cuts + keepalive on. Measured on test ports, Low Power Mode off.",
                 color=FG, fontsize=24, weight="bold", ha="center", va="center", alpha=p,
                 bbox=dict(boxstyle="round,pad=0.5", fc=PANEL, ec=N3, lw=2, alpha=p))
    fig.text(0.05, 0.04, "Proxy FIFO still serializes when the proxy is in the path; these benches hit the lead directly.",
             color=MUTED, fontsize=18)
scene(7 * FPS, how)

# 4. Wall aggregate writing (~9s)
def writing(t):
    header("Writing across chats", "wall aggregate tok/s · higher is better · medians of 2 · tg128")
    legend([("1 chat", N1), ("2 chats", N2), ("3 chats", N3)], xs=(0.05, 0.22, 0.40))
    ax = fig.add_axes([0.08, 0.18, 0.84, 0.55])
    vbars(ax, [(D["WALL"]["n1"], N1, False), (D["WALL"]["n2"], N2, False), (D["WALL"]["n3"], N3, False)],
          t, tps, 90, fs=16)
    p = ease((t - 2.8) / 0.7)
    if p > 0:
        fig.text(0.5, 0.08,
                 f"Two chats ≈1.6× one: Qwen3 {D['WALL']['n1'][0]:.1f}→{D['WALL']['n2'][0]:.1f},  "
                 f"Gemma 4 {D['WALL']['n1'][1]:.1f}→{D['WALL']['n2'][1]:.1f},  "
                 f"GPT-OSS {D['WALL']['n1'][2]:.1f}→{D['WALL']['n2'][2]:.1f}.\n"
                 f"Three chats ≈ two on wall time (two-stage pipeline); per-chat rate falls as they share.",
                 color=FG, fontsize=20, weight="bold", ha="center", va="center", alpha=p, linespacing=1.35,
                 bbox=dict(boxstyle="round,pad=0.45", fc=PANEL, ec=N2, lw=2, alpha=p))
scene(9 * FPS, writing)

# 5. TTFT fix (~8s)
def ttft(t):
    header("Three-chat wait for the first word", "seconds · lower is better · max TTFT before vs after the fair-schedule fix")
    legend([("Before (starved chat)", BEFORE), ("After (fair n_gen, t0)", AFTER)], xs=(0.05, 0.38))
    ax = fig.add_axes([0.12, 0.22, 0.76, 0.52])
    vbars(ax, [(D["TTFT_N3"]["before"], BEFORE, False), (D["TTFT_N3"]["after"], AFTER, False)],
          t, secs, 5.5, fs=18, labels=MODELS)
    p = ease((t - 2.2) / 0.7)
    if p > 0:
        fig.text(0.5, 0.10,
                 f"Was {D['TTFT_N3']['before'][1]:.2f} / {D['TTFT_N3']['before'][2]:.2f} / {D['TTFT_N3']['before'][0]:.2f} s "
                 f"(Gemma / GPT-OSS / Qwen3). Now ≤0.62 s. Wall aggregate recovered to ≈ two chats.",
                 color=FG, fontsize=22, weight="bold", ha="center", va="center", alpha=p,
                 bbox=dict(boxstyle="round,pad=0.45", fc=PANEL, ec=AFTER, lw=2, alpha=p))
scene(8 * FPS, ttft)

# 6. Quality + memory (~7s)
def quality(t):
    header("Quality and memory", "same three test questions · peak GB on the lead during N=3")
    p0 = ease((t - 0.2) / 0.7)
    box(0.08, 0.48, 0.38, 0.28, N3, p0)
    fig.text(0.27, 0.70, "Quality", color=N3, fontsize=28, weight="bold", ha="center", alpha=p0)
    fig.text(0.27, 0.60, D["QUALITY"], color=FG, fontsize=56, weight="bold", ha="center", alpha=p0)
    fig.text(0.27, 0.52, "on every model, every run", color=MUTED, fontsize=22, ha="center", alpha=p0)
    p1 = ease((t - 0.8) / 0.7)
    box(0.54, 0.42, 0.38, 0.34, N2, p1)
    fig.text(0.73, 0.70, "Peak GB (N=3)", color=N2, fontsize=26, weight="bold", ha="center", alpha=p1)
    for k, (lab, v) in enumerate(zip(SHORT, D["PEAK_N3"])):
        y = 0.62 - 0.07 * k
        fig.text(0.58, y, lab, color=MUTED, fontsize=22, va="center", alpha=p1)
        fig.text(0.88, y, f"{v:.2f}", color=FG, fontsize=24, weight="bold", ha="right", va="center", alpha=p1)
    p2 = ease((t - 2.0) / 0.7)
    if p2 > 0:
        fig.text(0.5, 0.22,
                 "Flag off single-chat writing still matches the keepalive baseline (~38 / 34 / 46 tok/s).",
                 color=FG, fontsize=24, weight="bold", ha="center", va="center", alpha=p2,
                 bbox=dict(boxstyle="round,pad=0.5", fc=PANEL, ec=N1, lw=2, alpha=p2))
    fig.text(0.05, 0.04, "Memory is for the lead Mini during the pipeline wave; packer holds the other half of the weights.",
             color=MUTED, fontsize=18)
scene(7 * FPS, quality)

# 7. Takeaways (~9s)
def take(t):
    fig.text(0.07, 0.88, "Takeaways", color=FG, fontsize=56, weight="bold")
    for k, (c, h, s) in enumerate(D["TAKE"]):
        c = {"ON": N2, "ONE": N3, "OFF": N1, "MUTED": MUTED, "RED": RED, "N2": N2, "N3": N3}[c]
        p = ease((t - 0.3 - 0.5 * k) / 0.7); y = 0.74 - 0.155 * k
        fig.patches.append(plt.Rectangle((0.07, y - 0.07), 0.008, 0.1, transform=fig.transFigure, color=c, alpha=p, figure=fig))
        fig.text(0.095 - 0.02 * (1 - p), y, h, color=FG, fontsize=30, weight="bold", alpha=p, va="center")
        fig.text(0.095 - 0.02 * (1 - p), y - 0.05, s, color=MUTED, fontsize=20, alpha=p, va="center")
    p = ease((t - 2.5) / 0.7)
    fig.text(0.07, 0.08,
             "Caveats: medians of ≥2 runs, Low Power Mode off, keepalive on, idea-5 cuts, test ports only.\n"
             "One chat is not faster — this raises total tokens/s across chats. Next up: guess ahead.",
             color="#d6dbe4", fontsize=20, va="center", alpha=p, style="italic")
scene(9 * FPS, take)

proc.stdin.close(); proc.wait()
print("done", proc.returncode, FRAME[0] / FPS, "s")
