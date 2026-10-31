# v4: Caravan v0 (45ed2c2 baseline) and Caravan v1 (rebased llama.cpp + auto cache setting) side by side,
# with LocalAI, llama.cpp and exo from v3. Usage: make_runtime_video_v4.py out.mp4 v4_data.json [--stills dir]
import subprocess, sys, os, json, matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib import font_manager as fm
_FD = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fonts")
for _f in ("InterLab-Regular.ttf", "InterLab-Bold.ttf"): fm.fontManager.addfont(os.path.join(_FD, _f))
plt.rcParams["font.family"] = "InterLab"
W, H, FPS = 1920, 1080, 30
OUT = sys.argv[1]; D = json.load(open(sys.argv[2]))
STILLS = sys.argv[sys.argv.index("--stills") + 1] if "--stills" in sys.argv else None
STILL_AT = {3.0, 11.0, 18.5, 27.0, 34.5, 45.0, 55.5, 63.0}
BG, FG, MUTED, GRID, RED = "#0f1117", "#f2f4f8", "#9aa3b2", "#262b36", "#ff5c5c"
RT = ["Caravan v0", "Caravan v1", "LocalAI", "llama.cpp", "exo"]
V0, V1, LOCALAI = "#2E7D62", "#34D399", "#F472B6"
COL = [V0, V1, LOCALAI, "#4FC3F7", "#C084FC"]
MODELS = ["Qwen3 30B", "Gemma 4 26B", "GPT-OSS 20B"]
TG, PP, PP16, TG16, MEM = D["TG"], D["PP"], D["PP16"], D["TG16"], D["MEM"]
METAL = 19.07
NR = len(RT)
from decimal import Decimal, ROUND_HALF_UP
def f1(v): return f"{v:,.1f}"
APPROX = set(map(tuple, D.get("approx", [])))
def r0(v): return f"{int(Decimal(str(round(v, 6))).quantize(Decimal('1'), ROUND_HALF_UP)):,}"
def ease(t): t = min(max(t, 0), 1); return 1 - (1 - t) ** 3
fig = plt.figure(figsize=(W/100, H/100), dpi=100, facecolor=BG)
proc = subprocess.Popen(["ffmpeg", "-y", "-loglevel", "error", "-f", "rawvideo", "-pix_fmt", "rgba", "-s", f"{W}x{H}", "-r", str(FPS), "-i", "-",
    "-c:v", "libx264", "-preset", "medium", "-crf", "18", "-pix_fmt", "yuv420p", "-r", str(FPS), "-movflags", "+faststart", OUT], stdin=subprocess.PIPE)
FRAME = [0]
def emit(alpha):
    if alpha < 1:
        fig.add_artist(plt.Rectangle((0, 0), 1, 1, transform=fig.transFigure, color=BG, alpha=1 - alpha, zorder=100))
    fig.canvas.draw(); proc.stdin.write(bytes(fig.canvas.buffer_rgba()))
    t = FRAME[0] / FPS
    if STILLS and any(abs(t - s) < 0.5 / FPS for s in STILL_AT): fig.savefig(os.path.join(STILLS, f"v4_t{t:04.1f}.png"), facecolor=BG)
    FRAME[0] += 1
def fade(i, n, f=12): return min(1, (i + 1) / f, (n - i) / f)
def header(title, sub):
    fig.text(0.05, 0.925, title, color=FG, fontsize=44, weight="bold", va="center")
    fig.text(0.05, 0.87, sub, color=MUTED, fontsize=24, va="center")
def legend(y=0.815):
    xs = (0.05, 0.18, 0.31, 0.42, 0.535)
    for x, r, c in zip(xs, RT, COL):
        fig.patches.append(plt.Rectangle((x, y - 0.012), 0.016, 0.026, transform=fig.transFigure, color=c, figure=fig))
        fig.text(x + 0.022, y, r, color=FG, fontsize=22, va="center", weight="bold" if r.startswith("Caravan") else "normal")
def bars(ax, data, t, fmt, ymax, start=0.0, fs=16, approx=(), rot=0):
    ax.set_facecolor(BG); w = 0.165
    for s in ax.spines.values(): s.set_visible(False)
    ax.tick_params(colors=FG, labelsize=24, length=0); ax.yaxis.set_tick_params(labelsize=18, labelcolor=MUTED)
    ax.grid(axis="y", color=GRID, lw=1); ax.set_axisbelow(True)
    ax.set_xticks(range(3)); ax.set_xticklabels(MODELS); ax.set_ylim(0, ymax); ax.set_xlim(-0.55, 2.55)
    for m in range(3):
        for r in range(NR):
            v = data[m][r]; x = m + (r - 2) * w
            p = ease((t - start - 0.25 * m - 0.07 * r) / 1.4)
            if v is None:
                if p > 0:
                    ax.bar(x, ymax * 0.06, w * 0.9, color="none", edgecolor=RED, lw=2.5, hatch="//", alpha=p)
                    ax.text(x, ymax * 0.08, "crashed", color=RED, fontsize=17, weight="bold", ha="center", va="bottom", rotation=90, alpha=p)
                continue
            ax.bar(x, v * p, w * 0.9, color=COL[r], edgecolor=FG if r == 1 else "none", lw=1.5 if r == 1 else 0)
            if p > 0.02:
                ax.text(x, v * p + ymax * 0.012, ("~" + r0(v) if (m, r) in approx and p >= 1 else fmt(v * p if p < 1 else v)),
                        color=V1 if r == 1 else FG, fontsize=fs, weight="bold", ha="center", va="bottom", rotation=rot)
