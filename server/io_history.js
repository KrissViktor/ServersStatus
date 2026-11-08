(() => {
  const root=document.getElementById('history-content');
  if(!root || !root.querySelector('.io-selector'))return;
  let pending=null,version=0;
  const expanded=new Set();
  function restore(){
    for(const chart of root.querySelectorAll('[data-chart-key]')){
      const open=expanded.has(chart.dataset.chartKey);
      chart.classList.toggle('is-expanded',open);
      const button=chart.querySelector('.chart-expand');
      if(button){button.textContent=open?'Сузить':'Расширить';button.setAttribute('aria-expanded',String(open))}
    }
  }
  root.addEventListener('click',event=>{
    const button=event.target.closest('.chart-expand');if(!button)return;
    const key=button.closest('[data-chart-key]').dataset.chartKey;
    if(expanded.has(key))expanded.delete(key);else expanded.add(key);
    restore();
  });
  // Background refresh replaces server-rendered charts; keep their chosen widths.
  new MutationObserver(records=>{if(records.some(record=>[...record.addedNodes].some(n=>n.nodeType===1)))restore()}).observe(root,{childList:true,subtree:true});
  async function update(form){
    if(pending)pending.abort();
    const current=++version,controller=new AbortController();pending=controller;
    root.dataset.fetchBusy='true';
    const url=new URL(location.href);
    for(const select of root.querySelectorAll('.io-selector select'))url.searchParams.set(select.name,select.value);
    const group=form.closest('[data-io-section]').dataset.ioSection;
    const status=()=>root.querySelector('[data-io-section="'+group+'"] .io-status');
    root.querySelectorAll('.io-status').forEach(n=>n.textContent='');
    status().textContent='Обновляем графики…';
    root.querySelectorAll('.io-plots').forEach(n=>n.setAttribute('aria-busy','true'));
    try{
      const response=await fetch(url,{signal:controller.signal,credentials:'same-origin',cache:'no-store'});
      if(!response.ok)throw new Error();
      const next=new DOMParser().parseFromString(await response.text(),'text/html');
      if(current!==version)return;
      if(!next.querySelector('.io-selector'))throw new Error();
      const x=scrollX,y=scrollY;
      document.body.style.minHeight=Math.max(innerHeight,y+innerHeight)+'px';
      for(const section of root.querySelectorAll('[data-io-section]')){
        const fresh=next.querySelector('[data-io-section="'+section.dataset.ioSection+'"]');
        if(!fresh)continue;
        section.querySelector('.io-plots').replaceChildren(...fresh.querySelector('.io-plots').childNodes);
        for(const input of section.querySelectorAll('.io-selector input,.io-selector select')){
          const source=fresh.querySelector('[name="'+input.name+'"]');if(source)input.value=source.value;
        }
        section.querySelector('.io-status').textContent='';
      }
      for(const link of root.querySelectorAll('.periods a')){
        const target=new URL(link.href);for(const key of ['nic','disk'])target.searchParams.set(key,url.searchParams.get(key)||'');link.href=target;
      }
      history.replaceState(null,'',url.pathname+url.search);restore();
      scrollTo({left:x,top:y,behavior:'instant'});
    }catch(error){if(error.name!=='AbortError' && current===version)status().textContent='Не удалось обновить графики. Выберите устройство ещё раз.'}
    finally{if(current===version){pending=null;delete root.dataset.fetchBusy;root.querySelectorAll('.io-plots').forEach(n=>n.removeAttribute('aria-busy'))}}
  }
  document.addEventListener('change',event=>{const form=event.target.closest('.io-selector');if(form && event.target.matches('select'))update(form)});
  document.addEventListener('submit',event=>{if(event.target.matches('.io-selector')){event.preventDefault();update(event.target)}});
})();
