#!/usr/bin/env python3
"""Fifteen-second Day 21 v2: one idea, from live Apply screenshots only.

Hook opens on the finished/ready moment with a plain payoff line, then shows
how: black Apply, Reloading model Mini-by-Mini, then Ready. Hard cuts, no
crossfades. Jargon in the screenshots (model name, EXO labels, layers, GB
budgets, health-check wording) is cropped or blurred, not rewritten.
Thunderbolt and reboot-restore claims are omitted. No live UI recording;
the production model was unloaded while this cut was made.
"""
from pathlib import Path
import argparse, hashlib, json, re, subprocess
import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageFont

HERE = Path(__file__).resolve().parent
ROOT = HERE / "day21-v2"
ASSETS = ROOT / "assets"
W, H, FPS = 1280, 720, 24
DURATION = 15
AREA_H, CAP_Y = 600, 620
BG, CAP_BG, FG = "#0b1016", "#06090d", "#f5f0e6"
FONT = "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"
BOLD = FONT.replace(".ttf", "-Bold.ttf")
HOOK = "New split, chatting again in 13 seconds"
NERD_LINES = [
    "For the nerds:",
    "split 27/37 back to 24/40",
    "reload 8.82 s · chat ready 12.93 s",
]
NERD = "For the nerds: split 27/37 back to 24/40 · reload 8.82 s · chat ready 12.93 s"
assert NERD_LINES[0] + " " + NERD_LINES[1] + " · " + NERD_LINES[2] == NERD

# Hard-cut timeline. Captions change on the same frame as the picture.
# (start_s, end_s, kind)
# kind: hook, apply, reload, ready, nerds
SHOTS = [
    (0.0, 3.0, "hook"),
    (3.0, 6.0, "apply"),
    (6.0, 9.5, "reload"),
    (9.5, 12.0, "ready"),
    (12.0, 15.0, "nerds"),
]
CAPS = [
    (3.0, 6.0, "Apply is black when the new split is ready."),
    (6.0, 9.5, "It tells you it's reloading, Mini by Mini."),
    (9.5, 12.0, "Chat is ready again in about 13 seconds."),
]
FORBIDDEN = re.compile(
    r"20\d\d|\*\*|\d+\s+tests?\b|tests? passed|"
    r"\b(?:Hermes|prefill|Huihui|abliterated|Claude|Thunderbolt|"
    r"comes back on its own|after a reboot)\b",
    re.I,
)

# Absolute boxes on the original PNGs, then cropped.
DONE_BLUR = [(61, 166, 88, 181), (61, 188, 88, 201)]  # EXO2, EXO1
DONE_CROP = (0, 8, 407, 235)
READY_BLUR = [
    (20, 566, 250, 598),  # EXO2 → EXO1 · 24 / 40 layers
    (14, 664, 370, 690),  # Preview: 24 / 40 layers · GB
]
READY_CROP = (0, 500, 407, 770)
# Apply fill on the uncropped ready PNG, used to assert the button is black.
APPLY_FILL = (28, 704, 80, 728)
RELOAD_BLUR = [
    (128, 186, 162, 202),  # EXO2
    (128, 206, 162, 222),  # EXO1
    (273, 226, 365, 242),  # health checks
]
RELOAD_CROP = (0, 8, 407, 262)


def font(n, bold=False):
    return ImageFont.truetype(BOLD if bold else FONT, n)


def width(draw, text, f):
    return draw.textbbox((0, 0), text, font=f)[2]


def center(draw, text, y, size, color=FG, bold=True):
    f = font(size, bold)
    tw = width(draw, text, f)
    assert tw <= W - 80, (text, tw)
    box = draw.textbbox((0, 0), text, font=f)
    assert y + box[3] < H - 16, (text, y, box)
    draw.text(((W - tw) / 2, y), text, font=f, fill=color)
    return tw


def blur_boxes(im, boxes, radius=10):
    im = im.copy()
    for x0, y0, x1, y1 in boxes:
        region = im.crop((x0, y0, x1, y1))
        region = region.filter(ImageFilter.GaussianBlur(radius=radius))
        region = region.filter(ImageFilter.GaussianBlur(radius=radius))
        im.paste(region, (x0, y0))
    return im


def fit(panel, max_w, max_h):
    scale = min(max_w / panel.width, max_h / panel.height)
    size = (round(panel.width * scale), round(panel.height * scale))
    return panel.resize(size, Image.Resampling.LANCZOS), scale


