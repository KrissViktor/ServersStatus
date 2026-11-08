(() => {
  if(window.serverFoldsInstalled)return;window.serverFoldsInstalled=true;
  function size(fold,wide){
    fold.classList.toggle('is-wide',wide);
    const button=fold.querySelector(':scope>summary>.fold-size');if(!button)return;
    button.setAttribute('aria-pressed',String(wide));button.title=wide?'Вернуть ширину колонки':'Развернуть блок на всю ширину';button.querySelector('span').textContent=wide?'Сузить':'Расширить';
  }
  window.setServerFoldSize=size;
  document.addEventListener('click',event=>{
    const button=event.target.closest('.fold-size');if(!button)return;
    event.preventDefault();event.stopPropagation();const fold=button.closest('details');fold.open=true;size(fold,!fold.classList.contains('is-wide'));
  });
  const heading=document.querySelector('.panel-name-heading'),trigger=heading?.querySelector('.panel-name-trigger'),form=heading?.querySelector('.panel-name-form');
  if(!trigger||!form)return;
  const input=form.elements.display_name,message=heading.querySelector('.panel-name-message');let saved=input.value,busy=false;
  function edit(){if(busy)return;form.hidden=false;trigger.hidden=true;message.textContent='';input.focus({preventScroll:true});input.select()}
  function cancel(){if(busy)return;input.value=saved;form.hidden=true;trigger.hidden=false;message.textContent='';trigger.focus({preventScroll:true})}
  trigger.addEventListener('dblclick',edit);trigger.addEventListener('keydown',event=>{if(event.key==='Enter'||event.key==='F2'){event.preventDefault();edit()}});
  form.querySelector('[data-name-cancel]').addEventListener('click',cancel);input.addEventListener('keydown',event=>{if(event.key==='Escape'){event.preventDefault();cancel()}});
  form.addEventListener('submit',async event=>{
    event.preventDefault();if(busy||!form.reportValidity())return;busy=true;message.textContent='Сохранение…';
    const live=document.getElementById('server-live');if(live)live.dataset.fetchBusy='true';
    const buttons=[...form.querySelectorAll('button')];buttons.forEach(b=>b.disabled=true);
    try{
      const response=await fetch(form.action,{method:'POST',credentials:'same-origin',headers:{'Content-Type':'application/x-www-form-urlencoded'},body:new URLSearchParams(new FormData(form))});
      if(!response.ok)throw Error('Не удалось сохранить название');
      const next=new DOMParser().parseFromString(await response.text(),'text/html'),name=next.querySelector('.panel-name-value');if(!name)throw Error('Не удалось подтвердить новое название');
      trigger.querySelector('.panel-name-value').textContent=name.textContent;saved=input.value.trim();input.value=saved;form.hidden=true;trigger.hidden=false;message.textContent='Название сохранено';
      const current=document.getElementById('server-live'),fresh=next.getElementById('server-live');
      if(current&&fresh){const states=new Map([...current.querySelectorAll('details[data-fold-key]')].map(d=>[d.dataset.foldKey,{open:d.open,wide:d.classList.contains('is-wide')}]));for(const d of fresh.querySelectorAll('details[data-fold-key]')){const state=states.get(d.dataset.foldKey);if(state){d.open=state.open;size(d,state.wide)}}current.innerHTML=fresh.innerHTML}
    }catch(error){message.textContent=error.message}finally{if(live)delete live.dataset.fetchBusy;busy=false;buttons.forEach(b=>b.disabled=false)}
  });
})();
