(() => {
  const panel=document.getElementById('remote-console');
  if (!panel?.dataset.url) return;
  const form=document.getElementById('console-form'), history=document.getElementById('console-history'), message=document.getElementById('console-message');
  if (!history) return;
  const review=document.getElementById('console-review');
  let busy=false, snapshot='', submitted=null;
  const node=(tag,text)=>{const n=document.createElement(tag);n.textContent=text;return n};
  async function refresh() {
    if (busy || document.hidden) return;
    try {
      const response=await fetch(panel.dataset.url,{cache:'no-store',credentials:'same-origin'});
      if (!response.ok) throw new Error();
      const result=await response.json();
      if (form) {
        const active=result.jobs.some(job=>['queued','running','uncertain'].includes(job.status));
        form.querySelector('button[type=submit]').disabled=active || !result.online || !result.info.enabled;
        review.hidden=!result.jobs.some(job=>job.status==='uncertain');
      }
      const current=result.jobs.find(job=>job.id===submitted);
      if (current) message.textContent='Команда #'+current.id+': '+current.label+'.';
      const serialized=JSON.stringify(result.jobs);
      if (serialized===snapshot) return;
      snapshot=serialized;
      const fragment=document.createDocumentFragment();
      for (const job of result.jobs) {
        const item=document.createElement('details');item.dataset.jobId=job.id;
        const old=[...history.querySelectorAll('details')].find(n=>n.dataset.jobId===String(job.id));
        item.open=old ? old.open : job===result.jobs[0];
        const date=new Date(job.created*1000).toLocaleString('ru-RU',{timeZone:'Europe/Moscow'});
        item.append(node('summary','#'+job.id+' · '+date+' МСК · '+job.label));
        item.append(node('pre',job.command));
        const output=node('pre',job.result.output || (job.status==='queued' ? 'Ожидаем агента…' : 'Вывод отсутствует'));
        output.style.cssText='white-space:pre-wrap;overflow:auto;max-height:400px;background:#080808;padding:14px;border-radius:8px';
        item.append(output);
        if (job.result.exit_code!==null && job.result.exit_code!==undefined)item.append(node('p','Код завершения: '+job.result.exit_code));
        if (job.result.truncated)item.append(node('p','Вывод сокращён до 16 Кб.'));
        fragment.append(item);
      }
      history.replaceChildren(fragment);
    } catch (_) {message.textContent='Не удалось обновить историю консоли. Повторим запрос.';}
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
    finally {busy=false;refresh();}
  }
  form?.addEventListener('submit',event=>{event.preventDefault();submit()});
  review?.addEventListener('click',()=>submit(true));
  refresh();setInterval(refresh,5000);
})();