def panel(name, boxes, crop):
    im = blur_boxes(Image.open(ASSETS / name).convert("RGB"), boxes)
    return im.crop(crop)


def caption_bar(im, text):
    d = ImageDraw.Draw(im)
    d.rectangle((0, CAP_Y, W, H), fill=CAP_BG)
    f = font(34, True)
    tw = width(d, text, f)
    assert tw <= W - 56, (text, tw)
    d.text(((W - tw) / 2, 650), text, font=f, fill=FG)
    return im


def place(im, panel_im, xy):
    im.paste(panel_im, xy)
    return xy


def hook_frame():
    im = Image.new("RGB", (W, H), BG)
    d = ImageDraw.Draw(im)
    center(d, HOOK, 52, 48, FG, True)
    p, _ = fit(panel("apply-done.png", DONE_BLUR, DONE_CROP), 760, 470)
    x, y = (W - p.width) // 2, 130
    im.paste(p, (x, y))
    return im


def apply_frame():
    im = Image.new("RGB", (W, H), BG)
    src = blur_boxes(Image.open(ASSETS / "apply-ready.png").convert("RGB"), READY_BLUR)
    p, scale = fit(src.crop(READY_CROP), 680, 560)
    x = (W - p.width) // 2
    y = 10 + (AREA_H - p.height) // 2
    im.paste(p, (x, y))
    # Map the uncropped Apply fill box into this frame and require it to be black.
    ax0 = x + round((APPLY_FILL[0] - READY_CROP[0]) * scale)
    ay0 = y + round((APPLY_FILL[1] - READY_CROP[1]) * scale)
    ax1 = x + round((APPLY_FILL[2] - READY_CROP[0]) * scale)
    ay1 = y + round((APPLY_FILL[3] - READY_CROP[1]) * scale)
    fill = np.array(im.crop((ax0, ay0, ax1, ay1)))
    mean = fill.mean(axis=(0, 1))
    luma = 0.2126 * mean[0] + 0.7152 * mean[1] + 0.0722 * mean[2]
    assert luma < 28, (tuple(mean.round(1)), luma, (ax0, ay0, ax1, ay1))
    return caption_bar(im, CAPS[0][2]), (ax0, ay0, ax1, ay1, luma, tuple(mean.round(1)))


def reload_frame():
    im = Image.new("RGB", (W, H), BG)
    p, _ = fit(panel("apply-reloading.png", RELOAD_BLUR, RELOAD_CROP), 740, 560)
    x, y = (W - p.width) // 2, 10 + (AREA_H - p.height) // 2
    im.paste(p, (x, y))
    return caption_bar(im, CAPS[1][2])


def ready_frame():
    im = Image.new("RGB", (W, H), BG)
    p, _ = fit(panel("apply-done.png", DONE_BLUR, DONE_CROP), 740, 560)
    x, y = (W - p.width) // 2, 10 + (AREA_H - p.height) // 2
    im.paste(p, (x, y))
    return caption_bar(im, CAPS[2][2])


def nerd_frame():
    im = Image.new("RGB", (W, H), BG)
    d = ImageDraw.Draw(im)
    center(d, NERD_LINES[0], 230, 40)
    center(d, NERD_LINES[1], 320, 40)
    center(d, NERD_LINES[2], 400, 40)
    return im


