# v5: Caravan v1 vs Caravan v2 (MLX step b: the Caravan MLX worker with per-session chat memory that survives
# restarts, GPT-OSS replies tidied). LocalAI, llama.cpp and exo as reference bars; v0 only in footnotes.
# Usage: make_runtime_video_v5.py out.mp4 v5_data.json [--stills dir]
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
STILL_AT = set(D.get("_stills", []))
BG, FG, MUTED, GRID, RED, PANEL = "#0f1117", "#f2f4f8", "#9aa3b2", "#262b36", "#ff5c5c", "#1b1f2a"
V0, V1, V2 = "#2E7D62", "#34D399", "#FACC15"
LOCALAI, LLAMA, EXO = "#F472B6", "#4FC3F7", "#C084FC"
MODELS = ["Qwen3 30B", "Gemma 4 26B", "GPT-OSS 20B"]
METAL = 19.07
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
    if STILLS and any(abs(t - s) < 0.5 / FPS for s in STILL_AT): fig.savefig(os.path.join(STILLS, f"v5_t{t:04.1f}.png"), facecolor=BG)
    FRAME[0] += 1
def fade(i, n, f=12): return min(1, (i + 1) / f, (n - i) / f)
def scene(n, draw):
    for i in range(n):
        fig.clf(); fig.patch.set_facecolor(BG); draw(i / FPS); emit(fade(i, n))
def header(title, sub):
    fig.text(0.05, 0.925, title, color=FG, fontsize=44, weight="bold", va="center")
    fig.text(0.05, 0.87, sub, color=MUTED, fontsize=24, va="center")
def legend(items, y=0.815, xs=None):
    x = 0.05
    for k, (lab, c) in enumerate(items):
        if xs: x = xs[k]
        fig.patches.append(plt.Rectangle((x, y - 0.012), 0.016, 0.026, transform=fig.transFigure, color=c, figure=fig))
        fig.text(x + 0.022, y, lab, color=FG, fontsize=22, va="center", weight="bold" if lab.startswith("Caravan v2") else "normal")
        if not xs: x += 0.035 + 0.0105 * len(lab)
from decimal import Decimal, ROUND_HALF_UP
def rh(v, nd): return str(Decimal(str(round(v, 6))).quantize(Decimal(1).scaleb(-nd), ROUND_HALF_UP))
def secs(v): return f"{rh(v, 1)} s" if v >= 10 else f"{rh(v, 2)} s"
def hbars(ax, rows, t, xmax, start=0.3, label_extra=None):
    """rows: per model, list of (value or None, color, note-when-None)."""
    ax.set_facecolor(BG)
    for s in ax.spines.values(): s.set_visible(False)
    ax.tick_params(colors=FG, labelsize=24, length=0); ax.xaxis.set_tick_params(labelsize=18, labelcolor=MUTED)
    ax.grid(axis="x", color=GRID, lw=1); ax.set_axisbelow(True); ax.set_xlim(0, xmax)
    n = len(rows[0]); h = 0.8 / n
    ax.set_ylim(2.6, -0.6); ax.set_yticks(range(3)); ax.set_yticklabels(MODELS)
    for m in range(3):
        for k, (v, c, miss) in enumerate(rows[m]):
            y = m + (k - (n - 1) / 2) * h
            p = ease((t - start - 0.35 * m - 0.15 * k) / 1.3)
            if v is None:
                if p > 0: ax.text(xmax * 0.005, y, miss, color=MUTED, fontsize=19, va="center", alpha=p, style="italic")
                continue
            ax.barh(y, v * p, h * 0.86, color=c, edgecolor=FG if c == V2 else "none", lw=1.5 if c == V2 else 0)
            if p > 0.02:
                val = v * p if p < 1 else v
                lbl = secs(val)
                if label_extra and p >= 1: lbl += label_extra(m, k, v)
                ax.text(v * p + xmax * 0.008, y, lbl, color=V2 if c == V2 else FG, fontsize=19, weight="bold", va="center")
