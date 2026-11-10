const p=require('/home/brenden/day19-video/node_modules/puppeteer-core');
const fs=require('fs'),assert=require('assert/strict');
const root='http://127.0.0.1:18190',out='/home/brenden/day21-tb-proof';
const status=async()=>{const r=await fetch(root+'/api/status');assert(r.ok);return r.json()};
const small=s=>({pid:s.worker.lead_pid,status:s.worker.status,model:s.worker.model_id,counts:s.worker.balance?.counts,order:s.worker.balance?.node_ids,kv_bits:s.active?.kv_bits,healthy:s.lead_healthy,peer:s.split?.peer});
(async()=>{
 const before=await status();assert.equal(before.worker.lead_pid,39479);assert.deepEqual(before.worker.balance.counts,[24,40]);assert.equal(before.active.kv_bits,16);assert(before.lead_healthy);
 const browser=await p.launch({executablePath:'/usr/bin/chromium',headless:true,defaultViewport:{width:1440,height:1900},args:['--no-sandbox','--disable-gpu']});
 const proof={before:small(before),errors:[],mutations:[],requests:[]};let page;
 try{
  page=await browser.newPage();page.on('pageerror',e=>proof.errors.push(String(e)));await page.setRequestInterception(true);
  page.on('request',r=>{if(['/api/models/load','/api/models/stop','/api/files/fetch','/api/chat'].some(x=>r.url().includes(x))){proof.mutations.push(r.url());return r.abort();}if(r.url().includes('/api/thunderbolt'))proof.requests.push({url:r.url(),method:r.method(),body:r.postData()});r.continue();});
  await page.goto(root+'/',{waitUntil:'networkidle2',timeout:30000});await page.click('#btnOpenTopo');await page.waitForFunction(()=>document.querySelectorAll('#balanceMemory .balance-card').length===2 && document.querySelector('#topoDrawer').classList.contains('open'),{timeout:30000});await page.waitForSelector('#thunderboltValidate',{visible:true});
  assert.equal(await page.$eval('#thunderboltPreview',e=>e.disabled),true);
  const response=page.waitForResponse(r=>r.url().endsWith('/api/thunderbolt/validate')&&r.request().method()==='POST',{timeout:60000});
  response.catch(()=>{});
  const start=Date.now();await page.click('#thunderboltValidate');const r=await response;const data=await r.json();proof.validation_wall_s=(Date.now()-start)/1000;proof.validation_http=r.status();
  fs.writeFileSync(out+'/api-readout.json',JSON.stringify(data,null,2));assert.equal(r.status(),200);
  await page.waitForFunction(()=>!document.querySelector('#thunderboltValidate').disabled,{timeout:5000});
  proof.edge_results=data.graph.edges.map(e=>({source:e.source,target:e.target,status:e.status,address:e.address,source_address:e.source_address,source_interface:e.source_interface,target_interface:e.target_interface,latency_ms:e.latency_ms,tcp_connect_ms:e.tcp_connect_ms,transport_bound:e.transport_bound,bound_ifindex:e.bound_ifindex,reason:e.reason}));
  const required=data.graph.edges.find(e=>e.source==='exo1'&&e.target==='exo2');assert(required);assert.equal(required.status,'verified',JSON.stringify(proof.edge_results));assert.equal(required.transport_bound,true);assert(required.bound_ifindex>0);assert.equal(required.source_interface,'en2');assert.equal(required.target_interface,'en2');
  assert.equal(await page.$eval('#thunderboltPreview',e=>e.disabled),true);
  await page.click('#thunderboltOptIn');await page.waitForFunction(()=>!document.querySelector('#thunderboltPreview').disabled,{timeout:3000});
  const planned=page.waitForResponse(r=>r.url().endsWith('/api/thunderbolt/plan'),{timeout:10000});await page.click('#thunderboltPreview');const pr=await planned;const plan=await pr.json();proof.plan_http=pr.status();fs.writeFileSync(out+'/plan-preview.json',JSON.stringify(plan,null,2));assert.equal(pr.status(),200,JSON.stringify(plan));assert.equal(plan.preview_only,true);assert.equal(plan.apply_supported,false);assert.equal(plan.matches_current_config,true);
  assert.deepEqual(plan.order,before.worker.balance.node_ids);assert.equal(plan.nodes.at(-1).peer,before.split.peer);proof.matches_live_endpoint=true;
  await page.waitForFunction(()=>document.querySelector('#thunderboltPlan').textContent.includes('Preview only · nothing applied'),{timeout:5000});
  proof.ui_readout=await page.$eval('#thunderboltReadout',e=>e.textContent);proof.ui_plan=await page.$eval('#thunderboltPlan',e=>e.textContent);
  await (await page.$('#thunderboltPanel')).screenshot({path:out+'/verified.png'});
  const after=await status();proof.after=small(after);assert.equal(after.worker.lead_pid,39479);assert.deepEqual(after.worker.balance.counts,[24,40]);assert.equal(after.active.kv_bits,16);assert(after.lead_healthy);assert.equal(after.worker.status,'ready');assert.equal(proof.errors.length,0);assert.equal(proof.mutations.length,0);proof.ok=true;console.log(JSON.stringify(proof,null,2));
 }catch(e){proof.error=String(e);console.error(e);if(page)await page.screenshot({path:out+'/debug.png',fullPage:true});process.exitCode=1;}
 finally{fs.writeFileSync(out+'/ui-proof.json',JSON.stringify(proof,null,2));await browser.close();}
})().catch(e=>{console.error(e);process.exit(1)});
