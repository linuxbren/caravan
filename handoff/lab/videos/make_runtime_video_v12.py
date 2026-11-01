# v12: Day 6 several chats — techie-friend audience (confident show-your-work).
# Usage: make_runtime_video_v12.py out.mp4 v12_data.json --day "Day 6" [--stills dir]
# Numbers rounded from measured medians; sources in BENCHMARKS / prior v10–v11 data.
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
ONE, TWO, THREE = "#94A3B8", "#FACC15", "#34D399"
BEFORE, AFTER = "#F87171", "#34D399"
CABLE = "#4FC3F7"
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
        fig.savefig(os.path.join(STILLS, f"v12_t{t:04.1f}.png"), facecolor=BG)
    FRAME[0] += 1
def fade(i, n, f=12):
    return min(1, (i + 1) / f, (n - i) / f)
def scene(n, draw):
    for i in range(n):
        fig.clf(); fig.patch.set_facecolor(BG); draw(i / FPS); emit(fade(i, n))
def header(title, sub):
    fig.text(0.05, 0.925, title, color=FG, fontsize=42, weight="bold", va="center")
    fig.text(0.05, 0.865, sub, color=MUTED, fontsize=26, va="center")
def legend(items, y=0.805, xs=None):
    x = 0.05
    for k, (lab, c) in enumerate(items):
        if xs: x = xs[k]
        fig.patches.append(plt.Rectangle((x, y - 0.012), 0.016, 0.026, transform=fig.transFigure, color=c, figure=fig))
        bold = "2 chats" in lab.lower() or "after" in lab.lower()
        fig.text(x + 0.022, y, lab, color=FG, fontsize=22, va="center", weight="bold" if bold else "normal")
        if not xs: x += 0.038 + 0.011 * len(lab)
def box(x, y, w, h, ec, a, fc=PANEL, lw=2.5):
    fig.patches.append(plt.Rectangle((x, y), w, h, transform=fig.transFigure, fc=fc, ec=ec, lw=lw, alpha=a, figure=fig))
def vbars(ax, series, t, fmt, ymax, start=0.0, fs=18, labels=SHORT, hl=None):
    ax.set_facecolor(BG); n = len(series); w = 0.8 / n
    for s in ax.spines.values(): s.set_visible(False)
    ax.tick_params(colors=FG, labelsize=24, length=0); ax.yaxis.set_tick_params(labelsize=18, labelcolor=MUTED)
    ax.grid(axis="y", color=GRID, lw=1); ax.set_axisbelow(True)
    ax.set_xticks(range(3)); ax.set_xticklabels(labels); ax.set_ylim(0, ymax); ax.set_xlim(-0.55, 2.55)
    for m in range(3):
        for r, (vals, c, faint) in enumerate(series):
            v = vals[m]; x = m + (r - (n - 1) / 2) * w
            if v is None: continue
            p = ease((t - start - 0.25 * m - 0.07 * r) / 1.4)
            highlight = (hl is None and c == TWO) or (hl is not None and c == hl)
            ax.bar(x, v * p, w * 0.9, color=c, alpha=0.55 if faint else 1,
                   edgecolor=FG if highlight else "none", lw=1.5 if highlight else 0)
            if p > 0.02:
                ax.text(x, v * p + ymax * 0.012, fmt(v * p if p < 1 else v),
                        color=TWO if highlight else (MUTED if faint else FG),
                        fontsize=fs, weight="bold", ha="center", va="bottom")

# Title ~5s
def title(t):
    a = ease(t / 0.8)
    fig.text(0.5, 0.66, "Several chats at once", color=FG, fontsize=68, weight="bold", ha="center", alpha=a)
    fig.text(0.5, 0.55, "Two Mac minis share one model", color=FG, fontsize=40, ha="center", alpha=a)
    x0 = 0.5 - 0.12
    for k, c in enumerate([ONE, TWO, THREE]):
        fig.patches.append(plt.Rectangle((x0 + k * 0.08, 0.47), 0.08 * ease((t - 0.3 - 0.15 * k) / 0.8), 0.014,
                                         transform=fig.transFigure, color=c, figure=fig))
    fig.text(0.5, 0.36,
             "Overlap work across chats so both GPUs stay busy",
             color=TWO, fontsize=28, ha="center", alpha=a)
    fig.text(0.5, 0.27,
             f"{DAY} of building Caravan  ·  Qwen3 · Gemma 4 · GPT-OSS",
             color=MUTED, fontsize=26, ha="center", alpha=a)
scene(5 * FPS, title)

