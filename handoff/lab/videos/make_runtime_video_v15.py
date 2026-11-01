# v15: Day 8 full local-model scoreboard — helpers + keepalive + several chats.
# Usage: make_runtime_video_v15.py out.mp4 v15_data.json --day "Day 8" [--stills dir]
# Numbers only from docs/BENCHMARKS.md (and matching METHODOLOGY / ROADMAP); never invent.
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
PIPE1, PIPE2, PIPE3 = "#64748B", "#FACC15", "#34D399"
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
        fig.savefig(os.path.join(STILLS, f"v15_t{t:04.1f}.png"), facecolor=BG)
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

OFF, ON = D["PAYOFF_BEFORE"], D["PAYOFF_AFTER"]

# --- Scene 0: PAYOFF first (~3s) ---
def payoff(t):
    a = ease(t / 0.3)
    fig.text(0.5, 0.78, "Six local models on two Mac minis", color=MUTED, fontsize=28, ha="center", alpha=a)
    p = ease((t - 0.1) / 0.45)
    fig.text(0.28, 0.48, f"{OFF:.0f}", color=BEFORE, fontsize=110, weight="bold", ha="center", alpha=p)
    fig.text(0.28, 0.34, "helper off", color=MUTED, fontsize=26, ha="center", alpha=p)
    fig.text(0.5, 0.48, "→", color=TWO, fontsize=80, weight="bold", ha="center", alpha=p)
    fig.text(0.72, 0.48, f"{ON:.0f}", color=AFTER, fontsize=110, weight="bold", ha="center", alpha=p)
    fig.text(0.72, 0.34, "1B helper on", color=MUTED, fontsize=26, ha="center", alpha=p)
    fig.text(0.5, 0.22, "Llama 8B writing speed  ·  tokens/sec  ·  biggest jump so far",
             color=TWO, fontsize=26, ha="center", alpha=ease((t - 0.55) / 0.4), weight="bold")
    caption(f"{DAY}: helpers + keepalive + several chats — all documented numbers")
scene(3 * FPS, payoff)

# --- Title ---
def title(t):
    a = ease(t / 0.6)
    fig.text(0.5, 0.64, "Full Day 8 scoreboard", color=FG, fontsize=56, weight="bold", ha="center", alpha=a)
    fig.text(0.5, 0.50, "Guess-ahead helpers, warm GPUs, and overlapping chats", color=FG, fontsize=30, ha="center", alpha=a)
    fig.text(0.5, 0.38, f"{DAY} of building Caravan  ·  Thunderbolt split across two Minis",
             color=MUTED, fontsize=24, ha="center", alpha=a)
    caption("Qwen3 · Gemma 4 · GPT-OSS · Llama 8B · Qwen2.5 · Distill-Qwen")
scene(5 * FPS, title)

# --- What we measured ---
def what(t):
    header("Three kinds of speedup", "same Minis · Low Power Mode off · medians of 2 · quality 3/3")
    rows = [
        ("Guess-ahead helper", "A tiny same-family model drafts the next word pieces; the big model still decides"),
        ("GPU keepalive", "While one Mini waits on the other, Metal stays warm instead of cooling down"),
        ("Several chats at once", "Two chats keep both halves busy — total writing speed across chats goes up"),
    ]
    for k, (h, d) in enumerate(rows):
        p = ease((t - 0.12 - 0.35 * k) / 0.55); y = 0.70 - 0.15 * k
        fig.text(0.09, y + 0.028, h, color=TWO, fontsize=28, weight="bold", va="center", alpha=p)
        fig.text(0.09, y - 0.032, d, color=FG, fontsize=22, va="center", alpha=p)
    caption("tokens/sec = writing speed  ·  wall aggregate = total words/sec across chats")
scene(9 * FPS, what)

