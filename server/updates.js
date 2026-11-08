(() => {
  if (!document.querySelector('[data-updates-root]'))return;
  let busy=false;
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
        const history=card.querySelector('[data-update-history]'),freshHistory=source.querySelector('[data-update-history]');
        const opened=new Map([...history.querySelectorAll('details')].map(n=>[n.dataset.updateJob,n.open]));
        for (const detail of freshHistory.querySelectorAll('details'))if(opened.has(detail.dataset.updateJob))detail.open=opened.get(detail.dataset.updateJob);
        if (history.innerHTML!==freshHistory.innerHTML) {
          const top=history.scrollTop;history.innerHTML=freshHistory.innerHTML;history.scrollTop=top;
        }
      }
    } catch (_) {} finally {busy=false;}
  },10000);
})();
