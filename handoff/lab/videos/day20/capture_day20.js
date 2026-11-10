const p=require('/home/brenden/day19-video/node_modules/puppeteer-core');
const fs=require('fs'), path=require('path');
const out='/home/brenden/day20-video/raw';const sl=ms=>new Promise(r=>setTimeout(r,ms));
(async()=>{
 const b=await p.launch({executablePath:'/usr/bin/chromium',headless:true,defaultViewport:{width:1280,height:720},args:['--no-sandbox','--disable-gpu','--window-size=1280,720']});
 const page=await b.newPage();
 await page.goto('http://127.0.0.1:18190/',{waitUntil:'networkidle2',timeout:30000});await sl(1500);
 fs.writeFileSync(out+'/labels.json',JSON.stringify(await page.evaluate(()=>[...document.querySelectorAll('button')].map(x=>({id:x.id,text:x.innerText}))),null,2));
 await page.screenshot({path:out+'/home.png'});
 await page.type('#input','Say hello in one short sentence.',{delay:15});
 await page.screenshot({path:out+'/typed.png'});
 const t=Date.now();await page.keyboard.press('Enter');
 const capture=[];
 for(let i=0;i<56;i++){const start=Date.now();const name='chat-'+String(i).padStart(3,'0')+'.png';await page.screenshot({path:path.join(out,name)});capture.push({name,elapsed_s:(Date.now()-t)/1000});await sl(Math.max(0,250-(Date.now()-start)));}
 await page.screenshot({path:out+'/answer.png'});
 await page.click('#btnOpenSettings');await sl(600);await page.screenshot({path:out+'/settings.png'});
 fs.writeFileSync(out+'/settings-text.txt',await page.evaluate(()=>document.querySelector('#settingsDrawer').innerText));
 await page.click('#btnCloseSettings');
 // Topology/balance only opens a drawer; never click load/apply/unload.
 const topo=await page.$('#btnOpenTopo');if(topo){await topo.click();await sl(500);await page.screenshot({path:out+'/topology.png'});}
 fs.writeFileSync(out+'/capture.json',JSON.stringify({viewport:[1280,720],prompt:'Say hello in one short sentence.',capture,body:await page.evaluate(()=>document.body.innerText)},null,2));
 await b.close();console.log('captured',capture.length,'frames; no model/settings changes');
})().catch(e=>{console.error(e);process.exit(1)});
