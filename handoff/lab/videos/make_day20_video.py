#!/usr/bin/env python3
"""Day20: actual UI crops plus explicitly editorial experiment decisions.
No synthetic UI/streaming, fabricated benchmark clocks or replayed model loads.
Fresh chat recording is trimmed after the real answer. Historical findings are
editorial notes, not depicted as current actions. Stats only in nerd end line.
"""
from pathlib import Path
import argparse,json,hashlib,re,subprocess
from PIL import Image,ImageDraw,ImageFont
HERE=Path(__file__).resolve().parent;ROOT=HERE/'day20';ASSETS=ROOT/'assets'
W,H,FPS=1280,720,24
BG='#0c1015';PANEL='#171d24';FG='#f4efe4';AMBER='#e9ba67';MUTED='#aab2b6';GREEN='#8fd4aa';RED='#ec9b88'
FONT='/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf';BOLD=FONT.replace('.ttf','-Bold.ttf')
SCENES=[
 (2,'chat','Alone vs +Hermes','Short prompt alone.\nFull tool setup\nwith Hermes.','Hermes adds tools. We cut the wait, not the tools.'),
 (3,'chat','The hidden wait','A chat title erased\nthe saved setup.','A tiny chat title was wiping the saved setup.'),
 (3,'chat','Kept','Separate the jobs.\nSave the shared setup.','Keep the setup. Read only what is new.'),
 (3,'chat','Tiny helper · opt-in','Big model: real work.\nTiny model: chat titles.','A tiny helper now handles chat titles.'),
 (2,'chat','Tried → dropped','Early warm-up added\nwork, not a payoff.','Early warm-up added work, not a faster answer.'),
 (3,'lookup','Optional','Copying got faster.\nNormal chat did not.','Guessing ahead helped copying, not everyday chat.'),
 (2,'memory','Tried → dropped','Smaller chat memory\nwas slower here.','Smaller chat memory was slower, so it stayed off.'),
 (3,'thinking','Per-request option','Less deliberation.\nMain Hermes unchanged.','Less thinking sped up short replies, with a tradeoff.'),
 (3,'oom','Recorded result','One Mac ran out of room.\nThe split worked.','One Mac ran out of room. Sharing the model worked.'),
 (3,'nodes','Earlier paired runs','Smaller models were\nfaster on one Mac.','Smaller models were faster without the extra hop.'),
 (3,'reboot','Recorded restart','No manual Load.\nSaved split restored.','About a minute later, it comes back without a click.'),
 (3,'nodes','Kept the useful parts','All main tools stayed.\nWasted work did not.','The tools stayed. The wasted work did not.'),
 (2,'end','Day 20','Caravan + Hermes','Less waiting. Same tools. Built in the open.'),
 (2,'nerds','Measured work, not magic','Full replies still take time.\nFirst tokens may be hidden thinking.','For the nerds: prefill 207.87→1.17s · titles 6.458→.114s · reboot 64.7s'),
]
def font(n,bold=False):return ImageFont.truetype(BOLD if bold else FONT,n)
def width(d,t,f):return d.textbbox((0,0),t,font=f)[2]
def wrap(d,text,f,maxw):
 result=[]
 for p in text.split('\n'):
  line=''
  for word in p.split():
   trial=(line+' '+word).strip()
   if line and width(d,trial,f)>maxw:result.append(line);line=word
   else:line=trial
  result.append(line)
 return result
def textblock(d,text,xy,n,maxw,color=FG,bold=False,leading=1.35):
 f=font(n,bold);lines=wrap(d,text,f,maxw);x,y=xy
 for s in lines:
  assert width(d,s,f)<=maxw,(s,maxw)
  d.text((x,y),s,font=f,fill=color);y+=round(n*leading)
 return y

def prepare(raw):
 """Save authentic source crops; no text is rewritten inside screenshots."""
 ASSETS.mkdir(parents=True,exist_ok=True);manifest=[]
 def crop(src,box,dest):
  original=raw/src;im=Image.open(original).convert('RGB');im.crop(box).save(ASSETS/dest,quality=94)
  manifest.append({'file':dest,'source':src,'source_sha256':hashlib.sha256(original.read_bytes()).hexdigest(),'crop_ltrb':box})
 crop('answer.png',(200,25,1067,126),'brand.jpg')
 for i in range(9):crop(f'chat-{i:03d}.png',(220,277,650,344),f'chat-{i:03d}.jpg')
 crop('answer.png',(220,277,650,344),'answer.jpg')
 crop('answer.png',(219,523,1065,595),'composer.jpg')
 crop('lookup.png',(860,345,1258,410),'lookup.jpg')
 crop('memory.png',(860,345,1258,410),'memory.jpg')
 crop('answer.png',(928,291,1060,326),'thinking.jpg')
 crop('topology-ready.png',(16,68,422,156),'lead.jpg')
 crop('topology-ready.png',(16,370,422,457),'packer.jpg')
 original=HERE/'day19_v5_unreachable.png';Image.open(original).convert('RGB').save(ASSETS/'reboot-unreachable.jpg',quality=94)
 manifest.append({'file':'reboot-unreachable.jpg','source':'day19_v5_unreachable.png; original reboot-watch2 frame f000044','source_sha256':hashlib.sha256(original.read_bytes()).hexdigest()})
 (ROOT/'source-manifest.json').write_text(json.dumps({'capture':'Real Caravan web UI at Omarchy localhost:18190,1280×720. Read-only drawers; one brief chat. No Apply/Load/Unload.','crops':manifest,'historical_source':'docs/DAY20.md and docs/BENCHMARKS.md; editorial summary, not a new before/after live run.'},indent=2)+'\n')
 for f in ['capture_day20.js','capture_details.js']:
  (ROOT/f).write_text((raw/f).read_text())

