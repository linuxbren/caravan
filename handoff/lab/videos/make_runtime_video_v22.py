# v22: Day 1 → Day 13 improvements (Day 14 break post). Based on v19; adds Day 13 (day13-gemma-prefix, day13-spc-learn) and milestones.
# v19: Day 12 vs Caravan v0 / v1 / v2 / v2.1 — writing, reading, wait before first word.
# Usage: make_runtime_video_v19.py out.mp4 v19_data.json [--stills dir] [--chart out.png]
# Numbers only from experiments.md (v0/v1 Oct 30 evening, v2 Oct 31, v2.1 Oct 31 LPM-off rerun)
# and handoff/lab/day12-speedups/idea1 + idea4, plus handoff/lab/v19-remeasure/RESULTS.md (Nov 4 re-measure)
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
    sys.exit("give a day label: --day 'Day 12' or --day-of YYYY-MM-DD")
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
        fig.savefig(os.path.join(STILLS, f"v22_t{t:04.1f}.png"), facecolor=BG)
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


def payoff(t):
    a = ease(t / 0.25)
    fig.text(0.5, 0.78, "Same long system prompt · a brand-new chat", color=MUTED, fontsize=26, ha="center", alpha=a)
    p = ease((t - 0.08) / 0.4)
    fig.text(0.5, 0.52, "First word ~2× sooner", color=AFTER, fontsize=64, weight="bold", ha="center", alpha=p)
PART = sys.argv[sys.argv.index("--part") + 1] if "--part" in sys.argv else "full"
CHART = sys.argv[sys.argv.index("--chart") + 1] if "--chart" in sys.argv else None
VC = {"v0": "#64748B", "v1": "#94A3B8", "v2": "#60A5FA", "v2.1": "#818CF8"}
def vcol(lab): return VC.get(lab, AFTER)

def bars(rows, t, top, unit, ymax):
    ax = fig.add_axes([0.08, 0.24, 0.86, 0.55], facecolor=BG)
    p = ease(t / 0.9)
    xs = range(len(rows))
    vals = [r[1] * p for r in rows]
    ax.bar(xs, vals, color=[vcol(r[0]) for r in rows], width=0.62)
    for i, r in enumerate(rows):
        ax.text(i, r[1] * p + ymax * 0.015, f"{r[1]:g}", color=FG, fontsize=22, ha="center", weight="bold", alpha=p)
        ax.text(i, -ymax * 0.07, r[0], color=FG, fontsize=18, ha="center", weight="bold")
        if len(r) > 2: ax.text(i, -ymax * 0.12, r[2], color=MUTED, fontsize=15, ha="center")
    ax.set_ylim(0, ymax); ax.set_xlim(-0.6, len(rows) - 0.4)
    ax.axis("off")
    ax.axvline(3.5, color=GRID, lw=2, ls="--")
    ax.text(1.5, ymax * 0.95, "one Mini", color=MUTED, fontsize=18, ha="center")
    ax.text(3.5 + (len(rows) - 4) / 2, ymax * 0.95, "two Minis (v3)", color=TWO, fontsize=18, ha="center")

def payoff(t):
    fig.text(0.5, 0.80, "Day 1 → Day 13 · same two Mac minis", color=MUTED, fontsize=26, ha="center", alpha=ease(t / 0.25))
    fig.text(0.5, 0.60, "Qwen3 writing 41.4 → 59.0 tok/s", color=AFTER, fontsize=56, weight="bold", ha="center", alpha=ease((t - 0.08) / 0.4))
    fig.text(0.5, 0.44, "Gemma new-chat wait 11.8 → 1.55 s", color=AFTER, fontsize=56, weight="bold", ha="center", alpha=ease((t - 0.3) / 0.4))
    fig.text(0.5, 0.30, "v0 one Mini (Oct 30) → v3 two Minis (Nov 4)", color=TWO, fontsize=24, ha="center", alpha=ease((t - 0.5) / 0.35))
    caption("13 days of Caravan · measured numbers only")
scene(3 * FPS, payoff)

def title(t):
    a = ease(t / 0.5)
    fig.text(0.5, 0.64, "Caravan: Day 1 → Day 13", color=FG, fontsize=60, weight="bold", ha="center", alpha=a)
    fig.text(0.5, 0.50, "Two Mac minis (M4, 24 GB) · four models · what each day added", color=FG, fontsize=26, ha="center", alpha=a)
    fig.text(0.5, 0.36, "Day 14 is a break, so here's the whole run", color=MUTED, fontsize=24, ha="center", alpha=a)
    caption("writing = tokens/sec out · reading = tokens/sec in · wait = seconds to first word")
scene(4 * FPS, title)

def miles(t):
    header("What each day added", "dates are build days · numbers from that day's write-up")
    for k, (dy, dt, txt) in enumerate(D["MILES"]):
        p = ease((t - 0.1 - 0.35 * k) / 0.45); y = 0.80 - 0.064 * k
        c = AFTER if dy == "Day 13" else TWO
        fig.text(0.07, y, dy, color=c, fontsize=21, weight="bold", va="center", alpha=p)
        fig.text(0.17, y, dt, color=MUTED, fontsize=17, va="center", alpha=p)
        fig.text(0.25, y, txt, color=FG, fontsize=19, va="center", alpha=p)
    caption("Each day's number is from its own test setup · not one continuous benchmark")
