# v13: Day 7 guess-ahead — techie-friend audience (confident show-your-work).
# Usage: make_runtime_video_v13.py out.mp4 v13_data.json --day "Day 7" [--stills dir]
# Numbers from Mini auto-pair benches Nov 1 (medians of 2); never invent.
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
    sys.exit("give a day label: --day 'Day 7' or --day-of YYYY-MM-DD")
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
        fig.savefig(os.path.join(STILLS, f"v13_t{t:04.1f}.png"), facecolor=BG)
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
        bold = "after" in lab.lower() or "on" in lab.lower() or "guesser" in lab.lower()
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
            if v is None:
                if t > start + 0.25 * m:
                    ax.text(x, ymax * 0.08, "skip", color=MUTED, fontsize=fs, ha="center", va="bottom", style="italic")
                continue
            p = ease((t - start - 0.25 * m - 0.07 * r) / 1.4)
            highlight = (hl is None and c == AFTER) or (hl is not None and c == hl)
            ax.bar(x, v * p, w * 0.9, color=c, alpha=0.55 if faint else 1,
                   edgecolor=FG if highlight else "none", lw=1.5 if highlight else 0)
            if p > 0.02:
                ax.text(x, v * p + ymax * 0.012, fmt(v * p if p < 1 else v),
                        color=TWO if highlight else (MUTED if faint else FG),
                        fontsize=fs, weight="bold", ha="center", va="bottom")

# Title ~5s
def title(t):
    a = ease(t / 0.8)
    fig.text(0.5, 0.66, "Guessing ahead", color=FG, fontsize=68, weight="bold", ha="center", alpha=a)
    fig.text(0.5, 0.55, "A small helper model drafts the next tokens", color=FG, fontsize=36, ha="center", alpha=a)
    x0 = 0.5 - 0.12
    for k, c in enumerate([ONE, TWO, THREE]):
        fig.patches.append(plt.Rectangle((x0 + k * 0.08, 0.47), 0.08 * ease((t - 0.3 - 0.15 * k) / 0.8), 0.014,
                                         transform=fig.transFigure, color=c, figure=fig))
    fig.text(0.5, 0.36,
             "One Thunderbolt check confirms a handful of guesses at once",
             color=TWO, fontsize=28, ha="center", alpha=a)
    fig.text(0.5, 0.27,
             f"{DAY} of building Caravan  ·  Qwen3 · Gemma 4 · GPT-OSS",
             color=MUTED, fontsize=26, ha="center", alpha=a)
scene(5 * FPS, title)

# How it works ~11s
def how(t):
    header("How the guesser fits the split", "lead Mini holds a tiny same-family draft; packer still runs the big model's first half")
    rows = [
        ("1.", "Pair by vocabulary", "Qwen drafts with Qwen; Gemma with Gemma. Mismatched token IDs get remapped or skipped."),
        ("2.", "Ask once, then remember", "Lead shows the helper size before any download. Decline sticks; no silent fetches."),
        ("3.", "Draft → verify → keep", "Helper proposes k tokens; one cable round trip checks them on the full model."),
    ]
    for k, (num, h, d) in enumerate(rows):
        p = ease((t - 0.2 - 0.55 * k) / 0.65); y = 0.72 - 0.14 * k
        fig.text(0.10, y, num, color=TWO, fontsize=36, weight="bold", va="center", alpha=p)
        fig.text(0.18, y + 0.028, h, color=FG, fontsize=30, weight="bold", va="center", alpha=p)
        fig.text(0.18, y - 0.038, d, color=MUTED, fontsize=24, va="center", alpha=p)
    p = ease((t - 2.6) / 0.7)
    if p > 0:
        fig.text(0.5, 0.20,
                 "tok/s = tokens per second (writing speed). Higher is better.",
                 color=FG, fontsize=26, weight="bold", ha="center", va="center", alpha=p,
                 bbox=dict(boxstyle="round,pad=0.5", fc=PANEL, ec=TWO, lw=2, alpha=p))
    fig.text(0.05, 0.04, "Off with --no-split-draft. Auto-pair reads agent/guessers.json on the lead only.",
             color=MUTED, fontsize=20)
scene(11 * FPS, how)

# Chart ~12s
def writing(t):
    header("Writing speed with guess-ahead", "tokens/sec · single chat · medians of 2 · higher is better")
    legend([("guesser off", BEFORE), ("auto-pair on", AFTER)], xs=(0.05, 0.28))
    ax = fig.add_axes([0.08, 0.16, 0.84, 0.58])
    off = D["WRITE"]["off"]; on = D["WRITE"]["on"]
    vbars(ax, [(off, BEFORE, True), (on, AFTER, False)], t, lambda v: f"{v:.0f}", 70, start=0.2, fs=22, hl=AFTER)
    fig.text(0.05, 0.04, "GPT-OSS has no small same-vocab draft yet, so Caravan skips pairing and stays at baseline.",
             color=MUTED, fontsize=20)
