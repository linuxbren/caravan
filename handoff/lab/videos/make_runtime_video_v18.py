# v18: Day 12 five easy speedups — shared prefix win, guess-ahead confirmed,
# stack no-go, look-back mixed, fused parked, MTP blocked.
# Usage: make_runtime_video_v18.py out.mp4 v18_data.json --day "Day 12" [--stills dir]
# Numbers only from handoff/lab/day12-fused/ + day12-speedups/ + experiments.md Day 12.
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
        fig.savefig(os.path.join(STILLS, f"v18_t{t:04.1f}.png"), facecolor=BG)
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

pfx = D["PREFIX"]
guess = D["GUESS"]
stack = D["STACK"]
lb = D["LOOKBACK"]
fused = D["FUSED"]
mtp = D["MTP"]

# --- 0. PAYOFF first ~3s ---
def payoff(t):
    a = ease(t / 0.25)
    fig.text(0.5, 0.78, "Same long system prompt · a brand-new chat", color=MUTED, fontsize=26, ha="center", alpha=a)
    p = ease((t - 0.08) / 0.4)
    fig.text(0.5, 0.52, "First word ~2× sooner", color=AFTER, fontsize=64, weight="bold", ha="center", alpha=p)
    fig.text(0.5, 0.34, f"Llama  {pfx['llama_off']}→{pfx['llama_on']} s   ·   Qwen3  {pfx['qwen_off']}→{pfx['qwen_on']} s",
             color=TWO, fontsize=26, ha="center", alpha=ease((t - 0.45) / 0.35), weight="bold")
    fig.text(0.5, 0.22, "wait before the first word · big model split across two Mac minis",
             color=MUTED, fontsize=22, ha="center", alpha=ease((t - 0.55) / 0.35))
    caption(f"{DAY}: five easy speedups — shared start of chats wins")
scene(3 * FPS, payoff)

# --- 1. Title ---
def title(t):
    a = ease(t / 0.5)
    fig.text(0.5, 0.64, "Five easy speedups", color=FG, fontsize=60, weight="bold", ha="center", alpha=a)
    fig.text(0.5, 0.50, "Tried on a big model split across two Mac minis", color=FG, fontsize=26, ha="center", alpha=a)
    fig.text(0.5, 0.36, f"{DAY} of building Caravan  ·  Thunderbolt between the Minis",
             color=MUTED, fontsize=24, ha="center", alpha=a)
    caption("writing speed = tokens/sec  ·  wait = seconds before the first word")
scene(4 * FPS, title)

# --- 2. Shared prefix WIN ---
def prefix_scene(t):
    header("Win: shared start of chats", "reuse a long system prompt across new chats · first word arrives sooner")
    a = ease(t / 0.35)
    # Llama box
    box(0.08, 0.30, 0.38, 0.48, BEFORE if t < 0.6 else AFTER, a)
    box(0.54, 0.30, 0.38, 0.48, AFTER, a)
    fig.text(0.27, 0.70, "Llama 8B", color=FG, fontsize=24, ha="center", alpha=a, weight="bold")
    fig.text(0.27, 0.58, f"{pfx['llama_off']} → {pfx['llama_on']} s", color=AFTER, fontsize=40, ha="center", alpha=a, weight="bold")
    fig.text(0.27, 0.46, f"~{pfx['llama_pct']}% faster first word", color=TWO, fontsize=20, ha="center", alpha=a)
    fig.text(0.27, 0.36, "cold → shared start", color=MUTED, fontsize=18, ha="center", alpha=a)
    fig.text(0.73, 0.70, "Qwen3 30B", color=FG, fontsize=24, ha="center", alpha=a, weight="bold")
    fig.text(0.73, 0.58, f"{pfx['qwen_off']} → {pfx['qwen_on']} s", color=AFTER, fontsize=40, ha="center", alpha=a, weight="bold")
    fig.text(0.73, 0.46, f"~{pfx['qwen_pct']}% faster first word", color=TWO, fontsize=20, ha="center", alpha=a)
    fig.text(0.73, 0.36, "cold → shared start", color=MUTED, fontsize=18, ha="center", alpha=a)
    fig.text(0.5, 0.22, "Not a writing-speed win — it shortens the wait before the reply starts",
             color=MUTED, fontsize=20, ha="center", alpha=ease((t - 0.4) / 0.4))
    caption("Agent-style chats often reuse the same long system prompt · Gemma still needs a packer fix")
