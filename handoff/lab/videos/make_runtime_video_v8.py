# v7: Caravan v2.1 (one Mac mini) vs Caravan v3 (one MLX model split across two Mac minis over Thunderbolt),
# plus the bigger-brother quants split across two Minis, and the split download.
# Usage: make_runtime_video_v7.py out.mp4 v7_data.json --day "Day 4" [--stills dir]
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
# Day of development for the title slide (no calendar dates on slides).
# --day "Day 3", or --day-of 2026-11-01 (Day 1 = Oct 30, 2026), or
# "_day" in the data JSON. Required: one of them must be given.
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
    sys.exit("give a day label: --day 'Day 3' or --day-of YYYY-MM-DD")
STILL_AT = set(D.get("_stills", []))
BG, FG, MUTED, GRID, RED, PANEL = "#0f1117", "#f2f4f8", "#9aa3b2", "#262b36", "#ff5c5c", "#1b1f2a"
V0, V1, V2 = "#2E7D62", "#34D399", "#FACC15"
V21, V3, BIG = "#34D399", "#FACC15", "#FB923C"
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
    if STILLS and any(abs(t - s) < 0.5 / FPS for s in STILL_AT): fig.savefig(os.path.join(STILLS, f"v8_t{t:04.1f}.png"), facecolor=BG)
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
        fig.text(x + 0.022, y, lab, color=FG, fontsize=22, va="center", weight="bold" if lab.startswith("Caravan v3") else "normal")
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

LAB = ["Qwen3 30B", "Gemma 4 26B", "GPT-OSS 20B"]
def tps(v): return f"{v:.1f}"
def gb(v): return rh(v, 1)
def box(x, y, w, h, ec, a, fc=PANEL, lw=2.5):
    fig.patches.append(plt.Rectangle((x, y), w, h, transform=fig.transFigure, fc=fc, ec=ec, lw=lw, alpha=a, figure=fig))

# 1. Title ---------------------------------------------------------------
def title(t):
    a = ease(t / 0.8)
    fig.text(0.5, 0.64, "Caravan v2.1 vs Caravan v3", color=FG, fontsize=76, weight="bold", ha="center", alpha=a)
    fig.text(0.5, 0.545, "One MLX model, split across two Mac minis", color=FG, fontsize=44, ha="center", alpha=a)
    x0 = 0.5 - 0.12
    for k, c in enumerate([V21, V3, BIG]):
        fig.patches.append(plt.Rectangle((x0 + k * 0.08, 0.47), 0.08 * ease((t - 0.3 - 0.15 * k) / 0.8), 0.014, transform=fig.transFigure, color=c, figure=fig))
    fig.text(0.5, 0.38, "v2.1 = the whole model on one Mac mini  ·  v3 = half the model on each Mini, linked by a Thunderbolt cable", color=V2, fontsize=27, ha="center", alpha=a)
    fig.text(0.5, 0.31, f"{DAY} of building Caravan  ·  two 24 GB Mac minis  ·  Qwen3 30B  ·  Gemma 4 26B  ·  GPT-OSS 20B", color=MUTED, fontsize=28, ha="center", alpha=a)
scene(4 * FPS, title)

