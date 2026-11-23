/* Explicit trusted link validation and opt-in plan preview. No apply API. */
(() => {
  const $=id=>document.getElementById(id),button=$('thunderboltInspect'),validate=$('thunderboltValidate'),
    out=$('thunderboltReadout'),opt=$('thunderboltOptIn'),preview=$('thunderboltPreview'),plan=$('thunderboltPlan');
  const text=(tag,value)=>{const e=document.createElement(tag);e.textContent=value;return e;};
  let last=null,timer=null,busy=false,expired=false;
  const available=()=>!!last?.validation_id && !expired && Date.now()/1000 < last.validated_at+(last.validation_ttl_s || 30);
  const gate=()=>{button.disabled=busy;validate.disabled=busy;preview.disabled=busy || !opt.checked || !available();};
  function expire(){expired=true;gate();plan.textContent=T('web.validation_expired_validate_again_before_request');
    for(const e of out.querySelectorAll('.tb-status.verified')){e.textContent=T('web.unverified_validation_expired');e.className='tb-status unverified';}}
  function draw(data){
    last=data;expired=false;opt.checked=false;plan.textContent='';clearTimeout(timer);
    out.replaceChildren(text('p',data.validation_id?T('web.read_only_bounded_link_validation_expires'):T('web.read_only_inventory_unverified_until_validate')));
    for(const n of data.nodes || []){
      out.append(text('p',n.label+': '+(n.offline?T('web.trusted_inspection_unavailable'):(n.interfaces || []).map(i=>`${i.interface} ${i.addresses.join(', ')} (${i.kind})`).join(' · ') || T('web.no_trusted_private_thunderbolt_address'))));
      if(n.error)out.append(text('small',n.error));
    }
    for(const e of data.graph?.edges || []){
      const row=text('div','');row.className='tb-edge';
      row.append(text('p',`${e.source} → ${e.target}: ${e.source_interface} ${e.source_address || ''} → ${e.target_interface || ''} ${e.address}`));
      const state=['verified','failed'].includes(e.status)?e.status:'unverified';
      let label=state==='verified'?T(`web.verified_latency_ms_ms_ssh_hello`, {latency_ms: e.latency_ms, v: e.tcp_connect_ms!==undefined?T(`web.tcp_connect_ms_ms_tcp_connect`, {tcp_connect_ms: e.tcp_connect_ms}):''}):state==='failed'?T('web.failed'):T('web.unverified');
      if(state!=='verified')label+=e.reachable===true?T(`web.tcp_reachable_v`, {v: typeof e.tcp_connect_ms==='number'?T(`web.tcp_connect_ms_ms_connect`, {tcp_connect_ms: e.tcp_connect_ms}):''}):e.reachable===false?T('web.tcp_unreachable'):T('web.reachability_unknown');
      const status=text('span',label);
      status.className='tb-status '+state;row.append(status,text('p',e.reason || T('web.not_validated')));out.append(row);
    }
    if(!(data.graph?.edges || []).length)out.append(text('p',T('web.no_candidate_routes_observed_existing_connection')));
    out.append(text('p',data.graph?.warning || T('web.model_data_plane_health_and_throughput')));
    if(data.validation_id){const expiry=Math.min(data.validated_at+(data.validation_ttl_s || 30),...(data.graph?.edges || []).filter(e=>e.status==='verified' && typeof e.checked_at==='number').map(e=>e.checked_at+30));timer=setTimeout(expire,Math.max(0,expiry*1000-Date.now()));}
  }
  async function inspect(active){
    busy=true;last=null;plan.textContent='';opt.checked=false;gate();out.textContent=active?T('web.validating_private_thunderbolt_links_with_bounde'):T('web.inspecting_configured_trusted_minis');
    try{
      const response=active?await fetch('/api/thunderbolt/validate',{method:'POST',headers:{'Content-Type':'application/json'},body:'{}'}):await fetch('/api/thunderbolt'),data=await response.json();
      if(!response.ok)throw Error(data.error || T('web.inspection_unavailable'));draw(data);
    }catch(error){last=null;out.textContent=T(`web.message_existing_connection_was_not_changed`, {message: (error.message)});}
    finally{busy=false;gate();}
  }
  button.onclick=()=>inspect(false);validate.onclick=()=>inspect(true);opt.onchange=gate;
  preview.onclick=async()=>{
    if(preview.disabled || !available() || !opt.checked)return;
    busy=true;gate();plan.textContent=T('web.preparing_a_preview_from_this_verified');
    try{
      const response=await fetch('/api/thunderbolt/plan',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({opt_in:true,validation_id:last.validation_id})}),data=await response.json();
      if(!response.ok || data.preview_only!==true || data.apply_supported!==false || !available() || data.validation_id!==last?.validation_id || !(data.expires_at>Date.now()/1000))throw Error(data.error || T('web.fresh_safe_preview_unavailable'));
      plan.replaceChildren(text('h4',T('web.preview_only_nothing_applied')),text('p',data.matches_current_config?T('web.matches_current_configured_peer_listen_endpoints'):T('web.differs_from_current_configured_endpoints_previe')));
      for(const n of data.nodes)plan.append(text('p',T(`web.id_peer_peer_listen_listen_upstream`, {id: n.id, peer: n.peer || T('web.none'), listen: n.listen || T('web.unchanged'), upstream_peer: n.upstream_peer || T('web.none')})));
      plan.append(text('p',data.warning));
      const details=text('details','');details.append(text('summary',T('web.plan_details')),text('pre',JSON.stringify(data,null,2)));plan.append(details);
    }catch(error){plan.textContent=T(`web.plan_unavailable_message_nothing_applied_no`, {message: error.message});}
    finally{busy=false;gate();}
  };
  gate();
})();