# --- Helper scoreboard ---
def helpers(t):
    header("Helper scoreboard", "writing speed · tokens/sec · helper off vs auto-pair on")
    labels = D["HELPER_LABELS"]
    off, on = D["HELPER_OFF"], D["HELPER_ON"]
    notes = D["HELPER_NOTE"]
    ax = fig.add_axes([0.07, 0.16, 0.86, 0.58])
    ax.set_facecolor(BG)
    for s in ax.spines.values(): s.set_visible(False)
    ax.tick_params(colors=FG, labelsize=16, length=0)
    ax.yaxis.set_tick_params(labelsize=15, labelcolor=MUTED)
    ax.grid(axis="y", color=GRID, lw=1); ax.set_axisbelow(True)
    n = len(labels); ax.set_xticks(range(n)); ax.set_xticklabels(labels)
    ax.set_ylim(0, 72); ax.set_xlim(-0.55, n - 0.45)
    w = 0.34
    for m in range(n):
        for r, (vals, c) in enumerate([(off, BEFORE), (on, AFTER)]):
            v = vals[m]; x = m + (r - 0.5) * w
            if v is None:
                if t > 0.35 + 0.12 * m:
                    ax.text(x, 4, "skip", color=MUTED, fontsize=16, ha="center", style="italic")
                continue
            p = ease((t - 0.15 - 0.12 * m - 0.06 * r) / 1.0)
            hl = (m == 3 and c == AFTER)  # Llama highlight
            ax.bar(x, v * p, w * 0.88, color=c, alpha=1,
                   edgecolor=FG if hl else "none", lw=2 if hl else 0)
            if p > 0.08:
                ax.text(x, v * p + 1.6, f"{v:.0f}", color=TWO if hl else FG,
                        fontsize=15, weight="bold", ha="center")
        # helper size note
        if t > 0.5 + 0.1 * m:
            ax.text(m, -6.5, notes[m], color=MUTED, fontsize=13, ha="center")
    fig.patches.append(plt.Rectangle((0.05, 0.795), 0.014, 0.022, transform=fig.transFigure, color=BEFORE, figure=fig))
    fig.text(0.072, 0.806, "helper off", color=FG, fontsize=18, va="center")
    fig.patches.append(plt.Rectangle((0.22, 0.795), 0.014, 0.022, transform=fig.transFigure, color=AFTER, figure=fig))
    fig.text(0.242, 0.806, "auto-pair on", color=FG, fontsize=18, va="center", weight="bold")
    fig.text(0.48, 0.806, "GPT-OSS auto-skips — no small same-family helper yet", color=MUTED, fontsize=16, va="center")
    caption("Same-family draft on the lead · one Thunderbolt check · big model still decides")
scene(14 * FPS, helpers)

# --- Keepalive ---
def keepalive(t):
    header("GPU keepalive (not a helper)", "writing speed while the other Mini answers over Thunderbolt")
    labels = D["KA_LABELS"]
    off, on = D["KA_OFF"], D["KA_ON"]
    ax = fig.add_axes([0.07, 0.16, 0.86, 0.58])
    ax.set_facecolor(BG)
    for s in ax.spines.values(): s.set_visible(False)
    ax.tick_params(colors=FG, labelsize=16, length=0)
    ax.yaxis.set_tick_params(labelsize=15, labelcolor=MUTED)
    ax.grid(axis="y", color=GRID, lw=1); ax.set_axisbefore = True
    ax.set_axisbelow(True)
    n = len(labels); ax.set_xticks(range(n)); ax.set_xticklabels(labels)
    ax.set_ylim(0, 55); ax.set_xlim(-0.55, n - 0.45)
    w = 0.34
    for m in range(n):
        for r, (vals, c) in enumerate([(off, BEFORE), (on, AFTER)]):
            v = vals[m]; x = m + (r - 0.5) * w
            p = ease((t - 0.12 - 0.1 * m - 0.05 * r) / 0.9)
            ax.bar(x, v * p, w * 0.88, color=c, alpha=1)
            if p > 0.08:
                ax.text(x, v * p + 1.2, f"{v:.0f}", color=FG, fontsize=15, weight="bold", ha="center")
    fig.patches.append(plt.Rectangle((0.05, 0.795), 0.014, 0.022, transform=fig.transFigure, color=BEFORE, figure=fig))
    fig.text(0.072, 0.806, "keepalive off", color=FG, fontsize=18, va="center")
    fig.patches.append(plt.Rectangle((0.26, 0.795), 0.014, 0.022, transform=fig.transFigure, color=AFTER, figure=fig))
    fig.text(0.282, 0.806, "keepalive on (default)", color=FG, fontsize=18, va="center", weight="bold")
    caption("Big lifts on 30B-class · smaller lifts on 8B/14B (already less cool-down)")
scene(12 * FPS, keepalive)

