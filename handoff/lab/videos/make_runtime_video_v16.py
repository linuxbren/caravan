# v16: Day 9 auto-settings — picks K + pipeline N with no flags; matches hand-tuned.
# Usage: make_runtime_video_v16.py out.mp4 v16_data.json --day "Day 9" [--stills dir]
# Numbers only from docs/BENCHMARKS.md Day 9 auto-tune table; live log from Mini no-flag start.
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
    sys.exit("give a day label: --day 'Day 9' or --day-of YYYY-MM-DD")
STILL_AT = set(D.get("_stills", []))
BG, FG, MUTED, GRID, PANEL = "#0f1117", "#f2f4f8", "#9aa3b2", "#262b36", "#1b1f2a"
ONE, TWO, THREE = "#94A3B8", "#FACC15", "#34D399"
BEFORE, AFTER = "#F87171", "#34D399"
TERM = "#0a0c12"
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
        fig.savefig(os.path.join(STILLS, f"v16_t{t:04.1f}.png"), facecolor=BG)
    FRAME[0] += 1
def fade(i, n, f=10):
    return min(1, (i + 1) / f, (n - i) / f)
def scene(n, draw):
    for i in range(n):
        fig.clf(); fig.patch.set_facecolor(BG); draw(i / FPS); emit(fade(i, n))
def header(title, sub):
    fig.text(0.05, 0.925, title, color=FG, fontsize=36, weight="bold", va="center")
    fig.text(0.05, 0.868, sub, color=MUTED, fontsize=22, va="center")
def caption(text, y=0.055):
    fig.patches.append(plt.Rectangle((0.04, y - 0.022), 0.92, 0.065, transform=fig.transFigure,
                                     fc="#0a0c12", ec=GRID, lw=1.5, alpha=0.92, figure=fig, zorder=50))
    fig.text(0.5, y + 0.01, text, color=FG, fontsize=22, ha="center", va="center", weight="bold", zorder=51)
def box(x, y, w, h, ec, a, fc=PANEL, lw=2.5):
    fig.patches.append(plt.Rectangle((x, y), w, h, transform=fig.transFigure, fc=fc, ec=ec, lw=lw, alpha=a, figure=fig))

models = D["MODELS"]

# --- Scene 0: PAYOFF first (~3s) ---
def payoff(t):
    a = ease(t / 0.25)
    fig.text(0.5, 0.78, "No flags. Caravan picks its own settings.", color=MUTED, fontsize=28, ha="center", alpha=a)
    p = ease((t - 0.08) / 0.4)
    fig.text(0.5, 0.52, "auto = hand-tuned", color=AFTER, fontsize=72, weight="bold", ha="center", alpha=p)
    fig.text(0.5, 0.34, "Qwen3 45.0 = 45.0   ·   Llama 22.5 ≈ 22.6   ·   Qwen2.5 12.4 = 12.4",
             color=TWO, fontsize=24, ha="center", alpha=ease((t - 0.45) / 0.35), weight="bold")
    fig.text(0.5, 0.22, "writing speed · tokens/sec · three models on two Mac minis",
             color=MUTED, fontsize=22, ha="center", alpha=ease((t - 0.55) / 0.35))
    caption(f"{DAY}: self-tuning defaults — fewer flags to learn")
scene(3 * FPS, payoff)

# --- Title ---
def title(t):
    a = ease(t / 0.5)
    fig.text(0.5, 0.64, "Auto-settings", color=FG, fontsize=64, weight="bold", ha="center", alpha=a)
    fig.text(0.5, 0.50, "Layer split + chat count, chosen from Mini memory", color=FG, fontsize=28, ha="center", alpha=a)
    fig.text(0.5, 0.36, f"{DAY} of building Caravan  ·  Thunderbolt split across two Minis",
             color=MUTED, fontsize=24, ha="center", alpha=a)
    caption("Omit the knobs · keep the flags for benches · one reason line in the log")
scene(4 * FPS, title)

# --- What it does ---
def what(t):
    header("What Caravan chooses now", "when you leave --split-packer-layers and --split-pipeline-chats off")
    rows = [
        ("Layer cut (K)", "How many early layers sit on the packer Mini — from each Mini's RAM + model size"),
        ("Chat count (N)", "How many chats can overlap on the split — capped at 2 so memory never swaps"),
        ("Flags still win", "Hand a number and Caravan uses it. Auto is the default path, not a lock-in."),
    ]
    for k, (h, d) in enumerate(rows):
        p = ease((t - 0.1 - 0.28 * k) / 0.5); y = 0.70 - 0.15 * k
        fig.text(0.09, y + 0.028, h, color=TWO, fontsize=28, weight="bold", va="center", alpha=p)
        fig.text(0.09, y - 0.032, d, color=FG, fontsize=22, va="center", alpha=p)
    caption("tokens/sec = writing speed  ·  K = packer layers  ·  N = overlapping chats")