scene(11 * FPS, prefix_scene)

# --- 3. Guess-ahead confirmed ---
def guess_scene(t):
    header("Confirmed: guess-ahead on one chat", "a tiny helper drafts the next words · the big model checks them in one trip")
    a = ease(t / 0.35)
    for k, m in enumerate(guess):
        p = ease((t - 0.15 - 0.25 * k) / 0.45)
        x0 = 0.08 + k * 0.46
        box(x0, 0.28, 0.40, 0.48, AFTER, p)
        fig.text(x0 + 0.20, 0.68, m["name"], color=FG, fontsize=24, ha="center", alpha=p, weight="bold")
        fig.text(x0 + 0.20, 0.55, f'{m["off"]} → {m["on"]}', color=AFTER, fontsize=44, ha="center", alpha=p, weight="bold")
        fig.text(x0 + 0.20, 0.42, "tok/s writing speed", color=MUTED, fontsize=18, ha="center", alpha=p)
        fig.text(x0 + 0.20, 0.34, f'+{m["pct"]}%', color=TWO, fontsize=28, ha="center", alpha=p, weight="bold")
    caption("One chat at a time · Gemma's number skipped (inconsistent between runs)")
scene(10 * FPS, guess_scene)

# --- 4. Stack no-go ---
def stack_scene(t):
    header("Didn't stack: two chats + guess-ahead", "two chats alone still help · adding guess-ahead made guesses worse")
    # table header
    for lab, x in [("Model", 0.08), ("2 chats alone", 0.38), ("2 chats + guess", 0.60), ("Guesses accepted", 0.82)]:
        fig.text(x, 0.74, lab, color=MUTED, fontsize=18, va="center", alpha=ease(t / 0.3))
    for k, m in enumerate(stack):
        p = ease((t - 0.2 - 0.15 * k) / 0.4)
        y = 0.62 - 0.12 * k
        fig.text(0.08, y, m["name"], color=FG, fontsize=22, va="center", alpha=p, weight="bold")
        fig.text(0.45, y, f'{m["n2_off"]}', color=AFTER, fontsize=24, va="center", alpha=p, ha="center", weight="bold")
        fig.text(0.66, y, f'{m["n2_on"]}', color=BEFORE, fontsize=24, va="center", alpha=p, ha="center", weight="bold")
        fig.text(0.90, y, f'{m["accept"]:.2f}', color=BEFORE, fontsize=22, va="center", alpha=p, ha="right")
    fig.text(0.5, 0.22, "Total writing across chats · guesses collapse when chats share the Minis",
             color=MUTED, fontsize=20, ha="center", alpha=ease((t - 0.5) / 0.4))
    caption("Two chats without guessing still ~1.6–1.8× total words/sec · leave them separate for now")
scene(11 * FPS, stack_scene)

# --- 5. Look-back mixed ---
def lookback_scene(t):
    header("Mixed: look-back per message", "only flip on when the reply is copying text from the prompt")
    a = ease(t / 0.35)
    box(0.08, 0.32, 0.38, 0.42, AFTER, a)
    box(0.54, 0.32, 0.38, 0.42, BEFORE, a)
    fig.text(0.27, 0.66, "Copy-text prompt", color=AFTER, fontsize=22, ha="center", alpha=a, weight="bold")
    fig.text(0.27, 0.52, f'{lb["qwen_repeat_off"]} → {lb["qwen_repeat_on"]}', color=AFTER, fontsize=40, ha="center", alpha=a, weight="bold")
    fig.text(0.27, 0.40, "Qwen3 tok/s · helped", color=MUTED, fontsize=18, ha="center", alpha=a)
    fig.text(0.73, 0.66, "One code prompt", color=BEFORE, fontsize=22, ha="center", alpha=a, weight="bold")
    fig.text(0.73, 0.52, f'{lb["qwen_code_off"]} → {lb["qwen_code_on"]}', color=BEFORE, fontsize=40, ha="center", alpha=a, weight="bold")
    fig.text(0.73, 0.40, "Qwen3 tok/s · hurt", color=MUTED, fontsize=18, ha="center", alpha=a)
    fig.text(0.5, 0.24, "Stays off by default · stricter gate after the false positives",
             color=TWO, fontsize=22, ha="center", weight="bold", alpha=ease((t - 0.4) / 0.4))
    caption("Look-back = matching n-grams already in the prompt · not a trained helper")