def scene(n, draw):
    for i in range(n):
        fig.clf(); fig.patch.set_facecolor(BG); draw(i / FPS); emit(fade(i, n))
def title(t):
    a = ease(t / 0.8)
    fig.text(0.5, 0.64, "Caravan v0 vs Caravan v1", color=FG, fontsize=76, weight="bold", ha="center", alpha=a)
    fig.text(0.5, 0.545, "next to LocalAI, llama.cpp and exo on a 24 GB Mac mini", color=FG, fontsize=44, ha="center", alpha=a)
    x0 = 0.5 - 0.25
    for k, c in enumerate(COL):
        fig.patches.append(plt.Rectangle((x0 + k * 0.10, 0.47), 0.10 * ease((t - 0.3 - 0.15 * k) / 0.8), 0.014 if k < 2 else 0.008, transform=fig.transFigure, color=c, figure=fig))
    fig.text(0.5, 0.38, "v1 = newer llama.cpp underneath + picks the faster chat-memory setting when it fits", color=V1, fontsize=28, ha="center", alpha=a)
    fig.text(0.5, 0.31, "Oct 30, 2026  ·  Qwen3 30B  ·  Gemma 4 26B  ·  GPT-OSS 20B", color=MUTED, fontsize=28, ha="center", alpha=a)
scene(4 * FPS, title)
def chart(titl, sub, data, fmt, ymax, foot, note=None):
    def d(t):
        header(titl, sub); legend()
        ax = fig.add_axes([0.07, 0.15, 0.88, 0.62]); bars(ax, data, t, fmt, ymax)
        if note:
            p = ease((t - 1.0) / 0.8)
            fig.text(0.95, 0.815, note, color=FG, fontsize=22, ha="right", va="center", alpha=p,
                     bbox=dict(boxstyle="round,pad=0.45", fc="#1b1f2a", ec=MUTED, lw=1.5, alpha=p))
        fig.text(0.05, 0.05, foot, color=MUTED, fontsize=19)
    return d
scene(8 * FPS, chart("Writing speed", "tokens per second while the model writes, higher is better", TG, lambda v: f"{v:.1f}", 58,
      "Middle result of 3 runs. exo uses a different model format (MLX), so its models are not byte-for-byte the same.",
      note="What's a token? About ¾ of a word."))
scene(7 * FPS, chart("Reading speed", "a ~4,000-token prompt (about 3,000 words), tokens/s, higher is better", PP, f1, 520,
      "Middle result of 3 runs. Caravan v0, v1 and LocalAI all run llama.cpp underneath; v1 uses a newer llama.cpp.\n"
      "v1 was measured later the same evening. A same-evening rerun of v0 came out up to 6% lower than the v0 bars shown here."))
def deep(t):
    header("Long chat (16,000 tokens of history)", "a new ~550-token message on a 16,000-token chat")
    legend()
    a1 = fig.add_axes([0.06, 0.2, 0.42, 0.53]); bars(a1, PP16, t, f1, 300, fs=12, approx=APPROX, rot=90)
    a1.set_title("Reading speed, tokens/s", color=FG, fontsize=26, pad=14); a1.tick_params(axis="x", labelsize=18)
    a2 = fig.add_axes([0.55, 0.2, 0.42, 0.53]); bars(a2, TG16, t, lambda v: f"{v:.1f}", 38, start=0.4, fs=12, rot=90)
    a2.set_title("Writing speed, tokens/s", color=FG, fontsize=26, pad=14); a2.tick_params(axis="x", labelsize=18)
    fig.text(0.05, 0.035, "Caravan, LocalAI and llama.cpp use a memory-saving setting for long chats here (v1 picks the faster one where it fits).\n"
             "exo's Qwen3 30B crashed before this test; exo reading speeds are approximate. Qwen3 30B used a single long chat slot to fit.", color=MUTED, fontsize=18)
