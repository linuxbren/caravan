# v17: Day 10 learn-from-chats — race, trap, second load, trust checks.
# Usage: make_runtime_video_v17.py out.mp4 v17_data.json --day "Day 10" --part 1|2 [--stills dir]
# Numbers only from day10-all-models-scoreboard.json + llama/qwen3 result JSONs.
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
PART = int(sys.argv[sys.argv.index("--part") + 1]) if "--part" in sys.argv else 1
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
    sys.exit("give a day label: --day 'Day 10' or --day-of YYYY-MM-DD")
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
        fig.savefig(os.path.join(STILLS, f"v17p{PART}_t{t:04.1f}.png"), facecolor=BG)
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

race = D["RACE"]
trap = D["TRAP"]
svb = D["SINGLE_VS_BOTH"]
cost = D["COST"]
qual = D["QUALITY"]
pull = D["PULL_PLUG"]
longp = D["LONG_PROMPT"]

# ========== PART 1: It tunes itself ==========
if PART == 1:

    def payoff(t):
        a = ease(t / 0.25)
        fig.text(0.5, 0.78, "No flags. No saved settings. Just replies.", color=MUTED, fontsize=28, ha="center", alpha=a)
        p = ease((t - 0.08) / 0.4)
        fig.text(0.5, 0.52, "It tunes itself", color=AFTER, fontsize=72, weight="bold", ha="center", alpha=p)
        fig.text(0.5, 0.34, "Day 9's guess was already right — on all 6 models",
                 color=TWO, fontsize=26, ha="center", alpha=ease((t - 0.45) / 0.35), weight="bold")
        fig.text(0.5, 0.22, "then a trap forced a relearn from real chats",
                 color=MUTED, fontsize=22, ha="center", alpha=ease((t - 0.55) / 0.35))
        caption(f"{DAY}: learn from chats — part 1 · It tunes itself")
    scene(3 * FPS, payoff)

    def title(t):
        a = ease(t / 0.5)
        fig.text(0.5, 0.64, "Learn from chats", color=FG, fontsize=64, weight="bold", ha="center", alpha=a)
        fig.text(0.5, 0.50, "Caravan tries chat counts, keeps the fast one, saves it", color=FG, fontsize=26, ha="center", alpha=a)
        fig.text(0.5, 0.36, f"{DAY} of building Caravan  ·  two Mac minis over Thunderbolt",
                 color=MUTED, fontsize=24, ha="center", alpha=a)
        caption("Overlapping chats = several people talking at once · writing speed = tokens per second")
    scene(5 * FPS, title)

    def race_scene(t):
        header("The race", "no flags · no saved file · just replies until it settles")
        fig.text(0.05, 0.80, "Honest note: Day 9's memory-based guess (2 chats) was already right on every model.",
                 color=TWO, fontsize=20, va="center", weight="bold",
                 alpha=ease(t / 0.35))
        # table header
        for i, (lab, x) in enumerate([("Model", 0.08), ("Day 9 guess", 0.42), ("Learned", 0.62), ("Writing speed", 0.78)]):
            fig.text(x, 0.72, lab, color=MUTED, fontsize=18, va="center", alpha=ease((t - 0.15) / 0.3))
        for k, m in enumerate(race):
            p = ease((t - 0.25 - 0.12 * k) / 0.4)
            y = 0.64 - 0.075 * k
            fig.text(0.08, y, m["name"], color=FG, fontsize=20, va="center", alpha=p, weight="bold")
            fig.text(0.45, y, f'{m["day9"]} chats', color=ONE, fontsize=20, va="center", alpha=p, ha="center")
            fig.text(0.64, y, f'{m["learned"]} chats', color=AFTER, fontsize=20, va="center", alpha=p, ha="center", weight="bold")
            fig.text(0.88, y, f'{m["single"]:.1f}', color=FG, fontsize=20, va="center", alpha=p, ha="right")
        caption("Hand-tuned was already ~same speed · the race did not climb past Day 9's pick")
    scene(12 * FPS, race_scene)

    def trap_scene(t):
        header("The trap (Qwen3 first)", "seeded wrong at 1 overlapping chat · watch it fix itself")
        # two big numbers
        a = ease(t / 0.4)
        box(0.08, 0.38, 0.38, 0.38, BEFORE, a)
        box(0.54, 0.38, 0.38, 0.38, AFTER, a)
        fig.text(0.27, 0.68, "1 chat at a time", color=BEFORE, fontsize=22, ha="center", alpha=a, weight="bold")
        fig.text(0.27, 0.55, f'{trap["probe_n1"]}', color=BEFORE, fontsize=64, ha="center", alpha=a, weight="bold")
        fig.text(0.27, 0.42, "tok/s writing speed", color=MUTED, fontsize=18, ha="center", alpha=a)
        fig.text(0.73, 0.68, "2 chats at once", color=AFTER, fontsize=22, ha="center", alpha=a, weight="bold")
        fig.text(0.73, 0.55, f'{trap["probe_n2"]}', color=AFTER, fontsize=64, ha="center", alpha=a, weight="bold")
        fig.text(0.73, 0.42, "tok/s writing speed", color=MUTED, fontsize=18, ha="center", alpha=a)
        fig.text(0.5, 0.28, f'Flipped back to 2 chats by reply {trap["switch_at"]}',
                 color=TWO, fontsize=28, ha="center", weight="bold", alpha=ease((t - 0.5) / 0.4))
        caption("Probe means from fair concurrent tests · trap started at N=1, relearned N=2")
    scene(11 * FPS, trap_scene)

    def second(t):
        header("Second load", "restart with the saved file · no rediscovery")
        box(0.06, 0.22, 0.88, 0.55, THREE, ease(t / 0.3), fc=TERM, lw=2)
        for k, line in enumerate(D["SECOND_LOAD"]):
            p = ease((t - 0.2 - 0.35 * k) / 0.45)
            y = 0.68 - 0.11 * k
            color = AFTER if "learned" in line else (TWO if "keep" in line else FG)
            fig.text(0.09, y, "› " + line, color=color, fontsize=17, va="center", alpha=p, family="monospace")
        caption("Saved winner loads first · Caravan still gently re-checks, then keeps the winner")
    scene(10 * FPS, second)

    def one_vs_both(t):
        header("One Mini vs both", "Llama 8B · can overlapping chats help on a single machine?")
        a = ease(t / 0.35)
        box(0.10, 0.30, 0.35, 0.42, BEFORE, a)
        box(0.55, 0.30, 0.35, 0.42, AFTER, a)
        fig.text(0.275, 0.66, "One Mini alone", color=BEFORE, fontsize=24, ha="center", alpha=a, weight="bold")
        fig.text(0.275, 0.52, f'{svb["one_mini_mean"]}', color=BEFORE, fontsize=56, ha="center", alpha=a, weight="bold")
        fig.text(0.275, 0.40, "tok/s · settles at 1 chat", color=MUTED, fontsize=18, ha="center", alpha=a)
        fig.text(0.725, 0.66, "Both Minis (split)", color=AFTER, fontsize=24, ha="center", alpha=a, weight="bold")
        fig.text(0.725, 0.52, f'{svb["both_single_mean"]}', color=AFTER, fontsize=56, ha="center", alpha=a, weight="bold")
        fig.text(0.725, 0.40, f'tok/s · settles at {svb["both_winner_chats"]} chats', color=MUTED, fontsize=18, ha="center", alpha=a)
        fig.text(0.5, 0.22, f'Hand-tuned on both was {svb["hand_tuned_both"]} — learned single-chat mean is close',
                 color=TWO, fontsize=20, ha="center", alpha=ease((t - 0.4) / 0.4))
        caption("Two chats help when the model is split across two machines — not when one Mini holds it all")
    scene(10 * FPS, one_vs_both)

    def take1(t):
        header("Takeaways", f"{DAY} · part 1 · It tunes itself")
        for k, (tone, h, d) in enumerate(D["TAKE1"]):
            p = ease((t - 0.1 - 0.28 * k) / 0.45); y = 0.72 - 0.13 * k
            c = TWO if tone == "ON" else (THREE if tone == "ONE" else MUTED)
            fig.patches.append(plt.Rectangle((0.07, y - 0.035), 0.012, 0.07, transform=fig.transFigure, color=c, figure=fig, alpha=p))
            fig.text(0.11, y + 0.018, h, color=FG, fontsize=22, weight="bold", va="center", alpha=p)
            fig.text(0.11, y - 0.028, d, color=MUTED, fontsize=17, va="center", alpha=p)
        caption(f"{DAY} · next: can you trust what it learned?")
    scene(10 * FPS, take1)

    def end1(t):
        a = ease(t / 0.5)
        fig.text(0.5, 0.60, "It tunes itself.", color=AFTER, fontsize=52, weight="bold", ha="center", alpha=a)
        fig.text(0.5, 0.44, "Day 9 guessed right · the trap still relearned · second load remembers",
                 color=FG, fontsize=24, ha="center", alpha=a)
        fig.text(0.5, 0.30, f"{DAY} · part 1 of 2 · Can you trust it? next",
                 color=MUTED, fontsize=22, ha="center", alpha=a)
        caption("Part 2: quality, learning cost, pull-the-plug, long prompts, scoreboard")
    scene(4 * FPS, end1)

