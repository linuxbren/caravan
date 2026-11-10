// Minimal DOM contract runner: exercises production handlers, never a real API.
const assert = require('node:assert/strict'), fs = require('node:fs'), vm = require('node:vm');
const V = require('../../proxy/web/balance_view.js');
class El {
  constructor(tag='div') { this.tagName=tag;this.children=[];this.attrs={};this.style={};this.listeners={};this.value='';this._text='';this.disabled=false;this.hidden=false;this.classList={contains:()=>true}; }
  set textContent(v) {this._text=String(v);this.children=[];} get textContent(){return this._text+this.children.map(e=>e.textContent).join('');}
  append(...els){this.children.push(...els);} replaceChildren(...els){this._text='';this.children=[...els];}
  setAttribute(k,v){this.attrs[k]=v;} addEventListener(k,f){this.listeners[k]=f;}
  get selectedOptions(){return this.children.filter(e=>e.value===this.value);}
}
function fixture(n=3,format='mlx') {
 const counts=Array(n).fill(4), node_ids=counts.map((_,i)=>'n'+i);let at=0;
 return {model_id:'tiny',counts,node_ids,format,mode:'auto',ready:true,margin_gb:1.75,note:'estimate',stages:counts.map((v,i)=>{const start=at;at+=v;return {id:node_ids[i],label:'Mini '+i,range:[start,at],capacity_gb:20,estimated_use_gb:8,headroom_gb:12,safe:true,downloads:[],metadata_ready:true};})};
}
function setup(){
 const elements={},document={getElementById:id=>elements[id] ||= new El(),createElement:tag=>new El(tag)};
 const requests=[], pending=[];let timer;
 const window={CaravanBalanceView:V,addEventListener(){}};
 const fetch=async(url,opts={})=>{requests.push({url,body:opts.body?JSON.parse(opts.body):null});if(url==='/api/models')return {ok:true,json:async()=>({models:[{id:'tiny',name:'Tiny model'}]})};if(url==='/api/balance'){let value=fixture();if(pending.length)value=await pending.shift();return {ok:true,json:async()=>value};}return {ok:true,json:async()=>({})};};
 document.getElementById('modelSelect').value='tiny';document.getElementById('balanceModel').value='tiny';document.getElementById('balanceApply').disabled=true;
 vm.runInNewContext(fs.readFileSync(require.resolve('../../proxy/web/balance.js'),'utf8'),{document,window,fetch,clearTimeout(){timer=null;},setTimeout:f=>{timer=f;return 1;},console});
 return {elements,requests,pending,async tick(){for(let i=0;i<8;i++)await new Promise(r=>setImmediate(r));},async open(){elements.btnOpenTopo.listeners.click();await this.tick();},async timer(){if(timer){const f=timer;timer=null;await f();await this.tick();}}};
}
(async()=>{
 const name=process.argv[2];let s,p;
 switch(name){
 case 'n_boundaries': for(const n of [1,2,3,7]){const c=Array(n).fill(4);for(let i=0;i<n-1;i++){const out=V.moveBoundary(c,i,999);assert.equal(out.reduce((a,b)=>a+b,0),4*n);assert.ok(out.every(x=>x>0));assert.equal(out[i+1],1);}}break;
 case 'invalid_boundary': for(const v of [NaN,Infinity,'x']) assert.throws(()=>V.moveBoundary([4,4],0,v));assert.throws(()=>V.moveBoundary([4,4],2,1));break;
 case 'cards_unknown': for(const value of [null,NaN,Infinity,-1])assert.equal(V.card({capacity_gb:value}).known,false);assert.equal(V.card({capacity_gb:20,estimated_use_gb:30,headroom_gb:-10,safe:false}).percent,100);break;
 case 'valid_plan':assert.equal(V.valid(fixture()),true);p=fixture();p.counts=[1];assert.equal(V.valid(p),false);p=fixture();p.counts[0]=.5;assert.equal(V.valid(p),false);p.format='gguf';assert.equal(V.valid(p),true);p.node_ids[1]=p.node_ids[0];assert.equal(V.valid(p),false);break;
 case 'summaries':p=fixture(7);assert.match(V.summary(p,false),/automatically/);assert.match(V.summary(p,true),/Mini 6 4 layers/);p.stages[4].headroom_gb=null;assert.match(V.summary(p,false),/blocked/);break;
 case 'default_auto':s=setup();await s.open();assert.equal(s.elements.balanceMemory.children.length,3);assert.equal(s.elements.balanceControls.hidden,true);assert.equal(s.elements.balanceAuto.disabled,true);assert.equal(s.requests.filter(x=>x.url==='/api/models/load').length,0);assert.equal(s.requests.at(-1).body.counts,null);break;
 case 'adjust_n':s=setup();s.pending.push(Promise.resolve(fixture(7)));await s.open();s.elements.balanceAdjust.onclick();assert.equal(s.elements.balanceControls.children.length,6);assert.equal(s.elements.balanceControls.hidden,false);assert.match(s.elements.balancePreview.textContent,/Mini 6 4 layers/);assert.equal(s.requests.length,2);break;
 case 'back_auto':s=setup();await s.open();s.elements.balanceAdjust.onclick();await s.elements.balanceAuto.onclick();await s.tick();assert.equal(s.elements.balanceControls.hidden,true);assert.equal(s.requests.at(-1).body.counts,null);assert.equal(s.requests.filter(x=>x.url==='/api/models/load').length,0);break;
 case 'slider_pending':s=setup();await s.open();s.elements.balanceAdjust.onclick();p=s.elements.balanceControls.children[0].children[1];p.value=5;p.oninput();assert.equal(s.elements.balanceApply.disabled,true);assert.match(s.elements.balancePreview.textContent,/Mini 0 5 layers/);await s.timer();assert.deepEqual(s.requests.at(-1).body.counts,[5,3,4]);break;
 case 'stale_response':s=setup();let resolve;s.pending.push(new Promise(r=>resolve=r));s.elements.btnOpenTopo.listeners.click();await s.tick();s.elements.balanceRepo.value='other/model';s.elements.balanceRepo.oninput();resolve(fixture());await s.tick();assert.equal(s.elements.balanceApply.disabled,true);assert.equal(s.elements.balanceMemory.children.length,0);assert.match(s.elements.balancePreview.textContent,/Source changed/);break;
 case 'error_disables':s=setup();await s.open();s.pending.push(Promise.resolve({error:'offline'}));await s.elements.balanceRefresh.onclick();await s.tick();assert.equal(s.elements.balanceApply.disabled,true);assert.equal(s.elements.balanceAdjust.disabled,true);assert.equal(s.elements.balanceMemory.children.length,0);break;
 case 'gguf_adjust':s=setup();s.pending.push(Promise.resolve(fixture(3,'gguf')));await s.open();s.elements.balanceAdjust.onclick();assert.equal(s.elements.balanceControls.children.length,3);p=s.elements.balanceControls.children[0].children[1];assert.equal(p.type,'number');p.value='0';p.oninput();assert.equal(s.elements.balanceApply.disabled,true);assert.match(s.elements.balancePreview.textContent,/positive/);break;
 case 'apply_exact':s=setup();await s.open();await s.elements.balanceApply.onclick();p=s.requests.find(x=>x.url==='/api/models/load');assert.deepEqual(p.body.counts,[4,4,4]);assert.deepEqual(p.body.node_ids,['n0','n1','n2']);assert.equal(p.body.model_id,'tiny');assert.equal(s.elements.balanceApply.disabled,true);await s.elements.balanceApply.onclick();assert.equal(s.requests.filter(x=>x.url==='/api/models/load').length,1);break;
 case 'unsafe_plan':s=setup();p=fixture();p.ready=false;p.stages[0].safe=false;s.pending.push(Promise.resolve(p));await s.open();assert.equal(s.elements.balanceApply.disabled,true);await s.elements.balanceApply.onclick();assert.equal(s.requests.filter(x=>x.url==='/api/models/load').length,0);break;
 default:throw Error(name);
 }
 console.log('PASS',name);
})().catch(e=>{console.error(e);process.exit(1);});
