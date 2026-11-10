#!/usr/bin/env python3
"""Day 19 v2: real UI footage, human benefit-led captions, no test counts, no jargon, no dates."""
import os, subprocess, sys, re
from PIL import Image, ImageDraw, ImageFont

W, H, FPS = 1280, 720, 24
BAND = 84
N = os.environ.get("CLIPS", "/workspace/d19v")
OUT = sys.argv[1] if len(sys.argv) > 1 else "/workspace/caravan-day19-v2.mp4"
FONT = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 28)
MONO = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"
DAY = "Day 19"

# Human, benefit-led, single-line. No launchd/pipeline/shards/stages/tests.
S = [
    ("01-home", 0.4, 3.6, None, "Two Macs. One model. Built in the open."),
    ("05-loaded", 0.4, 3.8, None, "Your big model is ready on both machines."),
    ("03-topology", 0.5, 4.2, None, "See how much free memory each Mac still has."),
    ("03-topology", 2.0, 4.0, (0, 40, 640, 520), "It splits the work so neither Mac runs out of room."),
    ("03-topology", 3.5, 3.8, (0, 40, 640, 520), "It picks a split that actually fits."),
    ("02-models", 0.5, 4.0, None, "Each Mac keeps what it needs on its own disk."),
    ("02-models", 2.0, 3.6, (640, 40, 1280, 520), "No hauling giant files back and forth."),
    ("04-settings", 0.5, 4.0, None, "Pull the plug and it comes back on its own."),
    ("04-settings", 2.0, 3.8, (640, 40, 1280, 520), "The last model you used returns the way you left it."),
    ("__remote__", 0, 4.0, None, "If the main path drops, another way in is ready."),
    ("__remote__", 0, 3.6, None, "Remote access stays watched without needing admin."),
    ("03-topology", 1.0, 4.2, (0, 40, 700, 560), "Right now Huihui is live across both Minis."),
    ("05-loaded", 1.0, 3.8, None, "Your chat agent can talk to it over the local link."),
    ("__title__", 0, 3.4, None, "Next: watch it learn a faster setting on screen."),
    ("__nerds__", 0, 3.2, None, "For the nerds: Huihui 24/40 on EXO2 then EXO1."),
]

DATE = re.compile(
    r"20\d\d|\b(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]* \d|\b\d{1,2}:\d\d\b|\b(AM|PM|tonight|yesterday|today|morning|evening)\b",
    re.I,
)
BAD = re.compile(
    r"\b\d+\s*tests?\b|\btests?\s+passed\b|launchd|pipeline_chats|\bshards?\b|\bstages?\b",
    re.I,
)

def check():
    d = ImageDraw.Draw(Image.new("RGB", (1, 1)))
    for _, _, _, _, c in S:
        assert "\n" not in c and not DATE.search(c), c
        assert not BAD.search(c), c
        l, t, r, b = d.textbbox((0, 0), c, font=FONT)
        assert r - l <= W - 40, (c, r - l)

def frames(clip, start, dur):
    p = subprocess.run(
        ["ffmpeg", "-loglevel", "error", "-ss", str(start), "-i", f"{N}/{clip}.mp4",
         "-t", str(dur), "-f", "rawvideo", "-pix_fmt", "rgb24", "-"],
        capture_output=True,
    ).stdout
    fs = [Image.frombytes("RGB", (W, H), p[i : i + W * H * 3]) for i in range(0, len(p) - W * H * 3 + 1, W * H * 3)]
    need = int(dur * FPS)
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
    if kind == "__remote__":
        return card(
            "Still reachable when a path fails",
            [
                ("Cable backup", "ready", G),
                ("Home-network backup", "ready", G),
                ("Remote watchdogs", "on a timer", G),
                ("Checked live", "all paths worked", G),
            ],
            "Falls over to the next path on its own",
        )
    if kind == "__nerds__":
        return card(
            "For the nerds",
            [
                ("Model", "Huihui 27B 4-bit", G),
                ("Split", "24 / 40", G),
                ("Order", "EXO2 then EXO1", G),
                ("Proxy", "local :8090", G),
            ],
            "Same live setup Hermes is using",
        )
    im = Image.new("RGB", (W, H), (18, 16, 12))
    d = ImageDraw.Draw(im)
    f = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 48)
    tw = d.textlength("caravan", font=f)
    d.text(((W - tw) // 2, H // 2 - 80), "caravan", font=f, fill=(242, 180, 90))
    f2 = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 32)
    tw2 = d.textlength(DAY, font=f2)
    d.text(((W - tw2) // 2, H // 2 + 10), DAY, font=f2, fill=(225, 215, 195))
    return im

def caption_band(im, text):
    overlay = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    od = ImageDraw.Draw(overlay)
    od.rectangle([0, H - BAND, W, H], fill=(8, 7, 5, 220))
    im2 = Image.alpha_composite(im.convert("RGBA"), overlay).convert("RGB")
    d = ImageDraw.Draw(im2)
    bbox = d.textbbox((0, 0), text, font=FONT)
    tw = bbox[2] - bbox[0]
    d.text(((W - tw) // 2, H - BAND + 26), text, font=FONT, fill=(235, 225, 205))
    return im2

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
        fs = [still(clip)] * int(du * FPS) if clip.startswith("__") else frames(clip, st, du)
        n = len(fs); caps.append(f"{t:6.1f}s  {cap}"); t += du
        for k, f in enumerate(fs):
            if crop:
                x0, y0, x1, y1 = crop
                p = k / max(1, n - 1); z = 0.02 * p
                dx = (x1 - x0) * z / 2; dy = (y1 - y0) * z / 2
                f = f.crop((int(x0 + dx), int(y0 + dy), int(x1 - dx), int(y1 - dy))).resize((W, H), Image.LANCZOS)
            ff.stdin.write(caption_band(f, cap).tobytes())
    ff.stdin.close(); rc = ff.wait()
    open(os.path.join(N, "day19_captions_v2.txt"), "w").write("\n".join(caps) + "\n")
    body = "\n".join(caps)
    assert not BAD.search(body) and not DATE.search(body), body
    print("wrote", OUT, "rc", rc, "duration", round(t, 2))
    print(body)
    return rc

if __name__ == "__main__":
    raise SystemExit(main())