# --- Pipeline ---
def pipeline(t):
    header("Several chats at once", "wall aggregate writing speed · tokens/sec across chats · N = 1 / 2 / 3")
    labels = D["PIPE_LABELS"]
    n1, n2, n3 = D["PIPE_N1"], D["PIPE_N2"], D["PIPE_N3"]
    ax = fig.add_axes([0.07, 0.16, 0.86, 0.58])
    ax.set_facecolor(BG)
    for s in ax.spines.values(): s.set_visible(False)
    ax.tick_params(colors=FG, labelsize=16, length=0)
    ax.yaxis.set_tick_params(labelsize=15, labelcolor=MUTED)
    ax.grid(axis="y", color=GRID, lw=1); ax.set_axisbelow(True)
    n = len(labels); ax.set_xticks(range(n)); ax.set_xticklabels(labels)
    ax.set_ylim(0, 85); ax.set_xlim(-0.6, n - 0.4)
    w = 0.24
    series = [(n1, PIPE1), (n2, PIPE2), (n3, PIPE3)]
    for m in range(n):
        for r, (vals, c) in enumerate(series):
            v = vals[m]; x = m + (r - 1) * w
            p = ease((t - 0.1 - 0.1 * m - 0.04 * r) / 0.85)
            ax.bar(x, v * p, w * 0.9, color=c, alpha=1)
            if p > 0.1:
                ax.text(x, v * p + 1.5, f"{v:.0f}", color=FG, fontsize=12, weight="bold", ha="center")
    fig.patches.append(plt.Rectangle((0.05, 0.795), 0.014, 0.022, transform=fig.transFigure, color=PIPE1, figure=fig))
    fig.text(0.072, 0.806, "1 chat", color=FG, fontsize=17, va="center")
    fig.patches.append(plt.Rectangle((0.18, 0.795), 0.014, 0.022, transform=fig.transFigure, color=PIPE2, figure=fig))
    fig.text(0.202, 0.806, "2 chats (~1.6×)", color=FG, fontsize=17, va="center", weight="bold")
    fig.patches.append(plt.Rectangle((0.40, 0.795), 0.014, 0.022, transform=fig.transFigure, color=PIPE3, figure=fig))
    fig.text(0.422, 0.806, "3 chats ≈ 2 on wall", color=FG, fontsize=17, va="center")
    caption("Two halves of the model · two chats keep both busy · third shares the same pipe")
scene(13 * FPS, pipeline)

# --- 12-family map + download ---
def map_dl(t):
    header("12-family helper map + download ask", "auto-pair when vocab matches · otherwise skip · ask once before any download")
    # left: families
    for k, (names, status) in enumerate(D["FAMILIES"]):
        p = ease((t - 0.1 - 0.3 * k) / 0.5); y = 0.72 - 0.14 * k
        box(0.06, y - 0.05, 0.52, 0.11, THREE if k < 2 else ONE, p, lw=2)
        fig.text(0.08, y + 0.025, names, color=FG, fontsize=18, weight="bold", va="center", alpha=p)
        fig.text(0.08, y - 0.025, status, color=MUTED, fontsize=16, va="center", alpha=p)
    # right: download cards
    fig.text(0.64, 0.78, "Real download prompt", color=TWO, fontsize=22, weight="bold", alpha=ease(t / 0.4))
    for k, (model, size, note) in enumerate(D["DL"]):
        p = ease((t - 0.35 - 0.25 * k) / 0.5); y = 0.66 - 0.15 * k
        box(0.62, y - 0.05, 0.32, 0.12, TWO, p, lw=2)
        fig.text(0.78, y + 0.025, f"{model} · {size}", color=FG, fontsize=18, weight="bold", ha="center", alpha=p)
        fig.text(0.78, y - 0.025, note, color=MUTED, fontsize=16, ha="center", alpha=p)
    caption("Live PTY yes on EXO1 · answer remembered · draft restored after the test")
scene(12 * FPS, map_dl)

# --- Takeaways ---
def take(t):
    header("Takeaways", f"{DAY} · every local model we’ve Mini-tested")
    for k, (tone, h, d) in enumerate(D["TAKE"]):
        p = ease((t - 0.1 - 0.32 * k) / 0.5); y = 0.72 - 0.13 * k
        c = TWO if tone == "ON" else (THREE if tone == "ONE" else MUTED)
        fig.patches.append(plt.Rectangle((0.07, y - 0.035), 0.012, 0.07, transform=fig.transFigure, color=c, figure=fig, alpha=p))
        fig.text(0.11, y + 0.018, h, color=FG, fontsize=24, weight="bold", va="center", alpha=p)
        fig.text(0.11, y - 0.028, d, color=MUTED, fontsize=18, va="center", alpha=p)
    caption(f"{DAY} · Caravan MLX split · fewer flags next (self-tuning + config.toml)")
scene(11 * FPS, take)

# --- End ---
def end(t):
    a = ease(t / 0.55)
    fig.text(0.5, 0.62, "Helpers · keepalive · several chats", color=AFTER, fontsize=40, weight="bold", ha="center", alpha=a)
    fig.text(0.5, 0.48, "Six models measured  ·  twelve families mapped", color=FG, fontsize=28, ha="center", alpha=a)
    fig.text(0.5, 0.34, f"{DAY} · Caravan  ·  next: fewer flags", color=MUTED, fontsize=24, ha="center", alpha=a)
    caption("Which family should we Mini-verify next?")
scene(5 * FPS, end)

proc.stdin.close(); proc.wait()
print(f"wrote {OUT} frames={FRAME[0]} dur={FRAME[0]/FPS:.1f}s")
