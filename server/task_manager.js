(() => {
  if(window.initTaskManagers){window.initTaskManagers(document);return;}
  const text=v=>v===null||v===undefined||v===''?'—':String(v);
  const node=(tag,value)=>{const n=document.createElement(tag);if(value!=null)n.textContent=value;return n};
  const bytes=v=>{if(v==null)return '—';const units=['Б','Кб','Мб','Гб','Тб'];let i=0;while(v>=1024&&i<4){v/=1024;i++}return v.toLocaleString('ru-RU',{maximumFractionDigits:2})+' '+units[i]};
  const states={running:'🟢 Работает',sleeping:'Ожидает',idle:'Ожидает',disk_sleep:'Ожидает диск',stopped:'🔴 Остановлена',paused:'🟡 На паузе',failed:'🔴 Ошибка',zombie:'Зомби',dead:'Завершён',start_pending:'🟠 Запускается',stop_pending:'🟠 Останавливается',pause_pending:'🟠 Переход на паузу',continue_pending:'🟠 Возобновляется',reloading:'🟠 Перезагружается',unavailable:'⚪ Недоступна'};
  const start=v=>({automatic:'Автоматически',manual:'Вручную',disabled:'Выключен',enabled:'Включён','enabled-runtime':'Включён до перезагрузки',static:'Статическая',masked:'Заблокирован',alias:'Псевдоним',generated:'Сгенерирован',transient:'Временная',indirect:'Косвенно'}[v]||text(v));
  const titles={service_type:'Тип Windows-службы',config_start_type:'Код типа запуска',error_control:'Обработка ошибок',config_binary_path:'Путь из конфигурации',load_order_group:'Группа загрузки',tag_id:'Тег загрузки',dependencies:'Зависимости',config_account:'Учётная запись из конфигурации',config_display_name:'Имя из конфигурации',binpath:'Команда запуска',description:'Описание',username:'Учётная запись',start_type:'Тип запуска',pid:'PID',Id:'Имя',Names:'Имена',LoadState:'Загрузка unit',ActiveState:'Состояние',SubState:'Подсостояние',UnitFileState:'Автозапуск',UnitFilePreset:'Политика автозапуска',Type:'Тип',MainPID:'Основной PID',ControlPID:'Управляющий PID',User:'Пользователь',Group:'Группа',DynamicUser:'Динамическая учётная запись',ExecStart:'Команда запуска',ExecStop:'Команда остановки',FragmentPath:'Файл службы',DropInPaths:'Дополнительные настройки',WorkingDirectory:'Рабочая папка',Restart:'Правило перезапуска',NRestarts:'Число перезапусков',Result:'Последний результат',ExecMainCode:'Код завершения процесса',ExecMainStatus:'Статус завершения',ActiveEnterTimestamp:'Последний переход в активное состояние',InactiveEnterTimestamp:'Последняя остановка',ExecMainStartTimestamp:'Последний запуск процесса',ExecMainExitTimestamp:'Последний выход процесса',StateChangeTimestamp:'Изменение состояния',MemoryCurrent:'Память сейчас',MemoryMax:'Ограничение памяти',CPUUsageNSec:'CPU: всего наносекунд',TasksCurrent:'Число задач',ControlGroup:'Контрольная группа',Requires:'Зависимости',Wants:'Желательные зависимости',After:'Порядок запуска',FreezerState:'Заморозка',error:'Ошибка чтения'};
  function init(root){
    root.querySelectorAll('.task-manager').forEach(panel=>{
      if(panel.dataset.taskReady)return;panel.dataset.taskReady='yes';
      const historical=panel.hasAttribute('data-task-payload');
      const saved=historical?JSON.parse(panel.dataset.taskPayload):null;
      let active='processes';const loaders={};
      const tabs=[...panel.querySelectorAll('[data-task-tab]')];
      function activate(kind){active=kind;for(const tab of tabs){const selected=tab.dataset.taskTab===kind;tab.setAttribute('aria-selected',String(selected));tab.tabIndex=selected?0:-1}for(const view of panel.querySelectorAll('[data-task-view]'))view.hidden=view.dataset.taskView!==kind;loaders[kind]?.()}
      tabs.forEach((tab,i)=>{tab.addEventListener('click',()=>activate(tab.dataset.taskTab));tab.addEventListener('keydown',e=>{if(['ArrowLeft','ArrowRight','Home','End'].includes(e.key)){e.preventDefault();const n=e.key==='Home'?0:e.key==='End'?tabs.length-1:(i+(e.key==='ArrowRight'?1:-1)+tabs.length)%tabs.length;tabs[n].focus();activate(tabs[n].dataset.taskTab)}})});
      for(const kind of ['processes','services']){
        const view=panel.querySelector('[data-task-view='+kind+']'),search=view.querySelector('.task-search'),filter=view.querySelector('.task-state'),sort=view.querySelector('.task-sort'),direction=view.querySelector('.task-direction'),body=view.querySelector('tbody'),info=view.querySelector('.task-info'),scroll=view.querySelector('.task-table-scroll');
        let entries=[],data=null,received=null,descending=kind==='processes',busy=false,signature='',message='',lastLoad=0;
        sort.value=kind==='processes'?'cpu_percent':'name';
        const value=(s,key)=>{const d=s.details||{};if(kind==='services'){if(key==='pid')return Number(d.MainPID||d.pid)||null;if(key==='start')return d.UnitFileState||d.start_type;if(key==='user')return d.User||d.username||(data?.platform==='linux'?(d.DynamicUser==='yes'?'Динамический пользователь':'root (по умолчанию)'):'')}return s[key]};
        const identity=s=>kind==='processes'?String(s.pid):s.name;
        function updateInfo(count){
          if(message){info.textContent=message;return}
          if(!data){info.textContent='Список ещё не получен. Обновите агент или проверьте его журнал.';return}
          if(data.status!=='available'){info.textContent='В этом измерении агент не смог прочитать список. Проверьте права службы агента.';return}
          const when=received?new Date(received*1000).toLocaleString('ru-RU',{timeZone:'Europe/Moscow'})+' МСК':'время неизвестно';
          info.textContent='Показано '+count+' из '+entries.length+' · Всего: '+(data.total??entries.length)+' · '+(historical?'Сохранено: '+when:'Обновлено '+Math.max(0,Math.floor(Date.now()/1000-received))+' с назад')+(data.unreadable?' · Ограничены сведения: '+data.unreadable:'')+(data.truncated?' · Список прочитан частично или сокращён агентом':'')+(data.archive_format==='legacy_top'?' · Старый архив: сохранён только топ по CPU и памяти':'');
        }
        function render(){
          const q=search.value.trim().toLocaleLowerCase('ru');
          const rows=entries.filter(s=>(filter.value==='all'||s.status===filter.value)&&(!q||JSON.stringify(s).toLocaleLowerCase('ru').includes(q))).sort((a,b)=>{
            const x=value(a,sort.value),y=value(b,sort.value);if(x==null||x==='')return y==null||y===''?identity(a).localeCompare(identity(b)):1;if(y==null||y==='')return -1;
            return (descending?-1:1)*(typeof x==='number'&&typeof y==='number'?x-y:String(x).localeCompare(String(y),'ru',{numeric:true,sensitivity:'base'}))||identity(a).localeCompare(identity(b),'ru',{numeric:true});
          });
          const opened=new Set([...body.querySelectorAll('details[open]')].map(n=>n.dataset.identity)),fragment=document.createDocumentFragment();
          for(const s of rows){
            const tr=node('tr');tr.dataset.rowId=identity(s);
            const keys=kind==='processes'?['name','pid','username','cpu_percent','memory_bytes','status']:['name','display_name','status','pid','start','user'];
            for(const key of keys){let v=value(s,key);if(key==='cpu_percent')v=v==null?'—':v.toFixed(2)+'%';else if(key==='memory_bytes')v=bytes(v);else if(key==='status')v=states[v]||text(v);else if(key==='start')v=start(v);tr.append(node('td',text(v)))}
            const td=node('td'),details=node('details');details.dataset.identity=identity(s);details.open=opened.has(identity(s));details.append(node('summary','Сведения'));const dl=node('dl');
            const fields=kind==='services'?s.details||{}:s;
            const processTitles={pid:'PID',name:'Процесс',username:'Пользователь',cpu_percent:'CPU, %',memory_bytes:'Резидентная память, байт',status:'Состояние'};
            for(const [k,v] of Object.entries(fields))dl.append(node('dt',(kind==='services'?titles:processTitles)[k]||k),node('dd',text(v)));
            if(!Object.keys(fields).length)dl.append(node('dd','Дополнительные данные недоступны'));
            details.append(dl);td.append(details);tr.append(td);fragment.append(tr);
          }
          if(!rows.length){const tr=node('tr'),td=node('td','Нет записей по выбранным условиям');td.colSpan=7;tr.append(td);fragment.append(tr)}
          const top=scroll.scrollTop,left=scroll.scrollLeft;body.replaceChildren(fragment);scroll.scrollTop=top;scroll.scrollLeft=left;
          direction.textContent=descending?'По убыванию ↓':'По возрастанию ↑';
          for(const th of view.querySelectorAll('th[aria-sort]'))th.setAttribute('aria-sort',th.querySelector('[data-sort]').dataset.sort===sort.value?(descending?'descending':'ascending'):'none');
          updateInfo(rows.length);
        }
        function accept(result){
          data=kind==='processes'?result.snapshot:result.inventory;received=result.received;message=result.message||'';entries=data?.items||[];
          const old=filter.value;filter.replaceChildren(node('option','Все'));filter.firstChild.value='all';
          for(const state of [...new Set(entries.map(s=>s.status))].sort()){const opt=node('option',states[state]||text(state));opt.value=state;filter.append(opt)}
          filter.value=[...filter.options].some(n=>n.value===old)?old:'all';render();
        }
        function newSort(){descending=!['name','pid','username','display_name','user'].includes(sort.value);render()}
        search.addEventListener('input',render);filter.addEventListener('change',render);sort.addEventListener('change',newSort);direction.addEventListener('click',()=>{descending=!descending;render()});
        view.querySelectorAll('[data-sort]').forEach(button=>button.addEventListener('click',()=>{if(sort.value===button.dataset.sort){descending=!descending;render()}else{sort.value=button.dataset.sort;newSort()}}));
        async function load(){
          if(historical||busy||document.hidden||active!==kind||!panel.isConnected)return;
          const fold=panel.closest('details.server-fold');if(fold&&!fold.open)return;
          if(Date.now()-lastLoad<1500)return;busy=true;
          try{const response=await fetch('/api/servers/'+panel.dataset.taskAgent+'/'+kind,{credentials:'same-origin',cache:'no-store'});if(!response.ok)throw Error();const result=await response.json(),next=JSON.stringify(result);lastLoad=Date.now();if(next!==signature){signature=next;accept(result)}}catch(_){info.textContent='Не удалось обновить список. Показаны последние полученные данные.'}finally{busy=false}
        }
        loaders[kind]=load;
        if(historical)accept(saved[kind]);else{render();const timer=setInterval(()=>{if(!panel.isConnected){clearInterval(timer);return}load()},10000);panel.closest('details.server-fold')?.addEventListener('toggle',()=>{if(active===kind)load()})}
      }
      activate('processes');
    });
  }
  window.initTaskManagers=init;init(document);
})();
