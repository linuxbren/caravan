# Caravan identity — A3

Current tagline: **Your Macs. One model.**

The mark is three evenly spaced, flat rounded Minis, linked through their centers,
with a small light at each bottom-right corner. No underline and no special lead
node. Keep the lowercase **caravan** wordmark beside it, not inside the Minis.
The number of boxes is a visual identity, not a three-machine limit.

## Files

All masters and exports live in `proxy/web/assets/brand/`:

- `mark.svg`: transparent, `currentColor`, 252×64 viewBox.
- `caravan-lockup.svg`: mark plus lowercase DejaVu Sans Mono Bold wordmark,
  converted to paths (no font download or platform substitution).
- `favicon.svg`: dark mark on an amber rounded square.
- `favicon-16.png`, `favicon-32.png`: dedicated pixel-grid small-size artwork.
- `favicon-180.png`: Apple touch icon; `favicon-512.png`: large icon.
- `app-icon.svg`, `app-icon.png`: 512px dark mark on an amber rounded square.
- `FONT-LICENSE.txt`: DejaVu/Bitstream font license for outlined wordmark.
- `build.py`: rebuild assets using `fonttools` and `cairosvg`, with the system
  `/usr/share/fonts/truetype/dejavu/DejaVuSansMono-Bold.ttf` installed.
  Header embeds the lockup inline; update that copy if changing the master.

The header's inline SVG uses `currentColor` from `--accent`:

| Theme | Accent |
| --- | --- |
| Amber | `#efc923` |
| Green | `#3ecf5a` |
| Meadow | `#2e7d32` |
| Nebula | `#e0893a` |

Standalone SVGs default to the surrounding SVG color (black without a specified
color); embedding an SVG with `<img>` does not inherit the host's CSS color.
Use inline SVG for themed applications. Leave some clear space around the mark,
keep the aspect ratio, and use the pixel-grid PNGs at 16/32px rather than shrinking
the wordmark. Favicons deliberately stay amber for recognition across themes.

## Validation — November 6, 2026, 10:25 PM CT

Headless `/usr/bin/google-chrome` rendered the actual local `index.html` via HTTP,
with each theme selected through `caravan-theme` localStorage. All eight checks
passed at 1280×900 and 390×900 CSS pixels: correct active theme, visible lockup,
and document scroll width equal to viewport width (no horizontal overflow).
These are static local previews, not evidence of a running model or inference.
No model loaded/stopped and no web restart needed; existing `/assets/` route works.

Box evidence:
- `/workspace/dbg/shots/logo-{amber,green,meadow,nebula}-{1280,390}.png`
- `/workspace/dbg/shots/logo-theme-comparison.png` (labeled real header crops)
- `/workspace/dbg/shots/logo-checks.json` (measured geometry/colors)
