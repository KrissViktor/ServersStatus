(() => {
  if (!document.querySelector('[data-updates-root]'))return;
  let busy=false;
  const search=document.querySelector('[data-update-search]');
  function filter(){const query=(search?.value||'').trim().toLocaleLowerCase('ru');for(const card of document.querySelectorAll('[data-update-card]'))card.hidden=!card.querySelector('[data-update-brief]').textContent.toLocaleLowerCase('ru').includes(query)}
  search?.addEventListener('input',filter);
  const bulk=document.querySelector('[data-bulk-update]');
  bulk?.addEventListener('submit',()=>{
    bulk.querySelector('button').disabled=true;
    bulk.querySelector('[data-bulk-progress]').hidden=false;
  });
  for (const history of document.querySelectorAll('[data-update-history]')) {
    const deactivate=()=>{history.classList.remove('scroll-active');history.style.overflowY='hidden';history.style.overscrollBehaviorY='auto'};
    history.addEventListener('click',()=>{history.focus({preventScroll:true});history.classList.add('scroll-active');history.style.overflowY='auto';history.style.overscrollBehaviorY='contain'});
    history.addEventListener('focusin',()=>{history.classList.add('scroll-active');history.style.overflowY='auto';history.style.overscrollBehaviorY='contain'});
    history.addEventListener('focusout',event=>{if(!history.contains(event.relatedTarget))deactivate()});
    history.addEventListener('pointerleave',()=>{if(history.contains(document.activeElement))document.activeElement.blur();deactivate()});
    history.addEventListener('wheel',event=>{
      if (!history.classList.contains('scroll-active')) {
        event.preventDefault();window.scrollBy({left:event.deltaX,top:event.deltaY,behavior:'instant'});
      }
    },{passive:false});
  }
  setInterval(async()=>{
    if (busy || document.hidden)return;
    busy=true;
    try {
      const response=await fetch('/updates',{credentials:'same-origin',cache:'no-store'});
      if (!response.ok)return;
      const next=new DOMParser().parseFromString(await response.text(),'text/html');
      for (const card of document.querySelectorAll('[data-update-card]')) {
        const source=[...next.querySelectorAll('[data-update-card]')].find(n=>n.dataset.updateCard===card.dataset.updateCard);
        if (!source)continue;
        card.dataset.updatePriority=source.dataset.updatePriority;
        const brief=card.querySelector('[data-update-brief]'),freshBrief=source.querySelector('[data-update-brief]');if(brief&&freshBrief&&brief.innerHTML!==freshBrief.innerHTML)brief.innerHTML=freshBrief.innerHTML;
        const summary=card.querySelector('[data-update-summary]'),fresh=source.querySelector('[data-update-summary]');
        const changedVersion=summary.querySelector('[data-running-version]')?.dataset.runningVersion!==fresh.querySelector('[data-running-version]')?.dataset.runningVersion;
        if (summary.innerHTML!==fresh.innerHTML)summary.innerHTML=fresh.innerHTML;
        if (changedVersion && card.querySelector('input[type=checkbox]'))card.querySelector('input[type=checkbox]').checked=false;
        const oldSelect=card.querySelector('select'),newSelect=source.querySelector('select');
        if (oldSelect && newSelect) {
          const value=oldSelect.value;
          if (oldSelect.innerHTML!==newSelect.innerHTML)oldSelect.innerHTML=newSelect.innerHTML;
          if ([...oldSelect.options].some(n=>n.value===value))oldSelect.value=value;
          oldSelect.disabled=newSelect.disabled;
          card.querySelector('form[data-update-form] button').disabled=source.querySelector('form[data-update-form] button').disabled;
        }
        const cancel=card.querySelector('[data-update-cancel]'),freshCancel=source.querySelector('[data-update-cancel]');
        if(cancel && freshCancel && cancel.innerHTML!==freshCancel.innerHTML)cancel.innerHTML=freshCancel.innerHTML;
        const history=card.querySelector('[data-update-history]'),freshHistory=source.querySelector('[data-update-history]');
        const opened=new Map([...history.querySelectorAll('details')].map(n=>[n.dataset.updateJob,n.open]));
        for (const detail of freshHistory.querySelectorAll('details'))if(opened.has(detail.dataset.updateJob))detail.open=opened.get(detail.dataset.updateJob);
        if (history.innerHTML!==freshHistory.innerHTML) {
          const top=history.scrollTop, focused=history.contains(document.activeElement);
          history.innerHTML=freshHistory.innerHTML;history.scrollTop=top;
          if(focused)history.focus({preventScroll:true});
        }
      }
      const root=document.querySelector('[data-updates-root]');if(!root.contains(document.activeElement)){const sorted=[...root.children].sort((a,b)=>Number(a.dataset.updatePriority)-Number(b.dataset.updatePriority));for(let i=0;i<sorted.length;i++)if(root.children[i]!==sorted[i])root.insertBefore(sorted[i],root.children[i]);}filter();
    } catch (_) {} finally {busy=false;}
  },10000);
})();