def vbars(ax, series, t, fmt, ymax, start=0.0, fs=16, labels=MODELS):
    """series: list of (values[3], color, faint)."""
    ax.set_facecolor(BG); n = len(series); w = 0.8 / n
    for s in ax.spines.values(): s.set_visible(False)
    ax.tick_params(colors=FG, labelsize=22, length=0); ax.yaxis.set_tick_params(labelsize=17, labelcolor=MUTED)
    ax.grid(axis="y", color=GRID, lw=1); ax.set_axisbelow(True)
    ax.set_xticks(range(3)); ax.set_xticklabels(labels); ax.set_ylim(0, ymax); ax.set_xlim(-0.55, 2.55)
    for m in range(3):
        for r, (vals, c, faint) in enumerate(series):
            v = vals[m]; x = m + (r - (n - 1) / 2) * w
            if v is None: continue
            p = ease((t - start - 0.25 * m - 0.07 * r) / 1.4)
            ax.bar(x, v * p, w * 0.9, color=c, alpha=0.55 if faint else 1, edgecolor=FG if c == V2 else "none", lw=1.5 if c == V2 else 0)
            if p > 0.02:
                ax.text(x, v * p + ymax * 0.012, fmt(v * p if p < 1 else v), color=V2 if c == V2 else (MUTED if faint else FG),
                        fontsize=fs, weight="bold", ha="center", va="bottom")

# 1. Title ---------------------------------------------------------------
def title(t):
    a = ease(t / 0.8)
    fig.text(0.5, 0.64, "Caravan v1 vs Caravan v2", color=FG, fontsize=76, weight="bold", ha="center", alpha=a)
    fig.text(0.5, 0.545, "MLX models now remember the chat, even after a restart", color=FG, fontsize=44, ha="center", alpha=a)
    x0 = 0.5 - 0.2
    for k, c in enumerate([V1, V2, LOCALAI, LLAMA, EXO]):
        fig.patches.append(plt.Rectangle((x0 + k * 0.08, 0.47), 0.08 * ease((t - 0.3 - 0.15 * k) / 0.8), 0.014 if k < 2 else 0.008, transform=fig.transFigure, color=c, figure=fig))
    fig.text(0.5, 0.38, "v2 = Caravan's own MLX server: keeps each chat's memory, saves it to disk, tidies GPT-OSS replies", color=V2, fontsize=27, ha="center", alpha=a)
    fig.text(0.5, 0.31, "Oct 31, 2026  ·  one 24 GB Mac mini  ·  Qwen3 30B  ·  Gemma 4 26B  ·  GPT-OSS 20B", color=MUTED, fontsize=28, ha="center", alpha=a)
scene(4 * FPS, title)

# 2. Next message ----------------------------------------------------------
def nextmsg(t):
    header("Answering the next message in a chat", "wait before the first word, seconds, lower is better · MLX versions of the models")
    legend([("Caravan v1 (MLX)", V1), ("Caravan v2 (MLX)", V2)], xs=(0.05, 0.25))
    for j, (key, ttl, xmax) in enumerate((("T2_4K", "4,000-token chat (about 3,000 words)", 13), ("T2_16K", "16,000-token chat", 68))):
        ax = fig.add_axes([0.12 + 0.46 * j, 0.22, 0.36, 0.5])
        rows = [[(D[key]["v1"][m], V1, "didn't fit in memory (v1 and v2)"), (D[key]["v2"][m], V2, "")] for m in range(3)]
        if j == 0:
            rows[0][1] = (D[key]["v2"][0], V2, "")
        hbars(ax, rows, t - 0.5 * j, xmax)
        ax.set_title(ttl, color=FG, fontsize=24, pad=12)
        if j: ax.set_yticklabels(["", "", ""])
    p = ease((t - 3.6) / 0.8)
    if p > 0:
        fig.text(0.5, 0.115, "v1 re-read the whole chat for every message on Gemma 4 and GPT-OSS. v2 reads only the new part:\n"
                 f"about {D['REREAD_T2_4K']['v2'][2]}–{D['REREAD_T2_4K']['v2'][0]} tokens instead of ~4,000 (a token is about ¾ of a word).",
                 color=FG, fontsize=23, weight="bold", ha="center", va="center", alpha=p, linespacing=1.4,
                 bbox=dict(boxstyle="round,pad=0.5", fc=PANEL, ec=V2, lw=2, alpha=p))
    fig.text(0.05, 0.03, "Qwen3 already reused the chat in v1. Qwen3 30B doesn't fit a 16,000-token chat in MLX on this Mac (out of GPU memory in v1 and v2).",
             color=MUTED, fontsize=18)