# 1b. Why Caravan links the Minis itself ------------------------------------------
def why(t):
    header("MLX runs the models; Caravan links the Minis", "MLX is Apple's toolkit for running AI models on Mac chips")
    p0 = ease((t - 0.2) / 0.7)
    fig.text(0.5, 0.71, "MLX runs every model here fine on each Mini, and the split across two Minis works for all three.",
             color=FG, fontsize=26, weight="bold", ha="center", va="center", alpha=p0,
             bbox=dict(boxstyle="round,pad=0.5", fc=PANEL, ec=V3, lw=2, alpha=p0))
    fig.text(0.07, 0.60, "What we didn't use: MLX's ready-made ways of linking two Macs", color=MUTED, fontsize=24, alpha=ease((t - 0.8) / 0.6))
    rows = [("Standard link", "stopped on our Thunderbolt cable for any message of about 2 MB or more"),
            ("Extra-fast direct-memory link", "needs Thunderbolt 5; these M4 Minis have Thunderbolt 4"),
            ("Built-in model splitting", "only covers Qwen models, not Gemma or GPT-OSS")]
    for k, (h, d) in enumerate(rows):
        p = ease((t - 1.2 - 0.5 * k) / 0.6); y = 0.51 - 0.095 * k
        fig.text(0.09, y, h, color=V21, fontsize=24, weight="bold", va="center", alpha=p)
        fig.text(0.42, y, d, color=FG, fontsize=22, va="center", alpha=p)
    p = ease((t - 3.2) / 0.8)
    if p > 0:
        fig.text(0.5, 0.17, "So Caravan uses MLX to run each half, plus its own simple connection to pass data between them.\n"
                 "That works for Qwen3, Gemma 4 and GPT-OSS.", color=FG, fontsize=24, weight="bold", ha="center", va="center",
                 alpha=p, linespacing=1.4, bbox=dict(boxstyle="round,pad=0.5", fc=PANEL, ec=V2, lw=2, alpha=p))
scene(8 * FPS, why)

# 2. How it works --------------------------------------------------------------
def how(t):
    header("How the split works", "each Mac mini holds half of the model's layers and only loads its own half")
    p1, p2, p3 = ease((t - 0.3) / 0.7), ease((t - 1.0) / 0.7), ease((t - 1.8) / 0.7)
    box(0.07, 0.36, 0.32, 0.36, V21, p1)
    fig.text(0.23, 0.66, "Packer 1  ·  Mac mini 2", color=V21, fontsize=30, weight="bold", ha="center", alpha=p1)
    for k, s in enumerate(["reads your words", "runs the first half of the layers", "sends a small summary on"]):
        fig.text(0.23, 0.58 - 0.065 * k, s, color=FG, fontsize=24, ha="center", alpha=p1)
    box(0.61, 0.36, 0.32, 0.36, V3, p2)
    fig.text(0.77, 0.66, "Lead  ·  Mac mini 1", color=V3, fontsize=30, weight="bold", ha="center", alpha=p2)
    for k, s in enumerate(["runs the second half", "picks the next word", "is the one your chat app talks to"]):
        fig.text(0.77, 0.58 - 0.065 * k, s, color=FG, fontsize=24, ha="center", alpha=p2)
    if p3 > 0:
        fig.patches.append(plt.Rectangle((0.40, 0.535), 0.20 * p3, 0.012, transform=fig.transFigure, color=LLAMA, figure=fig))
        fig.text(0.50, 0.585, "Thunderbolt cable", color=LLAMA, fontsize=22, ha="center", weight="bold", alpha=p3)
        fig.text(0.50, 0.49, f"{D['KB_MIN']:.0f}–{D['KB_MAX']:.0f} KB per token\nunder 1 ms", color=FG, fontsize=20, ha="center", va="top", alpha=p3, linespacing=1.3)
    p = ease((t - 3.0) / 0.8)
    if p > 0:
        fig.text(0.5, 0.22, "Both Minis remember each chat (their own half of it) and save it to disk, so a restart still picks up where you left off.",
                 color=FG, fontsize=23, weight="bold", ha="center", va="center", alpha=p,
                 bbox=dict(boxstyle="round,pad=0.5", fc=PANEL, ec=V2, lw=2, alpha=p))
    fig.text(0.05, 0.04, "The Mini you talk to is the lead; the other Minis are packers, numbered in layer order. Together they're a string.\n"
             "With more Minis: Packer 1 runs the first layers, then Packer 2, and so on, and the lead finishes.", color=MUTED, fontsize=18)
scene(9 * FPS, how)

