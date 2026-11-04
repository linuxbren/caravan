# v21: Day 13 — Gemma shared-prefix fix + self-tune per model.
# Usage: make_runtime_video_v21.py out.mp4 v21_data.json --day "Day 13" [--stills dir]
# Numbers only from handoff/lab/day13-gemma-prefix/ + day13-spc-learn/.
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
    sys.exit("give a day label: --day 'Day 13' or --day-of YYYY-MM-DD")
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
        fig.savefig(os.path.join(STILLS, f"v21_t{t:04.1f}.png"), facecolor=BG)
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
    fig.text(0.5, y + 0.01, text, color=FG, fontsize=20, ha="center", va="center", weight="bold", zorder=51)
def box(x, y, w, h, ec, a, fc=PANEL, lw=2.5):
    fig.patches.append(plt.Rectangle((x, y), w, h, transform=fig.transFigure, fc=fc, ec=ec, lw=lw, alpha=a, figure=fig))

G, Q, L = D["GEMMA"], D["QWEN"], D["LLAMA"]
LR = D["LEARN"]

# --- 0. PAYOFF first ~3s ---
def payoff(t):
    a = ease(t / 0.25)
    fig.text(0.5, 0.78, "Gemma · new chat · same long system prompt", color=MUTED, fontsize=26, ha="center", alpha=a)
    p = ease((t - 0.08) / 0.4)
    fig.text(0.5, 0.52, f"{G['off']:.1f} → {G['on']:.2f} s", color=AFTER, fontsize=72, weight="bold", ha="center", alpha=p)
    fig.text(0.5, 0.34, f"~{G['x']:.1f}× sooner to the first word",
             color=TWO, fontsize=30, ha="center", alpha=ease((t - 0.45) / 0.35), weight="bold")
    fig.text(0.5, 0.22, "big model split across two Mac minis",
             color=MUTED, fontsize=22, ha="center", alpha=ease((t - 0.55) / 0.35))
    caption(f"{DAY}: shared start of chats — Gemma finally works")
scene(3 * FPS, payoff)

# --- 1. Title ---
def title(t):
    a = ease(t / 0.5)
    fig.text(0.5, 0.64, "Shared start, fixed — and it learns", color=FG, fontsize=52, weight="bold", ha="center", alpha=a)
    fig.text(0.5, 0.48, "Gemma was stuck at 0%. Now it reuses the prompt. Caravan picks on/off per model.",
             color=FG, fontsize=24, ha="center", alpha=a)
    fig.text(0.5, 0.34, f"{DAY} of building Caravan  ·  Thunderbolt between the Minis",
             color=MUTED, fontsize=24, ha="center", alpha=a)
    caption("wait = seconds before the first word  ·  writing speed unchanged")
scene(4 * FPS, title)

# --- 2. Problem ---
def problem(t):
    header("The problem", "Day 12: Gemma got 0% from shared start on the split")
    a = ease(t / 0.35)
    box(0.08, 0.28, 0.84, 0.50, BEFORE, a)
    fig.text(0.5, 0.68, "Sliding-window layers can't be trimmed", color=BEFORE, fontsize=28, ha="center", alpha=a, weight="bold")
    fig.text(0.5, 0.54, "After saving a shared start, one Mini shortened its copy.",
             color=FG, fontsize=22, ha="center", alpha=a)
    fig.text(0.5, 0.44, "Gemma's windowed layers refused. The other Mini disagreed.",
             color=FG, fontsize=22, ha="center", alpha=a)
    fig.text(0.5, 0.34, "Full re-read every time  ·  shared start looked \"on\" but did nothing",
             color=TWO, fontsize=20, ha="center", alpha=ease((t - 0.4) / 0.4), weight="bold")
    caption("Two Minis must agree on how many prompt tokens they already share")
scene(10 * FPS, problem)

# --- 3. Fix + Gemma ---
def fix_scene(t):
    header("The fix", "if a layer can't trim, rebuild the shared start on both Minis")
    a = ease(t / 0.35)
    box(0.08, 0.30, 0.38, 0.48, BEFORE, a)
    box(0.54, 0.30, 0.38, 0.48, AFTER, a)
    fig.text(0.27, 0.70, "Before (Day 12)", color=MUTED, fontsize=22, ha="center", alpha=a)
    fig.text(0.27, 0.55, "~0%", color=BEFORE, fontsize=56, ha="center", alpha=a, weight="bold")
    fig.text(0.27, 0.40, "Minis disagreed · full re-read", color=MUTED, fontsize=18, ha="center", alpha=a)
    fig.text(0.73, 0.70, "Gemma now", color=MUTED, fontsize=22, ha="center", alpha=a)
    fig.text(0.73, 0.55, f"{G['off']:.1f} → {G['on']:.2f} s", color=AFTER, fontsize=36, ha="center", alpha=a, weight="bold")
    fig.text(0.73, 0.42, f"~{G['x']:.1f}× sooner  ·  −{G['pct']}%", color=TWO, fontsize=22, ha="center", alpha=a, weight="bold")
    fig.text(0.73, 0.34, f"Same answer: {D['QUALITY']}", color=MUTED, fontsize=18, ha="center", alpha=a)
    fig.text(0.5, 0.22, "One-time setup on the first chat is slower (rebuild) · later new chats are fast",
             color=MUTED, fontsize=18, ha="center", alpha=ease((t - 0.35) / 0.4))
    caption("Paired off vs on test · same long system prompt · new chat each time")
scene(11 * FPS, fix_scene)

