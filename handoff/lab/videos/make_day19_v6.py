#!/usr/bin/env python3
"""Day 19 v6: trim existing v5 footage only; correct YOU label and recovery value.

Frame-exact edit at 24 fps. Complete answer finishes ~6.5 s; retain through
7.5 s. Each static status card lasts 52 frames (~2.17 s); two end cards remain
48 frames each. No new footage or reconstructed streaming timings.
"""
import argparse,importlib.util,subprocess
from pathlib import Path
from PIL import Image,ImageDraw
HERE=Path(__file__).resolve().parent
spec=importlib.util.spec_from_file_location("v5",HERE/"make_day19_v5.py")
v5=importlib.util.module_from_spec(spec);spec.loader.exec_module(v5)
v4=v5.v4
FPS=24;W=1280;H=720
# Source v5 [inclusive first frame, exclusive end frame].
CUTS=[(0,180),(288,340),(384,436),(480,576),(576,628),(672,720),(720,768)]
CAPS=[(0,"Ask a simple question. Watch it answer live."),
      (53,"The words show up as they're written."),
      (180,"If the main path drops, another way in is ready."),
      (232,"It switched on its own. Everything stayed reachable."),
      (284,"Pull the plug, the computers come back on their own."),
      (380,"About a minute later, the model is back and answering."),
      (432,"Two Macs. One model. Built in the open."),
      (480,"For the nerds: Huihui 24/40 on EXO2 then EXO1.")]

def correct_text(im,source_frame):
    d=ImageDraw.Draw(im)
    if source_frame<24:
        # Original ASK label at (70,80); same YOU position/color as sent bubble.
        d.rectangle((65,75,170,115),fill=v4.BG)
        d.text((70,36),"YOU",font=v5.font(v4.FONT_B,22),fill=v4.AMBER)
    if 576<=source_frame<628:
        # Change only the right-hand recovery value; retain original left label.
        d.rectangle((630,280,1150,342),fill=v4.PANEL)
        f=v5.font(v4.FONT_B,40);value="64.7 s"
        width=d.textbbox((0,0),value,font=f)[2]
        d.text((W-140-width,284),value,font=f,fill=v4.GREEN)
    return im

def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--input",default="/workspace/caravan-day19-v5.mp4")
    ap.add_argument("--output",default="/workspace/caravan-day19-v6.mp4")
    args=ap.parse_args()
    selected={i for a,b in CUTS for i in range(a,b)}
    assert len(selected)==528
    v4.S=[("unused",0,c,None) for _,c in CAPS];v4.check()
    preview=Path(args.output).with_suffix("").with_name(Path(args.output).stem+"-review");preview.mkdir(exist_ok=True)
    dec=subprocess.Popen(["ffmpeg","-v","error","-i",args.input,"-f","rawvideo","-pix_fmt","rgb24","-"],stdout=subprocess.PIPE)
    enc=subprocess.Popen(["ffmpeg","-y","-v","error","-f","rawvideo","-pix_fmt","rgb24","-s","1280x720","-r","24","-i","-","-c:v","libx264","-preset","slow","-crf","20","-pix_fmt","yuv420p","-movflags","+faststart",args.output],stdin=subprocess.PIPE)
    frame_bytes=W*H*3;count=0
    for i in range(768):
        raw=dec.stdout.read(frame_bytes)
        assert len(raw)==frame_bytes,(i,len(raw))
        if i not in selected:continue
        im=correct_text(Image.frombytes("RGB",(W,H),raw),i)
        if count in [12,30,168,200,400,450,500]:im.save(preview/(f"frame-{count:03d}.png"))
        enc.stdin.write(im.tobytes());count+=1
    dec.stdout.close();enc.stdin.close()
    assert dec.wait()==0 and enc.wait()==0 and count==528
    text="\n".join(f"{n/FPS:6.3f}s  {cap}" for n,cap in CAPS)+"\n"
    (HERE/"day19_captions_v6.txt").write_text(text)
    print(args.output,"duration",count/FPS,"frames",count);print(text)
if __name__=="__main__":main()