# Split ~10s
def split_how(t):
    header("Layer split across two Minis", "each machine holds about half the model's layers")
    p0 = ease((t - 0.2) / 0.8)
    box(0.07, 0.42, 0.38, 0.34, ONE, p0)
    fig.text(0.26, 0.70, "Other Mini", color=ONE, fontsize=30, weight="bold", ha="center", alpha=p0)
    fig.text(0.26, 0.62, "top half of the layers", color=FG, fontsize=26, ha="center", alpha=p0)
    fig.text(0.26, 0.54, "runs first, sends hidden", color=MUTED, fontsize=24, ha="center", alpha=p0)
    fig.text(0.26, 0.47, "state over Thunderbolt", color=MUTED, fontsize=24, ha="center", alpha=p0)
    box(0.55, 0.42, 0.38, 0.34, TWO, p0)
    fig.text(0.74, 0.70, "Mini you talk to", color=TWO, fontsize=30, weight="bold", ha="center", alpha=p0)
    fig.text(0.74, 0.62, "bottom half of the layers", color=FG, fontsize=26, ha="center", alpha=p0)
    fig.text(0.74, 0.54, "finishes the step and", color=MUTED, fontsize=24, ha="center", alpha=p0)
    fig.text(0.74, 0.47, "samples the next token", color=MUTED, fontsize=24, ha="center", alpha=p0)
    p1 = ease((t - 1.6) / 0.7)
    if p1 > 0:
        fig.patches.append(plt.Rectangle((0.45, 0.575), 0.10 * p1, 0.014, transform=fig.transFigure, color=CABLE, figure=fig))
        fig.text(0.50, 0.64, "Thunderbolt", color=CABLE, fontsize=22, ha="center", weight="bold", alpha=p1)
    p2 = ease((t - 2.6) / 0.8)
    if p2 > 0:
        fig.text(0.5, 0.24,
                 "Every decode step: top half → cable → bottom half → next token.\n"
                 "One chat, two GPUs taking turns on the same reply.",
                 color=FG, fontsize=28, weight="bold", ha="center", va="center", alpha=p2, linespacing=1.45,
                 bbox=dict(boxstyle="round,pad=0.55", fc=PANEL, ec=TWO, lw=2, alpha=p2))
    fig.text(0.05, 0.04, "Memory per Mini is about half; quality matches running the whole model on one machine.",
             color=MUTED, fontsize=20)
scene(10 * FPS, split_how)

# Idle ~9s
def idle(t):
    header("One chat serializes the halves", "while one Mini computes, the other waits on the cable")
    rows = [
        ("1.", "Top half runs", "then blocks until the bottom half finishes"),
        ("2.", "Bottom half runs", "then blocks until the top half is ready again"),
        ("3.", "Net effect", "each Mini is idle roughly half of every step"),
    ]
    for k, (num, h, d) in enumerate(rows):
        p = ease((t - 0.25 - 0.55 * k) / 0.65); y = 0.70 - 0.13 * k
        fig.text(0.10, y, num, color=TWO, fontsize=36, weight="bold", va="center", alpha=p)
        fig.text(0.18, y + 0.028, h, color=FG, fontsize=32, weight="bold", va="center", alpha=p)
        fig.text(0.18, y - 0.038, d, color=MUTED, fontsize=26, va="center", alpha=p)
    p = ease((t - 2.4) / 0.7)
    if p > 0:
        fig.text(0.5, 0.22,
                 "Fine for a single user. Leaves throughput on the table when several chats want tokens.",
                 color=FG, fontsize=26, weight="bold", ha="center", va="center", alpha=p,
                 bbox=dict(boxstyle="round,pad=0.5", fc=PANEL, ec=ONE, lw=2, alpha=p))
    fig.text(0.05, 0.04, "Caveat for later: overlapping chats raises total tokens/sec — not the speed of one lone chat.",
             color=MUTED, fontsize=20)
scene(9 * FPS, idle)

# Two chats ~9s
def two_chats(t):
    header("Pipeline two chats across the string", "chat B's top half runs while chat A is on the bottom half")
    p0 = ease((t - 0.2) / 0.7)
    box(0.08, 0.48, 0.38, 0.28, TWO, p0)
    fig.text(0.27, 0.70, "Chat A", color=TWO, fontsize=32, weight="bold", ha="center", alpha=p0)
    fig.text(0.27, 0.60, "on the Mini you talk to", color=FG, fontsize=24, ha="center", alpha=p0)
    fig.text(0.27, 0.52, "(bottom half)", color=MUTED, fontsize=22, ha="center", alpha=p0)
    box(0.54, 0.48, 0.38, 0.28, THREE, p0)
    fig.text(0.73, 0.70, "Chat B", color=THREE, fontsize=32, weight="bold", ha="center", alpha=p0)
    fig.text(0.73, 0.60, "on the other Mini", color=FG, fontsize=24, ha="center", alpha=p0)
    fig.text(0.73, 0.52, "(top half)", color=MUTED, fontsize=22, ha="center", alpha=p0)
    p1 = ease((t - 1.5) / 0.7)
    if p1 > 0:
        fig.text(0.5, 0.36, "They swap each step. Both GPUs stay fed.", color=FG, fontsize=30, weight="bold",
                 ha="center", alpha=p1)
    p2 = ease((t - 2.5) / 0.7)
    if p2 > 0:
        fig.text(0.5, 0.22,
                 "Total writing speed across chats rises ~1.6×.\n"
                 "Per-chat rate falls a bit — two replies share the same two halves.",
                 color=FG, fontsize=26, weight="bold", ha="center", va="center", alpha=p2, linespacing=1.4,
                 bbox=dict(boxstyle="round,pad=0.5", fc=PANEL, ec=TWO, lw=2, alpha=p2))
    fig.text(0.05, 0.04, "Off by default; flag turns on the overlapped schedule. Single-chat path unchanged when off.",
             color=MUTED, fontsize=20)