# --- 4. Qwen3 + Llama ---
def others(t):
    header("Qwen3 and Llama still ~halve the wait", "same paired test · shared start already worked for them")
    a = ease(t / 0.35)
    box(0.08, 0.30, 0.38, 0.48, AFTER, a)
    box(0.54, 0.30, 0.38, 0.48, AFTER, a)
    fig.text(0.27, 0.70, "Qwen3 30B", color=FG, fontsize=24, ha="center", alpha=a, weight="bold")
    fig.text(0.27, 0.55, f"{Q['off']:.1f} → {Q['on']:.1f} s", color=AFTER, fontsize=40, ha="center", alpha=a, weight="bold")
    fig.text(0.27, 0.42, f"−{Q['pct']}%", color=TWO, fontsize=28, ha="center", alpha=a, weight="bold")
    fig.text(0.27, 0.34, "cold → shared start", color=MUTED, fontsize=18, ha="center", alpha=a)
    fig.text(0.73, 0.70, "Llama 8B", color=FG, fontsize=24, ha="center", alpha=a, weight="bold")
    fig.text(0.73, 0.55, f"{L['off']:.1f} → {L['on']:.1f} s", color=AFTER, fontsize=40, ha="center", alpha=a, weight="bold")
    fig.text(0.73, 0.42, f"−{L['pct']}%", color=TWO, fontsize=28, ha="center", alpha=a, weight="bold")
    fig.text(0.73, 0.34, "cold → shared start", color=MUTED, fontsize=18, ha="center", alpha=a)
    fig.text(0.5, 0.22, "Not a writing-speed win — it shortens the wait before the reply starts",
             color=MUTED, fontsize=20, ha="center", alpha=ease((t - 0.4) / 0.4))
    caption("Apples-to-apples with the Day 13 fix bench · not the later learn-run chats")
scene(10 * FPS, others)

# --- 5. Self-tune ---
def learn_scene(t):
    header("Self-tune: shared start per model", "like the other live settings — try on vs off from real chats")
    a = ease(t / 0.35)
    fig.text(0.5, 0.70, f"All three chose  {LR['chose'].upper()}", color=AFTER, fontsize=44, ha="center", alpha=a, weight="bold")
    fig.text(0.5, 0.56, f"after {LR['chats']} chats from empty settings · no flag",
             color=FG, fontsize=26, ha="center", alpha=a)
    # three chips
    for k, name in enumerate(LR["models"]):
        p = ease((t - 0.2 - 0.12 * k) / 0.4)
        x = 0.18 + k * 0.28
        box(x, 0.30, 0.22, 0.16, AFTER, p)
        fig.text(x + 0.11, 0.38, name, color=FG, fontsize=22, ha="center", alpha=p, weight="bold")
    fig.text(0.5, 0.22, f"One-time setup still costs (Gemma first chat ~{LR['gemma_store']:.0f} s) · later chats reuse it",
             color=MUTED, fontsize=18, ha="center", alpha=ease((t - 0.45) / 0.35))
    caption("Scores wait before first word · keeps store cost out of the \"on\" average · flag still wins")
scene(11 * FPS, learn_scene)

# --- 6. Issues ---
def issues(t):
    header("Issues to keep honest", "real tradeoffs · don't mix two different tests")
    a = ease(t / 0.35)
    rows = [
        ("One-time setup", "First chat with shared start on rebuilds the prefix (Gemma ~22–23 s once)."),
        ("Compare like with like", "Learn-run chats reused a longer chunk than the paired bench — don't mix hit times."),
        ("Still opt-in until learned", "Flag off by default for a brand-new model · saved winner turns it on next load."),
    ]
    for k, (h, d) in enumerate(rows):
        p = ease((t - 0.1 - 0.2 * k) / 0.45); y = 0.70 - 0.16 * k
        fig.patches.append(plt.Rectangle((0.07, y - 0.045), 0.012, 0.09, transform=fig.transFigure, color=TWO, figure=fig, alpha=p))
        fig.text(0.11, y + 0.02, h, color=FG, fontsize=22, weight="bold", va="center", alpha=p)
        fig.text(0.11, y - 0.035, d, color=MUTED, fontsize=18, va="center", alpha=p)
    caption("Paired bench = speedup claim  ·  learn run = what it chose and how many chats")
scene(10 * FPS, issues)

# --- 7. Takeaways ---
def take(t):
    header("Takeaways", f"{DAY} · Gemma fixed · self-tune shared start")
    for k, (tone, h, d) in enumerate(D["TAKE"]):
        p = ease((t - 0.1 - 0.25 * k) / 0.45); y = 0.74 - 0.13 * k
        c = TWO if tone == "ON" else (THREE if tone == "ONE" else MUTED)
        fig.patches.append(plt.Rectangle((0.07, y - 0.035), 0.012, 0.07, transform=fig.transFigure, color=c, figure=fig, alpha=p))
        fig.text(0.11, y + 0.018, h, color=FG, fontsize=21, weight="bold", va="center", alpha=p)
        fig.text(0.11, y - 0.028, d, color=MUTED, fontsize=16, va="center", alpha=p)
    caption(f"{DAY} · Caravan MLX split · shared-prefix still off until learned")
scene(12 * FPS, take)

# --- 8. End ---
def end(t):
    a = ease(t / 0.5)
    fig.text(0.5, 0.62, "Gemma's first word ~7.6× sooner.", color=AFTER, fontsize=44, weight="bold", ha="center", alpha=a)
    fig.text(0.5, 0.46, "Caravan now learns shared start per model  ·  Day 14 is a break for the v0→now video",
             color=FG, fontsize=20, ha="center", alpha=a)
    fig.text(0.5, 0.30, f"{DAY} · Caravan", color=MUTED, fontsize=24, ha="center", alpha=a)
    caption("Leave shared start off until a model proves it, or turn it on by default once learned?")
scene(4 * FPS, end)

proc.stdin.close(); proc.wait()
print(f"wrote {OUT} frames={FRAME[0]} dur={FRAME[0]/FPS:.1f}s")
