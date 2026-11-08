const p=require('/workspace/dbg/node_modules/puppeteer-core');const sl=ms=>new Promise(r=>setTimeout(r,ms));
(async()=>{const b=await p.launch({executablePath:'/usr/bin/google-chrome',args:['--no-sandbox','--disable-gpu'],defaultViewport:{width:1280,height:720}});
const pg=await b.newPage();await pg.goto('http://127.0.0.1:8779/',{waitUntil:'networkidle2'});await sl(2500);
const r=await pg.screencast({path:'r-warn.webm'});await sl(600);await pg.evaluate(()=>document.querySelector('#btnOpenSettings').click());await sl(1500);
await pg.evaluate(()=>document.querySelector('#modelWarn').scrollIntoView({behavior:'smooth',block:'center'}));await sl(2000);
await pg.evaluate(()=>{const a=document.querySelector('#modelWarn a');a.style.color='#ffd27a'});await sl(3500);await r.stop();
await pg.screenshot({path:'r-warn.png'});console.log(await pg.evaluate(()=>({cls:document.querySelector('#settingsDrawer').className,r:JSON.stringify(document.querySelector('#modelWarn').getBoundingClientRect())})));await b.close();})();
