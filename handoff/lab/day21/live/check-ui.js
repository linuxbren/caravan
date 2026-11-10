const p=require('/home/brenden/day19-video/node_modules/puppeteer-core');
const fs=require('fs'),assert=require('assert/strict');
(async()=>{
 const browser=await p.launch({executablePath:'/usr/bin/chromium',headless:true,defaultViewport:{width:1440,height:1700},args:['--no-sandbox','--disable-gpu']});
 try {
 const page=await browser.newPage(),errors=[],mutations=[];
 page.on('pageerror',e=>errors.push(String(e)));
 await page.setRequestInterception(true);
 page.on('request',r=>{if(['/api/models/load','/api/models/stop','/api/files/fetch'].some(x=>r.url().includes(x))){mutations.push(r.url());r.abort();}else r.continue();});
 await page.goto('http://127.0.0.1:18190/',{waitUntil:'networkidle2',timeout:30000});
 await page.click('#btnOpenTopo');
 await page.waitForFunction(()=>document.querySelectorAll('#balanceMemory .balance-card').length===2 && !document.querySelector('#balanceAdjust').disabled,{timeout:30000});
 assert.equal(await page.$eval('#balanceControls',e=>e.hidden),true);
 await (await page.$('#balancePanel')).screenshot({path:'/home/brenden/day21-balance-live/default.png'});
 await page.click('#balanceAdjust');
 assert.equal(await page.$$eval('#balanceControls input[type=range]',es=>es.length),1);
 await (await page.$('#balancePanel')).screenshot({path:'/home/brenden/day21-balance-live/adjust.png'});
 const before=await page.$eval('#balanceControls input',e=>Number(e.value));
 await page.$eval('#balanceControls input',e=>{e.value=Number(e.value)+1;e.dispatchEvent(new Event('input',{bubbles:true}));});
 assert.equal(await page.$eval('#balanceApply',e=>e.disabled),true);
 await page.waitForFunction(()=>!document.querySelector('#balanceApply').disabled,{timeout:30000});
 const moved=await page.$eval('#balancePreview',e=>e.textContent);
 await page.click('#balanceAuto');
 await page.waitForFunction(()=>document.querySelector('#balanceControls').hidden && !document.querySelector('#balanceAdjust').disabled,{timeout:30000});
 await page.click('#thunderboltInspect');
 await page.waitForFunction(()=>document.querySelector('#thunderboltReadout').textContent.includes('Data-service identity/reachability'),{timeout:30000});
 await (await page.$('#thunderboltPanel')).screenshot({path:'/home/brenden/day21-balance-live/thunderbolt.png'});
 const graphText=await page.$eval('#thunderboltReadout',e=>e.textContent);
 assert.match(graphText,/exo1 → exo2/);assert.match(graphText,/exo2 → exo1/);assert.match(graphText,/candidate only/);
 const result={graph_text:graphText,errors,mutations,initial_boundary:before,moved_preview:moved,default_preview:await page.$eval('#balancePreview',e=>e.textContent),mode:await page.$eval('#balanceMode',e=>e.textContent),model:await page.$eval('#balanceModelName',e=>e.textContent)};
 fs.writeFileSync('/home/brenden/day21-balance-live/ui-proof.json',JSON.stringify(result,null,2));
 assert.equal(errors.length,0);assert.equal(mutations.length,0);console.log(result);
 } finally {await browser.close();}
})().catch(e=>{console.error(e);process.exit(1)});