scene(10 * FPS, nextmsg)

# 3. Restart ---------------------------------------------------------------
def restart(t):
    header("Picking an MLX chat back up after a restart", "stop and start the server, then send the next message · seconds, lower is better")
    legend([("Caravan v1 (MLX): re-reads the chat", V1), ("Caravan v2 (MLX): loads from disk", V2), ("Caravan v2 (llama.cpp models)", LLAMA)],
           xs=(0.05, 0.335, 0.655))
    for j, (key, ttl, xmax) in enumerate((("RS_4K", "4,000-token chat", 19), ("RS_16K", "16,000-token chat", 70))):
        ax = fig.add_axes([0.12 + 0.46 * j, 0.25, 0.36, 0.47])
        rows = []
        for m in range(3):
            r = [(D[key]["v1"][m], V1, "MLX: didn't fit in memory"), (D[key]["v2"][m], V2, "")]
            if j: r.append((D["LLAMA_RS_16K"]["v2"][m] or D["LLAMA_RS_16K"]["v1"][m], LLAMA, ""))
            rows.append(r)
        hbars(ax, rows, t - 0.5 * j, xmax)
        ax.set_title(ttl, color=FG, fontsize=24, pad=12)
        if j: ax.set_yticklabels(["", "", ""])
    p = ease((t - 4.2) / 0.8)
    if p > 0:
        g, o = D["RS_16K"], D["RS_16K"]
        fig.text(0.5, 0.14, f"16,000-token chat: Gemma 4 {g['v1'][1]:.0f} s → {rh(g['v2'][1], 1)} s, GPT-OSS {o['v1'][2]:.0f} s → {rh(o['v2'][2], 1)} s.\n"
                 "LocalAI, llama.cpp and exo don't save chats: they re-read the whole chat (LocalAI: 49–80 s).", linespacing=1.4,
                 color=FG, fontsize=22, weight="bold", ha="center", va="center", alpha=p,
                 bbox=dict(boxstyle="round,pad=0.5", fc=PANEL, ec=V2, lw=2, alpha=p))
    sm = D["SAVE_MB"]
    fig.text(0.05, 0.035, f"Saved chat on disk: GPT-OSS {sm['4k'][2]} MB / {sm['16k'][2]} MB, Gemma 4 {sm['4k'][1]} / {sm['16k'][1]} MB, Qwen3 {sm['4k'][0]} MB (4,000 / 16,000-token chats).\n"
             "Read back from a warm disk (files recently written). Caravan v0 had no MLX; its llama.cpp chats took 48–56 s after a restart.", color=MUTED, fontsize=18)
scene(11 * FPS, restart)