scene(12 * FPS, writing)

# Numbers callout ~9s
def callout(t):
    header("What moved", "same machines, test ports, Low Power Mode off, warm-up first")
    cards = [
        (TWO, "Qwen3", "45.9 → 59.7", "+30%", "0.6B draft · k=3"),
        (THREE, "Gemma 4", "38.4 → 44.5", "+16%", "270M draft · k=2"),
        (ONE, "GPT-OSS", "34.3", "skip", "no small o200k draft"),
    ]
    for k, (c, name, nums, tag, note) in enumerate(cards):
        p = ease((t - 0.2 - 0.45 * k) / 0.7)
        x = 0.07 + k * 0.31
        box(x, 0.28, 0.28, 0.48, c, p)
        fig.text(x + 0.14, 0.68, name, color=c, fontsize=28, weight="bold", ha="center", alpha=p)
        fig.text(x + 0.14, 0.55, nums, color=FG, fontsize=32, weight="bold", ha="center", alpha=p)
        fig.text(x + 0.14, 0.44, tag, color=TWO if tag.startswith("+") else MUTED, fontsize=36, weight="bold", ha="center", alpha=p)
        fig.text(x + 0.14, 0.34, note, color=MUTED, fontsize=20, ha="center", alpha=p)
    fig.text(0.05, 0.04, "Quality checks 3/3 on every row. Shut-off fires when accepted guesses drop below break-even.",
             color=MUTED, fontsize=20)
scene(9 * FPS, callout)

# Quality / shut-off ~10s
def safety(t):
    header("Keep the helper honest", "first-load gate + mid-chat shut-off")
    rows = [
        ("Quality gate", "Three short prompts. Score only the final answer — strip thinking / channel blocks first."),
        ("Gemma detail", "Thought comes as <|channel>thought … <channel|>ANSWER. Matching inside the thought used to pass; not anymore."),
        ("Shut-off", "If accepted guesses fall below break-even (demo: 0.438 < 0.80), guessing turns off for that chat."),
    ]
    for k, (h, d) in enumerate(rows):
        p = ease((t - 0.2 - 0.55 * k) / 0.65); y = 0.70 - 0.15 * k
        fig.text(0.10, y + 0.03, h, color=TWO, fontsize=30, weight="bold", va="center", alpha=p)
        fig.text(0.10, y - 0.04, d, color=FG, fontsize=24, va="center", alpha=p)
    fig.text(0.05, 0.04, "Gate result is cached per model+guesser on the lead. Re-run after a matcher change.",
             color=MUTED, fontsize=20)
scene(10 * FPS, safety)

# Takeaways ~10s
def take(t):
    header("Takeaways", "Day 7 · guess-ahead auto-pair on the two-Mini split")
    items = D["TAKE"]
    for k, (tone, h, d) in enumerate(items):
        p = ease((t - 0.15 - 0.45 * k) / 0.6); y = 0.72 - 0.13 * k
        c = TWO if tone == "ON" else (THREE if tone == "ONE" else MUTED)
        fig.patches.append(plt.Rectangle((0.07, y - 0.035), 0.012, 0.07, transform=fig.transFigure, color=c, figure=fig, alpha=p))
        fig.text(0.11, y + 0.018, h, color=FG, fontsize=28, weight="bold", va="center", alpha=p)
        fig.text(0.11, y - 0.028, d, color=MUTED, fontsize=22, va="center", alpha=p)
    fig.text(0.05, 0.04, f"{DAY} of building Caravan in the open · linuxbren/caravan · caravan-v3-mlx-split",
             color=MUTED, fontsize=20)
scene(10 * FPS, take)

# End card ~5s
def end(t):
    a = ease(t / 0.7)
    fig.text(0.5, 0.58, "Guess ahead, verify once", color=FG, fontsize=52, weight="bold", ha="center", alpha=a)
    fig.text(0.5, 0.46, "Small draft on the lead · full model still decides", color=TWO, fontsize=30, ha="center", alpha=a)
    fig.text(0.5, 0.34, f"{DAY} · Caravan MLX split", color=MUTED, fontsize=26, ha="center", alpha=a)
scene(5 * FPS, end)

proc.stdin.close(); proc.wait()
print(f"wrote {OUT} frames={FRAME[0]} dur={FRAME[0]/FPS:.1f}s")
