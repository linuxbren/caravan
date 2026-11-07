"""Rebuild brand SVGs/PNGs; requires fonttools, cairosvg and DejaVu Sans Mono Bold."""
from pathlib import Path
from fontTools.ttLib import TTFont
from fontTools.pens.svgPathPen import SVGPathPen
import cairosvg
out=Path(__file__).resolve().parent
shape='<g fill="none" stroke="currentColor" stroke-width="9" stroke-linecap="round" stroke-linejoin="round"><rect x="8" y="12" width="72" height="40" rx="10"/><rect x="90" y="12" width="72" height="40" rx="10"/><rect x="172" y="12" width="72" height="40" rx="10"/><path d="M80 32h10m72 0h10"/></g><g fill="currentColor"><circle cx="64" cy="40" r="4"/><circle cx="146" cy="40" r="4"/><circle cx="228" cy="40" r="4"/></g>'
def svg(content,box,w,h): return f'<svg xmlns="http://www.w3.org/2000/svg" width="{w}" height="{h}" viewBox="{box}">{content}</svg>\n'
mark=svg(shape,'0 0 252 64',252,64)
(out/'mark.svg').write_text(mark)
font=TTFont('/usr/share/fonts/truetype/dejavu/DejaVuSansMono-Bold.ttf'); glyphs=font.getGlyphSet(); cmap=font.getBestCmap(); x=0; paths=[]
for c in 'caravan':
    name=cmap[ord(c)]; pen=SVGPathPen(glyphs); glyphs[name].draw(pen)
    paths.append(f'<path transform="translate({x} 0)" d="{pen.getCommands()}"/>'); x+=font['hmtx'][name][0]
word='<g fill="currentColor" transform="translate(276 50) scale(.026 - .026)">'+''.join(paths)+'</g>'
# Explicit negative scale token, accepted by SVG across renderers.
word=word.replace('.026 - .026','.026 -.026')
lock=svg(shape+word,'0 0 508 64',508,64)
(out/'caravan-lockup.svg').write_text(lock)
icon=svg('<rect width="512" height="512" rx="112" fill="#efc923"/><g color="#141210" transform="translate(42 202) scale(1.7)">'+shape+'</g>','0 0 512 512',512,512)
(out/'app-icon.svg').write_text(icon)
(out/'favicon.svg').write_text(icon)
for n in (180,512): cairosvg.svg2png(bytestring=icon.encode(),write_to=str(out/f'favicon-{n}.png'),output_width=n,output_height=n)
cairosvg.svg2png(bytestring=icon.encode(),write_to=str(out/'app-icon.png'),output_width=512,output_height=512)
# Dedicated pixel-grid small-size drawings: retain the three flat Minis and lights.
for n in (16,32):
    s=n/16
    small='<rect width="16" height="16" rx="3" fill="#efc923"/><g fill="none" stroke="#141210" stroke-linejoin="round"><rect x="1.5" y="6.5" width="3" height="3" rx="1"/><rect x="6.5" y="6.5" width="3" height="3" rx="1"/><rect x="11.5" y="6.5" width="3" height="3" rx="1"/><path d="M4.5 7.5h2m3 0h2"/></g><g fill="#141210"><path d="M3 8h1v1H3zM8 8h1v1H8zM13 8h1v1h-1z"/></g>'
    cairosvg.svg2png(bytestring=svg(small,'0 0 16 16',n,n).encode(),write_to=str(out/f'favicon-{n}.png'),output_width=n,output_height=n)
