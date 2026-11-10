#!/usr/bin/env python3
"""Replace only v4's 20–28s reboot beat with the verified second-reboot result.

All other footage/captions and the two 2-second end cards are sourced directly
from v4. Recovery status is a readable summary of native logs, not fabricated
UI footage. The unreachable image is a real reboot-watch2 capture (f000044).
The full-page captures immediately after page reload still say STARTING, so
those are deliberately NOT passed off as proof of model readiness.
Measured recovery: 64.735 s from first failed EXO1 probe to fully loaded;
full :18090 reply TTFT .815 s, 6.50 tok/s. Only "about a minute" is on screen.
"""
import argparse, importlib.util, os, subprocess, tempfile
from pathlib import Path
from PIL import Image, ImageFont, ImageDraw
HERE=Path(__file__).resolve().parent
spec=importlib.util.spec_from_file_location("v4",HERE/"make_day19_v4.py")
v4=importlib.util.module_from_spec(spec);spec.loader.exec_module(v4)
ORIGINAL_FONT=v4.font
VARIABLE=Path("/usr/share/fonts/truetype/sand-box/google/Noto Sans/NotoSans-VariableFont_wdth,wght.ttf")
def font(path,size):
    if Path(path).exists():return ORIGINAL_FONT(path,size)
    f=ImageFont.truetype(str(VARIABLE),size)
    f.set_variation_by_axes([700 if "Bold" in path else 400,100])
    return f
v4.font=font
S=list(v4.S)
S[5]=(S[5][0],S[5][1],"About a minute later, the model is back and answering.",None)
v4.S=S

def reboot_frame(kind,t,dur):
    if kind=="reboot_down":
        if t<1.5:return Image.open(HERE/"day19_v5_unreachable.png").convert("RGB")
        return v4.frame_reboot(kind,t,dur)
    return v4.status_card("The model",[
        ("Automatic restore","done",v4.GREEN),
        ("Same split ready","about a minute later",v4.GREEN),
    ])

def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--input",default="/workspace/caravan-day19-v4.mp4")
    ap.add_argument("--output",default="/workspace/caravan-day19-v5.mp4")
    args=ap.parse_args();v4.check()
    # Check all summary text fits within the panel without label/value overlap.
    d=ImageDraw.Draw(Image.new("RGB",(1280,720)))
    for label,value in [("Automatic restore","done"),("Same split ready","about a minute later")]:
        lw=d.textbbox((0,0),label,font=font(v4.FONT_R,36))[2]
        vw=d.textbbox((0,0),value,font=font(v4.FONT_B,40))[2]
        assert lw+vw+40 <= 1000,(label,value,lw,vw)
    for text in ["Automatic restore","done","Same split ready","about a minute later"]:
        assert "**" not in text and not v4.DATE.search(text) and not v4.BAD.search(text)
    # Review stills include all changed views at full output size.
    preview=Path(args.output).with_suffix("").with_name(Path(args.output).stem+"-review")
    preview.mkdir(exist_ok=True)
    for kind,t,name,cap in [("reboot_down",0,"20-down",S[4][2]),("reboot_down",2,"22-back",S[4][2]),("reboot_load",1,"25-restored",S[5][2])]:
        v4.caption_band(reboot_frame(kind,t,4),cap).save(preview/(name+".png"))
    with tempfile.TemporaryDirectory(prefix="day19-v5-") as tmp:
        beat=Path(tmp)/"reboot.mp4"
        ff=subprocess.Popen(["ffmpeg","-y","-v","error","-f","rawvideo","-pix_fmt","rgb24","-s","1280x720","-r","24","-i","-","-c:v","libx264","-preset","slow","-crf","18","-pix_fmt","yuv420p",str(beat)],stdin=subprocess.PIPE)
        for kind,dur,cap,_ in S[4:6]:
            for i in range(round(dur*24)):
                ff.stdin.write(v4.caption_band(reboot_frame(kind,i/24,dur),cap).tobytes())
        ff.stdin.close();assert ff.wait()==0
        subprocess.run(["ffmpeg","-y","-v","error","-i",args.input,"-i",str(beat),"-filter_complex","[0:v]trim=start=0:end=20,setpts=PTS-STARTPTS[a];[1:v]setpts=PTS-STARTPTS[b];[0:v]trim=start=28:end=32,setpts=PTS-STARTPTS[c];[a][b][c]concat=n=3:v=1:a=0[v]","-map","[v]","-r","24","-c:v","libx264","-preset","slow","-crf","20","-pix_fmt","yuv420p","-movflags","+faststart",args.output],check=True)
    t=0;caps=[]
    for _,dur,cap,_ in S:
        caps.append(f"{t:6.1f}s  {cap}");t+=dur
    body="\n".join(caps)+"\n";(HERE/"day19_captions_v5.txt").write_text(body)
    assert t==32.0
    print(args.output,"duration",t);print(body)
if __name__=="__main__":main()