# ========== PART 2: Can you trust it? ==========
else:

    def payoff2(t):
        a = ease(t / 0.25)
        fig.text(0.5, 0.78, "Learning is fine — but does the answer stay right?", color=MUTED, fontsize=26, ha="center", alpha=a)
        p = ease((t - 0.08) / 0.4)
        fig.text(0.5, 0.52, "12 / 12 on all six", color=AFTER, fontsize=68, weight="bold", ha="center", alpha=p)
        fig.text(0.5, 0.34, "quality checks passed · thinking models scored on the final answer",
                 color=TWO, fontsize=22, ha="center", alpha=ease((t - 0.45) / 0.35), weight="bold")
        fig.text(0.5, 0.22, "plus cost, pull-the-plug, and long-prompt checks",
                 color=MUTED, fontsize=22, ha="center", alpha=ease((t - 0.55) / 0.35))
        caption(f"{DAY}: learn from chats — part 2 · Can you trust it?")
    scene(3 * FPS, payoff2)

    def title2(t):
        a = ease(t / 0.5)
        fig.text(0.5, 0.64, "Can you trust it?", color=FG, fontsize=64, weight="bold", ha="center", alpha=a)
        fig.text(0.5, 0.50, "Quality, learning cost, restart, and long prompts", color=FG, fontsize=26, ha="center", alpha=a)
        fig.text(0.5, 0.36, f"{DAY} of building Caravan  ·  same six models",
                 color=MUTED, fontsize=24, ha="center", alpha=a)
        caption("Plain checks · real measured numbers · no hand-tuned vs learned time claim")
    scene(4 * FPS, title2)

    def quality(t):
        header("Quality check", "12 prompts × 6 models · score the final answer only")
        a = ease(t / 0.4)
        fig.text(0.5, 0.55, f'{qual["passed"]} / {qual["total"]}', color=AFTER, fontsize=96, weight="bold", ha="center", alpha=a)
        fig.text(0.5, 0.38, f'passed on every model ({qual["models"]} of {qual["models"]})',
                 color=FG, fontsize=28, ha="center", alpha=ease((t - 0.3) / 0.4))
        fig.text(0.5, 0.26, "Thinking models hide a draft — we only graded the visible final answer",
                 color=MUTED, fontsize=20, ha="center", alpha=ease((t - 0.45) / 0.4))
        caption("Same gate as guess-ahead · letter spell-outs like C-A-T count as cat")
    scene(9 * FPS, quality)

    def cost_scene(t):
        header("The cost of learning", "Llama · explore replies vs keep-the-winner replies")
        a = ease(t / 0.35)
        box(0.10, 0.30, 0.35, 0.42, BEFORE, a)
        box(0.55, 0.30, 0.35, 0.42, AFTER, a)
        fig.text(0.275, 0.66, f'Explore ({cost["explore_n"]} of {cost["total_n"]})', color=BEFORE, fontsize=22, ha="center", alpha=a, weight="bold")
        fig.text(0.275, 0.52, f'~{cost["explore_mean"]}', color=BEFORE, fontsize=56, ha="center", alpha=a, weight="bold")
        fig.text(0.275, 0.40, "tok/s while probing", color=MUTED, fontsize=18, ha="center", alpha=a)
        fig.text(0.725, 0.66, f'Keep ({cost["total_n"] - cost["explore_n"]} of {cost["total_n"]})', color=AFTER, fontsize=22, ha="center", alpha=a, weight="bold")
        fig.text(0.725, 0.52, f'~{cost["keep_mean"]}', color=AFTER, fontsize=56, ha="center", alpha=a, weight="bold")
        fig.text(0.725, 0.40, "tok/s on the winner", color=MUTED, fontsize=18, ha="center", alpha=a)
        fig.text(0.5, 0.22, f'About {cost["slowdown_pct"]}% slower on those explore replies — then back to normal',
                 color=TWO, fontsize=22, ha="center", weight="bold", alpha=ease((t - 0.4) / 0.4))
        caption("We did not time hand-tuned vs learned end-to-end — only this explore tax")
    scene(10 * FPS, cost_scene)

    def pull_scene(t):
        header("Pull the plug", "kill mid-run · restart · resume from the saved file")
        a = ease(t / 0.35)
        fig.text(0.5, 0.70, "Saved file was on disk mid-run", color=TWO, fontsize=26, ha="center", alpha=a, weight="bold")
        fig.text(0.5, 0.55, f'After restart: learned pipeline chats = {pull["after_winner_chats"]}',
                 color=AFTER, fontsize=32, ha="center", alpha=ease((t - 0.2) / 0.4), weight="bold")
        # little tps row
        fig.text(0.5, 0.40, "Next replies (tok/s):  " + "  ·  ".join(f"{x:.1f}" for x in pull["after_tps"]),
                 color=FG, fontsize=24, ha="center", alpha=ease((t - 0.4) / 0.4))
        fig.text(0.5, 0.26, "Same winner came back — no cold rediscovery from zero",
                 color=MUTED, fontsize=20, ha="center", alpha=ease((t - 0.55) / 0.35))
        caption("File on disk beats starting over · Caravan still re-checks gently after load")
    scene(9 * FPS, pull_scene)

    def long_scene(t):
        header("Long-prompt switch?", "Do long prompts flip the chat-count winner?")
        a = ease(t / 0.35)
        box(0.10, 0.32, 0.35, 0.40, ONE, a)
        box(0.55, 0.32, 0.35, 0.40, AFTER, a)
        fig.text(0.275, 0.64, "Short prompts", color=ONE, fontsize=22, ha="center", alpha=a, weight="bold")
        fig.text(0.275, 0.52, " · ".join(f"{x:.0f}" for x in longp["short_sample"]),
                 color=FG, fontsize=22, ha="center", alpha=a)
        fig.text(0.275, 0.40, f'stayed at {longp["winner_chats"]} chats', color=MUTED, fontsize=18, ha="center", alpha=a)
        fig.text(0.725, 0.64, "Long prompts", color=AFTER, fontsize=22, ha="center", alpha=a, weight="bold")
        fig.text(0.725, 0.52, " · ".join(f"{x:.0f}" for x in longp["long_sample"]),
                 color=FG, fontsize=22, ha="center", alpha=a)
        fig.text(0.725, 0.40, f'stayed at {longp["winner_chats"]} chats', color=MUTED, fontsize=18, ha="center", alpha=a)
        fig.text(0.5, 0.24, "No flip — long prompts kept the same overlapping-chat winner",
                 color=TWO, fontsize=22, ha="center", weight="bold", alpha=ease((t - 0.4) / 0.4))
        caption("Llama · short and long samples both held pipeline chats = 2")
    scene(9 * FPS, long_scene)

    def scoreboard(t):
        header("All-models scoreboard", "learned single-chat writing speed · Day 9 guess was right on all six")
        ax = fig.add_axes([0.08, 0.18, 0.84, 0.58])
        ax.set_facecolor(BG)
        for s in ax.spines.values(): s.set_visible(False)
        ax.tick_params(colors=FG, labelsize=16, length=0)
        ax.yaxis.set_tick_params(labelsize=14, labelcolor=MUTED)
        ax.grid(axis="y", color=GRID, lw=1); ax.set_axisbelow(True)
        labels = [m["name"].replace(" ", "\n") for m in race]
        n = len(race)
        ax.set_xticks(range(n)); ax.set_xticklabels(labels, fontsize=13)
        ax.set_ylim(0, 55); ax.set_xlim(-0.55, n - 0.45)
        w = 0.36
        for m_i, m in enumerate(race):
            for r, (key, c) in enumerate([("hand", ONE), ("single", AFTER)]):
                v = m[key]; x = m_i + (r - 0.5) * w
                p = ease((t - 0.1 - 0.12 * m_i - 0.04 * r) / 0.8)
                ax.bar(x, v * p, w * 0.88, color=c, alpha=1,
                       edgecolor=FG if key == "single" else "none", lw=1.5 if key == "single" else 0)
                if p > 0.08:
                    ax.text(x, v * p + 1.2, f"{v:.1f}", color=FG, fontsize=14, weight="bold", ha="center")
        fig.patches.append(plt.Rectangle((0.08, 0.80), 0.014, 0.018, transform=fig.transFigure, color=ONE, figure=fig))
        fig.text(0.10, 0.809, "hand-tuned (Day 9)", color=FG, fontsize=16, va="center")
        fig.patches.append(plt.Rectangle((0.36, 0.80), 0.014, 0.018, transform=fig.transFigure, color=AFTER, figure=fig))
        fig.text(0.38, 0.809, "learned single-chat mean", color=FG, fontsize=16, va="center", weight="bold")
        caption("Quality 12/12 · trap relearned on every model · hand-tuned vs learned wall time not measured")
    scene(13 * FPS, scoreboard)

    def take2(t):
        header("Takeaways", f"{DAY} · part 2 · Can you trust it?")
        for k, (tone, h, d) in enumerate(D["TAKE2"]):
            p = ease((t - 0.1 - 0.28 * k) / 0.45); y = 0.72 - 0.13 * k
            c = TWO if tone == "ON" else (THREE if tone == "ONE" else MUTED)
            fig.patches.append(plt.Rectangle((0.07, y - 0.035), 0.012, 0.07, transform=fig.transFigure, color=c, figure=fig, alpha=p))
            fig.text(0.11, y + 0.018, h, color=FG, fontsize=22, weight="bold", va="center", alpha=p)
            fig.text(0.11, y - 0.028, d, color=MUTED, fontsize=17, va="center", alpha=p)
        caption(f"{DAY} · Caravan MLX split · ROADMAP #13b learn-from-chats")
    scene(10 * FPS, take2)

    def end2(t):
        a = ease(t / 0.5)
        fig.text(0.5, 0.60, "You can trust the answers.", color=AFTER, fontsize=48, weight="bold", ha="center", alpha=a)
        fig.text(0.5, 0.44, "12/12 · ~30% explore tax · plug-pull resumes · long prompts held",
                 color=FG, fontsize=22, ha="center", alpha=a)
        fig.text(0.5, 0.28, f"{DAY} · Caravan  ·  #13b shipped", color=MUTED, fontsize=24, ha="center", alpha=a)
        caption("Ship the learn file by default, or keep it opt-in behind a flag?")
    scene(4 * FPS, end2)

proc.stdin.close(); proc.wait()
print(f"wrote {OUT} part={PART} frames={FRAME[0]} dur={FRAME[0]/FPS:.1f}s")