def paste(im,name,xy,size):
 shot=Image.open(ASSETS/name).convert('RGB');shot=shot.resize(size,Image.Resampling.LANCZOS);im.paste(shot,xy)

def view(scene,t):
 dur,kind,title,body,cap=scene;im=Image.new('RGB',(W,H),BG);d=ImageDraw.Draw(im)
 if kind in ['end','nerds']:
  d.text((60,60),'CARAVAN',font=font(25,True),fill=AMBER)
  textblock(d,title,(60,165),64,1160,FG,True)
  textblock(d,body,(64,300),37,1120,MUTED)
 else:
  # Editorial decision panel is distinct from actual UI crops at right.
  textblock(d,title,(48,50),37,352,AMBER,True)
  textblock(d,body,(48,185),34,345,FG)
  d.rounded_rectangle((428,42,1232,594),radius=20,fill=PANEL,outline='#39434b',width=2)
  paste(im,'brand.jpg',(448,65),(760,89))
  if kind in ['chat','reboot']:
   name=f'chat-{min(8,int(t*4)):03d}.jpg' if scene is SCENES[0] else 'answer.jpg'
   if kind=='reboot' and t<.85:
    paste(im,'reboot-unreachable.jpg',(450,166),(760,428))
   else:
    paste(im,name,(450,245),(760,118));paste(im,'composer.jpg',(450,444),(760,65))
  elif kind in ['lookup','memory']:
   paste(im,kind+'.jpg',(450,255),(760,124));textblock(d,'Actual controls · no settings changed',(450,445),24,760,MUTED)
  elif kind=='thinking':
   paste(im,'thinking.jpg',(586,250),(440,116));textblock(d,'Web request control · not main Hermes policy',(450,445),23,760,MUTED)
  elif kind in ['nodes','oom']:
   paste(im,'lead.jpg',(450,190),(760,165));paste(im,'packer.jpg',(450,380),(760,163))
   if kind=='oom':
    # Exact fragment of preserved historical Metal error, clearly editorial.
    d.rounded_rectangle((450,346,1210,400),radius=8,fill='#3d2224')
    d.text((469,355),'Recorded GPU error: Insufficient Memory',font=font(25,True),fill=RED)
  source='Real Caravan UI · edited for length'
  if kind in ['nodes','oom']:source='Current live nodes · earlier findings at left'
  if kind=='reboot':source='Recorded outcome → current ready UI (not new reboot footage)'
  textblock(d,source,(450,555),20,760,MUTED)
 # Captions are one line; big type, no dates or counts. Nerd line intentionally smaller.
 d.rectangle((0,620,W,H),fill='#080b0f')
 f=font(27 if kind=='nerds' else 34,True);tw=width(d,cap,f)
 assert tw<W-56,(cap,tw)
 d.text(((W-tw)/2,650),cap,font=f,fill=FG)
 return im

def main():
 ap=argparse.ArgumentParser(description=__doc__);ap.add_argument('--prepare',type=Path);ap.add_argument('--output',default='/workspace/caravan-day20.mp4');args=ap.parse_args()
 if args.prepare:prepare(args.prepare)
 total=0;caps=[]
 for s in SCENES:
  c=s[4];assert '\n' not in c and '**' not in c and not re.search(r'20\d\d|tests? passed|\b\d+ tests?\b',c,re.I)
  caps.append({'start_s':total,'end_s':total+s[0],'caption':c,'view':s[1]});total+=s[0]
 assert 25<=total<=40 and SCENES[-1][0]==SCENES[-2][0]==2
 (ROOT/'captions.json').write_text(json.dumps(caps,indent=2,ensure_ascii=False)+'\n')
 (ROOT/'captions.txt').write_text('\n'.join(f"{x['start_s']:05.1f}–{x['end_s']:05.1f}  {x['caption']}" for x in caps)+'\n')
 reviews=Path(args.output).with_suffix('').with_name(Path(args.output).stem+'-review');reviews.mkdir(exist_ok=True)
 ff=subprocess.Popen(['ffmpeg','-y','-v','error','-f','rawvideo','-pix_fmt','rgb24','-s',f'{W}x{H}','-r',str(FPS),'-i','-','-c:v','libx264','-preset','medium','-crf','18','-pix_fmt','yuv420p','-movflags','+faststart',args.output],stdin=subprocess.PIPE)
 count=0
 for si,s in enumerate(SCENES):
  for i in range(s[0]*FPS):
   im=view(s,i/FPS)
   if i==round(.75*FPS):im.save(reviews/f'{si:02d}-{s[1]}.png')
   ff.stdin.write(im.tobytes());count+=1
 ff.stdin.close();assert ff.wait()==0
 print(args.output,'duration',count/FPS,'seconds',count,'frames')
 print((ROOT/'captions.txt').read_text())
if __name__=='__main__':main()