scene(8 * FPS, what)

# --- Live log ---
def live(t):
    header("Real no-flag start (Llama 8B)", "test ports 8194 / 5560 · Low Power Mode off · captured on the Minis")
    box(0.06, 0.22, 0.88, 0.55, THREE, ease(t / 0.3), fc=TERM, lw=2)
    lines = D["LIVE_LOG"]
    for k, line in enumerate(lines):
        p = ease((t - 0.25 - 0.35 * k) / 0.45)
        y = 0.68 - 0.12 * k
        color = AFTER if "auto " in line else (TWO if "listening" in line else FG)
        # wrap-ish: show as terminal line
        fig.text(0.09, y, "› " + line, color=color, fontsize=18, va="center", alpha=p,
                 family="monospace", wrap=False)
    caption("Same pick the Day 9 benches used: K=16 · N=2 for Llama")
scene(10 * FPS, live)

# --- Scoreboard ---
def score(t):
    header("Auto vs hand-tuned", "writing speed · tokens/sec · medians of 2 · quality 3/3")
    fig.patches.append(plt.Rectangle((0.05, 0.795), 0.014, 0.022, transform=fig.transFigure, color=ONE, figure=fig))
    fig.text(0.072, 0.806, "hand-tuned flags", color=FG, fontsize=18, va="center")
    fig.patches.append(plt.Rectangle((0.30, 0.795), 0.014, 0.022, transform=fig.transFigure, color=AFTER, figure=fig))
    fig.text(0.322, 0.806, "auto (no flags)", color=FG, fontsize=18, va="center", weight="bold")
    ax = fig.add_axes([0.08, 0.16, 0.84, 0.58])
    ax.set_facecolor(BG)
    for s in ax.spines.values(): s.set_visible(False)
    ax.tick_params(colors=FG, labelsize=18, length=0)
    ax.yaxis.set_tick_params(labelsize=16, labelcolor=MUTED)
    ax.grid(axis="y", color=GRID, lw=1); ax.set_axisbelow(True)
    labels = [m["name"] for m in models]
    n = len(models)
    ax.set_xticks(range(n)); ax.set_xticklabels(labels)
    ax.set_ylim(0, 55); ax.set_xlim(-0.55, n - 0.45)
    w = 0.32
    for m_i, m in enumerate(models):
        for r, (key, c) in enumerate([("tuned", ONE), ("auto", AFTER)]):
            v = m[key]; x = m_i + (r - 0.5) * w
            p = ease((t - 0.12 - 0.15 * m_i - 0.05 * r) / 0.85)
            ax.bar(x, v * p, w * 0.88, color=c, alpha=1,
                   edgecolor=FG if key == "auto" else "none", lw=1.5 if key == "auto" else 0)
            if p > 0.08:
                ax.text(x, v * p + 1.2, f"{v:.1f}", color=FG, fontsize=18, weight="bold", ha="center")
        if t > 0.4 + 0.1 * m_i:
            ax.text(m_i, -5.5, f"K{m['k']}/N{m['n']}", color=MUTED, fontsize=15, ha="center")
    caption("Auto matched the same K and N the hand-tuned runs used")
scene(12 * FPS, score)

# --- Takeaways ---
def take(t):
    header("Takeaways", f"{DAY} · ROADMAP #13(a) detect-and-pick")
    for k, (tone, h, d) in enumerate(D["TAKE"]):
        p = ease((t - 0.1 - 0.28 * k) / 0.45); y = 0.72 - 0.13 * k
        c = TWO if tone == "ON" else (THREE if tone == "ONE" else MUTED)
        fig.patches.append(plt.Rectangle((0.07, y - 0.035), 0.012, 0.07, transform=fig.transFigure, color=c, figure=fig, alpha=p))
        fig.text(0.11, y + 0.018, h, color=FG, fontsize=24, weight="bold", va="center", alpha=p)
        fig.text(0.11, y - 0.028, d, color=MUTED, fontsize=18, va="center", alpha=p)
    caption(f"{DAY} · Caravan MLX split · next: learn per model + optional config.toml")
scene(9 * FPS, take)

# --- End ---
def end(t):
    a = ease(t / 0.5)
    fig.text(0.5, 0.60, "Fewer flags. Same speed.", color=AFTER, fontsize=48, weight="bold", ha="center", alpha=a)
    fig.text(0.5, 0.44, "Caravan reads the Minis and picks the cut", color=FG, fontsize=28, ha="center", alpha=a)
    fig.text(0.5, 0.30, f"{DAY} · Caravan  ·  #13(a) shipped", color=MUTED, fontsize=24, ha="center", alpha=a)
    caption("What should remember itself next — per-model settings, or a config file?")
scene(4 * FPS, end)

proc.stdin.close(); proc.wait()
print(f"wrote {OUT} frames={FRAME[0]} dur={FRAME[0]/FPS:.1f}s")
