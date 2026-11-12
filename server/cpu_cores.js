(() => {
  const states=new WeakMap();
  window.keepCpuCores=(previous,next)=>{const olds=Array.isArray(previous)?previous:[...previous.querySelectorAll('[data-cpu-cores]')];for(const old of olds){const fresh=[...next.querySelectorAll('[data-cpu-cores]')].find(d=>d.dataset.cpuUrl===old.dataset.cpuUrl);if(fresh)fresh.replaceWith(old)}};
  async function load(details,force=false,offset=null){
    if(!details.open||!details.isConnected)return;
    const old=states.get(details);if(old?.busy||old?.loaded&&!force)return;
    const controller=new AbortController(),state={busy:true,loaded:false,controller,offset:offset??old?.offset??0};states.set(details,state);
    const content=details.querySelector('.cpu-cores-content');if(!old?.loaded)content.textContent='Загрузка логических процессоров…';content.setAttribute('aria-busy','true');
    try{
      const url=new URL(details.dataset.cpuUrl,location.origin);url.searchParams.set('offset',state.offset);url.searchParams.set('all_cores','1');
      const response=await fetch(url,{credentials:'same-origin',cache:'no-store',signal:controller.signal});
      if(!response.ok)throw Error(response.status===401||response.status===403?'Доступ к графикам закрыт. Войдите в портал снова.':'Не удалось получить графики ядер');
      const data=await response.json();if(!details.isConnected||!details.open)return;
      state.offset=data.offset??state.offset;state.loaded=true;const top=content.scrollTop;const update=()=>{content.innerHTML=data.html;content.scrollTop=top};window.portalMotion?window.portalMotion.preserve(update):update();
    }catch(error){if(error.name!=='AbortError'&&details.isConnected){const text=document.createElement('p'),button=document.createElement('button');text.textContent=error.message;button.type='button';button.textContent='Повторить';button.addEventListener('click',()=>load(details,true));content.replaceChildren(text,button)}}
    finally{state.busy=false;content.removeAttribute('aria-busy')}
  }
  document.addEventListener('toggle',event=>{const details=event.target;if(!details.matches?.('[data-cpu-cores]'))return;if(details.open)load(details,true);else{const state=states.get(details);if(state?.busy){state.controller.abort();state.busy=false;state.loaded=false}}},true);
  document.addEventListener('click',event=>{const button=event.target.closest('[data-core-page]');if(button){event.preventDefault();load(button.closest('[data-cpu-cores]'),true,Number(button.dataset.corePage))}});
  const scan=()=>document.querySelectorAll('[data-cpu-cores][open]').forEach(d=>load(d));
  new MutationObserver(records=>{if(records.some(r=>[...r.addedNodes].some(n=>n.nodeType===1&&(n.matches?.('[data-cpu-cores]')||n.querySelector?.('[data-cpu-cores]')))))scan()}).observe(document.body,{childList:true,subtree:true});scan();
  setInterval(()=>{if(!document.hidden)document.querySelectorAll('[data-cpu-cores][open]:not([data-cpu-historical])').forEach(d=>{const box=d.getBoundingClientRect();if(box.width&&box.bottom>=0&&box.top<=innerHeight)load(d,true)})},10000);
})();