scene(16 * FPS, miles)

def versions(t):
    header("What each version was", "v0–v2.1 run on one Mini · v3 splits one model across two")
    for k, (v, d, h, s) in enumerate(D["VERSIONS"]):
        p = ease((t - 0.1 - 0.3 * k) / 0.45); y = 0.74 - 0.12 * k
        fig.patches.append(plt.Rectangle((0.07, y - 0.035), 0.012, 0.07, transform=fig.transFigure, color=vcol(v.split()[0]), figure=fig, alpha=p))
        fig.text(0.10, y + 0.015, f"{v}  ·  {d}", color=FG, fontsize=22, weight="bold", va="center", alpha=p)
        fig.text(0.36, y + 0.015, h, color=FG, fontsize=20, va="center", alpha=p)
        fig.text(0.36, y - 0.028, s, color=MUTED, fontsize=15, va="center", alpha=p)
    caption("v0 was llama.cpp only · MLX arrived in v1 · v3 is the two-Mini split")
scene(10 * FPS, versions)

def qwen(t):
    header("Writing speed: Qwen3 30B", "tokens/sec · one chat unless marked")
    bars(D["QWEN_WRITE"], t, 0, "tok/s", 80)
    caption("Split alone is slower than one Mini (45.4 vs 51.0) · guess-ahead and two chats pull ahead")
scene(12 * FPS, qwen)

def gemma(t):
    header("Writing speed: Gemma 4 26B", "tokens/sec · one chat unless marked")
    bars(D["GEMMA_WRITE"], t, 0, "tok/s", 65)
    caption("Guess-ahead skipped (inconsistent runs) · Nov 4 re-run of the plain split: 35.8")
scene(11 * FPS, gemma)

def gptoss(t):
    header("Writing speed: GPT-OSS 20B", "tokens/sec · one chat")
    bars(D["GPTOSS_WRITE"], t, 0, "tok/s", 50)
    caption("v3 split re-measured Nov 4 · no helper model fits GPT-OSS, so the split stays slower")
scene(9 * FPS, gptoss)

def llama(t):
    header("Writing speed: Llama 3.1 8B", "tokens/sec · v0 re-measured Nov 4 (GGUF) · v1–v2.1 re-measured Nov 4")
    bars(D["LLAMA_WRITE"], t, 0, "tok/s", 60)
    caption("Small model: one Mini and the split write about the same · guess-ahead doubles it")
scene(11 * FPS, llama)

def read(t):
    header("Reading speed (512-token prompt)", "tokens/sec · how fast it takes in your prompt")
    a = ease(t / 0.4)
    fig.text(0.50, 0.76, "Qwen3 30B", color=MUTED, fontsize=22, weight="bold", ha="center", alpha=a)
    fig.text(0.72, 0.76, "Gemma 4 26B", color=MUTED, fontsize=22, weight="bold", ha="center", alpha=a)
    for k, (v, q, g) in enumerate(D["READ"]):
        p = ease((t - 0.1 - 0.2 * k) / 0.4); y = 0.66 - 0.10 * k
        fig.text(0.12, y, v, color=FG, fontsize=24, weight="bold", va="center", alpha=p)
        for x, val in ((0.50, q), (0.72, g)):
            fig.text(x, y, f"{val:g}", color=AFTER if "v3" in v else FG, fontsize=28, weight="bold", ha="center", va="center", alpha=p)
    caption("Reading caught up in v1 and holds on the split (split re-measured Nov 4)")
scene(10 * FPS, read)

def race(t):
    header("Wait before the first word: new chat, same ~4k prompt", "seconds · Day 13 re-measure on the split · v2.1 / bare servers Nov 4")
    for lab, x in [("Qwen3", 0.36), ("Llama", 0.46), ("Gemma", 0.56)]:
        fig.text(x, 0.75, lab, color=MUTED, fontsize=20, weight="bold", ha="center", alpha=ease(t / 0.3))
    for k, (v, q, l, g, why) in enumerate(D["RACE"]):
        p = ease((t - 0.15 - 0.3 * k) / 0.45); y = 0.66 - 0.10 * k
        c = AFTER if "Day 13" in v else (MUTED if "bare" in v else FG)
        fig.text(0.05, y, v, color=c, fontsize=21, weight="bold", va="center", alpha=p)
        for x, val in ((0.36, q), (0.46, l), (0.56, g)):
            fig.text(x, y, val, color=c, fontsize=24, weight="bold", ha="center", va="center", alpha=p)
        fig.text(0.63, y, why, color=MUTED, fontsize=15, va="center", alpha=p)
    caption("Bare servers share one cache across all chats, so it's not like-for-like · Caravan keeps chats apart")
scene(14 * FPS, race)

