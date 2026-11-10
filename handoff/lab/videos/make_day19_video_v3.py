#!/usr/bin/env python3
"""Day 19 v3: live chat + real path fallback. Human captions. No test counts, no dates, no jargon."""
import os, subprocess, re, sys
from PIL import Image, ImageDraw, ImageFont

W, H, FPS = 1280, 720, 24
BAND = 84
CLIPS = "/home/brenden/day19-video/v3/clips"
OUT = sys.argv[1] if len(sys.argv) > 1 else "/home/brenden/day19-video/caravan-day19-v3.mp4"
FONT = ImageFont.truetype("/usr/share/fonts/noto/NotoSans-Bold.ttf", 28)
MONO = "/usr/share/fonts/liberation/LiberationMono-Bold.ttf"
if not os.path.exists(MONO):
    MONO = "/usr/share/fonts/noto/NotoSans-Bold.ttf"

# Tight crops — hide pills, model names, MODELS list, side chrome
CROP_TYPE = (175, 418, 1138, 568)
CROP_REPLY = (190, 170, 900, 500)

S = [
    # chat-live3 is 11.48s; typing starts ~0.4s
    ("chat-live3", 0.3, 4.4, CROP_TYPE, "Ask a simple question. Watch it answer live."),
    ("chat-live3", 4.4, 8.0, CROP_REPLY, "The words show up as they're written."),
    ("path-fallback", 0.3, 7.6, (50, 50, 1230, 670), "If the main path drops, another way in is ready."),
    ("path-fallback", 7.4, 4.0, (50, 50, 1230, 670), "It switched on its own. Everything stayed reachable."),
    ("__title__", 0, 3.8, None, "Two Macs. One model. Built in the open."),
    ("__nerds__", 0, 3.8, None, "For the nerds: Huihui 24/40 on EXO2 then EXO1."),
]

DATE = re.compile(r"20\d\d|\b(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]* \d|\b\d{1,2}:\d\d\b|\b(AM|PM|tonight|yesterday|today|morning|evening)\b", re.I)
BAD = re.compile(r"\b\d+\s*tests?\b|\btests?\s+passed\b|launchd|pipeline_chats|\bshards?\b|\bstages?\b|in our tests|:8090", re.I)

def check():
    d = ImageDraw.Draw(Image.new("RGB", (1, 1)))
    for *_, c in S:
        assert "\n" not in c and not DATE.search(c) and not BAD.search(c), c
        l, t, r, b = d.textbbox((0, 0), c, font=FONT)
        assert r - l <= W - 40, (c, r - l)

def frames(clip, start, dur):
    p = subprocess.run(
        ["ffmpeg", "-loglevel", "error", "-ss", str(start), "-i", f"{CLIPS}/{clip}.mp4",
         "-t", str(dur), "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{W}x{H}", "-"],
        capture_output=True,
    ).stdout
    step = W * H * 3
    fs = [Image.frombytes("RGB", (W, H), p[i:i+step]) for i in range(0, len(p) - step + 1, step)]
    need = int(round(dur * FPS))
    while len(fs) < need:
        fs.append(fs[-1] if fs else Image.new("RGB", (W, H), (14, 12, 8)))
    return fs[:need]

def card(title, rows, foot):
    im = Image.new("RGB", (W, H), (14, 12, 8))
    d = ImageDraw.Draw(im)
    ft = ImageFont.truetype(MONO, 36)
    fr = ImageFont.truetype(MONO, 28)
    fs = ImageFont.truetype(MONO, 20)
    G = (120, 210, 120)
    d.text((90, 80), title, font=ft, fill=(242, 180, 90))
    y = 180
    for a, b, c in rows:
        d.text((90, y), a, font=fr, fill=(225, 220, 205))
        d.text((620, y), b, font=fr, fill=c)
        y += 70
    if foot:
        d.text((90, H - BAND - 60), foot, font=fs, fill=(140, 130, 110))
    return im

def still(kind):
    G = (120, 210, 120)
    if kind == "__nerds__":
        return card("For the nerds", [
            ("Model", "Huihui 27B 4-bit", G),
            ("Split", "24 / 40", G),
            ("Order", "EXO2 then EXO1", G),
        ], "Same live setup your chat is using")
    im = Image.new("RGB", (W, H), (18, 16, 12))
    d = ImageDraw.Draw(im)
    f = ImageFont.truetype("/usr/share/fonts/noto/NotoSans-Regular.ttf", 48)
    tw = d.textlength("caravan", font=f)
    d.text(((W - tw) // 2, H // 2 - 80), "caravan", font=f, fill=(242, 180, 90))
    f2 = ImageFont.truetype("/usr/share/fonts/noto/NotoSans-Regular.ttf", 32)
    tw2 = d.textlength("Day 19", font=f2)
    d.text(((W - tw2) // 2, H // 2 + 10), "Day 19", font=f2, fill=(225, 215, 195))
    return im

def caption_band(im, text):
    overlay = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    od = ImageDraw.Draw(overlay)
    od.rectangle([0, H - BAND, W, H], fill=(8, 7, 5, 230))
    im2 = Image.alpha_composite(im.convert("RGBA"), overlay).convert("RGB")
    d = ImageDraw.Draw(im2)
    bbox = d.textbbox((0, 0), text, font=FONT)
    tw = bbox[2] - bbox[0]
    d.text(((W - tw) // 2, H - BAND + 26), text, font=FONT, fill=(235, 225, 205))
    return im2

def fit_crop(f, crop):
    x0, y0, x1, y1 = crop
    piece = f.crop((x0, y0, x1, y1))
    scale = W / piece.width
    nw, nh = W, int(piece.height * scale)
    # Never cover the caption band
    max_h = H - BAND - 30
    if nh > max_h:
        scale = max_h / piece.height
        nw, nh = int(piece.width * scale), max_h
        piece = piece.resize((nw, nh), Image.LANCZOS)
        canvas = Image.new("RGB", (W, H), (12, 14, 18))
        canvas.paste(piece, ((W - nw)//2, 40))
        return canvas
    piece = piece.resize((nw, nh), Image.LANCZOS)
    canvas = Image.new("RGB", (W, H), (12, 14, 18))
    y = max(30, (H - BAND - nh)//2)
    canvas.paste(piece, ((W - nw)//2, y))
    return canvas

def main():
    check()
    caps = []; t = 0.0
    ff = subprocess.Popen(
        ["ffmpeg", "-y", "-loglevel", "error",
         "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{W}x{H}", "-r", str(FPS),
         "-i", "-", "-c:v", "libx264", "-preset", "slow", "-crf", "22",
         "-pix_fmt", "yuv420p", "-movflags", "+faststart", OUT],
        stdin=subprocess.PIPE,
    )
    for clip, st, du, crop, cap in S:
        fs = [still(clip)] * int(round(du * FPS)) if clip.startswith("__") else frames(clip, st, du)
        n = len(fs)
        caps.append(f"{t:6.1f}s  {cap}")
        t += du
        for k, f in enumerate(fs):
            if crop:
                f = fit_crop(f, crop)
            ff.stdin.write(caption_band(f, cap).tobytes())
    ff.stdin.close()
    rc = ff.wait()
    body = "\n".join(caps) + "\n"
    open("/home/brenden/day19-video/v3/day19_captions_v3.txt", "w").write(body)
    assert not BAD.search(body) and not DATE.search(body), body
    print("wrote", OUT, "rc", rc, "duration", round(t, 2))
    print(body)
    return rc

if __name__ == "__main__":
    raise SystemExit(main())
