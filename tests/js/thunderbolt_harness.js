const fs=require('fs'),vm=require('vm'),assert=require('assert/strict');
class El {
 constructor(){this.children=[];this.value='';this.disabled=false;this.checked=false;this.className='';}
 set textContent(s){this.value=s;this.children=[];}get textContent(){return this.value+this.children.map(e=>e.textContent).join('');}
 append(...es){this.children.push(...es);}replaceChildren(...es){this.value='';this.children=es;}
 querySelectorAll(selector){const classes=selector.split('.').filter(Boolean);return this.children.flatMap(e=>[...(classes.every(c=>e.className.split(' ').includes(c))?[e]:[]),...e.querySelectorAll(selector)]);}
}
(async()=>{
 const name=process.argv[2],elements=Object.fromEntries(['Inspect','Validate','Readout','OptIn','Preview','Plan'].map(n=>['thunderbolt'+n,new El()])),requests=[],timers=[];
 const data={nodes:[{label:'Mini <not HTML>',interfaces:[{interface:'en2',addresses:['169.254.1.2'],kind:'thunderbolt'}]}],graph:{edges:[{source:'a',target:'b',source_interface:'en2',target_interface:'en2',source_address:'169.254.1.1',address:'169.254.1.2',status:'unverified',reason:'Not validated'}],warning:'Not model throughput'}};
 const validated=()=>({...data,validation_id:'token',validated_at:Date.now()/1000,validation_ttl_s:30,graph:{...data.graph,edges:[{...data.graph.edges[0],status:name==='failed'?'failed':'verified',reason:'Bound link',latency_ms:12,tcp_connect_ms:0.2}]}});
 vm.runInNewContext(fs.readFileSync(require.resolve('../../proxy/web/thunderbolt.js'),'utf8'),{document:{getElementById:id=>elements[id],createElement:()=>new El()},Date,setTimeout:f=>{timers.push(f);return timers.length;},clearTimeout:()=>{},fetch:async(...args)=>{requests.push(args);const url=args[0];assert(['/api/thunderbolt','/api/thunderbolt/validate','/api/thunderbolt/plan'].includes(url));if(name==='preview_expired'&&url.endsWith('/plan'))timers.at(-1)();const error=name==='error'||(name==='preview_error'&&url.endsWith('/plan'));return {ok:!error,json:async()=>error?{error:'offline'}:url.endsWith('/validate')?validated():url.endsWith('/plan')?{preview_only:true,apply_supported:false,validation_id:'token',expires_at:Date.now()/1000+30,matches_current_config:true,nodes:[{id:'b',peer:'169.254.1.2:5560',listen:'169.254.1.2:5560',upstream_peer:null}],warning:'No apply endpoint'}:data};}});
 const $=n=>elements['thunderbolt'+n];assert.equal(requests.length,0);assert.equal($('Preview').disabled,true);
 if(['success','error'].includes(name)){
  await $('Inspect').onclick();assert.equal(requests.length,1);assert.equal(requests[0].length,1);assert.equal(requests[0][0],'/api/thunderbolt');assert.equal($('Inspect').disabled,false);assert.match($('Readout').textContent,name==='error'?/offline.*no fallback/:/Mini <not HTML>.*Unverified/);
 }else if(name==='no_opt_in'){
  await $('Validate').onclick();assert.equal($('Preview').disabled,true);await $('Preview').onclick();assert.equal(requests.length,1);
 }else if(name==='missing_graph'){
  $('OptIn').checked=true;$('OptIn').onchange();assert.equal($('Preview').disabled,true);await $('Preview').onclick();assert.equal(requests.length,0);
 }else{
  await $('Validate').onclick();assert.equal(requests[0][0],'/api/thunderbolt/validate');assert.deepEqual(JSON.parse(requests[0][1].body),{});assert.equal($('Preview').disabled,true);
  if(name==='failed'){assert.match($('Readout').textContent,/Failed/);return;}
  assert.match($('Readout').textContent,/Verified · 12 ms SSH hello.*0.2 ms TCP/);
  $('OptIn').checked=true;$('OptIn').onchange();assert.equal($('Preview').disabled,false);
  if(name==='expired'){timers.at(-1)();assert.equal($('Preview').disabled,true);assert.match($('Readout').textContent,/Unverified · validation expired/);await $('Preview').onclick();assert.equal(requests.length,1);}
  else if(['preview','preview_error','preview_expired'].includes(name)){await $('Preview').onclick();assert.equal(requests[1][0],'/api/thunderbolt/plan');assert.deepEqual(JSON.parse(requests[1][1].body),{opt_in:true,validation_id:'token'});assert.match($('Plan').textContent,['preview_error','preview_expired'].includes(name)?/Nothing applied; no fallback/:/Preview only · nothing applied.*Matches current.*169.254.1.2:5560/);}
 }
 console.log('ok',name);
})().catch(e=>{console.error(e);process.exit(1)});
