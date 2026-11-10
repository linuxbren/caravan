#!/usr/bin/env python3
"""Day 19 video: real Caravan web UI footage + cards. Single-line bottom captions. No dates on screen."""
import os, subprocess, sys, re, io
from PIL import Image, ImageDraw, ImageFont

W, H, FPS = 1280, 720, 24
BAND = 84
N = os.environ.get("CLIPS", "/workspace/d19v")
OUT = sys.argv[1] if len(sys.argv) > 1 else "/workspace/caravan-day19.mp4"
FONT = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 30)
MONO = "/usr/share/fonts/truetype/dejavu/DejaVuSansMono-Bold.ttf"
if not os.path.exists(MONO):
    MONO = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"
DAY = os.environ.get("VIDEO_DAY", "Day 19")

# (clip, start_s, dur_s, crop or None, caption)
S = [
    ("01-home", 0.4, 3.6, None, "Two Mac minis. One model. Built in the open."),
    ("05-loaded", 0.4, 3.8, None, "Huihui is ready across both Minis."),
    ("03-topology", 0.5, 4.2, None, "Topology: live memory on every Mini."),
    ("03-topology", 2.0, 4.0, (0, 40, 640, 520), "Balance: 24 layers here, 40 on the lead."),
    ("03-topology", 3.5, 3.8, (0, 40, 640, 520), "Auto picks a split from real free RAM."),
    ("02-models", 0.5, 4.0, None, "Each Mini keeps its own files."),
    ("02-models", 2.0, 3.6, (640, 40, 1280, 520), "No lead-to-packer weight ferry."),
    ("04-settings", 0.5, 4.0, None, "Install got quieter: one launchd path."),
    ("04-settings", 2.0, 3.8, (640, 40, 1280, 520), "Last successful model comes back as you left it."),
    ("__remote__", 0, 4.2, None, "Remote access: Thunderbolt and LAN SSH backups."),
    ("__remote__", 0, 3.8, None, "Tailscale guards run on a timer. Non-root."),
    ("__tests__", 0, 4.2, None, "738 tests passed. Day 19 release is out."),
    ("01-home", 1.0, 3.8, None, "Hermes chats through the local proxy."),
    ("__title__", 0, 3.6, None, "Next: self-tune climbs you can see."),
]

DATE = re.compile(
    r"20\d\d|\b(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]* \d|\b\d{1,2}:\d\d\b|\b(AM|PM|tonight|yesterday|today|morning|evening)\b",
    re.I,
)

def check():
    d = ImageDraw.Draw(Image.new("RGB", (1, 1)))
    for _, _, _, _, c in S:
        assert "\n" not in c and not DATE.search(c), c
        l, t, r, b = d.textbbox((0, 0), c, font=FONT)
        assert r - l <= W - 60, (c, r - l)

def frames(clip, start, dur):
    p = subprocess.run(
        [
            "ffmpeg", "-loglevel", "error", "-ss", str(start), "-i", f"{N}/{clip}.mp4",
            "-t", str(dur), "-f", "rawvideo", "-pix_fmt", "rgb24", "-",
        ],
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
    d.text((90, 80), title, font=ft, fill=(242, 180, 90))
    y = 180
    for a, b, c in rows:
        d.text((90, y), a, font=fr, fill=(225, 220, 205))
        d.text((620, y), b, font=fr, fill=c)
        y += 70
    if foot:
        d.text((90, H - BAND - 60), foot, font=fs, fill=(140, 130, 110))
    return im

G, R, Y = (120, 210, 120), (230, 110, 100), (235, 200, 110)

def still(kind):
    if kind == "__remote__":
        return card(
            "Remote access hardened",
            [
                ("Thunderbolt SSH", "backup path", G),
                ("LAN SSH", "backup path", G),
                ("Tailscale guards", "two-minute, non-root", G),
                ("Real SSH paths checked", "5 / 5", G),
            ],
            "caravan-ssh route fallback",
        )
    if kind == "__tests__":
        return card(
            "Day 19 release checks",
            [
                ("Full box suite", "738 passed", G),
                ("Package suite", "738 passed", G),
                ("Balance split", "24 / 40", G),
                ("Hermes proxy", "loopback :8090", G),
            ],
            DAY + " tag published",
        )
    im = Image.new("RGB", (W, H), (18, 16, 12))
    d = ImageDraw.Draw(im)
    f = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 48)
    t = "caravan"
    tw = d.textlength(t, font=f)
    d.text(((W - tw) // 2, H // 2 - 80), t, font=f, fill=(242, 180, 90))
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
    d.text(((W - tw) // 2, H - BAND + 24), text, font=FONT, fill=(235, 225, 205))
    return im2

def main():
    check()
    caps = []
    t = 0.0
    ff = subprocess.Popen(
        [
            "ffmpeg", "-y", "-loglevel", "error",
            "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{W}x{H}", "-r", str(FPS),
            "-i", "-", "-c:v", "libx264", "-preset", "slow", "-crf", "22",
            "-pix_fmt", "yuv420p", "-movflags", "+faststart", OUT,
        ],
        stdin=subprocess.PIPE,
    )
    for clip, st, du, crop, cap in S:
        if clip.startswith("__"):
            fs = [still(clip)] * int(du * FPS)
        else:
            fs = frames(clip, st, du)
        n = len(fs)
        caps.append(f"{t:6.1f}s  {cap}")
        t += du
        for k, f in enumerate(fs):
            if crop:
                x0, y0, x1, y1 = crop
                p = k / max(1, n - 1)
                z = 0.02 * p
                dx = (x1 - x0) * z / 2
                dy = (y1 - y0) * z / 2
                f = f.crop((int(x0 + dx), int(y0 + dy), int(x1 - dx), int(y1 - dy))).resize((W, H), Image.LANCZOS)
            f = caption_band(f, cap)
            ff.stdin.write(f.tobytes())
    ff.stdin.close()
    rc = ff.wait()
    open(os.path.join(N, "day19_captions.txt"), "w").write("\n".join(caps) + "\n")
    print("wrote", OUT, "rc", rc, "duration", round(t, 2), "captions", len(caps))
    return rc

if __name__ == "__main__":
    raise SystemExit(main())
