const p=require('/workspace/dbg/node_modules/puppeteer-core');const sl=ms=>new Promise(r=>setTimeout(r,ms));
(async()=>{const b=await p.launch({executablePath:'/usr/bin/google-chrome',args:['--no-sandbox','--disable-gpu'],defaultViewport:{width:1280,height:720}});
async function chat(url,name,prompt){const pg=await b.newPage();await pg.goto(url,{waitUntil:'networkidle2'});await sl(2500);
 const r=await pg.screencast({path:`r-${name}.webm`});await sl(500);await pg.click('#input');await pg.type('#input',prompt,{delay:30});await sl(300);await pg.click('#btnSend');await sl(name==='gib'?9000:5000);await r.stop();
 await pg.screenshot({path:`r-${name}.png`});
 console.log(name,await pg.evaluate(()=>({pill:document.querySelector('#statusText')?.innerText,warn:document.querySelector('#modelWarn')?.innerText,hidden:document.querySelector('#modelWarn')?.hidden,timing:[...document.querySelectorAll('.timing')].map(e=>e.innerText)})));
 return pg;}
const pg=await chat('http://127.0.0.1:8779/','clean','Say hello in one sentence.');
await chat('http://127.0.0.1:8780/','gib','Say hello in one sentence.');
const r=await pg.screencast({path:'r-warn.webm'});await pg.evaluate(()=>document.querySelector('#modelWarn')?.scrollIntoView({block:'center'}));await sl(1000);
await pg.evaluate(()=>{const a=[...document.querySelectorAll('#modelWarn a')][0];if(a){a.style.outline='2px solid #f2b45a';a.style.outlineOffset='3px'}});await sl(4000);await r.stop();await pg.screenshot({path:'r-warn.png'});
await b.close();})().catch(e=>{console.error(e);process.exit(1)});
