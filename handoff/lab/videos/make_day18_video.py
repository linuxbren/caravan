#!/usr/bin/env python3
"""Day 18 roundup video: single-line captions in a bottom band. 1280x720 H.264, silent."""
import os, subprocess, sys, io
from PIL import Image, ImageDraw, ImageFont
W, H, FPS, SEG = 1280, 720, 24, 4.0
BAND = 92; MAXW = W - 80
SH = os.environ.get("SHOTS", "/workspace/dbg/shots")
OUT = sys.argv[1] if len(sys.argv) > 1 else "/workspace/caravan-day18.mp4"
FONT = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 30)
TITLE = "__title__"
S = [
 (TITLE, "Caravan, Day 18: one AI model running across Mac minis."),
 (TITLE, "A full day: downloads, output fixes, splits, picker, GGUF."),
 ("__dl__", "Downloads: Resume now picks up mid-file with HTTP Range."),
 ("__dl__", "Verified live on both Minis, MLX shards and GGUF files."),
 ("__dl__", "When a download finishes, Caravan asks: Load now or Not now."),
 ("__dl__", "Split downloads no longer overcount or show a false stall."),
 ("__out__", "Output fixes: Dark Champion 21B was writing gibberish."),
 ("__out__", "Its config shares word tables, but the files ship both."),
 ("__out__", "Caravan skipped one table. Now it follows the config."),
 ("__out__", "And a split stage refuses to run if weights are missing."),
 ("__out__", "Rope scaling now applied for about 40 model classes."),
 ("__split__", "Split safety: Caravan checks each Mini's free memory."),
 ("__split__", "A 24/8 split left EXO2 at 1.5 GB free: every chat got 507."),
 ("__split__", "16 layers on each Mini works: 14 to 20 tok/s."),
 ("__split__", "The balance math works for any number of Minis."),
 ("__pick__", "Picker: unusual models get a plain-language ⚠ heads-up."),
 ("__pick__", "One click on Report this model opens a prefilled issue."),
 ("__pick__", "You review and submit it. Caravan never sends it itself."),
 ("__pick__", "An optional warning ping is there, and it's off by default."),
 ("__gguf__", "GGUF: each Mini now loads its share from its own disk."),
 ("__gguf__", "Qwen3 30B: EXO2's 8.41 GB share loaded in 19 s."),
 ("__gguf__", "Optimize now works on GGUF models, and on 1 or 2 Minis."),
 ("__gguf__", "MLX Optimize now also tries MTP and adaptive lookup."),
 ("__llama__", "After release: new llama.cpp vs old, head to head."),
 ("__llama__", "New gets the first token out faster, but writes ~2% slower."),
 ("__llama__", "So the current llama.cpp stays the default for now."),
 ("__test__", "Every reply now logs first-token time and write speed."),
 ("__test__", "Brenden's test: 31 replies, about 12 tok/s, no gibberish."),
 ("__test__", "487 tests pass. Out now as the Day 18 release."),
 (TITLE, "Next: a Balance control for splits. That was Day 18."),
]