scene(10 * FPS, lookback_scene)

# --- 6. Fused parked ---
def fused_scene(t):
    header("Parked: fused kernels", "combine GPU steps · MLX already does the easy ones")
    for lab, x in [("Model", 0.08), ("Where", 0.36), ("Off", 0.58), ("On", 0.74), ("Δ", 0.88)]:
        fig.text(x, 0.74, lab, color=MUTED, fontsize=18, va="center", alpha=ease(t / 0.3))
    for k, m in enumerate(fused):
        p = ease((t - 0.15 - 0.12 * k) / 0.4)
        y = 0.64 - 0.10 * k
        fig.text(0.08, y, m["name"], color=FG, fontsize=20, va="center", alpha=p, weight="bold")
        fig.text(0.36, y, m["where"], color=MUTED, fontsize=18, va="center", alpha=p)
        fig.text(0.60, y, f'{m["off"]}', color=ONE, fontsize=20, va="center", alpha=p, ha="center")
        fig.text(0.76, y, f'{m["on"]}', color=FG, fontsize=20, va="center", alpha=p, ha="center")
        delta = (m["on"] - m["off"]) / m["off"] * 100
        fig.text(0.90, y, f'{delta:+.1f}%', color=MUTED, fontsize=20, va="center", alpha=p, ha="right")
    fig.text(0.5, 0.22, "*Gemma: only one fusion (custom SwiGLU) — fused attention crashes on its head size",
             color=MUTED, fontsize=18, ha="center", alpha=ease((t - 0.45) / 0.35))
    caption("Biggest change anywhere ~±0.5% · quality 3/3 · park unless custom Metal matmul later")
scene(11 * FPS, fused_scene)

# --- 7. MTP blocked ---
def mtp_scene(t):
    header("Blocked: the model's own guesser", "recover built-in guess heads if a model ships them")
    a = ease(t / 0.4)
    fig.text(0.5, 0.58, f'{mtp["with_mtp"]} / {mtp["models_checked"]}', color=BEFORE, fontsize=96, weight="bold", ha="center", alpha=a)
    fig.text(0.5, 0.40, "of our models ship a built-in guesser", color=FG, fontsize=28, ha="center", alpha=ease((t - 0.25) / 0.4))
    fig.text(0.5, 0.26, f'Waiting on {mtp["waiting_on"]}',
             color=TWO, fontsize=24, ha="center", weight="bold", alpha=ease((t - 0.45) / 0.4))
    caption("Not that MLX stripped them — the originals never had them · helper drafts still work")
scene(9 * FPS, mtp_scene)

# --- 8. Takeaways ---
def take(t):
    header("Takeaways", f"{DAY} · five easy speedups on the two-Mini split")
    for k, (tone, h, d) in enumerate(D["TAKE"]):
        p = ease((t - 0.1 - 0.25 * k) / 0.45); y = 0.74 - 0.13 * k
        c = TWO if tone == "ON" else (THREE if tone == "ONE" else MUTED)
        fig.patches.append(plt.Rectangle((0.07, y - 0.035), 0.012, 0.07, transform=fig.transFigure, color=c, figure=fig, alpha=p))
        fig.text(0.11, y + 0.018, h, color=FG, fontsize=21, weight="bold", va="center", alpha=p)
        fig.text(0.11, y - 0.028, d, color=MUTED, fontsize=16, va="center", alpha=p)
    caption(f"{DAY} · Caravan MLX split · shared-prefix flag off by default")
scene(12 * FPS, take)

# --- 9. End ---
def end(t):
    a = ease(t / 0.5)
    fig.text(0.5, 0.62, "Shared starts cut the wait in half.", color=AFTER, fontsize=44, weight="bold", ha="center", alpha=a)
    fig.text(0.5, 0.46, "Guess-ahead still the writing win · stacking with two chats does not · fuse parked",
             color=FG, fontsize=20, ha="center", alpha=a)
    fig.text(0.5, 0.30, f"{DAY} · Caravan  ·  five easy speedups", color=MUTED, fontsize=24, ha="center", alpha=a)
    caption("Ship shared-prefix on by default, or keep it opt-in until Gemma's packer trim is fixed?")
scene(4 * FPS, end)

proc.stdin.close(); proc.wait()
print(f"wrote {OUT} frames={FRAME[0]} dur={FRAME[0]/FPS:.1f}s")
