/* Explicit trusted link validation and opt-in plan preview. No apply API. */
(() => {
  const $=id=>document.getElementById(id),button=$('thunderboltInspect'),validate=$('thunderboltValidate'),
    out=$('thunderboltReadout'),opt=$('thunderboltOptIn'),preview=$('thunderboltPreview'),plan=$('thunderboltPlan');
  const text=(tag,value)=>{const e=document.createElement(tag);e.textContent=value;return e;};
  let last=null,timer=null,busy=false,expired=false;
  const available=()=>!!last?.validation_id && !expired && Date.now()/1000 < last.validated_at+(last.validation_ttl_s || 30);
  const gate=()=>{button.disabled=busy;validate.disabled=busy;preview.disabled=busy || !opt.checked || !available();};
  function expire(){expired=true;gate();plan.textContent='Validation expired. Validate again before requesting a new preview; nothing was applied.';
    for(const e of out.querySelectorAll('.tb-status.verified')){e.textContent='Unverified · validation expired';e.className='tb-status unverified';}}
  function draw(data){
    last=data;expired=false;opt.checked=false;plan.textContent='';clearTimeout(timer);
    out.replaceChildren(text('p',data.validation_id?'Read-only · bounded link validation · expires within 30 seconds · automatic routing off.':'Read-only inventory · unverified until Validate links · automatic routing off.'));
    for(const n of data.nodes || []){
      out.append(text('p',n.label+': '+(n.offline?'trusted inspection unavailable':(n.interfaces || []).map(i=>`${i.interface} ${i.addresses.join(', ')} (${i.kind})`).join(' · ') || 'no trusted private Thunderbolt address')));
      if(n.error)out.append(text('small',n.error));
    }
    for(const e of data.graph?.edges || []){
      const row=text('div','');row.className='tb-edge';
      row.append(text('p',`${e.source} → ${e.target}: ${e.source_interface} ${e.source_address || ''} → ${e.target_interface || ''} ${e.address}`));
      const state=['verified','failed'].includes(e.status)?e.status:'unverified';
      let label=state==='verified'?`Verified · ${e.latency_ms} ms SSH hello${e.tcp_connect_ms!==undefined?' · '+e.tcp_connect_ms+' ms TCP connect':''}`:state==='failed'?'Failed':'Unverified';
      if(state!=='verified')label+=e.reachable===true?' · TCP reachable'+(typeof e.tcp_connect_ms==='number'?' · '+e.tcp_connect_ms+' ms connect':''):e.reachable===false?' · TCP unreachable':' · reachability unknown';
      const status=text('span',label);
      status.className='tb-status '+state;row.append(status,text('p',e.reason || 'Not validated'));out.append(row);
    }
    if(!(data.graph?.edges || []).length)out.append(text('p','No candidate routes observed. Existing connection was not changed.'));
    out.append(text('p',data.graph?.warning || 'Model data-plane health and throughput are not tested.'));
    if(data.validation_id){const expiry=Math.min(data.validated_at+(data.validation_ttl_s || 30),...(data.graph?.edges || []).filter(e=>e.status==='verified' && typeof e.checked_at==='number').map(e=>e.checked_at+30));timer=setTimeout(expire,Math.max(0,expiry*1000-Date.now()));}
  }
  async function inspect(active){
    busy=true;last=null;plan.textContent='';opt.checked=false;gate();out.textContent=active?'Validating private Thunderbolt links with bounded SSH hellos…':'Inspecting configured trusted Minis…';
    try{
      const response=active?await fetch('/api/thunderbolt/validate',{method:'POST',headers:{'Content-Type':'application/json'},body:'{}'}):await fetch('/api/thunderbolt'),data=await response.json();
      if(!response.ok)throw Error(data.error || 'Inspection unavailable');draw(data);
    }catch(error){last=null;out.textContent=error.message+'. Existing connection was not changed; no fallback.';}
    finally{busy=false;gate();}
  }
  button.onclick=()=>inspect(false);validate.onclick=()=>inspect(true);opt.onchange=gate;
  preview.onclick=async()=>{
    if(preview.disabled || !available() || !opt.checked)return;
    busy=true;gate();plan.textContent='Preparing a preview from this verified graph only…';
    try{
      const response=await fetch('/api/thunderbolt/plan',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({opt_in:true,validation_id:last.validation_id})}),data=await response.json();
      if(!response.ok || data.preview_only!==true || data.apply_supported!==false || !available() || data.validation_id!==last?.validation_id || !(data.expires_at>Date.now()/1000))throw Error(data.error || 'Fresh safe preview unavailable');
      plan.replaceChildren(text('h4','Preview only · nothing applied'),text('p',data.matches_current_config?'Matches current configured peer/listen endpoints (resolved from trusted inventory).':'Differs from current configured endpoints — preview only; nothing changed.'));
      for(const n of data.nodes)plan.append(text('p',`${n.id}: peer ${n.peer || 'none'} · listen ${n.listen || 'unchanged'} · upstream ${n.upstream_peer || 'none'}`));
      plan.append(text('p',data.warning));
      const details=text('details','');details.append(text('summary','Plan details'),text('pre',JSON.stringify(data,null,2)));plan.append(details);
    }catch(error){plan.textContent='Plan unavailable: '+error.message+'. Nothing applied; no fallback.';}
    finally{busy=false;gate();}
  };
  gate();
})();