def learn(t):
    header("Day 13: it tunes shared start itself", "first 7 chats with a model: try off, try on, keep the winner · mean wait, seconds")
    fig.text(0.45, 0.72, "off (cold)", color=MUTED, fontsize=20, weight="bold", ha="center", alpha=ease(t / 0.3))
    fig.text(0.65, 0.72, "on (reused)", color=MUTED, fontsize=20, weight="bold", ha="center", alpha=ease(t / 0.3))
    for k, (m, off, on) in enumerate(D["LEARN"]):
        p = ease((t - 0.15 - 0.3 * k) / 0.45); y = 0.60 - 0.12 * k
        fig.text(0.10, y, m, color=FG, fontsize=24, weight="bold", va="center", alpha=p)
        fig.text(0.45, y, off, color=FG, fontsize=28, weight="bold", ha="center", va="center", alpha=p)
        fig.text(0.65, y, on, color=AFTER, fontsize=28, weight="bold", ha="center", va="center", alpha=p)
        fig.text(0.78, y, "chose on", color=TWO, fontsize=20, va="center", alpha=p)
    caption("Different setup from the race (longer tool prompt, more reused) · Gemma pays ~23 s once to set up")
scene(11 * FPS, learn)

def take(t):
    header("Takeaways", "Day 1 → Day 13")
    T = [("ON", "One Mini got faster at writing (v0 → v2.1)", "Qwen3 41.4 → 51.0 · Gemma 34.4 → 41.3 · Llama 21.2 → 23.3 tok/s"),
         ("OFF", "Splitting across two Minis costs speed on its own", "Qwen3 51.0 one Mini vs 45.4 split · GPT-OSS 36.5 vs 31.9"),
         ("ON", "Later days win it back and more", "guess-ahead Qwen3 59.0 · Llama 49.7 · two chats Qwen3 72.5 total"),
         ("ONE", "Waiting for a new chat: halved on Days 12–13, Gemma ~7.6×", "Qwen3 9.3 → 5.0 · Llama 17.5 → 8.9 · Gemma 11.8 → 1.55 s"),
         ("OFF", "Still missing", "GPT-OSS has no guesser · Gemma guess-ahead inconsistent · reading on split ≈ one Mini")]
    for k, (tone, h, d) in enumerate(T):
        p = ease((t - 0.1 - 0.25 * k) / 0.45); y = 0.76 - 0.12 * k
        c = TWO if tone == "ON" else (THREE if tone == "ONE" else MUTED)
        fig.patches.append(plt.Rectangle((0.07, y - 0.035), 0.012, 0.07, transform=fig.transFigure, color=c, figure=fig, alpha=p))
        fig.text(0.11, y + 0.018, h, color=FG, fontsize=21, weight="bold", va="center", alpha=p)
        fig.text(0.11, y - 0.028, d, color=MUTED, fontsize=16, va="center", alpha=p)
    caption("v0 is llama.cpp, later MLX · numbers from separate sessions, ±~6% day to day")
scene(13 * FPS, take)

def end(t):
    a = ease(t / 0.5)
    fig.text(0.5, 0.62, "Next: try it yourself.", color=AFTER, fontsize=50, weight="bold", ha="center", alpha=a)
    fig.text(0.5, 0.47, "A web page to pick a model, chat, and see the timing of every reply", color=FG, fontsize=24, ha="center", alpha=a)
    fig.text(0.5, 0.32, "Day 1 → Day 13 · Caravan", color=MUTED, fontsize=24, ha="center", alpha=a)
    caption("Measured numbers only · missing cells marked")
scene(5 * FPS, end)
proc.stdin.close(); proc.wait()
print(f"wrote {OUT} frames={FRAME[0]} dur={FRAME[0]/FPS:.1f}s")

if CHART:
    f2, axs = plt.subplots(2, 2, figsize=(16, 12), facecolor=BG); axs = axs.ravel()
    for ax, key, ttl in [(axs[0], "QWEN_WRITE", "Qwen3 30B writing (tok/s)"), (axs[1], "GEMMA_WRITE", "Gemma 4 26B writing (tok/s)"), (axs[2], "LLAMA_WRITE", "Llama 3.1 8B writing (tok/s)"), (axs[3], "GPTOSS_WRITE", "GPT-OSS 20B writing (tok/s)")]:
        rows = D[key]; ax.set_facecolor(BG)
        b = ax.bar([f"{r[0]}\n{r[2]}" for r in rows], [r[1] for r in rows], color=[vcol(r[0]) for r in rows])
        for bb, r in zip(b, rows): ax.text(bb.get_x() + bb.get_width() / 2, r[1] + 1, f"{r[1]:g}", color=FG, ha="center", fontsize=13, weight="bold")
        ax.set_title(ttl, color=FG, fontsize=18, weight="bold"); ax.tick_params(colors=FG, labelsize=11)
        for s in ax.spines.values(): s.set_color(GRID)
    f2.suptitle("Caravan Day 1 (v0) → Day 13 (v3) · v0–v2.1 one Mini · v3 split across two Minis", color=MUTED, fontsize=15)
    f2.tight_layout(); f2.savefig(CHART, facecolor=BG, dpi=120); print("chart", CHART)
