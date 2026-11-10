#!/usr/bin/env python3
"""Fourteen-second, single-idea Day20 cut using honestly labeled measured counters.

No browser/UI footage is represented here. Old before-fix state cannot be
inferred from an unrelated fresh Hello clip: both counters illustrate published
setup measurements, not a live request. Before is accelerated; after advances
at real elapsed speed until1.17s. No worker/cache/service changes are needed.
"""
from pathlib import Path
import argparse,json,re,subprocess
from PIL import Image,ImageDraw,ImageFont
HERE=Path(__file__).resolve().parent
OUTDIR=HERE/'day20-v2'
W,H,FPS=1280,720,24
BG='#0b1016';FG='#f5f0e6';MUTED='#bac1c7';BEFORE='#efb970';AFTER='#9cddb8'
FONT='/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf';BOLD=FONT.replace('.ttf','-Bold.ttf')
CAPS=[(0,3,'Skip minutes of repeated setup before a reply.'),
      (3,7,'Before: rereading the setup took over three minutes.'),
      (7,10,'After: the saved setup takes about a second.')]
FINAL='For the nerds: setup reread 207.87 s to 1.17 s · chat titles 6.458 s to 0.114 s'
PROVENANCE='Animated counters from recorded measurements'

def font(n,bold=False):return ImageFont.truetype(BOLD if bold else FONT,n)
def center(d,text,y,size,color=FG,bold=False):
 f=font(size,bold);box=d.textbbox((0,0),text,font=f);width=box[2]-box[0]
 assert width<=W-80,(text,width)
 assert y+box[3]<H-25,(text,y,box)
 d.text(((W-width)/2,y),text,font=f,fill=color)

def frame(n):
 t=n/FPS;im=Image.new('RGB',(W,H),BG);d=ImageDraw.Draw(im)
 if t<3:
  center(d,"Your AI assistant's setup",95,40,MUTED)
  center(d,'3 min → 1 s',225,124,FG,True)
  center(d,'Rounded setup times, not the full reply',415,31,MUTED)
 elif t<7:
  center(d,'Before',85,50,BEFORE,True)
  # Explicit animation of measured duration. Not a fabricated inference trace.
  elapsed=207.87*min(1,(t-3)/3.4)
  center(d,f'{elapsed:.2f} s',225,116,BEFORE,True)
  center(d,'Counter sped up · not a live recording',420,31,MUTED)
 else:
  if t<10:
   elapsed=min(1.17,t-7)
   center(d,'After',85,50,AFTER,True)
   center(d,f'{elapsed:.2f} s',225,116,AFTER,True)
   center(d,'Saved setup reused' if elapsed>=1.17 else 'Reading the saved setup',420,34,MUTED)
  else:
   # Plain final card, all requested words preserved, wrapped only for readability.
   lines=['For the nerds:','setup reread 207.87 s to 1.17 s ·','chat titles 6.458 s to 0.114 s']
   assert ' '.join(lines)==FINAL
   for line,y,size in zip(lines,[195,290,370],[43,46,46]):center(d,line,y,size,FG)
   return im
 center(d,PROVENANCE,545,26,MUTED)
 cap=next(c for start,end,c in CAPS if start<=t<end)
 d.rectangle((0,620,W,H),fill='#06090d')
 center(d,cap,650,34,FG,True)
 return im

def main():
 ap=argparse.ArgumentParser(description=__doc__);ap.add_argument('--output',default='/workspace/caravan-day20-v2.mp4');args=ap.parse_args()
 OUTDIR.mkdir(exist_ok=True)
 texts=[c for _,_,c in CAPS]+[FINAL,PROVENANCE,"Your AI assistant's setup",'3 min → 1 s']
 for s in texts:
  assert not re.search(r'\b(?:Hermes|prefill|Huihui|abliterated|Claude|AMBER|GREEN|READY|NEBULA|GPU)\b|20\d\d|\*\*|\d+\s+tests?\b|tests? passed',s,re.I),s
 for a,b,c in CAPS:assert b-a>=3 and '\n' not in c
 assert 14-10>=3
 manifest={'duration_s':14,'fps':FPS,'dimensions':[W,H],'captions':[{'start_s':a,'end_s':b,'text':c} for a,b,c in CAPS],'final_card':{'start_s':10,'end_s':14,'text':FINAL},'footage':'No live/UI footage. Explicitly labeled animation of recorded measurements; before counter sped up, after counter real elapsed speed to1.17s.','numbers':{'setup_before_s':207.87,'setup_after_s':1.17,'title_before_s':6.458,'title_after_s':.114},'sources':['docs/DAY20.md: original207.87s prefill and real-use1.17s setup','docs/DAY20.md: PhaseB title median6.458→.114s','docs/BENCHMARKS.md: same recorded measurements'],'precision':'Opening3min→1s is reviewer-requested rounded shorthand. These are setup times, not total reply/first visible word guarantees.'}
 (OUTDIR/'manifest.json').write_text(json.dumps(manifest,indent=2,ensure_ascii=False)+'\n')
 (OUTDIR/'captions.txt').write_text('\n'.join(f'{a:.1f}–{b:.1f}s  {c}' for a,b,c in CAPS)+'\n10.0–14.0s  [plain final card] '+FINAL+'\n')
 reviews=Path(args.output).with_suffix('').with_name(Path(args.output).stem+'-review');reviews.mkdir(exist_ok=True)
 ff=subprocess.Popen(['ffmpeg','-y','-v','error','-f','rawvideo','-pix_fmt','rgb24','-s','1280x720','-r',str(FPS),'-i','-','-c:v','libx264','-preset','medium','-crf','18','-pix_fmt','yuv420p','-movflags','+faststart',args.output],stdin=subprocess.PIPE)
 for n in range(14*FPS):
  im=frame(n)
  if n in [0,120,166,180,208,264]:im.save(reviews/f'frame-{n:03d}.png')
  ff.stdin.write(im.tobytes())
 ff.stdin.close();assert ff.wait()==0
 print(args.output,'14.000 seconds');print((OUTDIR/'captions.txt').read_text())
if __name__=='__main__':main()
