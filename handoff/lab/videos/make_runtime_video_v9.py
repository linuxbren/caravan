# v9: Caravan v3 split + GPU keepalive (on) vs keepalive off, with one-Mini (v2.1) as reference.
# Usage: make_runtime_video_v9.py out.mp4 v9_data.json --day "Day 5" [--stills dir]
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
    sys.exit("give a day label: --day 'Day 5' or --day-of YYYY-MM-DD")
STILL_AT = set(D.get("_stills", []))
BG, FG, MUTED, GRID, RED, PANEL = "#0f1117", "#f2f4f8", "#9aa3b2", "#262b36", "#ff5c5c", "#1b1f2a"
ONE, OFF, ON = "#34D399", "#94A3B8", "#FACC15"
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
        fig.savefig(os.path.join(STILLS, f"v9_t{t:04.1f}.png"), facecolor=BG)
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
        bold = "keepalive on" in lab.lower() or lab.startswith("Caravan v3 +")
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
            hl = (c == ON)
            ax.bar(x, v * p, w * 0.9, color=c, alpha=0.55 if faint else 1,
                   edgecolor=FG if hl else "none", lw=1.5 if hl else 0)
            if p > 0.02:
                ax.text(x, v * p + ymax * 0.012, fmt(v * p if p < 1 else v),
                        color=ON if hl else (MUTED if faint else FG),
                        fontsize=fs, weight="bold", ha="center", va="bottom")

# 1. Title
def title(t):
    a = ease(t / 0.8)
    fig.text(0.5, 0.64, "Waking the GPUs between turns", color=FG, fontsize=68, weight="bold", ha="center", alpha=a)
    fig.text(0.5, 0.545, "Caravan v3 split + GPU keepalive", color=FG, fontsize=40, ha="center", alpha=a)
    x0 = 0.5 - 0.12
    for k, c in enumerate([ONE, OFF, ON]):
        fig.patches.append(plt.Rectangle((x0 + k * 0.08, 0.47), 0.08 * ease((t - 0.3 - 0.15 * k) / 0.8), 0.014,
                                         transform=fig.transFigure, color=c, figure=fig))
    fig.text(0.5, 0.38,
             "latest = keepalive on  ·  before = same split, keepalive off  ·  reference = one Mini",
             color=ON, fontsize=26, ha="center", alpha=a)
    fig.text(0.5, 0.30,
             f"{DAY} of building Caravan  ·  two 24 GB Mac minis  ·  Qwen3 30B  ·  Gemma 4 26B  ·  GPT-OSS 20B",
             color=MUTED, fontsize=26, ha="center", alpha=a)
scene(4 * FPS, title)

# 2. The problem
def problem(t):
    header("The GPUs were napping", "in the v3 split, Packer 1 and the lead take turns on each token")
    p0 = ease((t - 0.2) / 0.7)
    box(0.07, 0.48, 0.38, 0.28, OFF, p0)
    fig.text(0.26, 0.70, "Packer 1", color=OFF, fontsize=28, weight="bold", ha="center", alpha=p0)
    fig.text(0.26, 0.62, "runs the first half of the layers", color=FG, fontsize=22, ha="center", alpha=p0)
    fig.text(0.26, 0.55, "then waits ~15–20 ms", color=MUTED, fontsize=22, ha="center", alpha=p0)
    box(0.55, 0.48, 0.38, 0.28, ON, p0)
    fig.text(0.74, 0.70, "Lead", color=ON, fontsize=28, weight="bold", ha="center", alpha=p0)
    fig.text(0.74, 0.62, "runs the second half, picks the word", color=FG, fontsize=22, ha="center", alpha=p0)
    fig.text(0.74, 0.55, "then waits ~15–20 ms", color=MUTED, fontsize=22, ha="center", alpha=p0)
    p1 = ease((t - 1.4) / 0.7)
    if p1 > 0:
        fig.patches.append(plt.Rectangle((0.45, 0.605), 0.10 * p1, 0.012, transform=fig.transFigure, color=LLAMA, figure=fig))
        fig.text(0.50, 0.66, "Thunderbolt", color=LLAMA, fontsize=20, ha="center", weight="bold", alpha=p1)
    p2 = ease((t - 2.2) / 0.8)
    if p2 > 0:
        fig.text(0.5, 0.28,
                 f"After that idle, Metal costs about {D['COOLDOWN_MS']} ms extra to wake up for the next half.\n"
                 "That cool-down was most of the leftover “split tax” on writing speed.",
                 color=FG, fontsize=26, weight="bold", ha="center", va="center", alpha=p2, linespacing=1.4,
                 bbox=dict(boxstyle="round,pad=0.55", fc=PANEL, ec=ON, lw=2, alpha=p2))
    fig.text(0.05, 0.04, "The Mini you talk to is the lead; Packer 1 runs the first layers. Together they're a string.",
             color=MUTED, fontsize=18)
