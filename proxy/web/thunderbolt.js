/* Explicit read-only inspection. Never wired into model loads or route config. */
(() => {
  const button=document.getElementById('thunderboltInspect'),out=document.getElementById('thunderboltReadout');
  const text=(tag,value)=>{const e=document.createElement(tag);e.textContent=value;return e;};
  button.onclick=async()=>{
    button.disabled=true;out.textContent='Inspecting configured trusted Minis…';
    try {
      const response=await fetch('/api/thunderbolt'),data=await response.json();
      if(!response.ok)throw Error(data.error || 'Inspection unavailable');
      out.replaceChildren(text('p','Read-only · automatic routing off · results cached for 30 seconds.'));
      for(const n of data.nodes || []){
        out.append(text('p',n.label+': '+(n.offline ? 'trusted inspection unavailable' :
          (n.interfaces || []).map(i=>`${i.interface} ${i.addresses.join(', ')} (${i.kind})`).join(' · ') || 'no verified private Thunderbolt address')));
        if(n.error)out.append(text('small',n.error));
      }
      for(const e of data.graph?.edges || [])out.append(text('p',`${e.source} → ${e.target}: ${e.source_interface} → ${e.address} · candidate only`));
      if(!(data.graph?.edges || []).length)out.append(text('p','No candidate routes observed. Existing connection was not changed.'));
      out.append(text('p',data.graph?.warning || 'Data-plane identity and reachability are not verified.'));
    } catch(error) {out.textContent=error.message+'. Existing connection was not changed.';}
    finally {button.disabled=false;}
  };
})();