# 4. GPT-OSS tidy ----------------------------------------------------------
def tidy(t):
    header("GPT-OSS replies, tidied", "the same question, what the chat app gets back")
    for j, (who, c, lines) in enumerate((
            ("Caravan v1 (MLX)", V1, ["<|channel|>analysis<|message|>User asks:", "\"What is the capital of Australia?\" ...", "<|end|><|start|>assistant<|channel|>final", "<|message|>Canberra."]),
            ("Caravan v2 (MLX)", V2, ["answer:     Canberra.", "", "reasoning (kept separate):", "User asks: \"What is the capital of ...\""]))):
        p = ease((t - 0.3 - 1.0 * j) / 0.8); x = 0.06 + 0.46 * j
        fig.patches.append(plt.Rectangle((x, 0.36), 0.42, 0.40, transform=fig.transFigure, fc=PANEL, ec=c, lw=2.5, alpha=p, figure=fig))
        fig.text(x + 0.02, 0.715, who, color=c, fontsize=28, weight="bold", alpha=p, va="center")
        for k, l in enumerate(lines):
            col = (RED if "<|" in l else FG) if j == 0 else (FG if k < 1 else MUTED)
            fig.text(x + 0.02, 0.64 - 0.065 * k, l, color=col, fontsize=20, family="monospace", alpha=p, va="center",
                     weight="bold" if (j == 1 and k == 0) else "normal")
    p = ease((t - 2.6) / 0.8)
    if p > 0:
        fig.text(0.5, 0.25, "Why it matters: the tidy reply is what the app sends back next time, and it matches what v2 remembers,\n"
                 f"so the next message re-reads {D['REREAD_T2_4K']['v2'][2]} tokens instead of {D['REREAD_T2_4K']['v1'][2]:,}. Memory use: no change (13.7 vs 13.9 GB).",
                 color=FG, fontsize=23, ha="center", va="center", alpha=p, linespacing=1.4, weight="bold")
    fig.text(0.05, 0.05, "Reasoning comes back in a separate field, the same way llama.cpp returns it. Apps that send it back don't break the chat memory.",
             color=MUTED, fontsize=18)
scene(9 * FPS, tidy)

# 5. Speed ----------------------------------------------------------------
def speed(t):
    header("Speed didn't get worse", "tokens per second (a token is about ¾ of a word), higher is better · middle of 3 runs")
    legend([("Caravan v1 (MLX)", V1), ("Caravan v2 (MLX)", V2), ("exo (MLX)", EXO), ("LocalAI", LOCALAI), ("llama.cpp", LLAMA)])
    for j, (key, ttl, ymax, fmt) in enumerate((("TG", "Writing speed", 58, lambda v: f"{v:.1f}"), ("PP", "Reading a ~4,000-token prompt", 520, lambda v: f"{v:.0f}"))):
        ax = fig.add_axes([0.06 + 0.48 * j, 0.2, 0.42, 0.52])
        ser = [(D[key]["v1"], V1, False), (D[key]["v2"], V2, False), (D[key]["exo"], EXO, True), (D[key]["localai"], LOCALAI, True), (D[key]["llama"], LLAMA, True)]
        vbars(ax, ser, t - 0.4 * j, fmt, ymax, fs=13, labels=["Qwen3", "Gemma 4", "GPT-OSS"])
        ax.set_title(ttl, color=FG, fontsize=26, pad=14)
    fig.text(0.05, 0.04, "v2 writes 4–6% faster. Reading: about the same; Gemma 4 short prompts (~500 tokens) read 7% slower, Qwen3 long ones 4% slower.\n"
             "Faint bars (Oct 30 compare): LocalAI and llama.cpp run the GGUF versions, exo the MLX ones. v1 MLX measured Oct 30; Caravan v0 had no MLX.",
             color=MUTED, fontsize=18)
scene(9 * FPS, speed)

# 6. Memory ---------------------------------------------------------------
def mem(t):
    header("Memory used", "GB at the peak during the speed tests, lower is better · this Mac lets the GPU use about 19 GB")
    legend([("Caravan v1 (MLX)", V1), ("Caravan v2 (MLX)", V2), ("exo (MLX)", EXO), ("LocalAI", LOCALAI), ("llama.cpp", LLAMA)])
    ax = fig.add_axes([0.07, 0.17, 0.88, 0.58])
    ser = [(D["MEM"]["v1"], V1, False), (D["MEM"]["v2"], V2, False), (D["MEM"]["exo"], EXO, True), (D["MEM"]["localai"], LOCALAI, True), (D["MEM"]["llama"], LLAMA, True)]
    vbars(ax, ser, t, lambda v: f"{v:.1f}", 24, fs=16)
    p = ease((t - 1.8) / 0.8)
    if p > 0:
        ax.axhline(METAL, color=RED, lw=3, ls="--", xmax=p, zorder=1)
        ax.text(2.55, METAL + 0.35, "GPU memory limit ≈ 19 GB", color=RED, fontsize=22, weight="bold", ha="right", alpha=p)
    fig.text(0.05, 0.035, "v2 keeps one copy of each chat's memory instead of copying it for every message, so it doesn't use more, even while remembering chats.\n"
             "Qwen3 30B still needs MLX's tightest settings and sits right at the limit. 16,000-token chats: Gemma 4 17.7 GB, GPT-OSS 14.1 GB in v2.",
             color=MUTED, fontsize=18)
