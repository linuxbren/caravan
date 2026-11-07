#!/usr/bin/env python3
"""Day 17 tour video: single-line captions in a bottom band. 1280x720 H.264, silent."""
import os, subprocess, sys, io
from PIL import Image, ImageDraw, ImageFont
W, H, FPS, SEG = 1280, 720, 24, 4.2
BAND = 92; MAXW = W - 80
SH = os.environ.get("SHOTS", "/workspace/dbg/shots")
OUT = sys.argv[1] if len(sys.argv) > 1 else "/workspace/caravan-day17.mp4"
FONT = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 30)
TITLE = "__title__"
S = [
 (TITLE, "Caravan, Day 17: one AI model running across Mac minis."),
 (TITLE, "Your Mac minis. One model. Built in the open."),
 ("day17-final-main.png", "Speed first. We count tok/s, roughly words per second."),
 ("day17-final-main.png", "Orvena 4B's built-in guess-ahead: 36.95 to 54.13 tok/s, +46.5%."),
 ("day17-final-main.png", "Two chats at once on a split model: +69.7% combined output."),
 ("day17-final-main.png", "Prompt lookup: +44% on repeated text, 5.8% slower on mixed chats."),
 ("day17-final-main.png", "So prompt lookup stays an experiment for now."),
 ("day17-final-picker-step2.png", "The model picker: choose a model, then where it lives, right below."),
 ("picker-progress-all-2.png", "Download bars now show real network speed, one bar per Mini."),
 ("picker-progress-all-2.png", "The 'stall' was our bug: the bar only counted bytes on disk."),
 ("resume-2-stopped-all.png", "Stopped or failed downloads now get a Resume button."),
 ("resume-4-progress-all.png", "Resume picks the download back up, with automatic retry."),
 ("picker-v3-maxsize.png", "The size filter now defaults to Any size, not 20 GB."),
 ("day17-final-ondisk.png", "On disk lists each model and helper by name, per Mini."),
 ("day17-final-ondisk.png", "Caravan now asks before downloading a helper: Download or Not now."),
 ("day17-final-chat-stats.png", "Under each reply: how fast it read your prompt and wrote the answer."),
 ("day17-final-settings.png", "Settings got the same clean look as Models and Topology."),
 ("settings-hints.png", "One plain hint per setting, with gains only where we measured them."),
 ("day17-final-hf-accepted.png", "Hugging Face token (the key for gated downloads): just 'accepted'."),
 ("day17-final-theme-meadow.png", "Four themes, one layout: 24 of 24 checks line up within 1 pixel."),
 ("day17-final-gguf-settings.png", "The big one: GGUF models now split across both Minis in the web UI."),
 ("day17-final-gguf-settings.png", "GGUF is llama.cpp's model format. The command line could already."),
 ("day17-final-gguf-topology.png", "Only the lead Mini needs the file. The split loaded in 18.6 s."),
 ("day17-final-gguf-chat.png", "Qwen3 30B split over two Minis: 34.7 tok/s. On one Mini: 42.9."),
 ("day17-final-gguf-chat.png", "Splitting is ~19% slower, so it's for models too big for one Mini."),
 ("day17-final-gguf-stopped.png", "It passed 20 of 20 load and unload steps over 5 cycles."),
 ("day17-final-topology.png", "Locked down: the split server only talks to your own Minis."),
 ("day17-final-topology.png", "From another laptop on the network, port 50052 is refused."),
 ("day17-final-back-to-mlx.png", "Next: each Mini loads its own share, plus a newer llama.cpp."),
 ("day17-final-back-to-mlx.png", "Then we re-test every speed. That was Day 17."),
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
    d = ImageDraw.Draw(im); t = "Day 17 · Nov 6–7, 2026"
    d.text(((W - d.textlength(t, font=f))//2, (H-BAND)//2 + 60), t, font=f, fill=(220, 210, 190))
    return im

def check():
    d = ImageDraw.Draw(Image.new("RGB", (1, 1)))
    for i, (_, c) in enumerate(S):
        w = d.textlength(c, font=FONT)
        assert "\n" not in c and w <= MAXW, (i, c, w)
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
            src = title_img() if img == TITLE else Image.open(os.path.join(SH, img)).convert("RGB")
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
    open(os.environ.get("CAPS", "/workspace/day17/video-captions.txt"), "w").write(
        "\n".join(f"{i*SEG:6.1f}s  {c}" for i, (_, c) in enumerate(S)) + "\n")

if __name__ == "__main__": main()
