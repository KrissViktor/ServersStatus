(() => {
  const panel=document.getElementById('remote-console');
  if (!panel?.dataset.url) return;
  const form=document.getElementById('console-form'), history=document.getElementById('console-history'), message=document.getElementById('console-message');
  if (!history) return;
  const review=document.getElementById('console-review'), inputForm=document.getElementById('console-input-form');
  const clearButton=document.getElementById('console-clear'),archiveButton=document.getElementById('console-archive'),moreButton=document.getElementById('console-more'),scope=document.getElementById('console-scope');
  let archive=false, extraJobs=[], nextCursor=null, lastJobs=[], clearBefore=Number(sessionStorage.getItem('console-clear:'+panel.dataset.agent) || 0);
  let runningId=null, sendingInput=false;
  let busy=false, fetching=false, snapshot='', submitted=null, refreshDelay=5000, timer=null;
  const node=(tag,text)=>{const n=document.createElement(tag);n.textContent=text;return n};
  async function refresh() {
    if (busy || fetching || document.hidden) return;
    fetching=true;
    try {
      const response=await fetch(panel.dataset.url+'?archive='+archive,{cache:'no-store',credentials:'same-origin'});
      if (response.status===401 || response.status===403) {clearTimeout(timer);panel.closest('details.server-fold')?.remove();panel.remove();return;}
      if (!response.ok) throw new Error();
      const result=await response.json();
      refreshDelay=result.jobs.some(job=>['queued','running'].includes(job.status)) ? 1000 : 5000;
      runningId=result.jobs.find(job=>job.status==='running')?.id || null;
      if (inputForm)inputForm.hidden=!runningId || !result.info.interactive_input;
      if (form) {
        const active=result.jobs.some(job=>['queued','running','uncertain'].includes(job.status));
        form.querySelector('button[type=submit]').disabled=active || !result.online || !result.info.enabled;
        review.hidden=!result.jobs.some(job=>job.status==='uncertain');
      }
      const current=result.jobs.find(job=>job.id===submitted);
      if (current) message.textContent='Команда #'+current.id+': '+current.label+'.';
      if (!extraJobs.length)nextCursor=result.next;
      const seen=new Set(result.jobs.map(job=>job.id));
      lastJobs=[...result.jobs,...extraJobs.filter(job=>!seen.has(job.id) && job.created>=result.cutoff)].sort((a,b)=>b.id-a.id);
      const visibleJobs=lastJobs.filter(job=>archive || job.id>clearBefore || ['queued','running','uncertain'].includes(job.status));
      if(moreButton)moreButton.hidden=!nextCursor;
      const serialized=JSON.stringify(visibleJobs);
      if (serialized===snapshot) return;
      snapshot=serialized;
      const fragment=document.createDocumentFragment(), positions=new Map();
      for (const item of history.querySelectorAll('details')) {
        const pre=item.querySelector('[data-console-output]');
        if (pre)positions.set(item.dataset.jobId,{top:pre.scrollTop,follow:pre.scrollHeight-pre.clientHeight-pre.scrollTop<24});
      }
      for (const job of visibleJobs) {
        const item=document.createElement('details');item.dataset.jobId=job.id;
        const old=[...history.querySelectorAll('details')].find(n=>n.dataset.jobId===String(job.id));
        item.open=old ? old.open : job===visibleJobs[0];
        const date=new Date(job.created*1000).toLocaleString('ru-RU',{timeZone:'Europe/Moscow'});
        item.append(node('summary','#'+job.id+' · '+date+' МСК · '+job.label));
        item.append(node('pre',job.command));
        const output=node('pre',job.result.output || (job.status==='queued' ? 'Ожидаем агента…' : job.status==='running' ? 'Команда выполняется, ожидаем вывод…' : 'Вывод отсутствует'));
        output.dataset.consoleOutput=job.id;
        output.style.cssText='white-space:pre-wrap;overflow:auto;max-height:400px;background:#080808;padding:14px;border-radius:8px';
        item.append(output);
        if (job.result.exit_code!==null && job.result.exit_code!==undefined)item.append(node('p','Код завершения: '+job.result.exit_code));
        if (job.result.truncated)item.append(node('p','Вывод сокращён до 16 Кб.'));
        fragment.append(item);
      }
      history.replaceChildren(fragment);
      for (const pre of history.querySelectorAll('[data-console-output]')) {
        const saved=positions.get(pre.dataset.consoleOutput);
        pre.scrollTop=!saved || saved.follow ? pre.scrollHeight : saved.top;
      }
    } catch (_) {message.textContent='Не удалось обновить историю консоли. Повторим запрос.';}
    finally {fetching=false;}
  }
  async function submit(isReview=false) {
    if (busy || (!isReview && !form.reportValidity()))return;
    if (isReview && !form.elements.confirmation.checked) {message.textContent='Подтвердите целевой сервер.';return;}
    busy=true;message.textContent='Отправляем…';
    try {
      const fields=new FormData(form);
      const response=await fetch(panel.dataset.url,{method:'POST',credentials:'same-origin',headers:{'Content-Type':'application/json'},body:JSON.stringify({csrf:fields.get('csrf'),command:isReview ? 'review' : fields.get('command'),confirmation:fields.get('confirmation') ? panel.dataset.agent : '',timeout:Number(fields.get('timeout')),review:isReview})});
      const result=await response.json();
      if (!response.ok)throw new Error(typeof result.detail==='string' ? result.detail : 'Команда не принята');
      if (!isReview) submitted=result.id;
      message.textContent=isReview ? 'Результат отмечен как проверенный.' : 'Команда #'+result.id+' в очереди. Ожидаем агента.';
    } catch(error) {message.textContent=error.message;}
    finally {busy=false;poll();}
  }
  clearButton?.addEventListener('click',()=>{
    clearBefore=Math.max(clearBefore,...lastJobs.filter(job=>!['queued','running','uncertain'].includes(job.status)).map(job=>job.id));
    sessionStorage.setItem('console-clear:'+panel.dataset.agent,String(clearBefore));
    archive=false;extraJobs=[];nextCursor=null;snapshot='';history.replaceChildren();
    archiveButton.textContent='Показать всю историю';scope.textContent='История за последний час · завершённые записи скрыты визуально';poll();
  });
  archiveButton?.addEventListener('click',()=>{
    archive=!archive;extraJobs=[];nextCursor=null;snapshot='';
    archiveButton.textContent=archive ? 'Вернуться к последнему часу' : 'Показать всю историю';
    scope.textContent=archive ? 'Вся история за последние 6 месяцев' : 'История за последний час';poll();
  });
  moreButton?.addEventListener('click',async()=>{
    if(!nextCursor || fetching)return;
    fetching=true;
    try {
      const response=await fetch(panel.dataset.url+'?archive='+archive+'&before='+nextCursor,{cache:'no-store',credentials:'same-origin'});
      if(!response.ok)throw new Error();
      const result=await response.json();extraJobs=[...new Map([...lastJobs,...extraJobs,...result.jobs].map(job=>[job.id,job])).values()];nextCursor=result.next;snapshot='';
    } catch(_){message.textContent='Не удалось загрузить историю.'}
    finally{fetching=false;poll();}
  });
  async function sendControl(action) {
    if (!runningId || sendingInput)return;
    sendingInput=true;
    try {
      const response=await fetch(panel.dataset.url+'/'+runningId+'/control',{method:'POST',credentials:'same-origin',headers:{'Content-Type':'application/json'},body:JSON.stringify({csrf:form.elements.csrf.value,confirmation:panel.dataset.agent,action,text:action==='stdin' ? inputForm.elements.stdin.value : ''})});
      const result=await response.json();
      if (!response.ok)throw new Error(typeof result.detail==='string' ? result.detail : 'Не удалось передать ответ');
      if (action==='stdin')inputForm.elements.stdin.value='';
      message.textContent=action==='cancel' ? 'Запрошена остановка команды.' : action==='eof' ? 'Отправлен конец ввода.' : 'Ответ отправлен агенту.';
    } catch(error) {message.textContent=error.message;}
    finally {sendingInput=false;poll();}
  }
  inputForm?.addEventListener('submit',event=>{event.preventDefault();sendControl('stdin')});
  inputForm?.querySelector('[data-console-eof]').addEventListener('click',()=>sendControl('eof'));
  inputForm?.querySelector('[data-console-cancel]').addEventListener('click',()=>sendControl('cancel'));
  form?.addEventListener('submit',event=>{event.preventDefault();submit()});
  review?.addEventListener('click',()=>submit(true));
  async function poll(){clearTimeout(timer);await refresh();clearTimeout(timer);if(panel.isConnected)timer=setTimeout(poll,refreshDelay)}
  poll();
})();