scene(9 * FPS, deep)
def mem(t):
    header("Memory used", "GB at the peak, lower is better. This Mac lets the GPU use about 19 GB"); legend()
    ax = fig.add_axes([0.07, 0.17, 0.88, 0.60]); bars(ax, MEM, t, lambda v: f"{v:.1f}", 24)
    p = ease((t - 1.8) / 0.8)
    if p > 0:
        ax.axhline(METAL, color=RED, lw=3, ls="--", xmax=p, zorder=1)
        ax.text(2.55, METAL + 0.35, "GPU memory limit ≈ 19 GB", color=RED, fontsize=22, weight="bold", ha="right", alpha=p)
    fig.text(0.05, 0.03, "v1 spends spare memory on a faster chat-memory setting when it fits (Gemma 4: +2 GB, still under the limit), and keeps\n"
             "the leaner one when it doesn't (Qwen3 30B). Highest memory used by each app during the tests (exo: its own peak figure).", color=MUTED, fontsize=18, va="bottom")
scene(7 * FPS, mem)
RL = ["First message (nothing saved yet)", "Caravan v0 after restart", "Caravan v1 after restart"]
RC = ["#5b6475", V0, V1]
def resume(t):
    header("Picking a chat back up after a restart", "wait before the first word, seconds, lower is better · 16,000-token chat")
    for k, (lab, c) in enumerate(zip(RL, RC)):
        x = (0.05, 0.33, 0.56)[k]
        fig.patches.append(plt.Rectangle((x, 0.798), 0.016, 0.026, transform=fig.transFigure, color=c, figure=fig))
        fig.text(x + 0.022, 0.81, lab, color=FG, fontsize=22, va="center")
    ax = fig.add_axes([0.17, 0.30, 0.76, 0.47]); ax.set_facecolor(BG)
    for s in ax.spines.values(): s.set_visible(False)
    ax.tick_params(colors=FG, labelsize=24, length=0); ax.xaxis.set_tick_params(labelsize=18, labelcolor=MUTED)
    ax.grid(axis="x", color=GRID, lw=1); ax.set_axisbelow(True); ax.set_xlim(0, 100); ax.set_ylim(2.6, -0.6)
    ax.set_yticks(range(3)); ax.set_yticklabels(MODELS)
    h = 0.27
    for m in range(3):
        vals = [D["COLD"][m], D["RES_V0"][m], D["RES_V1"][m]]
        for k in range(3):
            v = vals[k]; y = m + (k - 1) * h
            p = ease((t - 0.3 - 0.35 * m - 0.15 * k) / 1.3)
            bad = (k == 1 and v > 10)
            ax.barh(y, v * p, h * 0.88, color=RED if bad else RC[k])
            if p > 0.02:
                val = v * p if p < 1 else v
                lbl = f"{val:.1f} s" if val >= 10 else f"{val:.2f} s"
                if bad and p >= 1: lbl += "   saved, but re-read from scratch"
                if k == 2 and p >= 1 and m > 0: lbl += "   loaded back from disk"
                ax.text(v * p + 0.8, y, lbl, color=(RED if bad else (V1 if k == 2 else FG)), fontsize=19, weight="bold", va="center")
    p = ease((t - 3.0) / 0.8)
    if p > 0:
        ax.text(58, 1.55, f"v1: {D['RES_V0'][1]/D['RES_V1'][1]:.0f}× and {D['RES_V0'][2]/D['RES_V1'][2]:.0f}× faster", color=V1, fontsize=26, weight="bold", va="center", alpha=p)
    p2 = ease((t - 4.8) / 0.8)
    if p2 > 0:
        fig.text(0.5, 0.175, "LocalAI, llama.cpp and exo don't keep chats across a restart on their own:\nthey re-read the whole chat (LocalAI: 80 s, 56 s, 49 s).",
                 color=FG, fontsize=24, weight="bold", ha="center", va="center", alpha=p2, linespacing=1.4,
                 bbox=dict(boxstyle="round,pad=0.5", fc="#1b1f2a", ec=V1, lw=2, alpha=p2))
    fig.text(0.05, 0.035, "Restart = stop and start the server again. Gemma 4 and GPT-OSS use a different attention design that v0 couldn't reload; v1's newer\n"
             "llama.cpp saves the extra pieces it needs. Cost: bigger save files (Gemma 4: about 850 MB per chat instead of 290 MB).", color=MUTED, fontsize=18)
