#!/usr/bin/env python3
"""Twenty-second Day 21 cut from live Balance and Thunderbolt screenshots.

Real UI crops, not bullet slides or reconstructed streaming. Apply-ready,
reloading, and done frames are the post-styling live shots (black Apply when
ready, grey while reloading). Auto crop stops above Apply so the earlier
yellow fill is not shown. No live recording or reload was performed for this
cut. The typographic end card is measured Apply timings only; it does not
claim post-reboot restore.
"""
from pathlib import Path
import argparse, hashlib, json, re, subprocess
from PIL import Image, ImageDraw, ImageFont

HERE = Path(__file__).resolve().parent
ROOT = HERE / "day21"
ASSETS = ROOT / "assets"
W, H, FPS = 1280, 720, 24
DURATION = 20
AREA_H, TARGET_W, CAP_Y = 600, 620, 620
BG, CAP_BG, FG, MUTED = "#0b1016", "#06090d", "#f5f0e6", "#bac1c7"
FONT = "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"
BOLD = FONT.replace(".ttf", "-Bold.ttf")
FADE = 6  # frames

# (start_s, end_s, asset or None, crop ltrb or None, kind)
# kind 'ui' uses a live screenshot crop; 'nerds' is the typographic end card.
VISUALS = [
    (0.0, 3.0, "balance-auto.png", (0, 0, 407, 500), "ui"),
    (3.0, 6.5, "apply-ready.png", (0, 500, 407, 770), "ui"),
    (6.5, 8.7, "apply-reloading.png", (0, 0, 407, 270), "ui"),
    (8.7, 10.5, "apply-reloading.png", (0, 588, 407, 875), "ui"),
    (10.5, 13.5, "apply-done.png", (0, 0, 407, 290), "ui"),
    (13.5, 16.5, "tb-verified.png", (0, 16, 407, 440), "ui"),
    (16.5, 20.0, None, None, "nerds"),
]
CAPS = [
    (0.0, 3.0, "Pick how your Macs share the model — or let it decide."),
    (3.0, 6.5, "Adjust the split. Apply is black when it's ready."),
    (6.5, 10.5, "It tells you it's reloading, Mini by Mini."),
    (10.5, 13.5, "Chat is ready again in about 13 seconds."),
    (13.5, 16.5, "It checks the Thunderbolt link between your Macs."),
]
NERD_LINES = ["For the nerds:", "reload 8.82 s · chat ready 12.93 s"]
NERD = " ".join(NERD_LINES)
FORBIDDEN = re.compile(
    r"20\d\d|\*\*|\d+\s+tests?\b|tests? passed|"
    r"\b(?:Hermes|prefill|Huihui|abliterated|Claude|comes back on its own)\b",
    re.I,
)


def font(n, bold=False):
    return ImageFont.truetype(BOLD if bold else FONT, n)


def width(draw, text, f):
    return draw.textbbox((0, 0), text, font=f)[2]


def center(draw, text, y, size, color=FG, bold=False):
    f = font(size, bold)
    tw = width(draw, text, f)
    assert tw <= W - 80, (text, tw)
    assert y + draw.textbbox((0, 0), text, font=f)[3] < H - 20, (text, y)
    draw.text(((W - tw) / 2, y), text, font=f, fill=color)
    return tw


def caption_bar(im, text):
    d = ImageDraw.Draw(im)
    d.rectangle((0, CAP_Y, W, H), fill=CAP_BG)
    if text:
        f = font(34, True)
        tw = width(d, text, f)
        assert tw <= W - 56, (text, tw)
        d.text(((W - tw) / 2, 650), text, font=f, fill=FG)
    return im


def fit_panel(panel):
    scale = min(TARGET_W / panel.width, AREA_H / panel.height)
    size = (round(panel.width * scale), round(panel.height * scale))
    return panel.resize(size, Image.Resampling.LANCZOS)


def ui_frame(asset, crop):
    panel = fit_panel(Image.open(ASSETS / asset).convert("RGB").crop(crop))
    im = Image.new("RGB", (W, H), BG)
    x = (W - panel.width) // 2
    y = 10 + (AREA_H - panel.height) // 2
    im.paste(panel, (x, y))
    return im


def nerd_frame():
    im = Image.new("RGB", (W, H), BG)
    d = ImageDraw.Draw(im)
    center(d, NERD_LINES[0], 250, 40, FG, True)
    center(d, NERD_LINES[1], 340, 40, FG, True)
    return im