# 3. Memory per Mini ----------------------------------------------------------
def mem(t):
    header("Memory per Mac mini", "GB at the peak, lower is better · the GPU on each Mini can use about 19 GB")
    legend([("Caravan v2.1: whole model on one Mini", V21), ("Caravan v3: busiest Mini of the two", V3)], xs=(0.05, 0.42))
    ax = fig.add_axes([0.07, 0.17, 0.88, 0.58])
    vbars(ax, [(D["MEM"]["v21"], V21, False), (D["MEM"]["v3"], V3, False)], t, gb, 24, fs=20, labels=LAB)
    p = ease((t - 1.8) / 0.8)
    if p > 0:
        ax.axhline(METAL, color=RED, lw=3, ls="--", xmax=p, zorder=1)
        ax.text(2.55, METAL + 0.35, "GPU memory limit ≈ 19 GB", color=RED, fontsize=22, weight="bold", ha="right", alpha=p)
    fig.text(0.05, 0.035, "Each Mini now holds about half the model, so roughly half the memory, and there's room for longer chats and bigger models.\n"
             "Qwen3 30B went from right at the limit to about 10.5 GB per Mini.", color=MUTED, fontsize=19)
scene(8 * FPS, mem)

# 4. Long chats ----------------------------------------------------------------
def chats(t):
    header("Long chats", "a 16,000-token chat (about 12,000 words) · seconds, lower is better")
    legend([("Caravan v2.1 (one Mini)", V21), ("Caravan v3 (two Minis)", V3)], xs=(0.05, 0.30))
    for j, (key, ttl, xmax) in enumerate((("C16K", "First read of the whole chat", 95), ("T2_16K", "Next message in the same chat", 1.0))):
        ax = fig.add_axes([0.12 + 0.46 * j, 0.24, 0.36, 0.48])
        rows = [[(D[key]["v21"][m], V21, "didn't fit in memory on one Mini"), (D[key]["v3"][m], V3, "")] for m in range(3)]
        hbars(ax, rows, t - 0.5 * j, xmax)
        ax.set_title(ttl, color=FG, fontsize=24, pad=12)
        if j: ax.set_yticklabels(["", "", ""])
    p = ease((t - 3.6) / 0.8)
    if p > 0:
        fig.text(0.5, 0.13, f"Qwen3 30B can now hold a 16,000-token chat: it ran out of memory on one Mini. It still found the hidden word.\n"
                 f"After a restart, a 4,000-token chat picks back up in {min(D['RS4K']['v3']):.1f}–{max(D['RS4K']['v3']):.1f} s on two Minis ({min(D['RS4K']['v21']):.1f}–{max(D['RS4K']['v21']):.1f} s on one).",
                 color=FG, fontsize=22, weight="bold", ha="center", va="center", alpha=p, linespacing=1.4,
                 bbox=dict(boxstyle="round,pad=0.5", fc=PANEL, ec=V2, lw=2, alpha=p))
    fig.text(0.05, 0.035, "The first read is slower on two Minis (the halves take turns). After that, each message only reads the new part: about half a second either way.",
             color=MUTED, fontsize=18)
scene(10 * FPS, chats)

# 5. Speed ----------------------------------------------------------------------
def speed(t):
    header("The price: speed", "tokens per second (a token is about ¾ of a word), higher is better")
    legend([("Caravan v2.1 (one Mini)", V21), ("Caravan v3 (two Minis)", V3)], xs=(0.05, 0.30))
    for j, (key, ttl, ymax, fmt) in enumerate((("TG", "Writing speed", 58, tps), ("PP4K", "Reading a ~4,000-token prompt", 520, lambda v: f"{v:.0f}"))):
        ax = fig.add_axes([0.06 + 0.48 * j, 0.2, 0.42, 0.52])
        vbars(ax, [(D[key]["v21"], V21, False), (D[key]["v3"], V3, False)], t - 0.4 * j, fmt, ymax, fs=17, labels=["Qwen3", "Gemma 4", "GPT-OSS"])
        ax.set_title(ttl, color=FG, fontsize=26, pad=14)
    lo, hi = D["TG_DROP"]
    fig.text(0.05, 0.04, f"Two Minis write {lo}–{hi}% slower and read about 16–25% slower. They work one after the other, not at the same time,\n"
             "so splitting buys memory, not speed. Still well above reading pace for a chat. Quality: 3 of 3 test questions right on both, for all three models.",
             color=MUTED, fontsize=18)
scene(9 * FPS, speed)