def frame(n, apply_info=None):
    t = n / FPS
    if t >= DURATION:
        t = DURATION - 1e-9
    kind = next(k for a, b, k in SHOTS if a <= t < b)
    if kind == "hook":
        return hook_frame()
    if kind == "apply":
        im, info = apply_frame()
        if apply_info is not None:
            apply_info.append(info)
        return im
    if kind == "reload":
        return reload_frame()
    if kind == "ready":
        return ready_frame()
    if kind == "nerds":
        return nerd_frame()
    raise AssertionError(kind)


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--output", default="/workspace/caravan-day21-v2.mp4")
    args = ap.parse_args()

    texts = [HOOK, NERD] + list(NERD_LINES) + [c for _, _, c in CAPS]
    for s in texts:
        assert not FORBIDDEN.search(s), s
        assert "\n" not in s
    for a, b, c in CAPS:
        assert b - a >= 2.5, (a, b, c)
    assert SHOTS[0][2] == "hook" and SHOTS[0][1] - SHOTS[0][0] >= 2.5
    assert SHOTS[-1][2] == "nerds" and SHOTS[-1][1] - SHOTS[-1][0] >= 3
    assert abs(SHOTS[-1][1] - DURATION) < 1e-9
    assert 12 <= DURATION <= 15
    # The ready Apply screenshot must be the post-styling black button file.
    ready_hash = hashlib.sha256((ASSETS / "apply-ready.png").read_bytes()).hexdigest()
    expected = hashlib.sha256(Path("/workspace/day21-apply-ready.png").read_bytes()).hexdigest()
    assert ready_hash == expected, "apply-ready.png is not the post-styling black-Apply shot"

    sources = {
        name: hashlib.sha256((ASSETS / name).read_bytes()).hexdigest()
        for name in ("apply-ready.png", "apply-reloading.png", "apply-done.png")
    }
    manifest = {
        "duration_s": DURATION,
        "fps": FPS,
        "dimensions": [W, H],
        "captions": (
            [{"start_s": 0.0, "end_s": 3.0, "text": f"[hook, no bottom caption] {HOOK}"}]
            + [{"start_s": a, "end_s": b, "text": c} for a, b, c in CAPS]
            + [{"start_s": 12.0, "end_s": 15.0, "text": f"[plain final card] {NERD}"}]
        ),
        "cuts_s": [a for a, _, _ in SHOTS],
        "transitions": "Hard cuts only; captions change on the cut frame.",
        "footage": (
            "Live Day 21 Apply screenshots only: apply-ready.png (black Apply, "
            "captured after the styling change), apply-reloading.png, "
            "apply-done.png. Crops and Gaussian blurs hide model-name, EXO "
            "labels, layers, GB budgets, and health-check wording. Screenshot "
            "text is not rewritten. No Thunderbolt, no live recording, no "
            "Apply/Load/Unload for this cut, no reboot-restore claim."
        ),
        "numbers": {
            "apply_backend_ready_s": 8.82,
            "apply_chat_usable_s": 12.93,
            "caption_chat_ready_rounded_s": 13,
            "split_from": "27/37",
            "split_to": "24/40",
            "split_shown_on": "nerds card only; 27/37 is not in the screenshots",
        },
        "sources": [
            "docs/release-notes/day21.md: UI Apply Huihui 27/37 back to 24/40 KV16, backend Ready 8.82s, chat usable 12.93s including polling",
            "/workspace/day21-apply-ready.png, day21-apply-reloading.png, day21-apply-done.png",
        ],
        "asset_sha256": sources,
        "precision": (
            "Hook and caption '13 seconds' / 'about 13 seconds' is the rounded "
            "chat-usable time. Exact 12.93 s and backend Ready 8.82 s, plus "
            "27/37 back to 24/40, are on the final card. The reload banner's "
            "'about 10 seconds' is the product estimate, left unaltered."
        ),
    }
    (ROOT / "manifest.json").write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False) + "\n"
    )
    lines = [f"0.0–3.0s  [hook, no bottom caption] {HOOK}"]
    lines += [f"{a:.1f}–{b:.1f}s  {c}" for a, b, c in CAPS]
    lines.append(f"12.0–15.0s  [plain final card] {NERD}")
    (ROOT / "captions.txt").write_text("\n".join(lines) + "\n")

    reviews = Path(args.output).with_suffix("").with_name(
        Path(args.output).stem + "-review"
    )
    reviews.mkdir(exist_ok=True)
    # Every cut, plus a mid-shot frame for each beat.
    keep = {0, 36, 72, 96, 144, 180, 228, 252, 288, 324, 359}

    apply_info = []
    ff = subprocess.Popen(
        [
            "ffmpeg", "-y", "-v", "error",
            "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{W}x{H}",
            "-r", str(FPS), "-i", "-",
            "-c:v", "libx264", "-preset", "medium", "-crf", "18",
            "-pix_fmt", "yuv420p", "-movflags", "+faststart",
            args.output,
        ],
        stdin=subprocess.PIPE,
    )
    for n in range(DURATION * FPS):
        im = frame(n, apply_info if n == 72 else None)
        if n in keep:
            im.save(reviews / f"frame-{n:03d}.png")
        ff.stdin.write(im.tobytes())
    ff.stdin.close()
    assert ff.wait() == 0
    assert apply_info, "Apply frame was not sampled"
    ax0, ay0, ax1, ay1, luma, mean = apply_info[0]
    print(
        args.output,
        f"{DURATION:.3f} seconds",
        f"Apply fill luma={luma:.1f} mean={mean} box={(ax0, ay0, ax1, ay1)}",
    )
    print((ROOT / "captions.txt").read_text())


if __name__ == "__main__":
    main()
