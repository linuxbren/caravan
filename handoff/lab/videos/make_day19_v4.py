#!/usr/bin/env python3
"""Day 19 v4: big phone-readable type, complete wrapped answer, simple status views.

Chat Q is the same live question from the v3 screencast. The complete on-screen
answer is a real post-restore reply (thinking off) to that question, with
markdown asterisks stripped for display. Switchover and reboot beats are
drawn from the real logs/timings, not invented. Reboot auto-restore was
partial: the computers and web service came back on their own; the model
needed a manual Load after restore blocked.
"""
import os, subprocess, re, sys, math
from PIL import Image, ImageDraw, ImageFont

W, H, FPS = 1280, 720, 24
BAND = 100
OUT = sys.argv[1] if len(sys.argv) > 1 else "/home/brenden/day19-video/caravan-day19-v4.mp4"
CAPTIONS_PATH = "/home/brenden/day19-video/v4/day19_captions_v4.txt"
FONT_B = "/usr/share/fonts/noto/NotoSans-Bold.ttf"
FONT_R = "/usr/share/fonts/noto/NotoSans-Regular.ttf"
BG = (12, 14, 18)
AMBER = (242, 180, 90)
CREAM = (235, 225, 205)
MUTED = (160, 150, 130)
GREEN = (120, 210, 120)
RED = (230, 110, 90)
PANEL = (22, 24, 30)
YOU_BG = (42, 36, 22)
BOT_BG = (28, 30, 36)

QUESTION = "Name three fruits that are usually red."
ANSWER = (
    "Here are three fruits that are usually red:\n"
    "1. Apples (specifically varieties like Red Delicious or Fuji)\n"
    "2. Strawberries\n"
    "3. Cherries"
)

# (kind, duration_s, caption, payload)
S = [
    ("chat", 2.2, "Ask a simple question. Watch it answer live.", None),
    ("chat", 9.8, "The words show up as they're written.", None),
    ("switch_1", 4.0, "If the main path drops, another way in is ready.", None),
    ("switch_2", 4.0, "It switched on its own. Everything stayed reachable.", None),
    ("reboot_down", 4.0, "Pull the plug, the computers come back on their own.", None),
    ("reboot_load", 4.0, "The model needed a Load. Then the same split was ready.", None),
    ("title", 2.0, "Two Macs. One model. Built in the open.", None),
    ("nerds", 2.0, "For the nerds: Huihui 24/40 on EXO2 then EXO1.", None),
]

DATE = re.compile(
    r"20\d\d|\b(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]* \d|"
    r"\b\d{1,2}:\d\d\b|\b(AM|PM|tonight|yesterday|today|morning|evening)\b",
    re.I,
)
BAD = re.compile(
    r"\b\d+\s*tests?\b|\btests?\s+passed\b|launchd|pipeline_chats|\bshards?\b|"
    r"\bstages?\b|in our tests|:8090",
    re.I,
)


def font(path, size):
    return ImageFont.truetype(path, size)


def wrap(draw, text, fnt, max_w):
    lines = []
    for para in text.split("\n"):
        if not para:
            lines.append("")
            continue
        words = para.split(" ")
        cur = words[0]
        for w in words[1:]:
            trial = cur + " " + w
            if draw.textbbox((0, 0), trial, font=fnt)[2] <= max_w:
                cur = trial
            else:
                lines.append(cur)
                cur = w
        lines.append(cur)
    return lines


def rounded(d, xy, r, fill):
    d.rounded_rectangle(xy, radius=r, fill=fill)


