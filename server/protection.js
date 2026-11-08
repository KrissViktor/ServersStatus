(() => {
  const button=document.getElementById('protection-toggle'),dialog=document.getElementById('protection-dialog'),content=document.getElementById('protection-content');
  if (!button || !dialog)return;
  let state=null,busy=false,refreshing=null;
  function icon(open) {
    button.hidden=!open && button.dataset.protectionEntry!=='true';
    button.classList.toggle('is-unlocked',open);
    button.setAttribute('aria-label',open ? 'Защита снята' : 'Снять защиту');
    button.title=open ? 'Защита снята — управление доступом' : 'Снять защиту';
    button.querySelector('[data-lock-shackle]').setAttribute('d',open ? 'M7 10V7a5 5 0 0 1 9-3' : 'M7 10V7a5 5 0 0 1 10 0v3');
  }
  async function updatePage(open) {
    if (!open) {
      const panel=document.querySelector('[data-protected-pane]');
      if(panel){const wrapper=panel.closest('details.server-fold');if(wrapper)wrapper.remove();else panel.remove()}
      for(const script of document.querySelectorAll('[data-protected-script]'))script.remove();
    }
    if (!document.getElementById('server-live'))return;
    const response=await fetch(location.href,{cache:'no-store',credentials:'same-origin'});
    if(!response.ok)return;
    const next=new DOMParser().parseFromString(await response.text(),'text/html');
    const current=document.getElementById('server-live'),fresh=next.getElementById('server-live');
    if(current && fresh){
      const key=n=>n.dataset.foldKey || n.querySelector('summary')?.textContent;
      const expanded=new Map([...current.querySelectorAll('details')].map(n=>[key(n),{open:n.open,wide:n.classList.contains('is-wide')}]));
      for(const n of fresh.querySelectorAll('details'))if(expanded.has(key(n))){const state=expanded.get(key(n));n.open=state.open;window.setServerFoldSize?.(n,state.wide)}
      current.innerHTML=fresh.innerHTML;
    }
    if(open && !document.querySelector('[data-protected-pane]')) {
      const panel=next.querySelector('[data-protected-pane]'),script=next.querySelector('[data-protected-script]');
      const reference=document.querySelector('.task-manager')?.closest('details.server-fold') || document.querySelector('.process-panel')?.closest('details.server-fold') || current;
      if(panel && reference){
        const wrapper=panel.closest('details.server-fold') || panel;
        reference.after(wrapper);
        if(script){const execute=document.createElement('script');execute.dataset.protectedScript='';execute.textContent=script.textContent;wrapper.after(execute)}
      }
    }
  }
  async function sync() {
    if(refreshing)return refreshing;
    refreshing=(async()=>{
      try {
        const response=await fetch('/console-access/status',{cache:'no-store',credentials:'same-origin'});
        if(!response.ok)return;
        const result=await response.json(),open=!!result.unlocked;
        icon(open);
        const changed=state!==null && state!==open;state=open;
        if(changed)await updatePage(open);
      } catch(_){}
    })();
    try{await refreshing}finally{refreshing=null}
  }
  async function load() {
    content.textContent='Загрузка…';
    try {
      const response=await fetch('/console-access?modal=1',{cache:'no-store',credentials:'same-origin'});
      if(!response.ok || response.redirected)throw new Error();
      content.innerHTML=await response.text();content.querySelector('input[name=code]')?.focus();
    } catch(_){content.textContent='Не удалось открыть проверку. Проверьте вход на портал.'}
  }
  button.addEventListener('click',()=>{dialog.showModal();load()});
  document.getElementById('protection-close').addEventListener('click',()=>{if(!busy)dialog.close()});
  dialog.addEventListener('click',event=>{const box=dialog.getBoundingClientRect();if(event.target===dialog && !busy && (event.clientX<box.left || event.clientX>box.right || event.clientY<box.top || event.clientY>box.bottom))dialog.close()});
  dialog.addEventListener('cancel',event=>{if(busy)event.preventDefault()});
  content.addEventListener('submit',async event=>{
    const form=event.target;if(!form.matches('form'))return;event.preventDefault();
    if(busy || !form.reportValidity())return;
    busy=true;const submit=form.querySelector('button');submit.disabled=true;submit.textContent='Проверяем…';
    try {
      const response=await fetch(new URL(form.action).pathname+'?modal=1',{method:'POST',credentials:'same-origin',headers:{'Content-Type':'application/x-www-form-urlencoded'},body:new URLSearchParams(new FormData(form))});
      const html=await response.text();
      if(response.status!==200 && response.status!==400)throw new Error();
      content.innerHTML=html;content.querySelector('input[name=code]')?.focus();
      await sync();
      if(response.ok && !content.querySelector('form') && !state)await sync();
      if(response.ok && (new URL(form.action).pathname.endsWith('/lock') || (state && !content.querySelector('form'))))dialog.close();
    } catch(_){content.textContent='Не удалось завершить проверку. Закройте окно и попробуйте ещё раз.'}
    finally{busy=false;}
  });
  sync();setInterval(()=>{if(!document.hidden)sync()},5000);
})();
