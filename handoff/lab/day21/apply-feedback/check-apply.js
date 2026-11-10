const p=require('/home/brenden/day19-video/node_modules/puppeteer-core');
const fs=require('fs'),assert=require('assert/strict');
const root='http://127.0.0.1:18190', out='/home/brenden/day21-apply-proof';
const mid='huihui-qwen3-5-27b-claude-4-6-opus-abliterated-4bit';
const snap=async()=>{const r=await fetch(root+'/api/status');assert(r.ok);return r.json()};
const small=s=>({status:s.worker.status,pid:s.worker.lead_pid,model:s.worker.model_id,counts:s.worker.balance?.counts,node_ids:s.worker.balance?.node_ids,kv_bits:s.active?.kv_bits,healthy:s.lead_healthy,settings:s.worker.settings});
(async()=>{
 const before=await snap();assert.equal(before.worker.status,'ready');assert.equal(before.worker.model_id,mid);assert.equal(before.active.kv_bits,16);assert.equal(before.worker.lead_pid,35708,'web restart must preserve the original live worker');
 assert.notDeepEqual(before.worker.balance.counts,[24,40],'preflight target already running: do not silently choose another live split');
 const browser=await p.launch({executablePath:'/usr/bin/chromium',headless:true,defaultViewport:{width:1440,height:1700},args:['--no-sandbox','--disable-gpu']});
 const proof={before:small(before),errors:[],loads:[],blocked:[],statuses:[],click_at:null};let page,clicked=false;
 try {
  page=await browser.newPage();page.on('pageerror',e=>proof.errors.push(String(e)));
  page.on('response',async r=>{if(r.url().endsWith('/api/models/load')){proof.load_responses=proof.load_responses||[];proof.load_responses.push({status:r.status(),body:await r.json()});}});
  await page.exposeFunction('recordWorker',s=>proof.statuses.push({...small(s),at:new Date().toISOString()}));
  await page.evaluateOnNewDocument(()=>window.addEventListener('caravan-worker-status',e=>window.recordWorker(e.detail)));
  await page.setRequestInterception(true);
  page.on('request',r=>{
   if(r.method()==='POST' && r.url().endsWith('/api/models/load')){
    const q=JSON.parse(r.postData()||'{}');
    if(q.model_id!==mid || JSON.stringify(q.counts)!=='[24,40]' || JSON.stringify(q.node_ids)!=='["exo2","exo1"]' || q.settings?.kv_bits!=='16' || proof.loads.length){proof.blocked.push({url:r.url(),reason:'unexpected reload'});return r.abort();}
    proof.loads.push(q);return r.continue();
   }
   if(r.method()!=='GET' && ['/api/chat','/api/models/stop','/api/files/fetch'].some(x=>r.url().includes(x))){proof.blocked.push({url:r.url(),reason:'unexpected mutation'});return r.abort();}
   r.continue();
  });
  await page.goto(root+'/',{waitUntil:'networkidle2',timeout:30000});await page.click('#btnOpenTopo');
  await page.waitForFunction(()=>document.querySelectorAll('#balanceMemory .balance-card').length===2 && !document.querySelector('#balanceAdjust').disabled,{timeout:30000});
  await page.click('#balanceAdjust');
  await page.$eval('#balanceControls input[type=range]',e=>{e.value='24';e.dispatchEvent(new Event('input',{bubbles:true}));});
  await page.waitForFunction(()=>!document.querySelector('#balanceApply').disabled && document.querySelector('#balancePreview').textContent.includes('24'),{timeout:30000});
  await page.waitForFunction(()=>getComputedStyle(document.querySelector('#balanceApply')).backgroundColor==='rgb(0, 0, 0)',{timeout:5000});
  proof.ready=await page.$eval('#balanceApply',e=>({disabled:e.disabled,background:getComputedStyle(e).backgroundColor,color:getComputedStyle(e).color}));assert.equal(proof.ready.background,'rgb(0, 0, 0)');assert.equal(proof.ready.disabled,false);
  proof.preview=await page.$eval('#balancePreview',e=>e.textContent);
  await (await page.$('#balancePanel')).screenshot({path:out+'/ready.png'});
  proof.click_at=new Date().toISOString();const start=Date.now();clicked=true;await page.click('#balanceApply');
  await page.waitForFunction(()=>window.caravanBalanceReloading && document.querySelector('#balanceReloadTitle').textContent.includes('Reloading model'),{timeout:5000});
  await page.waitForFunction(()=>getComputedStyle(document.querySelector('#balanceApply')).backgroundColor==='rgb(51, 51, 51)',{timeout:5000});
  proof.reloading=await page.evaluate(()=>({banner:document.querySelector('#balanceReloadTitle').textContent,chatBanner:document.querySelector('#balanceChatNotice').textContent,applyDisabled:document.querySelector('#balanceApply').disabled,applyBackground:getComputedStyle(document.querySelector('#balanceApply')).backgroundColor,inputDisabled:document.querySelector('#input').disabled,sendDisabled:document.querySelector('#btnSend').disabled,fieldsetDisabled:document.querySelector('#balanceControlLock').disabled,steps:document.querySelector('#balanceReloadSteps').textContent}));
  assert(proof.reloading.applyDisabled && proof.reloading.inputDisabled && proof.reloading.sendDisabled && proof.reloading.fieldsetDisabled);assert.equal(proof.reloading.applyBackground,'rgb(51, 51, 51)');
  await page.$eval('#input',e=>{e.value='This must not send during reload';e.dispatchEvent(new KeyboardEvent('keydown',{key:'Enter',bubbles:true,cancelable:true}));});
  await (await page.$('#balancePanel')).screenshot({path:out+'/reloading.png'});
  await page.waitForFunction(()=>(document.querySelector('#balanceReloadTitle').textContent==='Ready, new split applied.' && !document.querySelector('#input').disabled) || document.querySelector('#balanceReload').dataset.state==='error',{timeout:90000});
  assert.equal(await page.$eval('#balanceReloadTitle',e=>e.textContent),'Ready, new split applied.');
  proof.ready_ui_s=(Date.now()-start)/1000;
  await page.$eval('#input',e=>{e.value='';});
  proof.done=await page.evaluate(()=>({banner:document.querySelector('#balanceReloadTitle').textContent,applyDisabled:document.querySelector('#balanceApply').disabled,applyBackground:getComputedStyle(document.querySelector('#balanceApply')).backgroundColor,inputDisabled:document.querySelector('#input').disabled,sendDisabled:document.querySelector('#btnSend').disabled,fieldsetDisabled:document.querySelector('#balanceControlLock').disabled,steps:document.querySelector('#balanceReloadSteps').textContent}));
  assert(proof.done.applyDisabled);assert(!proof.done.inputDisabled && !proof.done.sendDisabled && !proof.done.fieldsetDisabled);
  await (await page.$('#balancePanel')).screenshot({path:out+'/done.png'});
  const after=await snap();proof.after=small(after);assert.equal(after.worker.status,'ready');assert(after.lead_healthy);assert.equal(after.worker.model_id,mid);assert.deepEqual(after.worker.balance.counts,[24,40]);assert.equal(after.active.kv_bits,16);assert.notEqual(after.worker.lead_pid,before.worker.lead_pid);assert.equal(proof.loads.length,1);assert.equal(proof.blocked.length,0);assert.equal(proof.errors.length,0);
  proof.ok=true;console.log(JSON.stringify(proof,null,2));
 } catch(e) {proof.error=String(e);console.error(e);process.exitCode=1;
  // No experimental alternative target: a started test may only restore the requested24/40 KV16.
  if(clicked){const s=await snap();if(s.worker.status==='ready' && (s.worker.model_id!==mid || JSON.stringify(s.worker.balance?.counts)!=='[24,40]' || s.active?.kv_bits!==16)){const r=await fetch(root+'/api/models/load',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({model_id:mid,node_ids:['exo2','exo1'],counts:[24,40],balance:true,settings:{...before.worker.settings,kv_bits:'16',self_tune:'off',guess_ahead:'off',prompt_lookup:'off',shared_start:'off',pipeline_chats:'1',fuse_kernels:'auto',keepalive:'auto'}})});proof.restore_request_status=r.status;}}
 } finally {fs.writeFileSync(out+'/apply-proof.json',JSON.stringify(proof,null,2));await browser.close();}
})().catch(e=>{console.error(e);process.exit(1)});