scene(9 * FPS, two_chats)

# Chart ~10s
def writing(t):
    header("Writing speed across chats", "tokens/sec (how fast it writes) · total over the wave · higher is better")
    legend([("1 chat", ONE), ("2 chats", TWO), ("3 chats", THREE)], xs=(0.05, 0.22, 0.42))
    ax = fig.add_axes([0.08, 0.20, 0.84, 0.52])
    vbars(ax, [(D["WRITE"]["one"], ONE, False), (D["WRITE"]["two"], TWO, False), (D["WRITE"]["three"], THREE, False)],
          t, lambda v: f"{v:.0f}", 95, fs=18)
    p = ease((t - 2.8) / 0.7)
    if p > 0:
        fig.text(0.5, 0.08,
                 f"Two chats: Qwen3 {D['WRITE']['one'][0]}→{D['WRITE']['two'][0]},  "
                 f"Gemma 4 {D['WRITE']['one'][1]}→{D['WRITE']['two'][1]},  "
                 f"GPT-OSS {D['WRITE']['one'][2]}→{D['WRITE']['two'][2]}.\n"
                 "Three chats ≈ two on wall speed — only two GPUs to keep busy.",
                 color=FG, fontsize=22, weight="bold", ha="center", va="center", alpha=p, linespacing=1.35,
                 bbox=dict(boxstyle="round,pad=0.45", fc=PANEL, ec=TWO, lw=2, alpha=p))
scene(10 * FPS, writing)

# Wait ~10s
def wait_fix(t):
    header("Wait before the first word (3 chats)", "seconds · lower is better · third chat was starved for turns")
    legend([("Before fair schedule", BEFORE), ("After", AFTER)], xs=(0.05, 0.38))
    ax = fig.add_axes([0.12, 0.24, 0.76, 0.48])
    vbars(ax, [(D["WAIT_THREE"]["before"], BEFORE, False), (D["WAIT_THREE"]["after"], AFTER, False)],
          t, lambda v: f"{v:.1f} s", 5.5, fs=20, labels=MODELS, hl=AFTER)
    p = ease((t - 2.4) / 0.7)
    if p > 0:
        fig.text(0.5, 0.10,
                 "Scheduler kept feeding the chats that already had work; the new one waited ~4 s.\n"
                 "Preferring fewer tokens so far (then oldest) drops that to ~0.6 s.",
                 color=FG, fontsize=24, weight="bold", ha="center", va="center", alpha=p, linespacing=1.35,
                 bbox=dict(boxstyle="round,pad=0.45", fc=PANEL, ec=AFTER, lw=2, alpha=p))
scene(10 * FPS, wait_fix)

# Takeaways ~10s
def take(t):
    fig.text(0.07, 0.88, "Takeaways", color=FG, fontsize=52, weight="bold")
    for k, (c, h, s) in enumerate(D["TAKE"]):
        c = {"ON": TWO, "ONE": THREE, "OFF": ONE, "MUTED": MUTED, "RED": RED}[c]
        p = ease((t - 0.35 - 0.55 * k) / 0.7); y = 0.74 - 0.15 * k
        fig.patches.append(plt.Rectangle((0.07, y - 0.065), 0.008, 0.1, transform=fig.transFigure, color=c, alpha=p, figure=fig))
        fig.text(0.095 - 0.02 * (1 - p), y, h, color=FG, fontsize=28, weight="bold", alpha=p, va="center")
        fig.text(0.095 - 0.02 * (1 - p), y - 0.048, s, color=MUTED, fontsize=22, alpha=p, va="center")
    p = ease((t - 2.8) / 0.7)
    fig.text(0.07, 0.08,
             "Rounded from measured medians the same evening. One chat still turn-takes; this is multi-chat throughput.\n"
             "Building Caravan in the open. Next up: guess-ahead decoding.",
             color="#d6dbe4", fontsize=20, va="center", alpha=p, style="italic")
scene(10 * FPS, take)

proc.stdin.close(); proc.wait()
print("done", proc.returncode, FRAME[0] / FPS, "s")