def visual_at(t):
    for start, end, asset, crop, kind in VISUALS:
        if start <= t < end or (t == DURATION and end == DURATION):
            if kind == "nerds":
                return nerd_frame(), None
            cap = next(c for a, b, c in CAPS if a <= t < b)
            return ui_frame(asset, crop), cap
    raise AssertionError(t)


def blended_visual(t):
    # Crossfade only between consecutive UI shots that share a cut.
    cuts = [end for _, end, _, _, kind in VISUALS if kind == "ui" and end < DURATION]
    for cut in cuts:
        lo, hi = cut - FADE / FPS, cut
        if lo <= t < hi:
            a, cap_a = visual_at(lo - 1e-6)
            b, cap_b = visual_at(cut)
            frac = (t - lo) / (hi - lo)
            im = Image.blend(a.convert("RGB"), b.convert("RGB"), frac)
            # Keep the outgoing caption until the cut, then the incoming one.
            return im, (cap_a if frac < 1 else cap_b)
    return visual_at(t)


def frame(n):
    t = n / FPS
    im, cap = blended_visual(min(t, DURATION - 1e-6))
    if t >= 16.5:
        # Plain final card, no empty caption bar — same as the Day 20 v2 end card.
        return im
    return caption_bar(im, cap)


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--output", default="/workspace/caravan-day21.mp4")
    args = ap.parse_args()

    texts = [c for _, _, c in CAPS] + NERD_LINES + [NERD]
    for s in texts:
        assert not FORBIDDEN.search(s), s
        assert "\n" not in s
        assert "comes back" not in s.lower()
        assert "reboot" not in s.lower()
    for a, b, c in CAPS:
        assert b - a >= 3, (a, b, c)
    assert VISUALS[-1][4] == "nerds" and VISUALS[-1][1] - VISUALS[-1][0] >= 3
    assert abs(VISUALS[-1][1] - DURATION) < 1e-9
    assert 12 <= DURATION <= 20

    sources = {}
    for name in sorted({v[2] for v in VISUALS if v[2]}):
        sources[name] = hashlib.sha256((ASSETS / name).read_bytes()).hexdigest()

    manifest = {
        "duration_s": DURATION,
        "fps": FPS,
        "dimensions": [W, H],
        "captions": [{"start_s": a, "end_s": b, "text": c} for a, b, c in CAPS],
        "final_card": {"start_s": 16.5, "end_s": 20.0, "text": NERD},
        "footage": (
            "Live Day 21 UI screenshots from the Caravan web Balance and "
            "Thunderbolt panels. Crops only; no text rewritten inside the "
            "screenshots. No new Apply/Load/Unload or screen recording was "
            "made for this cut. End card is typographic measured timings, "
            "not a reboot claim."
        ),
        "numbers": {
            "apply_backend_ready_s": 8.82,
            "apply_chat_usable_s": 12.93,
            "caption_chat_ready_rounded_s": 13,
        },
        "sources": [
            "docs/release-notes/day21.md: UI Apply Huihui 27/37 back to 24/40 KV16, backend Ready 8.82s, chat usable 12.93s including polling",
            "docs/DAY21.md: same Apply measurement",
            "Live screenshots: day21-balance-live.png, day21-apply-ready.png, day21-apply-reloading.png, day21-apply-done.png, day21-tb-verified.png",
        ],
        "asset_sha256": sources,
        "precision": (
            "Caption 'about 13 seconds' is the rounded chat-usable time. "
            "Exact 12.93 s and backend Ready 8.82 s are on the final card. "
            "The on-screen reload banner's 'about 10 seconds' is the product "
            "estimate, left unaltered in the screenshot."
        ),
    }
    (ROOT / "manifest.json").write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False) + "\n"
    )
    cap_txt = "\n".join(f"{a:.1f}–{b:.1f}s  {c}" for a, b, c in CAPS)
    cap_txt += f"\n16.5–20.0s  [plain final card] {NERD}\n"
    (ROOT / "captions.txt").write_text(cap_txt)

    reviews = Path(args.output).with_suffix("").with_name(
        Path(args.output).stem + "-review"
    )
    reviews.mkdir(exist_ok=True)
    keep = {0, 36, 72, 96, 156, 180, 220, 252, 280, 324, 360, 396, 420, 456, 479}

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
        im = frame(n)
        if n in keep:
            im.save(reviews / f"frame-{n:03d}.png")
        ff.stdin.write(im.tobytes())
    ff.stdin.close()
    assert ff.wait() == 0
    print(args.output, f"{DURATION:.3f} seconds")
    print((ROOT / "captions.txt").read_text())


if __name__ == "__main__":
    main()