scene(8 * FPS, mem)

# 7. MLX limits list -------------------------------------------------------
LIM = [(V2, "Fixed: Gemma 4 and GPT-OSS now reuse the chat between messages"),
       (V2, "Fixed: MLX chats are saved to disk and loaded back after a restart"),
       (V2, "Fixed: GPT-OSS replies come back tidy, reasoning kept separate"),
       ("#FBBF24", "Still: Qwen3 30B needs MLX's tightest memory settings"),
       (RED, "Still: Qwen3 30B can't hold a 16,000-token chat in MLX (llama.cpp can)"),
       ("#FBBF24", "New cost: saved chats take 100–570 MB each on disk"),
       ("#FBBF24", "New cost: the MLX server takes 6–9 s to start (it loads everything up front)")]
def limits(t):
    header("MLX inside Caravan: what's fixed, what's not", "the list from the v1 video, updated")
    for k, (c, s) in enumerate(LIM):
        p = ease((t - 0.4 - 0.45 * k) / 0.6); y = 0.74 - 0.085 * k
        fig.patches.append(plt.Rectangle((0.08, y - 0.02), 0.007, 0.045, transform=fig.transFigure, color=c, alpha=p, figure=fig))
        fig.text(0.1 - 0.02 * (1 - p), y, s, color=FG, fontsize=29, va="center", alpha=p, weight="bold" if c == V2 else "normal")
    fig.text(0.05, 0.05, "Tried an 8-bit chat memory for Qwen3 to fit 16,000 tokens: still out of GPU memory, and reading got slower. Left it off.",
             color=MUTED, fontsize=19)
scene(10 * FPS, limits)

# 8. Takeaways + next --------------------------------------------------------
def take(t):
    fig.text(0.07, 0.86, "Takeaways", color=FG, fontsize=56, weight="bold")
    T = [(V2, "MLX chats: next message in about half a second", "was 9–11 s on Gemma 4 and GPT-OSS (37–55 s on a 16,000-token chat)"),
         (V2, "After a restart: about 0.6 s instead of 13–60 s", "loaded back from disk, not re-read · saved chats now capped at 50 GB per Mini, oldest go first"),
         (LLAMA, D.get("_llama_take", "llama.cpp models: same speed as v1"), D.get("_llama_take2", "and still pick a chat back up in about a second after a restart")),
         (MUTED, "Next: split one MLX model across two Mac minis", "then per-model settings, less proxy overhead, memory headroom, restores from a cold disk")]
    for k, (c, h, s) in enumerate(T):
        p = ease((t - 0.3 - 0.5 * k) / 0.7); y = 0.72 - 0.155 * k
        fig.patches.append(plt.Rectangle((0.07, y - 0.07), 0.008, 0.1, transform=fig.transFigure, color=c, alpha=p, figure=fig))
        fig.text(0.095 - 0.02 * (1 - p), y, h, color=FG, fontsize=34, weight="bold", alpha=p, va="center")
        fig.text(0.095 - 0.02 * (1 - p), y - 0.05, s, color=MUTED, fontsize=24, alpha=p, va="center")
    p = ease((t - 2.5) / 0.7)
    fig.text(0.07, 0.09, "Caveats: one Mac mini, one test session per setup; v1 MLX speeds were measured the evening before.\n"
             "MLX and GGUF versions of a model aren't byte-for-byte the same.", color="#d6dbe4", fontsize=22, va="center", alpha=p, style="italic")
scene(9 * FPS, take)
proc.stdin.close(); proc.wait(); print("done", proc.returncode, FRAME[0] / FPS, "s")
