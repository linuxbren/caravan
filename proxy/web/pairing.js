(function () {
'use strict';
let token='';
let lastPeers=[], lastBusy=false, activePeerIds=null;
function paintRemovals(){
  if(!window.openCaravanPairing)return;
  for(const old of document.querySelectorAll('[data-pair-remove]'))old.remove();
  for(const peer of lastPeers){
    if(peer.direction!=='outgoing')continue;
    const card=document.getElementById('nodeCard-'+peer.node_id);if(!card)continue;
    const button=document.createElement('button');button.type='button';button.className='ghost';button.dataset.pairRemove=peer.id;
    button.textContent=peer.state==='removal-pending'?'Retry removal':'Remove this Mac';button.disabled=lastBusy;
    button.onclick=()=>run(button,async()=>{if(!window.confirm('Remove this connection? Model files will be kept.'))return;const out=await post('remove',{id:peer.id});message(out.pending?out.message:'Mac removed.');await state();});
    card.append(button);
  }
}

const fragments=new URLSearchParams(location.hash.slice(1));
const capability=fragments.get('pair');
const nextHome=fragments.get('next')==='home';
history.replaceState(null,'',location.pathname + (location.hash === '#add-mac' ? '#add-mac' : ''));
try { document.documentElement.dataset.theme=localStorage.getItem('caravan-theme') || 'amber'; } catch (_) {}
const initialized=capability?fetch('/api/pairing/session',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({capability})}).then(async r=>{if(!r.ok)throw Error((await r.json()).error);if(location.pathname==='/pairing')location.replace(nextHome?'/':'/#add-mac');}):Promise.resolve();
const el=id=>document.getElementById(id);
const message=text=>{el('message').textContent=text;};
async function post(action,body={}){
  const r=await fetch('/api/pairing/'+action,{method:'POST',headers:{'Content-Type':'application/json','X-Caravan-Pairing':token},body:JSON.stringify(body)});
  const out=await r.json();if(!r.ok)throw Error(out.error||'Please try again.');return out;
}
function text(tag,content,parent){const n=document.createElement(tag);n.textContent=content;parent.append(n);return n;}
async function state(){
  const r=await fetch('/api/pairing/state',{cache:'no-store'});const s=await r.json();if(!r.ok)throw Error(s.error);token=s.token;
  el('loginStatus').textContent=s.remote_login?'Remote Login is reachable on this Mac. Make sure this account is allowed in the setting.':'Turn on Remote Login for this account, then return here.';
  el('mycode').textContent=s.code||'No code is showing';
  el('expiry').textContent=s.code?'One use only. Expires in '+Math.ceil(s.expires_in/60)+' minutes.':'Click Show a new code when you are ready.';
  const ids=s.peers.filter(p=>p.direction==='outgoing' && p.state==='active').map(p=>p.id);
  const added=activePeerIds!==null && ids.some(id=>!activePeerIds.includes(id));
  activePeerIds=ids;
  lastPeers=s.peers; lastBusy=s.busy;
  el('connected').replaceChildren();
  for(const peer of s.peers){
    const row=document.createElement('div');row.className='mac';text('strong',peer.name,row);
    text('p',peer.direction==='incoming'?'Added by your first Mac. Remove this connection there.':peer.state==='active'?'Connected. Ready for your next model.':'Connection needs attention ('+peer.state+'). Try removing it, then add it again.',row);
    if(peer.direction==='outgoing'){
      const b=text('button',peer.state==='removal-pending'?'Retry removal':'Remove this Mac',row);b.disabled=s.busy;
      b.onclick=()=>run(b,async()=>{if(!window.confirm('Remove this connection? Model files will be kept.'))return;const out=await post('remove',{id:peer.id});message(out.pending?out.message:'Mac removed.');await state();});
    }
    if(!window.openCaravanPairing) el('connected').append(row);
  }
  paintRemovals();
  if(added)window.dispatchEvent(new CustomEvent('caravan-pairing-complete'));
  return s;
}
async function run(button,fn){button.disabled=true;try{await fn();}catch(e){message(e.message);}finally{button.disabled=false;}}
el('code').onclick=()=>run(el('code'),async()=>{await post('code');await state();message('Enter this code on your first Mac. Keep it private.');});
el('settings').onclick=()=>run(el('settings'),async()=>{await post('remote-login');message('Turn on Remote Login for this account, then return here. If the pane did not open, go to System Settings → General → Sharing → Remote Login.');});
el('find').onclick=()=>run(el('find'),async()=>{
  message('Looking for nearby Macs…');const out=await post('discover');el('nearby').replaceChildren();
  for(const peer of out.nodes){
    const row=document.createElement('div');row.className='mac';text('strong',peer.name,row);text('p',peer.source,row);
    if(!peer.remote_login)text('p','On the new Mac, open Caravan → Topology → Add a Mac and turn on Remote Login.',row);
    if(!peer.accepting)text('p','On the new Mac, click Show a new code, then find Macs again.',row);
    const input=document.createElement('input');input.type='password';input.inputMode='numeric';input.autocomplete='off';input.placeholder='Pairing code';input.maxLength=9;input.setAttribute('aria-label','Code shown on '+peer.name);row.append(input);
    const b=text('button','Add this Mac',row);b.disabled=!peer.accepting||!peer.remote_login;
    b.onclick=()=>run(b,async()=>{message('Checking the code and saving the connection…');try{await post('add',{id:peer.id,code:input.value});input.value='';message('Mac added. Return to Caravan and choose your next model. Use Balance to check a cable connection before loading.');await state();window.dispatchEvent(new CustomEvent('caravan-pairing-complete'));}finally{input.value='';}});
    el('nearby').append(row);
  }
  message(out.nodes.length?'Enter the code from the Mac you want to add.':'No nearby Macs yet. On the new Mac, check Caravan is open, then try again.');
});
window.refreshCaravanPairing=()=>initialized.then(()=>state()).catch(e=>message(e.message));
window.paintPairingRemovals=paintRemovals;
initialized.then(()=>state()).then(()=>message('Ready. Follow the steps below on each Mac.')).catch(e=>message(e.message));
setInterval(()=>initialized.then(()=>state()).catch(()=>{}),10000);

})();