# 6. Where the time goes ------------------------------------------------------
def cost(t):
    header("Where the time goes, per token written", "milliseconds, lower is better · a token is about ¾ of a word · the cable is not the problem")
    ax = fig.add_axes([0.14, 0.24, 0.8, 0.5]); ax.set_facecolor(BG)
    for s in ax.spines.values(): s.set_visible(False)
    ax.tick_params(colors=FG, labelsize=22, length=0); ax.xaxis.set_tick_params(labelsize=17, labelcolor=MUTED)
    ax.grid(axis="x", color=GRID, lw=1); ax.set_axisbelow(True); ax.set_xlim(0, 45)
    ys, lbls = [], []
    for m in range(3):
        c = D["COST"][m]; p = ease((t - 0.3 - 0.4 * m) / 1.2)
        y1, y2 = m * 1.0 - 0.18, m * 1.0 + 0.18
        ax.barh(y1, c["whole"] * p, 0.32, color=V21)
        if p > 0.05: ax.text(c["whole"] * p + 0.4, y1, f"{c['whole']:.0f} ms", color=FG, fontsize=18, va="center", weight="bold")
        x = 0
        for k, (v, col) in enumerate(((c["front"], V21), (c["link"], LLAMA), (c["head"], V3))):
            ax.barh(y2, v * p, 0.32, left=x * p, color=col, alpha=0.6 if k == 0 else 1, edgecolor=FG if col == V3 else "none", lw=1.2)
            x += v
        if p > 0.05: ax.text(x * p + 0.4, y2, f"{c['front']:.0f} + {c['link']:.1f} + {c['head']:.0f} ms", color=V2, fontsize=18, va="center", weight="bold")
    ax.set_ylim(2.6, -0.6); ax.set_yticks(range(3)); ax.set_yticklabels(LAB)
    legend([("v2.1: whole model, one Mini", V21), ("v3: Packer 1's half", "#1f7a5c"), ("cable", LLAMA), ("Lead's half", V3)], xs=(0.05, 0.33, 0.55, 0.66))
    p = ease((t - 2.6) / 0.8)
    if p > 0:
        fig.text(0.5, 0.13, f"Each half takes 60–85% of the time the whole model took on one Mini: fixed overhead per step, not the cable.\n"
                 f"The cable adds under 1 ms and {D['KB_MIN']:.0f}–{D['KB_MAX']:.0f} KB per token; a 4,000-token read sends {D['MB4K_MIN']:.0f}–{D['MB4K_MAX']:.0f} MB in a few hundredths of a second.",
                 color=FG, fontsize=22, weight="bold", ha="center", va="center", alpha=p, linespacing=1.4,
                 bbox=dict(boxstyle="round,pad=0.5", fc=PANEL, ec=V2, lw=2, alpha=p))
    fig.text(0.05, 0.035, "Next to try: overlap the two halves and trim per-step overhead. Parked on the roadmap for now.", color=MUTED, fontsize=18)
scene(9 * FPS, cost)

# 7. Bigger brothers ------------------------------------------------------------------
def big(t):
    header("Bigger brothers, split across two Minis", "the same model at a higher-quality setting (8-bit) · both versions on two Minis")
    cols = ["", "Writing\ntok/s", "Reading 4k\ntok/s", "Memory per\nMini (GB)", "16k chat,\nfirst read", "Quality"]
    xs = [0.05, 0.40, 0.52, 0.645, 0.775, 0.90]
    for k, c in enumerate(cols):
        fig.text(xs[k], 0.77, c, color=MUTED, fontsize=21, va="center", ha="left" if k == 0 else "center", linespacing=1.2)
    y = 0.68
    for i, r in enumerate(D["BB"]):
        p = ease((t - 0.4 - 0.7 * i) / 0.6)
        for j, (sub, col) in enumerate(((r["small"], V3), (r.get("big"), BIG))):
            yy = y - 0.055 * j
            if j == 0: box(0.04, yy - 0.088, 0.92, 0.118, GRID, p, lw=1.5)
            if sub is None: continue
            fig.text(xs[0] + 0.01, yy, sub["label"], color=col, fontsize=22, weight="bold", va="center", alpha=p)
            if sub.get("note"):
                fig.text(xs[1] - 0.04, yy, sub["note"], color=MUTED, fontsize=20, style="italic", va="center", alpha=p); continue
            vals = [tps(sub["tg"]), f"{sub['pp4k']:.0f}", gb(sub["mem"]), secs(sub["c16k"]) if sub.get("c16k") else "–", f"{sub['q']}/3"]
            for k, v in enumerate(vals):
                fig.text(xs[k + 1], yy, v, color=FG, fontsize=22, ha="center", va="center", alpha=p, weight="bold" if j else "normal")
        y -= 0.135
    p = ease((t - 4.0) / 0.8)
    if p > 0:
        fig.text(0.5, 0.085, D["BB_NOTE"], color=FG, fontsize=18, weight="bold", ha="center", va="center", alpha=p, linespacing=1.4,
                 bbox=dict(boxstyle="round,pad=0.5", fc=PANEL, ec=BIG, lw=2, alpha=p))