def caption_band(im, text):
    capf = font(FONT_B, 34)
    overlay = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    od = ImageDraw.Draw(overlay)
    od.rectangle([0, H - BAND, W, H], fill=(8, 7, 5, 235))
    im2 = Image.alpha_composite(im.convert("RGBA"), overlay).convert("RGB")
    d = ImageDraw.Draw(im2)
    bbox = d.textbbox((0, 0), text, font=capf)
    tw = bbox[2] - bbox[0]
    d.text(((W - tw) // 2, H - BAND + 30), text, font=capf, fill=CREAM)
    return im2


def check():
    d = ImageDraw.Draw(Image.new("RGB", (1, 1)))
    capf = font(FONT_B, 34)
    for _, _, c, _ in S:
        assert "\n" not in c and not DATE.search(c) and not BAD.search(c), c
        l, t, r, b = d.textbbox((0, 0), c, font=capf)
        assert r - l <= W - 48, (c, r - l)


def frame_chat(t):
    """t in [0, 12). Type for 1s, bubble at 1.0, first words by 2.0, done ~8s."""
    im = Image.new("RGB", (W, H), BG)
    d = ImageDraw.Draw(im)
    qf = font(FONT_B, 40)
    af = font(FONT_R, 38)
    lf = font(FONT_B, 22)
    # typed portion
    n = min(len(QUESTION), int(round(len(QUESTION) * min(1.0, t / 1.0))))
    typed = QUESTION[:n]
    # layout column
    margin = 70
    col_w = W - 2 * margin
    y = 36
    # YOU bubble after send
    if t >= 1.0:
        d.text((margin, y), "YOU", font=lf, fill=AMBER)
        y += 34
        q_lines = wrap(d, QUESTION, qf, col_w - 48)
        line_h = 52
        box_h = 28 + line_h * len(q_lines)
        rounded(d, (margin, y, margin + col_w, y + box_h), 22, YOU_BG)
        yy = y + 12
        for line in q_lines:
            d.text((margin + 24, yy), line, font=qf, fill=CREAM)
            yy += line_h
        y = y + box_h + 28
    else:
        # big input while typing
        d.text((margin, 80), "ASK", font=lf, fill=AMBER)
        rounded(d, (margin, 120, margin + col_w, 120 + 110), 22, YOU_BG)
        cursor = "|" if int(t * 8) % 2 == 0 else " "
        d.text((margin + 24, 148), typed + cursor, font=qf, fill=CREAM)

    # answer streams starting at 2.0s, finishes by 8.0s
    if t >= 1.6:
        d.text((margin, y), "CARAVAN", font=lf, fill=AMBER)
        y += 34
        visible = ""
        if t >= 1.85:
            # first words visible by 2.0 s; complete by ~6.5 s
            prog = min(1.0, (t - 1.85) / 4.65)
            prog = 1 - (1 - prog) ** 1.25
            nch = max(1, int(round(len(ANSWER) * prog)))
            visible = ANSWER[:nch]
        a_lines = wrap(d, visible if visible else " ", af, col_w - 48)
        line_h = 50
        box_h = 28 + line_h * max(1, len(a_lines))
        # keep box inside caption band
        max_bottom = H - BAND - 16
        if y + box_h > max_bottom:
            box_h = max_bottom - y
        rounded(d, (margin, y, margin + col_w, y + box_h), 22, BOT_BG)
        yy = y + 12
        for line in a_lines:
            if yy + line_h > y + box_h - 8:
                break
            d.text((margin + 24, yy), line, font=af, fill=CREAM)
            yy += line_h
    return im


def status_card(title, rows, foot=None):
    """rows: list of (label, value, color). Big phone type."""
    im = Image.new("RGB", (W, H), BG)
    d = ImageDraw.Draw(im)
    tf = font(FONT_B, 48)
    lf = font(FONT_R, 36)
    vf = font(FONT_B, 40)
    ff = font(FONT_R, 26)
    # title
    tw = d.textbbox((0, 0), title, font=tf)[2]
    d.text(((W - tw) // 2, 56), title, font=tf, fill=AMBER)
    # rows in a wide panel
    panel = (90, 160, W - 90, H - BAND - 40)
    rounded(d, panel, 28, PANEL)
    y = 200
    for label, value, color in rows:
        d.text((140, y), label, font=lf, fill=MUTED)
        # value right-aligned-ish
        vw = d.textbbox((0, 0), value, font=vf)[2]
        d.text((W - 140 - vw, y - 2), value, font=vf, fill=color)
        y += 86
    if foot:
        fw = d.textbbox((0, 0), foot, font=ff)[2]
        d.text(((W - fw) // 2, H - BAND - 70), foot, font=ff, fill=MUTED)
    return im


def frame_switch(kind):
    if kind == "switch_1":
        return status_card("Connection", [
            ("Main connection", "off", RED),
            ("Backup connection", "on", GREEN),
        ])
    return status_card("Connection", [
        ("Main connection", "off", RED),
        ("Backup connection", "on, switched by itself", GREEN),
    ])


def frame_reboot(kind, t, dur):
    if kind == "reboot_down":
        # Real captured unreachable card, then a short "they're back" flash
        # Hold unreachable for most of the beat, last 1s show computers back.
        im = Image.new("RGB", (W, H), (12, 14, 18))
        d = ImageDraw.Draw(im)
        if t < 1.5:
            f = font(FONT_B, 64)
            msg = "Caravan unreachable"
            tw = d.textbbox((0, 0), msg, font=f)[2]
            d.text(((W - tw) // 2, H // 2 - 80), msg, font=f, fill=AMBER)
        else:
            return status_card("After the plug was pulled", [
                ("Computers", "back on their own", GREEN),
                ("Web service", "back on its own", GREEN),
            ])
        return im
    return status_card("The model", [
        ("Automatic restore", "blocked", RED),
        ("After a Load", "same split ready", GREEN),
    ])


def frame_title():
    im = Image.new("RGB", (W, H), (18, 16, 12))
    d = ImageDraw.Draw(im)
    f = font(FONT_R, 64)
    tw = d.textbbox((0, 0), "caravan", font=f)[2]
    d.text(((W - tw) // 2, H // 2 - 90), "caravan", font=f, fill=AMBER)
    f2 = font(FONT_R, 36)
    sub = "Two Macs. One model. Built in the open."
    tw2 = d.textbbox((0, 0), sub, font=f2)[2]
    d.text(((W - tw2) // 2, H // 2 + 10), sub, font=f2, fill=CREAM)
    return im


def frame_nerds():
    return status_card("For the nerds", [
        ("Model", "Huihui 27B 4-bit", GREEN),
        ("Split", "24 / 40", GREEN),
        ("Order", "EXO2 then EXO1", GREEN),
    ])


CHAT_T0 = {"t": 0.0}

def make_segment(kind, dur):
    n = int(round(dur * FPS))
    frames = []
    chat_base = CHAT_T0["t"] if kind == "chat" else 0.0
    for i in range(n):
        t = i / FPS
        if kind == "chat":
            im = frame_chat(chat_base + t)
        elif kind.startswith("switch"):
            im = frame_switch(kind)
        elif kind.startswith("reboot"):
            im = frame_reboot(kind, t, dur)
        elif kind == "title":
            im = frame_title()
        elif kind == "nerds":
            im = frame_nerds()
        else:
            raise SystemExit(f"unknown {kind}")
        frames.append(im)
    if kind == "chat":
        CHAT_T0["t"] += dur
    return frames


def main():
    check()
    caps = []
    t = 0.0
    ff = subprocess.Popen(
        [
            "ffmpeg", "-y", "-loglevel", "error",
            "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{W}x{H}", "-r", str(FPS),
            "-i", "-", "-c:v", "libx264", "-preset", "slow", "-crf", "20",
            "-pix_fmt", "yuv420p", "-movflags", "+faststart", OUT,
        ],
        stdin=subprocess.PIPE,
    )
    for kind, du, cap, _ in S:
        fs = make_segment(kind, du)
        caps.append(f"{t:6.1f}s  {cap}")
        t += du
        for im in fs:
            ff.stdin.write(caption_band(im, cap).tobytes())
    ff.stdin.close()
    rc = ff.wait()
    body = "\n".join(caps) + "\n"
    open(CAPTIONS_PATH, "w").write(body)
    assert not BAD.search(body) and not DATE.search(body), body
    print("wrote", OUT, "rc", rc, "duration", round(t, 2))
    print(body)
    return rc


if __name__ == "__main__":
    raise SystemExit(main())
