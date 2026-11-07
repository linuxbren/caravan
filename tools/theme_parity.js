const p=require('puppeteer-core');const fs=require('fs');
const THEMES=['amber','green','meadow','nebula'];
const VIEWS={main:null,settings:'#btnOpenSettings',models:'#btnOpenPicker',topology:'#btnOpenTopo'};
const SIZES={desktop:[1280,900],phone:[390,844]};
const shots=process.argv[2]==='shots';
(async()=>{const b=await p.launch({executablePath:'/usr/bin/google-chrome',args:['--no-sandbox','--disable-gpu']});
let fails=0,total=0;const report=[];
for(const [sz,[w,h]] of Object.entries(SIZES)){for(const [v,btn] of Object.entries(VIEWS)){
 const res={};
 for(const t of THEMES){const pg=await b.newPage();await pg.setViewport({width:w,height:h});
  await pg.goto(process.env.CARAVAN_URL||'http://127.0.0.1:8190/',{waitUntil:'networkidle2'});
  await pg.evaluate(t=>{document.querySelector(`#themeSwitch button[data-theme="${t}"]`).click()},t);
  if(btn){await pg.evaluate(s=>document.querySelector(s).click(),btn);}
  await pg.evaluate(()=>{const s=document.createElement('style');s.textContent='*,*::before,*::after{transition:none!important;animation:none!important}';document.head.appendChild(s)});
  await new Promise(r=>setTimeout(r,600));
  res[t]=await pg.evaluate(()=>[...document.querySelectorAll('button,select,input,textarea,.theme-switch,.pill,h1,h2,.chip,.tag,label')].filter(e=>{const r=e.getBoundingClientRect();return r.width>0&&r.height>0&&getComputedStyle(e).visibility!=='hidden'}).map(e=>{const r=e.getBoundingClientRect();const cs=getComputedStyle(e);return{k:(e.id||e.className||e.tagName)+':'+(e.textContent||'').trim().slice(0,20),x:r.x,y:r.y,w:r.width,h:r.height,fs:cs.fontSize,ff:cs.fontFamily.split(',')[0]}}));
  if(shots) await pg.screenshot({path:`/workspace/tp/s-${sz}-${v}-${t}.png`});
  await pg.close();}
 const A=res.amber;
 for(const t of THEMES.slice(1)){const B=res[t];total++;let bad=[];
  if(A.length!==B.length)bad.push(`count ${A.length} vs ${B.length}`);
  for(let i=0;i<Math.min(A.length,B.length);i++){const a=A[i],c=B[i];
   if(['x','y','w','h'].some(k=>Math.abs(a[k]-c[k])>1)||a.fs!==c.fs)bad.push(`${a.k} amber(${a.x|0},${a.y|0},${a.w|0}x${a.h|0},${a.fs},${a.ff}) ${t}(${c.x|0},${c.y|0},${c.w|0}x${c.h|0},${c.fs},${c.ff})`);}
  if(bad.length)fails++;report.push(`${sz} ${v} ${t}: ${bad.length?'FAIL '+bad.length:'OK'} (${A.length} elements)`);bad.slice(0,6).forEach(x=>report.push('   '+x));}
}}
console.log(report.join('\n'));console.log(`\n${total-fails}/${total} theme×view×size combos match Amber within 1px`);await b.close();})();
