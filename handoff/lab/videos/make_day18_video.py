#!/usr/bin/env python3
"""Day 18 video: real Caravan web UI footage (live + replayed), single-line bottom captions. No dates on screen."""
import os, subprocess, sys, re, io
from PIL import Image, ImageDraw, ImageFont
W,H,FPS=1280,720,24; BAND=84
N=os.environ.get("CLIPS","/workspace/d18v/n"); OUT=sys.argv[1] if len(sys.argv)>1 else "/workspace/caravan-day18.mp4"
FONT=ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",32)
MONO="/home/box/.local/share/fonts/JetBrainsMono-Bold.ttf"
DAY=os.environ.get("VIDEO_DAY","Day 18")
# (clip, start_s, dur_s, crop(x0,y0,x1,y1) or None, caption)
S=[
 ("r-clean",0.6,3.4,None,"A 21B AI model, split across two Mac minis."),
 ("r-clean",4.0,3.5,(120,100,920,550),"It answers cleanly. First word in half a second."),
 ("r-gib",2.5,4.0,(120,100,920,550),"It was speaking gibberish. Here's why."),
 ("r-gib",6.5,4.0,(120,100,920,550),"One of its word tables never got loaded."),
 ("r-gib",10.5,4.0,(120,100,920,550),"Now Caravan refuses to run with missing pieces."),
 ("r-clean",7.4,3.6,(120,100,920,550),"Fixed: same model, clean replies."),
 ("r-warn",1.0,4.0,(660,40,1280,389),"Odd models now get a plain-language ⚠ heads-up."),
 ("r-warn",5.0,3.6,(660,40,1280,389),"One click on Report this model. You review it first."),
 ("05-picker",0.5,4.0,None,"Downloads: one bar per Mini, with real speed."),
 ("05-picker",4.5,4.0,(0,180,640,540),"Stopped downloads now resume mid-file."),
 ("05-picker",8.5,3.4,(0,180,640,540),"No more starting a 5 GB file over."),
 ("03-topo",0.5,4.0,None,"Topology: every Mini's memory, live."),
 ("03-topo",4.5,4.0,(0,40,640,400),"Caravan now checks free memory before splitting."),
 ("03-topo",8.5,3.4,(0,40,640,400),"A 24/8 split ran out of room. 16 and 16 just works."),
 ("04-settings",0.5,4.0,None,"Optimize now tunes GGUF models too."),
 ("04-settings",4.5,5.0,(640,190,1280,550),"It tries each option and keeps the faster one."),
 ("__llama__",0,4.2,None,"Newer llama.cpp: faster first word, 2% slower writing."),
 ("__llama__",0,3.6,None,"So we kept the current one."),
 ("r-clean",7.4,4.0,(160,200,840,583),"Every reply now logs its first-word time and speed."),
 ("__test__",0,4.2,None,"Brenden's test: 31 replies, about 12 tok/s, no gibberish."),
 ("__test__",0,3.8,None,"487 tests pass. The Day 18 release is out."),
 ("__title__",0,4.0,None,"Next: a Balance control for splits."),
]
DATE=re.compile(r"20\d\d|\b(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]* \d|\b\d{1,2}:\d\d\b|\b(AM|PM|tonight|yesterday|today|morning|evening)\b",re.I)
def check():
    d=ImageDraw.Draw(Image.new("RGB",(1,1)))
    for _,_,_,_,c in S:
        assert "\n" not in c and not DATE.search(c),c
        l,t,r,b=d.textbbox((0,0),c,font=FONT); assert r-l<=W-80,(c,r-l)
def frames(clip,start,dur):
    p=subprocess.run(["ffmpeg","-loglevel","error","-ss",str(start),"-i",f"{N}/{clip}.mp4","-t",str(dur),"-f","rawvideo","-pix_fmt","rgb24","-"],capture_output=True).stdout
    fs=[Image.frombytes("RGB",(W,H),p[i:i+W*H*3]) for i in range(0,len(p)-W*H*3+1,W*H*3)]
    need=int(dur*FPS); 
    while len(fs)<need: fs.append(fs[-1])
    return fs[:need]