def title_img():
    im = Image.new("RGB", (W, H - BAND), (18, 16, 12))
    try:
        import cairosvg
        svg = open(os.path.join(os.path.dirname(__file__), "../../../proxy/web/assets/brand/caravan-lockup.svg")).read()
        svg = svg.replace("currentColor", "#f2b45a")
        png = cairosvg.svg2png(bytestring=svg.encode(), output_width=760)
        logo = Image.open(io.BytesIO(png)).convert("RGBA")
    except Exception:
        logo = Image.open(os.path.join(SH, "logo-tagline.png")).convert("RGBA")
    im.paste(logo, ((W - logo.width)//2, (H - BAND - logo.height)//2 - 30), logo)
    f = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 34)
    d = ImageDraw.Draw(im); t = os.environ.get("VIDEO_SUBTITLE", "Day 18")  # rule: no dates on screen
    d.text(((W - d.textlength(t, font=f))//2, (H-BAND)//2 + 60), t, font=f, fill=(220, 210, 190))
    return im

MONO = "/home/box/.local/share/fonts/JetBrainsMono-Bold.ttf"
def card(title, rows, foot):
    im = Image.new("RGB", (W, H - BAND), (12, 12, 10)); d = ImageDraw.Draw(im)
    ft = ImageFont.truetype(MONO, 34); fr = ImageFont.truetype(MONO, 26); fs = ImageFont.truetype(MONO, 18)
    d.text((80, 50), title, font=ft, fill=(242, 180, 90)); y = 130
    for a, b, c in rows:
        d.text((80, y), a, font=fr, fill=(225, 220, 205)); d.text((640, y), b, font=fr, fill=c); y += 62
    d.text((80, H - BAND - 50), foot, font=fs, fill=(130, 125, 110)); return im
G, R, Y = (120, 210, 120), (230, 110, 100), (235, 200, 110)
def speed_img():
    return card("Day 17 speed results (tok/s = words per second, roughly)", [
        ("Orvena 4B, guess-ahead head", "36.95 -> 54.13 tok/s  +46.5%", G),
        ("  guesses accepted", "550 / 560", G),
        ("Two chats at once, split model", "+69.7% combined output", G),
        ("  with a helper, two chats", "-29.4%", R),
        ("Prompt lookup, repeated text", "+44%", G),
        ("Prompt lookup, mixed chats", "-5.8%  (stays experimental)", R)],
        "Source: docs/DAY17-BENCHMARKS.md, bench/results/day17/")
def lock_img():
    return card("Lockdown check: can a non-Mini reach the split server?", [
        ("EXO2 rpc-server listens on", "127.0.0.1:50052 only", G),
        ("Omarchy -> EXO2 LAN :50052", "Connection refused", G),
        ("Omarchy -> EXO2 Tailscale :50052", "Connection refused", G),
        ("Omarchy -> exo1:50052", "refused", G),
        ("EXO1 -> EXO2 Thunderbolt/LAN", "refused (uses SSH tunnel)", G),
        ("Split still ran", "34.7 tok/s write", Y)],
        "Source: docs/SECURITY.md, docs/DAY17.md")

def dl_img(): return card("Downloads and loading", [
 ("Resume", "HTTP Range, mid-file", G), ("  verified live", "EXO1 and EXO2", G),
 ("Download finishes, nothing loaded", "asks: Load now / Not now", G),
 ("Split download progress", "no overcount, no false stall", G),
 ("Saved split point", "picker, inventory, load agree", G)], "Source: docs/release-notes/day18.md")
def out_img(): return card("Correct output", [
 ("Dark Champion 21B, split 24/8", "gibberish from token 1", R),
 ("  cause", "input word table never loaded", R),
 ("  fix (07249e7)", "follow config tie flag", G),
 ("  missing weights", "stage refuses to run", G),
 ("Rope scaling", "~40 mlx_lm classes fixed", G),
 ("MTP weights in a split", "lead only", G)], "Source: docs/DAY18.md")
def split_img(): return card("Split safety: Dark Champion 21B on two 24 GB Minis", [
 ("24/8 split, EXO2 free", "1.51-1.71 GB  (margin 1.75)", R),
 ("  result", "every chat HTTP 507", R),
 ("16/16 split, ~11.3 GB each", "fits", G),
 ("  \"Say hello\" write speed", "20.0 tok/s, first token 0.51 s", G),
 ("  300-word answer", "14.2 tok/s, first token 0.47 s", G),
 ("Balance math", "any number of Minis", Y)], "Source: docs/DAY18.md")
def pick_img(): return card("Model picker", [
 ("Unusual model", "⚠ + plain-language line", G),
 ("Report this model", "prefilled GitHub issue", G),
 ("  contains", "model id, warning, version", G),
 ("  sent by Caravan?", "never, you submit it", G),
 ("Warning ping", "opt-in, off by default", Y)], "Source: docs/release-notes/day18.md")
def gguf_img(): return card("GGUF (llama.cpp) and Optimize now", [
 ("Each peer loads its share", "from its own disk", G),
 ("  qwen2.5-3b", "0.8 GB in 6.2 s", G),
 ("  Qwen3-30B-A3B, EXO2 share", "8.41 GB in 19.0 s", G),
 ("GGUF Optimize now", "live on 1 and 2 Minis", G),
 ("  result", "defaults were fastest, kept", Y),
 ("MLX Optimize now adds", "MTP, adaptive lookup", G)], "Source: docs/DAY18.md")
def llama_img(): return card("llama.cpp 6a1a922 (old) vs 76a67730 (new), write tok/s", [
 ("Qwen2.5-3B, one Mini", "50.3 vs 49.0   1st 0.07 vs 0.04 s", R),
 ("Qwen2.5-3B, split", "41.8 vs 41.0   1st 0.08 vs 0.05 s", R),
 ("Qwen3-30B, one Mini", "43.3 vs 43.5   1st 0.16 vs 0.15 s", G),
 ("Qwen3-30B, split", "35.0 vs 35.6   1st 0.17 vs 0.16 s", G),
 ("Decision", "keep 6a1a922 as default", Y)], "3 runs each, temp 0. Source: docs/DAY18.md")
def test_img(): return card("Timing log and Brenden's live test", [
 ("Per-reply log line", "first token + write tok/s", G),
 ("  test chat", "0.51 s first, 14.05 tok/s", G),
 ("Brenden's session, 16/16", "31 replies in about 19 min", G),
 ("  average write speed", "11.96 tok/s (~13.7 early)", G),
 ("  gibberish / 507s", "none", G),
 ("  lead Mini peak", "13.07 GB", Y)], "487 tests OK. Day 18 release")
CARDS = {"__dl__": dl_img, "__out__": out_img, "__split__": split_img, "__pick__": pick_img,
 "__gguf__": gguf_img, "__llama__": llama_img, "__test__": test_img}

def check():
    import re
    DATE = re.compile(r"20\d\d|\b(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]* \d")
    for _, c in S: assert not DATE.search(c), ("date on screen", c)
    d = ImageDraw.Draw(Image.new("RGB", (1, 1)))
    for i, (_, c) in enumerate(S):
        l, t, r, b = d.textbbox((0, 0), c, font=FONT)
        assert "\n" not in c and r - l <= MAXW - 80 and b - t < 40, (i, c, r - l)
    return True

def main():
    check()
    cache = {}
    ff = subprocess.Popen(["ffmpeg", "-y", "-loglevel", "error", "-f", "rawvideo", "-pix_fmt", "rgb24",
        "-s", f"{W}x{H}", "-r", str(FPS), "-i", "-", "-c:v", "libx264", "-preset", "slow", "-crf", "30",
        "-pix_fmt", "yuv420p", "-movflags", "+faststart", OUT], stdin=subprocess.PIPE)
    n = int(SEG * FPS); prev = None; t0 = 0
    for i, (img, cap) in enumerate(S):
        if img != prev: t0 = i; prev = img
        if img not in cache:
            if img == TITLE: src = title_img()
            elif img in CARDS: src = CARDS[img]()
            else:
                f, _, box = img.partition("@"); src = Image.open(os.path.join(SH, f)).convert("RGB")
                if box: src = src.crop(tuple(int(v) for v in box.split(",")))
            cache[img] = src
        src = cache[img]; run = sum(1 for x in S if x[0] == img)
        for k in range(n):
            p = ((i - t0) * n + k) / (run * n)
            z = 1.0 + 0.05 * p
            aw, ah = W, H - BAND
            sc = min(aw / src.width, ah / src.height) * z
            r = src.resize((int(src.width*sc), int(src.height*sc)), Image.BILINEAR)
            fr = Image.new("RGB", (W, H), (10, 10, 10))
            x = (aw - r.width)//2; y = (ah - r.height)//2
            fr.paste(r.crop((max(0,-x), max(0,-y), max(0,-x)+min(aw,r.width), max(0,-y)+min(ah,r.height))), (max(0,x), max(0,y)))
            d = ImageDraw.Draw(fr)
            d.rectangle((0, H-BAND, W, H), fill=(14, 14, 14)); d.line((0, H-BAND, W, H-BAND), fill=(60, 60, 60))
            a = min(1, k/6, (n-k)/6)
            col = tuple(int(c*a + 14*(1-a)) for c in (245, 240, 230))
            tw = d.textlength(cap, font=FONT)
            d.text(((W-tw)/2, H-BAND/2), cap, font=FONT, fill=col, anchor="lm")
            ff.stdin.write(fr.tobytes())
    ff.stdin.close(); ff.wait()
    open(os.environ.get("CAPS", "/workspace/day18/video-captions.txt"), "w").write(
        "\n".join(f"{i*SEG:6.1f}s  {c}" for i, (_, c) in enumerate(S)) + "\n")

if __name__ == "__main__": main()
