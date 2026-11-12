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
  let informationSequence=0;
  function information(root=document){
    for(const panel of root.querySelectorAll('.server-information')){
      const folds=[...panel.querySelectorAll('.section-fold')].filter(f=>f.closest('.server-information')===panel);
      if(!folds.length||panel.classList.contains('section-browser'))continue;
      panel.classList.add('section-browser');
      const nav=document.createElement('nav');nav.className='section-picker';nav.setAttribute('aria-label','Разделы информации о сервере');
      const requested=panel.closest('.server-detail') && new URLSearchParams(location.search).has('stability') ? folds.find(f=>f.querySelector(':scope>summary>.fold-title')?.textContent.trim()==='Доступность и агент') : null;
      const selected=folds.find(f=>f.open)||requested||folds[0];
      let currentFold=null;
      function choose(fold){
        const changed=currentFold&&currentFold!==fold;
        folds.forEach(item=>{const active=item===fold;item.open=active;item.querySelector(':scope>summary').setAttribute('aria-expanded',String(active));nav.querySelector(`[data-section-key="${item.dataset.foldKey}"]`).setAttribute('aria-pressed',String(active))});
        const button=nav.querySelector(`[data-section-key="${fold.dataset.foldKey}"]`);window.portalMotion?.indicator(nav,button,!currentFold);if(changed)window.portalMotion?.reveal(fold.querySelector(':scope>section'));currentFold=fold;
      }
      folds.forEach((fold,index)=>{
        const title=fold.querySelector(':scope>summary>.fold-title'),body=fold.querySelector(':scope>section');
        const label=title.cloneNode(true);label.querySelectorAll('.count,.section-icon').forEach(item=>item.remove());
        const name=label.textContent.trim(),button=document.createElement('button');
        button.type='button';button.dataset.sectionKey=fold.dataset.foldKey;button.title=name;button.setAttribute('aria-label',name);
        button.append(title.querySelector('.section-icon').cloneNode(true));
        const caption=document.createElement('span');caption.className='sr-only';caption.textContent=name;button.append(caption);
        body.id=`server-section-${++informationSequence}-${fold.dataset.foldKey}`;button.setAttribute('aria-controls',body.id);
        button.addEventListener('click',()=>window.portalMotion?window.portalMotion.preserve(()=>choose(fold)):choose(fold));
        button.addEventListener('keydown',event=>{if(!['ArrowDown','ArrowUp','Home','End'].includes(event.key))return;event.preventDefault();const buttons=[...nav.querySelectorAll('button')].filter(item=>!item.hidden);const current=buttons.indexOf(button);const next=event.key==='Home'?0:event.key==='End'?buttons.length-1:(current+(event.key==='ArrowDown'?1:-1)+buttons.length)%buttons.length;buttons[next].focus();buttons[next].click()});
        nav.append(button);
        const heading=document.createElement('h3');heading.className='section-browser-title';heading.innerHTML=title.innerHTML;body.prepend(heading);
      });
      panel.prepend(nav);choose(selected);
    }
  }
  window.initServerInformation=information;
  information();
  const detailRoot=document.querySelector('.server-detail'),collapseButton=document.getElementById('collapse-details');
  if(detailRoot && collapseButton){
    // The selected icon pane is navigation, not an expanded detail.
    const expandedDetails=()=>[...detailRoot.querySelectorAll('details[open]')].filter(detail=>!detail.matches('.section-browser .section-fold'));
    const syncCollapse=()=>{collapseButton.hidden=expandedDetails().length===0};
    collapseButton.addEventListener('click',()=>{expandedDetails().forEach(detail=>detail.open=false);syncCollapse()});
    detailRoot.addEventListener('toggle',syncCollapse,true);
    new MutationObserver(syncCollapse).observe(detailRoot,{subtree:true,childList:true,attributes:true,attributeFilter:['open']});
    syncCollapse();
  }
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
      if(current&&fresh){const states=new Map([...current.querySelectorAll('details[data-fold-key]')].map(d=>[d.dataset.foldKey,{open:d.open,wide:d.classList.contains('is-wide')}]));for(const d of fresh.querySelectorAll('details[data-fold-key]')){const state=states.get(d.dataset.foldKey);if(state){d.open=state.open;size(d,state.wide)}}current.innerHTML=fresh.innerHTML;information()}
    }catch(error){message.textContent=error.message}finally{if(live)delete live.dataset.fetchBusy;busy=false;buttons.forEach(b=>b.disabled=false)}
  });
})();
