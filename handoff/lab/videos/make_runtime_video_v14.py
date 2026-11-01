# v14: Day 8 Llama guess-ahead — payoff in first 3s, burn-in captions.
# Usage: make_runtime_video_v14.py out.mp4 v14_data.json --day "Day 8" [--stills dir]
# Numbers from Mini Llama suite Nov 1 (medians of 2); never invent.
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
    sys.exit("give a day label: --day 'Day 8' or --day-of YYYY-MM-DD")
STILL_AT = set(D.get("_stills", []))
BG, FG, MUTED, GRID, PANEL = "#0f1117", "#f2f4f8", "#9aa3b2", "#262b36", "#1b1f2a"
ONE, TWO, THREE = "#94A3B8", "#FACC15", "#34D399"
BEFORE, AFTER = "#F87171", "#34D399"
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
        fig.savefig(os.path.join(STILLS, f"v14_t{t:04.1f}.png"), facecolor=BG)
    FRAME[0] += 1
def fade(i, n, f=10):
    return min(1, (i + 1) / f, (n - i) / f)
def scene(n, draw):
    for i in range(n):
        fig.clf(); fig.patch.set_facecolor(BG); draw(i / FPS); emit(fade(i, n))
def header(title, sub):
    fig.text(0.05, 0.925, title, color=FG, fontsize=40, weight="bold", va="center")
    fig.text(0.05, 0.865, sub, color=MUTED, fontsize=24, va="center")
def caption(text, y=0.06):
    """Burn-in caption strip (readable muted)."""
    fig.patches.append(plt.Rectangle((0.04, y - 0.025), 0.92, 0.07, transform=fig.transFigure,
                                     fc="#0a0c12", ec=GRID, lw=1.5, alpha=0.92, figure=fig, zorder=50))
    fig.text(0.5, y + 0.01, text, color=FG, fontsize=26, ha="center", va="center", weight="bold", zorder=51)
def box(x, y, w, h, ec, a, fc=PANEL, lw=2.5):
    fig.patches.append(plt.Rectangle((x, y), w, h, transform=fig.transFigure, fc=fc, ec=ec, lw=lw, alpha=a, figure=fig))

OFF, ON = D["LLAMA_OFF"], D["LLAMA_ON"]

# --- Scene 0: PAYOFF first (~3s) ---
def payoff(t):
    a = ease(t / 0.35)
    fig.text(0.5, 0.72, "Llama 8B writing speed", color=MUTED, fontsize=32, ha="center", alpha=a)
    # big numbers
    p = ease((t - 0.15) / 0.5)
    fig.text(0.32, 0.48, f"{OFF:.0f}", color=BEFORE, fontsize=120, weight="bold", ha="center", alpha=p)
    fig.text(0.32, 0.34, "helper off", color=MUTED, fontsize=28, ha="center", alpha=p)
    fig.text(0.5, 0.48, "→", color=TWO, fontsize=90, weight="bold", ha="center", alpha=p)
    fig.text(0.68, 0.48, f"{ON:.0f}", color=AFTER, fontsize=120, weight="bold", ha="center", alpha=p)
    fig.text(0.68, 0.34, "1B helper on", color=MUTED, fontsize=28, ha="center", alpha=p)
    fig.text(0.5, 0.22, "tokens/sec  ·  ~2.3× on the count prompt", color=TWO, fontsize=30, ha="center",
             alpha=ease((t - 0.6) / 0.5), weight="bold")
    caption(f"{DAY}: {OFF:.1f} → {ON:.1f} tokens/sec with a tiny same-family helper")
scene(3 * FPS, payoff)

# --- Title ~5s ---
def title(t):
    a = ease(t / 0.7)
    fig.text(0.5, 0.62, "Guess-ahead on Llama 8B", color=FG, fontsize=58, weight="bold", ha="center", alpha=a)
    fig.text(0.5, 0.50, "A 1B helper drafts; the full split model still decides", color=FG, fontsize=32, ha="center", alpha=a)
    fig.text(0.5, 0.38, f"{DAY} of building Caravan  ·  two Mac minis over Thunderbolt",
             color=MUTED, fontsize=26, ha="center", alpha=a)
    caption("Same vocabulary family only · lead asks once before any download")
scene(5 * FPS, title)

# --- How ~10s ---
def how(t):
    header("What we ran today", "full Mini suite on Meta-Llama-3.1-8B-Instruct-4bit")
    rows = [
        ("Keepalive on/off", "Metal stays warm while waiting on the other Mini"),
        ("Several chats (1 / 2 / 3)", "wall throughput across chats, plus wait before the first word"),
        ("Guess-ahead on vs off", "four prompt types · quality gate · shut-off · download ask"),
    ]
    for k, (h, d) in enumerate(rows):
        p = ease((t - 0.15 - 0.45 * k) / 0.6); y = 0.70 - 0.14 * k
        fig.text(0.10, y + 0.025, h, color=TWO, fontsize=30, weight="bold", va="center", alpha=p)
        fig.text(0.10, y - 0.035, d, color=FG, fontsize=24, va="center", alpha=p)
    caption("Low Power Mode off · test ports · medians of 2 · real numbers only")
scene(10 * FPS, how)