scene(12 * FPS, resume)
def mlx(t):
    header("New in v1: MLX models inside Caravan (early)", "the same models in Apple's MLX format, run through Caravan · tokens/s, higher is better")
    LC = [V1, "#FBBF24"]; LL = ["Caravan v1 (llama.cpp)", "Caravan v1 + MLX"]
    for k, (lab, c) in enumerate(zip(LL, LC)):
        x = (0.05, 0.25)[k]
        fig.patches.append(plt.Rectangle((x, 0.798), 0.016, 0.026, transform=fig.transFigure, color=c, figure=fig))
        fig.text(x + 0.022, 0.81, lab, color=FG, fontsize=22, va="center")
    for j, (key, ttl, ymax) in enumerate((("MLX_TG", "Writing speed", 58), ("MLX_PP", "Reading speed (~4,000 tokens)", 520))):
        ax = fig.add_axes([0.06 + 0.33 * j, 0.24, 0.29, 0.5]); ax.set_facecolor(BG)
        for s in ax.spines.values(): s.set_visible(False)
        ax.tick_params(colors=FG, labelsize=17, length=0); ax.yaxis.set_tick_params(labelsize=15, labelcolor=MUTED)
        ax.grid(axis="y", color=GRID, lw=1); ax.set_axisbelow(True); ax.set_ylim(0, ymax); ax.set_xlim(-0.6, 2.6)
        ax.set_xticks(range(3)); ax.set_xticklabels(["Qwen3", "Gemma 4", "GPT-OSS"]); ax.set_title(ttl, color=FG, fontsize=24, pad=12)
        for m in range(3):
            for r in range(2):
                v = D[key][m][r]; x = m + (r - 0.5) * 0.36; p = ease((t - 0.3 * j - 0.2 * m - 0.1 * r) / 1.3)
                ax.bar(x, v * p, 0.32, color=LC[r])
                if p > 0.02: ax.text(x, v * p + ymax * 0.012, f"{v * p:.0f}" if j else f"{v * p:.1f}", color=FG, fontsize=15, weight="bold", ha="center", va="bottom")
    items = [(V1, "All three models answer correctly through Caravan"),
             ("#FBBF24", "Not yet: saving chats. After a restart, MLX re-reads the chat"),
             ("#FBBF24", "Qwen3 30B only fit after tightening MLX's memory settings"),
             ("#FBBF24", "GPT-OSS replies need tidying (MLX leaves its 'thinking' markup in)"),
             ("#FBBF24", "Gemma 4 and GPT-OSS didn't reuse the chat between messages")]
    for k, (c, s) in enumerate(items):
        p = ease((t - 1.5 - 0.45 * k) / 0.6); y = 0.70 - 0.095 * k
        fig.patches.append(plt.Rectangle((0.73, y - 0.018), 0.006, 0.04, transform=fig.transFigure, color=c, alpha=p, figure=fig))
        fig.text(0.745, y, s, color=FG, fontsize=19, va="center", alpha=p, wrap=True)
    fig.text(0.05, 0.05, "Tested with mlx-lm 0.32.2 on the 4-bit (Qwen3, Gemma 4) and MXFP4 (GPT-OSS) MLX versions, so not byte-for-byte the same models.\n"
             "Peak memory with MLX: Qwen3 19.0 GB (right at the limit), Gemma 4 18.6 GB, GPT-OSS 13.9 GB.", color=MUTED, fontsize=18)
scene(9 * FPS, mlx)
TAKE = [(V1, "v1 picks Gemma 4 and GPT-OSS chats back up in under 1 s", "after a restart. v0 re-read them from scratch: 56 s and 48 s. Qwen3 stays at about 1 s"),
        (V1, "v1 reads about 6% faster and writes 2–5% faster than v0", "mostly from the newer llama.cpp underneath; the faster chat-memory setting adds a bit more"),
        (COL[4], "exo still writes fastest on short chats", "but it's slowest at reading long chats and uses the most memory"),
        (RED, "Qwen3 30B still barely fits on a 24 GB Mac mini", "18.7–20.4 GB used against a ~19 GB GPU memory limit, whichever app runs it")]
def take(t):
    fig.text(0.07, 0.86, "Takeaways", color=FG, fontsize=56, weight="bold")
    for k, (c, h, s) in enumerate(TAKE):
        p = ease((t - 0.3 - 0.5 * k) / 0.7); y = 0.72 - 0.155 * k
        fig.patches.append(plt.Rectangle((0.07, y - 0.07), 0.008, 0.1, transform=fig.transFigure, color=c, alpha=p, figure=fig))
        fig.text(0.095 - 0.02 * (1 - p), y, h, color=FG, fontsize=34, weight="bold", alpha=p, va="center")
        fig.text(0.095 - 0.02 * (1 - p), y - 0.05, s, color=MUTED, fontsize=24, alpha=p, va="center")
    p = ease((t - 2.5) / 0.7)
    fig.text(0.07, 0.09, "Caveats: one Mac mini, one test session per setup; v1 was measured later the same evening than the others.\n"
             "exo uses a different model format (MLX), so its models aren't byte-for-byte the same.", color="#d6dbe4", fontsize=22, va="center", alpha=p, style="italic")
scene(9 * FPS, take)
proc.stdin.close(); proc.wait(); print("done", proc.returncode, FRAME[0] / FPS, "s")