scene(8 * FPS, problem)

# 3. The fix
def fix(t):
    header("The fix: keep Metal warm while you wait", "a short-lived side thread runs a tiny GPU eval during the peer wait, then stops")
    rows = [
        ("Before each wait", "start a tiny keep-awake on the GPU"),
        ("While the peer works", "Metal stays warm instead of cooling down"),
        ("Before your own layers", "stop the keep-awake, then run the real work"),
    ]
    for k, (h, d) in enumerate(rows):
        p = ease((t - 0.3 - 0.55 * k) / 0.6); y = 0.68 - 0.12 * k
        fig.text(0.10, y, f"{k + 1}.", color=ON, fontsize=32, weight="bold", va="center", alpha=p)
        fig.text(0.18, y + 0.025, h, color=FG, fontsize=30, weight="bold", va="center", alpha=p)
        fig.text(0.18, y - 0.035, d, color=MUTED, fontsize=24, va="center", alpha=p)
    p = ease((t - 2.4) / 0.7)
    if p > 0:
        fig.text(0.5, 0.22,
                 "On by default. Turn it off with a flag or an env var if you want the old behavior.",
                 color=FG, fontsize=24, weight="bold", ha="center", va="center", alpha=p,
                 bbox=dict(boxstyle="round,pad=0.5", fc=PANEL, ec=ONE, lw=2, alpha=p))
    fig.text(0.05, 0.04, "A long-lived keep-awake thread was tried and rejected: writing got slower. Spawn-per-wait is what shipped.",
             color=MUTED, fontsize=18)
scene(7 * FPS, fix)

# 4. Writing speed
def writing(t):
    header("Writing speed", "tokens per second (a token is about ¾ of a word) · higher is better · medians of 2")
    legend([("One Mini (v2.1)", ONE), ("v3 split, keepalive off", OFF), ("v3 split + keepalive on", ON)],
           xs=(0.05, 0.28, 0.55))
    ax = fig.add_axes([0.08, 0.18, 0.84, 0.55])
    vbars(ax, [(D["TG"]["one"], ONE, False), (D["TG"]["off"], OFF, False), (D["TG"]["on"], ON, False)],
          t, tps, 58, fs=17)
    p = ease((t - 2.8) / 0.7)
    if p > 0:
        g = D["GAIN_PCT"]
        fig.text(0.5, 0.08,
                 f"Keepalive on vs off: Qwen3 {D['TG']['off'][0]:.1f} → {D['TG']['on'][0]:.1f} (+{g[0]}%),  "
                 f"Gemma 4 {D['TG']['off'][1]:.1f} → {D['TG']['on'][1]:.1f} (+{g[1]}%),  "
                 f"GPT-OSS {D['TG']['off'][2]:.1f} → {D['TG']['on'][2]:.1f} (+{g[2]}%).\n"
                 f"Now within about 7–11% of one Mini, while still using half the memory per Mini.",
                 color=FG, fontsize=20, weight="bold", ha="center", va="center", alpha=p, linespacing=1.35,
                 bbox=dict(boxstyle="round,pad=0.45", fc=PANEL, ec=ON, lw=2, alpha=p))