# --- Family compare ~12s ---
def compare(t):
    header("Where Llama lands vs other families", "writing speed · tokens/sec · helper off vs auto-pair on")
    labels = D["COMPARE_LABELS"]
    off, on = D["COMPARE_OFF"], D["COMPARE_ON"]
    ax = fig.add_axes([0.08, 0.18, 0.84, 0.58])
    ax.set_facecolor(BG)
    for s in ax.spines.values(): s.set_visible(False)
    ax.tick_params(colors=FG, labelsize=22, length=0)
    ax.yaxis.set_tick_params(labelsize=16, labelcolor=MUTED)
    ax.grid(axis="y", color=GRID, lw=1); ax.set_axisbelow(True)
    n = len(labels); ax.set_xticks(range(n)); ax.set_xticklabels(labels)
    ax.set_ylim(0, 70); ax.set_xlim(-0.6, n - 0.4)
    w = 0.34
    for m in range(n):
        for r, (vals, c) in enumerate([(off, BEFORE), (on, AFTER)]):
            v = vals[m]; x = m + (r - 0.5) * w
            if v is None:
                if t > 0.4 + 0.2 * m:
                    ax.text(x, 3, "skip", color=MUTED, fontsize=18, ha="center", style="italic")
                continue
            p = ease((t - 0.2 - 0.2 * m - 0.08 * r) / 1.2)
            hl = (m == 2 and c == AFTER)
            ax.bar(x, v * p, w * 0.9, color=c, alpha=1,
                   edgecolor=FG if hl else "none", lw=2 if hl else 0)
            if p > 0.05:
                ax.text(x, v * p + 1.5, f"{v:.0f}", color=TWO if hl else FG,
                        fontsize=18, weight="bold", ha="center")
    # legend
    fig.patches.append(plt.Rectangle((0.05, 0.805), 0.016, 0.026, transform=fig.transFigure, color=BEFORE, figure=fig))
    fig.text(0.075, 0.818, "helper off", color=FG, fontsize=20, va="center")
    fig.patches.append(plt.Rectangle((0.24, 0.805), 0.016, 0.026, transform=fig.transFigure, color=AFTER, figure=fig))
    fig.text(0.265, 0.818, "auto-pair on", color=FG, fontsize=20, va="center", weight="bold")
    caption("Llama’s relative jump is the biggest so far on these Minis")
scene(12 * FPS, compare)

# --- Suite cards ~10s ---
def suite(t):
    header("The rest of the suite", "same method as Qwen3 / Gemma / GPT-OSS tables")
    cards = [
        (TWO, "Keepalive", D["SUITE"]["keepalive"], "writing off → on"),
        (THREE, "Several chats", D["SUITE"]["pipeline"], "wall speed N=1 / 2 / 3"),
        (ONE, "Accept rate", D["SUITE"]["accept"], "count prompt · quality 3/3"),
    ]
    for k, (c, name, nums, note) in enumerate(cards):
        p = ease((t - 0.15 - 0.4 * k) / 0.65)
        x = 0.07 + k * 0.31
        box(x, 0.30, 0.28, 0.46, c, p)
        fig.text(x + 0.14, 0.68, name, color=c, fontsize=26, weight="bold", ha="center", alpha=p)
        fig.text(x + 0.14, 0.52, nums, color=FG, fontsize=28, weight="bold", ha="center", alpha=p)
        fig.text(x + 0.14, 0.38, note, color=MUTED, fontsize=20, ha="center", alpha=p)
    caption("Shut-off still kills guessing when accepts fall below break-even")
scene(10 * FPS, suite)

# --- Takeaways ~10s ---
def take(t):
    header("Takeaways", f"{DAY} · Llama 8B Mini-verified")
    for k, (tone, h, d) in enumerate(D["TAKE"]):
        p = ease((t - 0.12 - 0.4 * k) / 0.55); y = 0.72 - 0.13 * k
        c = TWO if tone == "ON" else (THREE if tone == "ONE" else MUTED)
        fig.patches.append(plt.Rectangle((0.07, y - 0.035), 0.012, 0.07, transform=fig.transFigure, color=c, figure=fig, alpha=p))
        fig.text(0.11, y + 0.018, h, color=FG, fontsize=26, weight="bold", va="center", alpha=p)
        fig.text(0.11, y - 0.028, d, color=MUTED, fontsize=20, va="center", alpha=p)
    caption(f"{DAY} · Caravan MLX split · linuxbren/caravan")
scene(10 * FPS, take)

# --- End ~4s ---
def end(t):
    a = ease(t / 0.6)
    fig.text(0.5, 0.58, f"{OFF:.0f} → {ON:.0f} tokens/sec", color=AFTER, fontsize=56, weight="bold", ha="center", alpha=a)
    fig.text(0.5, 0.44, "Llama 8B + 1B helper on the two-Mini split", color=FG, fontsize=30, ha="center", alpha=a)
    fig.text(0.5, 0.32, f"{DAY} · Caravan", color=MUTED, fontsize=26, ha="center", alpha=a)
    caption("Which open model should we pair next?")
scene(4 * FPS, end)

proc.stdin.close(); proc.wait()
print(f"wrote {OUT} frames={FRAME[0]} dur={FRAME[0]/FPS:.1f}s")
