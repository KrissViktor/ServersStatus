(() => {
  const path=location.pathname;
  document.addEventListener('change',event=>{
    const select=event.target.closest('select[data-auto-group]');const form=select?.form;
    if(!form||form.method.toLowerCase()!=='get')return;
    if(!form.reportValidity())return;
    if(form.id==='compare-filter')for(const input of form.querySelectorAll('input[name=agents]'))input.disabled=true;
    form.setAttribute('aria-busy','true');
    if(form.requestSubmit)form.requestSubmit();else form.submit();
  });

  window.addEventListener('pageshow',()=>document.querySelectorAll('select[data-auto-group]').forEach(select=>select.form?.removeAttribute('aria-busy')));
  const areas={groups:['/groups'],compare:['/compare','/daily','/history/','/heatmap','/dependencies','/timeline/'],problems:['/events','/problems','/timeline/'],updates:['/updates'],admin:['/admin','/agents','/settings/','/checks/','/users','/host','/portal-health','/portal-settings','/bot','/ai','/windows/','/console-access']};
  let active=path==='/wallboard'?'/wallboard':'/';
  for(const [area,paths] of Object.entries(areas))if(paths.some(prefix=>prefix.endsWith('/')?path.startsWith(prefix):path===prefix))active='/'+area;
  document.querySelectorAll('[data-primary-page]').forEach(link=>{if(link.dataset.primaryPage===active)link.setAttribute('aria-current','page')});
  const crumbs=document.querySelector('.portal-breadcrumbs');
  if(crumbs&&path!=='/'){
    const addLink=(label,href)=>{const link=document.createElement('a');link.href=href;link.textContent=label;crumbs.append(link)};
    addLink('Серверы','/?reset=1');
    const context=path.match(/^\/(servers|settings|checks|history|windows|timeline)\/([^/]+)$/);
    let title=document.querySelector('h1')?.textContent||'Текущая страница';
    if(context){
      const names={servers:'Обзор',settings:'Настройки мониторинга',checks:'Проверки приложений',history:'История нагрузки',windows:'Сведения Windows',timeline:'Лента событий'};
      let name=document.querySelector('.panel-name-value')?.textContent||title.replace(/^(Проверки приложений|Лента)\s*·\s*/, '');
      if(context[1]==='windows')name=document.querySelector('h2')?.textContent||context[2];
      crumbs.append(document.createTextNode(' / '));addLink(name,'/servers/'+context[2]);title=names[context[1]];
    }else{
      const section=document.querySelector('[data-primary-page="'+active+'"]');
      if(section&&active!=='/'&&path!==active){crumbs.append(document.createTextNode(' / '));addLink(section.textContent,section.getAttribute('href'))}
    }
    const current=document.createElement('span');current.setAttribute('aria-current','page');current.textContent=title;crumbs.append(document.createTextNode(' / '),current);crumbs.hidden=false;
  }
  for(const form of document.querySelectorAll('[data-check-editor]')){
    const slots=[...form.querySelectorAll('[data-check-slot]')];
    function fields(slot){
      const kind=slot.querySelector('select').value;
      const target=slot.querySelector('input[name^=target_]');target.placeholder=kind==='http'?'https://server.example/health':'Имя сервера или IP';
      const port=slot.querySelector('input[name^=port_]');port.type='number';port.min='1';port.max='65535';port.required=kind!=='http';
      for(const label of slot.querySelectorAll('[data-check-field]'))label.hidden=!({port:['tcp','sql'],contains:['http'],database:['sql']}[label.dataset.checkField].includes(kind));
      for(const input of slot.querySelectorAll('input,select'))input.disabled=slot.hidden||!!input.closest('[hidden]');
    }
    function update(){slots.forEach(fields);form.querySelector('[data-add-check]').disabled=slots.every(slot=>!slot.hidden);form.querySelector('[data-check-empty]').hidden=slots.some(slot=>!slot.hidden)}
    form.addEventListener('change',()=>update());
    form.addEventListener('click',event=>{
      if(event.target.closest('[data-add-check]')){const slot=slots.find(slot=>slot.hidden);if(slot){slot.hidden=false;update();slot.querySelector('input').focus();form.dispatchEvent(new Event('formchange'))}}
      if(event.target.closest('[data-remove-check]')){const slot=event.target.closest('[data-check-slot]');slot.hidden=true;for(const input of slot.querySelectorAll('input'))input.value='';update();form.dispatchEvent(new Event('formchange'))}
    });update();
  }
  const dirty=new Set();
  for(const form of document.querySelectorAll('[data-dirty-form]')){
    const state=form.querySelector('[data-form-state]');const initial=new URLSearchParams(new FormData(form)).toString();
    const update=()=>{const changed=new URLSearchParams(new FormData(form)).toString()!==initial;form.classList.toggle('has-changes',changed);changed?dirty.add(form):dirty.delete(form);state.textContent=changed?'Есть несохранённые изменения':'Изменений нет'};
    form.addEventListener('input',update);form.addEventListener('change',update);form.addEventListener('formchange',update);
    form.addEventListener('submit',async event=>{
      event.preventDefault();if(!form.reportValidity())return;
      const data=new FormData(form);if(event.submitter?.name)data.append(event.submitter.name,event.submitter.value);
      const button=event.submitter;if(button)button.disabled=true;state.textContent='Сохраняем…';form.dataset.saving='true';
      try{
        const response=await fetch(form.action||location.href,{method:'POST',body:new URLSearchParams(data),credentials:'same-origin'});
        if(!response.ok){let message='Не удалось сохранить. Проверьте поля и повторите.';try{const value=await response.json();if(typeof value.detail==='string')message=value.detail}catch(_){}state.textContent=message;return}
        dirty.delete(form);location.assign(response.url);
      }catch(_){state.textContent='Нет связи с порталом. Введённые данные сохранены в форме.'}
      finally{if(button)button.disabled=false;delete form.dataset.saving}
    });
  }
  window.addEventListener('beforeunload',event=>{if(dirty.size){event.preventDefault();event.returnValue=''}});
})();
