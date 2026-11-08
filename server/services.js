(() => {
  const panel=document.querySelector('.all-services-panel');if(!panel)return;
  const body=panel.querySelector('.services-rows'),info=panel.querySelector('.services-info'),search=panel.querySelector('.services-search'),filter=panel.querySelector('.services-filter'),expand=panel.querySelector('.services-expand');
  let entries=[],inventory=null,received=null,capable=false,expanded=false,busy=false,signature='',visibleCount=0,filteredCount=0;
  const labels={running:'🟢 Работает',stopped:'🔴 Остановлена',paused:'🟡 На паузе',failed:'🔴 Ошибка',start_pending:'🟠 Запускается',stop_pending:'🟠 Останавливается',pause_pending:'🟠 Переход на паузу',continue_pending:'🟠 Возобновляется',reloading:'🟠 Перезагружается',unavailable:'⚪ Недоступна'};
  const titles={service_type:'Тип Windows-службы',config_start_type:'Код типа запуска',error_control:'Обработка ошибок',config_binary_path:'Путь из конфигурации',load_order_group:'Группа загрузки',tag_id:'Тег загрузки',dependencies:'Зависимости',config_account:'Учётная запись из конфигурации',config_display_name:'Имя из конфигурации',binpath:'Команда запуска',description:'Описание',username:'Учётная запись',start_type:'Тип запуска',pid:'PID',Id:'Имя',Names:'Имена',LoadState:'Загрузка unit',ActiveState:'Состояние',SubState:'Подсостояние',UnitFileState:'Автозапуск',UnitFilePreset:'Политика автозапуска',Type:'Тип',MainPID:'Основной PID',ControlPID:'Управляющий PID',User:'Пользователь',Group:'Группа',DynamicUser:'Динамическая учётная запись',ExecStart:'Команда запуска',ExecStop:'Команда остановки',FragmentPath:'Файл службы',DropInPaths:'Дополнительные настройки',WorkingDirectory:'Рабочая папка',Restart:'Правило перезапуска',NRestarts:'Число перезапусков',Result:'Последний результат',ExecMainCode:'Код завершения процесса',ExecMainStatus:'Статус завершения',ActiveEnterTimestamp:'Последний переход в активное состояние',InactiveEnterTimestamp:'Последняя остановка',ExecMainStartTimestamp:'Последний запуск процесса',ExecMainExitTimestamp:'Последний выход процесса',StateChangeTimestamp:'Изменение состояния',MemoryCurrent:'Память сейчас',MemoryMax:'Ограничение памяти',CPUUsageNSec:'CPU: всего наносекунд',TasksCurrent:'Число задач',ControlGroup:'Контрольная группа',Requires:'Зависимости',Wants:'Желательные зависимости',After:'Порядок запуска',FreezerState:'Заморозка',error:'Ошибка чтения'};
  const node=(tag,text)=>{const n=document.createElement(tag);if(text!=null)n.textContent=text;return n};
  const startType=v=>({automatic:'Автоматически',manual:'Вручную',disabled:'Выключен',enabled:'Включён','enabled-runtime':'Включён до перезагрузки',static:'Статическая',masked:'Заблокирован',alias:'Псевдоним',generated:'Сгенерирован',transient:'Временная',indirect:'Косвенно'}[v]||v||'—');
  function render(){
    const q=search.value.trim().toLocaleLowerCase('ru');
    const found=entries.filter(s=>{
      const state=filter.value,match=state==='all'||(state==='other'?!['running','stopped','paused','failed'].includes(s.status):s.status===state);
      return match && (!q || [s.name,s.display_name,...Object.values(s.details||{})].join(' ').toLocaleLowerCase('ru').includes(q));
    }).sort((a,b)=>a.name.localeCompare(b.name,'ru',{numeric:true,sensitivity:'base'}));
    const selected=expanded?found:found.slice(0,20),open=new Set([...body.querySelectorAll('details[open]')].map(n=>n.dataset.service));
    const fragment=document.createDocumentFragment();
    for(const s of selected){
      const tr=node('tr'),name=node('td');name.append(node('b',s.name),node('p',s.display_name||s.name));tr.append(name,node('td',labels[s.status]||('⚪ '+s.status)));
      const d=s.details||{};tr.append(node('td',d.MainPID||d.pid||'—'),node('td',startType(d.UnitFileState||d.start_type)),node('td',d.User||d.username||(inventory?.platform==='linux'?(d.DynamicUser==='yes'?'Динамический пользователь':'root (по умолчанию)'):'—')));
      const td=node('td'),details=node('details');details.dataset.service=s.name;details.open=open.has(s.name);details.append(node('summary','Сведения'));
      const list=node('dl');for(const [key,value] of Object.entries(d)){list.append(node('dt',titles[key]||key),node('dd',value||'—'))}
      if(!Object.keys(d).length)list.append(node('dd','Дополнительные данные недоступны'));
      details.append(list);td.append(details);tr.append(td);fragment.append(tr);
    }
    const container=panel.querySelector('.services-table'),top=container.scrollTop;body.replaceChildren(fragment);container.scrollTop=top;
    expand.disabled=found.length<=20;expand.textContent=expanded?'Свернуть до 20':'Показать все ('+found.length+')';expand.setAttribute('aria-expanded',String(expanded));
    visibleCount=selected.length;filteredCount=found.length;renderInfo();
    if(inventory?.status==='available' && !selected.length){const tr=node('tr'),td=node('td','Нет служб по выбранным условиям');td.colSpan=6;tr.append(td);body.append(tr)}
  }
  function renderInfo(){
    if(!inventory)info.textContent=capable?'Агент поддерживает список служб, но ещё не передал его. Дождитесь минуты; затем проверьте журнал агента и приём /api/processes/ в reverse proxy.':'Полный список служб ещё не получен. Обновите агент для этой возможности.';
    else if(inventory.status!=='available')info.textContent='⚪ Агент не смог прочитать службы. Проверьте systemd/права службы агента.';
    else{
      const age=Math.max(0,Math.floor(Date.now()/1000-received));
      info.textContent='Показано '+visibleCount+' из '+filteredCount+' · Всего служб: '+inventory.total+' · Данные '+age+' с назад'+(age>180?' · Данные устарели':'')+(inventory.unreadable?' · Недоступны сведения: '+inventory.unreadable:'')+(inventory.truncated?' · Исходный список сокращён или прочитан частично':'');
    }
  }
  async function load(){
    const fold=panel.closest('details.server-fold');if(busy||document.hidden||body.contains(document.activeElement)||(fold&&!fold.open))return;
    busy=true;
    try{const response=await fetch(panel.dataset.servicesUrl,{credentials:'same-origin',cache:'no-store'});if(!response.ok)throw new Error();const data=await response.json();const next=JSON.stringify(data);inventory=data.inventory;received=data.received;capable=!!data.capable;
      if(signature!==next){signature=next;entries=inventory?.items||[];render()}else renderInfo();
    }catch(_){info.textContent='Не удалось обновить список служб. Повторим запрос.'}finally{busy=false}
  }
  search.addEventListener('input',render);filter.addEventListener('change',render);expand.addEventListener('click',()=>{expanded=!expanded;render()});
  document.addEventListener('toggle',event=>{if(event.target===panel.closest('details.server-fold')&&event.target.open)load()},true);
  render();load();setInterval(load,10000);
})();