scene(9 * FPS, writing)

# 5. Reading speed
def reading(t):
    header("Reading speed", "tokens per second · higher is better · no regression with keepalive on")
    legend([("One Mini (v2.1)", ONE), ("v3 split, keepalive off", OFF), ("v3 split + keepalive on", ON)],
           xs=(0.05, 0.28, 0.55))
    for j, (key, ttl, ymax, fmt) in enumerate((
            ("PP512", "Reading a ~512-token prompt", 520, lambda v: f"{v:.0f}"),
            ("PP4K", "Reading a ~4,000-token prompt", 520, lambda v: f"{v:.0f}"))):
        ax = fig.add_axes([0.06 + 0.48 * j, 0.18, 0.42, 0.52])
        vbars(ax, [(D[key]["one"], ONE, False), (D[key]["off"], OFF, False), (D[key]["on"], ON, False)],
              t - 0.35 * j, fmt, ymax, fs=15)
        ax.set_title(ttl, color=FG, fontsize=24, pad=12)
    fig.text(0.05, 0.04,
             "Reading stayed flat or rose a little with keepalive on. Peak memory per Mini unchanged. Quality: 3 of 3 test questions right on every run.",
             color=MUTED, fontsize=18)
scene(9 * FPS, reading)

# 6. Wait before the first word
def wait(t):
    header("Wait before the first word", "seconds on a short writing run · lower is better · keepalive on vs off")
    legend([("v3 split, keepalive off", OFF), ("v3 split + keepalive on", ON)], xs=(0.05, 0.35))
    ax = fig.add_axes([0.12, 0.22, 0.76, 0.52])
    vbars(ax, [(D["TTFT"]["off"], OFF, False), (D["TTFT"]["on"], ON, False)],
          t, secs, 0.55, fs=18, labels=MODELS)
    p = ease((t - 2.2) / 0.7)
    if p > 0:
        fig.text(0.5, 0.10,
                 "Slightly quicker to the first word as well — the first half no longer pays the cool-down.",
                 color=FG, fontsize=24, weight="bold", ha="center", va="center", alpha=p,
                 bbox=dict(boxstyle="round,pad=0.45", fc=PANEL, ec=ON, lw=2, alpha=p))
scene(7 * FPS, wait)

# 7. Takeaways
def take(t):
    fig.text(0.07, 0.88, "Takeaways", color=FG, fontsize=56, weight="bold")
    for k, (c, h, s) in enumerate(D["TAKE"]):
        c = {"ON": ON, "ONE": ONE, "OFF": OFF, "MUTED": MUTED, "RED": RED}[c]
        p = ease((t - 0.3 - 0.5 * k) / 0.7); y = 0.74 - 0.155 * k
        fig.patches.append(plt.Rectangle((0.07, y - 0.07), 0.008, 0.1, transform=fig.transFigure, color=c, alpha=p, figure=fig))
        fig.text(0.095 - 0.02 * (1 - p), y, h, color=FG, fontsize=32, weight="bold", alpha=p, va="center")
        fig.text(0.095 - 0.02 * (1 - p), y - 0.05, s, color=MUTED, fontsize=22, alpha=p, va="center")
    p = ease((t - 2.5) / 0.7)
    fig.text(0.07, 0.08,
             "Caveats: medians of 2 runs, one evening, Low Power Mode off on both Minis.\n"
             "One Mini numbers are Caravan v2.1 on the same hardware. Keepalive is on by default in the split.",
             color="#d6dbe4", fontsize=20, va="center", alpha=p, style="italic")
scene(9 * FPS, take)

proc.stdin.close(); proc.wait()
print("done", proc.returncode, FRAME[0] / FPS, "s")
