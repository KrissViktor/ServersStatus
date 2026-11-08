(() => {
  const dialog=document.getElementById('rdp-action-dialog');if(!dialog)return;
  const form=dialog.querySelector('form'),message=document.getElementById('rdp-action-message'),submit=document.getElementById('rdp-action-submit');
  let selected=null,busy=false,polling=null;
  const titles={disconnect:'Отключить RDP',logoff:'Завершить RDP-сеанс',shadow:'Shadow RDP'};
  const descriptions={disconnect:'Пользователь будет отключён, программы продолжат работать. Он сможет подключиться снова.',logoff:'Все программы этого сеанса будут закрыты. Несохранённые данные могут быть потеряны. Учётная запись Windows останется.',shadow:'Скачайте .cmd и запустите на вашем Windows-компьютере (при необходимости — от администратора). Нужны сетевой доступ к этому серверу, права администратора и разрешённый Shadow RDP в политике Windows. Используются ваши административные учётные данные. Пароли портал не хранит; согласие пользователя запрашивается стандартными средствами Windows.'};
  document.addEventListener('click',event=>{
    const button=event.target.closest('[data-rdp-action]');if(!button || button.disabled)return;
    const row=button.closest('[data-rdp-target]');if(!row)return;
    clearTimeout(polling);selected={target:JSON.parse(row.dataset.rdpTarget),url:row.dataset.rdpUrl,csrf:row.dataset.rdpCsrf,host:row.dataset.rdpHost,action:button.dataset.rdpAction};
    form.reset();form.hidden=false;submit.disabled=false;message.textContent='';
    document.getElementById('rdp-action-title').textContent=titles[selected.action];
    const target=selected.target;
    document.getElementById('rdp-action-target').textContent=selected.host+' · '+(target.domain?target.domain+String.fromCharCode(92):'')+target.username+' · сеанс '+target.session_id;
    document.getElementById('rdp-action-description').textContent=descriptions[selected.action];
    document.getElementById('rdp-logoff-confirm').hidden=selected.action!=='logoff';form.elements.confirmation.required=selected.action==='logoff';
    document.getElementById('rdp-action-confirm').hidden=selected.action==='shadow';form.elements.confirm.required=selected.action!=='shadow';
    submit.textContent=selected.action==='shadow'?'Скачать команду подключения':titles[selected.action];dialog.showModal();
  });
  dialog.querySelector('[data-rdp-close]').addEventListener('click',()=>{if(!busy)dialog.close()});
  dialog.addEventListener('cancel',event=>{if(busy)event.preventDefault()});
  dialog.addEventListener('close',()=>{clearTimeout(polling);selected=null});
  async function poll(operation,id){
    if(!dialog.open || selected!==operation)return;
    try{
      const response=await fetch(operation.url+'/operations',{credentials:'same-origin',cache:'no-store'});
      if(response.status===403 || response.status===401){message.textContent='Доступ закрыт. Снимите защиту повторно.';return}
      if(!response.ok)throw new Error();
      const data=await response.json();if(selected!==operation || !dialog.open)return;
      const job=data.jobs.find(job=>job.id===id);
      if(job){
        message.textContent='Команда #'+id+' · '+job.label+(job.output?String.fromCharCode(10)+job.output:'');
        if(['succeeded','failed','expired','uncertain','reviewed','cancelled','timeout'].includes(job.status)){
          if(job.status==='succeeded')message.textContent+=String.fromCharCode(10)+'Проверьте следующий отчёт агента: успешный ответ означает, что Windows приняла действие.';
          if(job.status==='uncertain')message.textContent+=String.fromCharCode(10)+'Проверьте сеанс на сервере. Для повтора требуется подтверждение проверки результата.';
          return;
        }
      }
    }catch(_){if(selected===operation)message.textContent='Не удалось получить состояние. Повторим запрос.'}
    if(selected===operation && dialog.open)polling=setTimeout(()=>poll(operation,id),2000);
  }
  form.addEventListener('submit',async event=>{
    event.preventDefault();if(busy || !selected || !form.reportValidity())return;
    const operation=selected;
    if(operation.action==='logoff' && form.elements.confirmation.value!==operation.target.username){message.textContent='Введите точное имя пользователя: '+operation.target.username;return}
    busy=true;submit.disabled=true;message.textContent='Отправляем…';
    const payload={...operation.target,csrf:operation.csrf,action:operation.action,confirmation:form.elements.confirmation.value};
    try{
      const response=await fetch(operation.url+(operation.action==='shadow'?'/shadow':''),{method:'POST',credentials:'same-origin',headers:{'Content-Type':'application/json'},body:JSON.stringify(payload)});
      if(!response.ok){const error=await response.json();throw new Error(typeof error.detail==='string'?error.detail:'Не удалось выполнить действие')}
      if(operation.action==='shadow'){
        const url=URL.createObjectURL(await response.blob()),link=document.createElement('a');link.href=url;link.download='ServersStatus-Shadow-'+operation.target.session_id+'.cmd';document.body.append(link);link.click();link.remove();setTimeout(()=>URL.revokeObjectURL(url),30000);
        message.textContent='Команда скачана. Запустите файл на вашем Windows-компьютере. Если имя сервера недоступно из вашей сети, сначала подключитесь к сети сервера через VPN.';form.hidden=true;
      }else{
        const result=await response.json();form.hidden=true;message.textContent='Команда #'+result.id+' в очереди. Дождитесь ответа агента.';poll(operation,result.id);
      }
    }catch(error){message.textContent=error.message;submit.disabled=false}
    finally{busy=false}
  });
})();
