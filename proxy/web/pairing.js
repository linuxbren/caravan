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
    button.textContent=peer.state==='removal-pending'?T('web.retry_removal'):T('web.remove_this_mac');button.disabled=lastBusy;
    button.onclick=()=>run(button,async()=>{if(!window.confirm(T('web.remove_this_connection_model_files_will')))return;const out=await post('remove',{id:peer.id});message(out.pending?out.message:T('web.mac_removed'));await state();});
    card.append(button);
  }
}

const fragments=new URLSearchParams(location.hash.slice(1));
const capability=fragments.get('pair');
const nextHome=fragments.get('next')==='home';
history.replaceState(null,'',location.pathname + (location.hash === '#add-mac' ? '#add-mac' : ''));
try {
  let _t = localStorage.getItem('caravan-theme') || 'amber';
  if (_t === 'nebula') _t = 'campfire';
  if (!['amber','green','meadow','campfire'].includes(_t)) _t = 'amber';
  document.documentElement.dataset.theme = _t;
} catch (_) {}
const initialized=capability?fetch('/api/pairing/session',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({capability})}).then(async r=>{if(!r.ok)throw Error((await r.json()).error);if(location.pathname==='/pairing')location.replace(nextHome?'/':'/#add-mac');}):Promise.resolve();
const el=id=>document.getElementById(id);
const message=text=>{el('message').textContent=text;};
async function post(action,body={}){
  const r=await fetch('/api/pairing/'+action,{method:'POST',headers:{'Content-Type':'application/json','X-Caravan-Pairing':token},body:JSON.stringify(body)});
  const out=await r.json();if(!r.ok)throw Error(out.error||T('web.please_try_again'));return out;
}
function text(tag,content,parent){const n=document.createElement(tag);n.textContent=content;parent.append(n);return n;}
async function state(){
  const r=await fetch('/api/pairing/state',{cache:'no-store'});const s=await r.json();if(!r.ok)throw Error(s.error);token=s.token;
  el('loginStatus').textContent=s.remote_login?T('web.remote_login_is_reachable_on_this'):T('web.turn_on_remote_login_for_this');
  el('mycode').textContent=s.code||T('web.no_code_is_showing');
  el('expiry').textContent=s.code?T(`web.one_use_only_expires_in_v`, {v: Math.ceil(s.expires_in/60)}):T('web.click_show_a_new_code_when');
  const ids=s.peers.filter(p=>p.direction==='outgoing' && p.state==='active').map(p=>p.id);
  const added=activePeerIds!==null && ids.some(id=>!activePeerIds.includes(id));
  activePeerIds=ids;
  lastPeers=s.peers; lastBusy=s.busy;
  el('connected').replaceChildren();
  for(const peer of s.peers){
    const row=document.createElement('div');row.className='mac';text('strong',peer.name,row);
    text('p',peer.direction==='incoming'?T('web.added_by_your_first_mac_remove'):peer.state==='active'?T('web.connected_ready_for_your_next_model'):T(`web.connection_needs_attention_state_try_removing`, {state: peer.state}),row);
    if(peer.direction==='outgoing'){
      const b=text('button',peer.state==='removal-pending'?T('web.retry_removal'):T('web.remove_this_mac'),row);b.disabled=s.busy;
      b.onclick=()=>run(b,async()=>{if(!window.confirm(T('web.remove_this_connection_model_files_will')))return;const out=await post('remove',{id:peer.id});message(out.pending?out.message:T('web.mac_removed'));await state();});
    }
    if(!window.openCaravanPairing) el('connected').append(row);
  }
  paintRemovals();
  if(added)window.dispatchEvent(new CustomEvent('caravan-pairing-complete'));
  return s;
}
async function run(button,fn){button.disabled=true;try{await fn();}catch(e){message(e.message);}finally{button.disabled=false;}}
el('code').onclick=()=>run(el('code'),async()=>{await post('code');await state();message(T('web.enter_this_code_on_your_first'));});
el('settings').onclick=()=>run(el('settings'),async()=>{await post('remote-login');message(T('web.turn_on_remote_login_for_this_2'));});
el('find').onclick=()=>run(el('find'),async()=>{
  message(T('web.looking_for_nearby_macs'));const out=await post('discover');el('nearby').replaceChildren();
  for(const peer of out.nodes){
    const row=document.createElement('div');row.className='mac';text('strong',peer.name,row);text('p',peer.source,row);
    if(!peer.remote_login)text('p',T('web.on_the_new_mac_open_caravan'),row);
    if(!peer.accepting)text('p',T('web.on_the_new_mac_click_show'),row);
    const input=document.createElement('input');input.type='password';input.inputMode='numeric';input.autocomplete='off';input.placeholder=T('web.pairing_code');input.maxLength=9;input.setAttribute('aria-label',T(`web.code_shown_on_name`, {name: peer.name}));row.append(input);
    const b=text('button',T('web.add_this_mac'),row);b.disabled=!peer.accepting||!peer.remote_login;
    b.onclick=()=>run(b,async()=>{message(T('web.checking_the_code_and_saving_the'));try{await post('add',{id:peer.id,code:input.value});input.value='';message(T('web.mac_added_return_to_caravan_and'));await state();window.dispatchEvent(new CustomEvent('caravan-pairing-complete'));}finally{input.value='';}});
    el('nearby').append(row);
  }
  message(out.nodes.length?T('web.enter_the_code_from_the_mac'):T('web.no_nearby_macs_yet_on_the'));
});
window.refreshCaravanPairing=()=>initialized.then(()=>state()).catch(e=>message(e.message));
window.paintPairingRemovals=paintRemovals;
initialized.then(()=>state()).then(()=>message(T('web.ready_follow_the_steps_below_on'))).catch(e=>message(e.message));
setInterval(()=>initialized.then(()=>state()).catch(()=>{}),10000);

})();