scene(12 * FPS, big)

# 8. Split download --------------------------------------------------------------
def dl(t):
    header("Each Mini downloads only its own half", "GB downloaded from Hugging Face, lower is better (prototype)")
    legend([("whole model (what each Mini needed before)", MUTED), ("Lead (Mac mini 1)", V3), ("Packer 1 (Mac mini 2)", V21)], xs=(0.05, 0.47, 0.66))
    ax = fig.add_axes([0.08, 0.2, 0.86, 0.52])
    n = len(D["DL"])
    ser = [([r["full"] for r in D["DL"]], MUTED, True), ([r["head"] for r in D["DL"]], V3, False), ([r["front"] for r in D["DL"]], V21, False)]
    ax.set_facecolor(BG); w = 0.8 / 3
    for s in ax.spines.values(): s.set_visible(False)
    ax.tick_params(colors=FG, labelsize=22, length=0); ax.yaxis.set_tick_params(labelsize=17, labelcolor=MUTED)
    ax.grid(axis="y", color=GRID, lw=1); ax.set_axisbelow(True); ax.set_xticks(range(n)); ax.set_xticklabels([r["name"] for r in D["DL"]])
    ax.set_ylim(0, 38); ax.set_xlim(-0.55, n - 0.45)
    for m in range(n):
        for k, (vals, c, faint) in enumerate(ser):
            v = vals[m]; x = m + (k - 1) * w; p = ease((t - 0.3 - 0.3 * m - 0.1 * k) / 1.2)
            ax.bar(x, v * p, w * 0.9, color=c, alpha=0.5 if faint else 1)
            if p > 0.02: ax.text(x, v * p + 0.5, f"{v:.1f}", color=FG, fontsize=19, weight="bold", ha="center", va="bottom")
    fig.text(0.05, 0.05, D["DL_NOTE"], color=MUTED, fontsize=18)
scene(8 * FPS, dl)

# 9. Takeaways ---------------------------------------------------------------------
def take(t):
    fig.text(0.07, 0.86, "Takeaways", color=FG, fontsize=56, weight="bold")
    for k, (c, h, s) in enumerate(D["TAKE"]):
        c = {"V3": V3, "V21": V21, "BIG": BIG, "MUTED": MUTED, "RED": RED}[c]
        p = ease((t - 0.3 - 0.5 * k) / 0.7); y = 0.72 - 0.155 * k
        fig.patches.append(plt.Rectangle((0.07, y - 0.07), 0.008, 0.1, transform=fig.transFigure, color=c, alpha=p, figure=fig))
        fig.text(0.095 - 0.02 * (1 - p), y, h, color=FG, fontsize=34, weight="bold", alpha=p, va="center")
        fig.text(0.095 - 0.02 * (1 - p), y - 0.05, s, color=MUTED, fontsize=24, alpha=p, va="center")
    p = ease((t - 2.5) / 0.7)
    fig.text(0.07, 0.09, "Caveats: one test session per setup, all on the same day. Two 24 GB M4 Mac minis joined by a Thunderbolt cable.\n"
             "One Mini's numbers are Caravan v2.1 on that same Mini.", color="#d6dbe4", fontsize=22, va="center", alpha=p, style="italic")
scene(9 * FPS, take)
proc.stdin.close(); proc.wait(); print("done", proc.returncode, FRAME[0] / FPS, "s")