def card(title,rows,foot):
    im=Image.new("RGB",(W,H),(14,12,8));d=ImageDraw.Draw(im)
    ft=ImageFont.truetype(MONO,40);fr=ImageFont.truetype(MONO,30);fs=ImageFont.truetype(MONO,20)
    d.text((90,80),title,font=ft,fill=(242,180,90));y=180
    for a,b,c in rows: d.text((90,y),a,font=fr,fill=(225,220,205));d.text((560,y),b,font=fr,fill=c);y+=70
    if foot: d.text((90,H-BAND-60),foot,font=fs,fill=(140,130,110))
    return im
G,R,Y=(120,210,120),(230,110,100),(235,200,110)
def still(kind):
    if kind=="__llama__": return card("llama.cpp: current vs newer (write tok/s)",[
        ("3B, one Mini","50.3 vs 49.0",R),("3B, two Minis","41.8 vs 41.0",R),("30B, one Mini","43.3 vs 43.5",G),("30B, two Minis","35.0 vs 35.6",G),("First word","newer is faster",G)],"3 runs each")
    if kind=="__test__": return card("Brenden's live test, 21B on two Minis",[
        ("Replies","31",G),("Average writing speed","about 12 tok/s",G),("Gibberish","none",G),("Out-of-memory refusals","none",G),("Tests passing","487",G)],DAY+" release")
    im=Image.new("RGB",(W,H),(18,16,12))
    svg=open("/workspace/caravan/proxy/web/assets/brand/caravan-lockup.svg").read().replace("currentColor","#f2b45a") if os.path.exists("/workspace/caravan/proxy/web/assets/brand/caravan-lockup.svg") else None
    try:
        import cairosvg
        logo=Image.open(io.BytesIO(cairosvg.svg2png(bytestring=svg.encode(),output_width=760))).convert("RGBA")
    except Exception:
        logo=Image.open("/workspace/dbg/shots/logo-tagline.png").convert("RGBA")
    im.paste(logo,((W-logo.width)//2,(H-BAND-logo.height)//2-40),logo)
    f=ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",40);d=ImageDraw.Draw(im)
    d.text(((W-d.textlength(DAY,font=f))//2,(H-BAND)//2+50),DAY,font=f,fill=(225,215,195));return im
def main():
    check()
    ff=subprocess.Popen(["ffmpeg","-y","-loglevel","error","-f","rawvideo","-pix_fmt","rgb24","-s",f"{W}x{H}","-r",str(FPS),"-i","-","-c:v","libx264","-preset","slow","-crf","24","-pix_fmt","yuv420p","-movflags","+faststart",OUT],stdin=subprocess.PIPE)
    caps=[];t=0.0
    for clip,st,du,crop,cap in S:
        fs=[still(clip)]*int(du*FPS) if clip.startswith("__") else frames(clip,st,du)
        n=len(fs);caps.append(f"{t:6.1f}s  {cap}");t+=du
        for k,f in enumerate(fs):
            if crop:
                x0,y0,x1,y1=crop;p=k/max(1,n-1);z=0.02*p
                dx=(x1-x0)*z/2;dy=(y1-y0)*z/2
                f=f.crop((int(x0+dx),int(y0+dy),int(x1-dx),int(y1-dy))).resize((W,H),Image.LANCZOS)
            fr=f.copy();ov=Image.new("RGBA",(W,BAND),(10,10,10,225));fr.paste(ov,(0,H-BAND),ov)
            d=ImageDraw.Draw(fr);a=min(1,k/5,(n-k)/5);col=tuple(int(c*a+10*(1-a)) for c in (248,244,234))
            d.text((W/2,H-BAND/2),cap,font=FONT,fill=col,anchor="mm");ff.stdin.write(fr.tobytes())
    ff.stdin.close();ff.wait()
    open(os.environ.get("CAPS","/workspace/d18v/captions.txt"),"w").write("\n".join(caps)+"\n")
if __name__=="__main__": main()
