/* UI labels only. Report contents and integration payloads stay in the source language. */
(() => {
  const key='serversstatus.language';
  const translations=new Map(`
Язык сайта|Site language
Тема сайта|Site theme
Системная|System
Светлая|Light
Тёмная|Dark
Войти|Sign in
Войти в панель|Open dashboard
Выйти|Sign out
Логин|Username
Пароль|Password
Проверяем данные…|Signing in…
Неверный логин или пароль.|Incorrect username or password.
Слишком много попыток. Попробуйте позже.|Too many attempts. Try again later.
Не удалось войти. Повторите попытку.|Sign-in failed. Try again.
Не удалось связаться с порталом. Повторите попытку.|Could not reach the portal. Try again.
Состояние серверов|Server health
в одном месте|in one place
Server Pulse показывает нагрузку, свободное место, состояние служб и резервных копий. По истории замеров можно понять, когда началась проблема и что происходило с сервером в тот момент.|Server Pulse tracks resource usage, free space, services, and backups. Historical reports show when an issue started and what was happening on the server at the time.
Посмотреть пример ↓|View demo ↓
Как это работает|How it works
Последние 60 минут · пример|Last 60 minutes · demo
Как выглядит обзор|Dashboard preview
Вымышленные серверы и показатели|Sample servers and metrics
Пример списка серверов|Sample server list
Сервер|Server
Серверы|Servers
Состояние|Status
Диск|Disk
Диск почти заполнен|Disk nearly full
На связи|Online
Пример мониторинга сайтов|Website monitoring demo
TLS действителен|TLS certificate valid
TLS истекает через 9 дней|TLS expires in 9 days
Агенты собирают замеры|Agents collect measurements
Агенты Windows и Linux отправляют метрики, сведения о дисках, службах и резервных копиях по HTTPS.|Windows and Linux agents send metrics, disk, service, and backup data over HTTPS.
Портал хранит историю|The portal stores history
Выбирайте период, сравнивайте серверы и открывайте снимок исходного отчёта по точке графика.|Choose a date range, compare servers, and inspect the original report behind a chart point.
Уведомления помогают реагировать|Get notified when something changes
Портал показывает инциденты, а мониторы сайтов проверяют HTTP и сроки сертификатов. Предупреждения можно получать в Telegram.|The portal shows incidents and checks HTTP responses and certificate expiry. Alerts can be sent to Telegram.
От замера до решения|From measurement to resolution
Пример инцидента|Sample incident
Мало места на диске|Low disk space
Диск заполнился на 91%|Disk usage reached 91%
На обзоре появилось предупреждение.|A warning appeared on the dashboard.
Открыли снимок сервера|Opened a server snapshot
По выбранной точке проверили нагрузку, свободное место и состояние бэкапов.|The selected report showed resource usage, free space, and backup status.
Место освободилось|Disk space was freed
Новый отчёт агента подтвердил восстановление.|A new agent report confirmed recovery.
Для ежедневной работы|For day-to-day operations
CPU, RAM и диски на общей шкале. Откройте снимок по точке, чтобы увидеть исходный отчёт.|CPU, RAM, and disks share a timeline. Select a point to open the original report.
Прогноз заполнения дисков, повторяющиеся сбои и бэкапы, требующие проверки.|Disk usage forecasts, recurring incidents, and backups that need attention.
Ожидаемый HTTP-код, время отклика, срок действия TLS и история проверок.|Expected HTTP status, latency, TLS expiry, and check history.
Загрузка CPU, демонстрационные данные|CPU usage, sample data
Занятость RAM, демонстрационные данные|RAM usage, sample data
Заполненность диска, демонстрационные данные|Disk usage, sample data
Основные разделы|Main navigation
Разделы портала|Portal sections
Путь страницы|Breadcrumbs
Мониторы|Monitors
Мониторы сайтов|Website monitors
Группы|Groups
Группы серверов|Server groups
Аналитика|Analytics
Проблемы|Issues
План на неделю|Weekly plan
Обновления|Updates
Администрирование|Administration
Настройки|Settings
Настройки мониторинга|Monitoring settings
Большой экран|Wallboard
Экран|Wallboard
Обзор серверов|Server overview
Карточки|Cards
Таблица|Table
Обычные|Standard
Компактные|Compact
Карта|Map
Связи|Dependencies
Связи серверов|Server dependencies
Сравнение|Compare
Сравнение серверов|Compare servers
Сводка за сутки|Daily summary
Всего|Total
Онлайн|Online
Нет связи|Offline
Диски от 85%|Disks at 85% or above
Поиск|Search
Показать|Show
Группа|Group
Все группы|All groups
Все серверы|All servers
Есть проблемы|Has issues
Сбросить|Reset
По названию|By name
По числу проблем|By issue count
По состоянию связи|By connection status
По загрузке CPU|By CPU usage
По занятости RAM|By RAM usage
По заполнению дисков|By disk usage
По доступности|By uptime
По возрасту отчёта|By report age
Возрастание|Ascending
Убывание|Descending
Сортировка серверов|Sort servers
Порядок серверов|Server order
Изменить направление сортировки|Reverse sort order
Процессор|Processor
Оперативная память|Memory
Последний отчёт|Latest report
Отчёты поступают|Receiving reports
Ожидаем первый отчёт агента|Waiting for the first agent report
Проблем по полученным данным нет|No issues in the latest report
Всё в порядке|All systems operational
Нет проблем без отметки|No unacknowledged issues
Управление отметками|Manage acknowledgements
Доступность|Uptime
Доступность · 24 ч|Uptime · 24 h
Нет данных|No data
История нагрузки|Resource history
ИСТОРИЯ НАГРУЗКИ|RESOURCE HISTORY
Период истории|History range
15 минут|15 minutes
Час|Hour
6 часов|6 hours
Последние сутки|Last 24 hours
Неделя|Week
30 дней|30 days
С|From
По|To
Показать по датам|Apply dates
Среднее CPU|Average CPU
Среднее RAM|Average RAM
Пик CPU|Peak CPU
Пик RAM|Peak RAM
Минимум CPU|Minimum CPU
Минимум RAM|Minimum RAM
Заполненность дисков|Disk usage
Заполненность диска|Disk usage
Сеть|Network
Дисковые операции|Disk I/O
Дисковое устройство|Disk device
Сетевой интерфейс|Network interface
История инцидентов|Incident history
Загрузка…|Loading…
Повторить загрузку|Retry
Снимок сервера|Server snapshot
Исходные отчёты|Raw reports
Закрыть|Close
Внешний вид|Appearance
Тема сохраняется в этом браузере.|The theme is saved in this browser.
Настройки и обслуживание портала|Portal settings and maintenance
Управление агентами|Agent management
Добавить компьютер|Add computer
Пользователи|Users
Добавить пользователя|Add user
Создать пользователя|Create user
Добавить монитор|Add monitor
Добавить или изменить связь|Add or edit dependency
Сохранить связь|Save dependency
Сеансы портала|Portal sessions
Текущие|Active
Завершённые|Ended
Неудачные входы|Failed sign-ins
Завершить сеанс|End session
Сохранить|Save
Добавить|Add
Удалить|Delete
Резервные копии|Backups
Службы|Services
Процессы|Processes
Диски|Disks
История проверок|Check history
Последние проверки|Recent checks
Интервал, секунд|Interval, seconds
Ожидаемый HTTP-код|Expected HTTP status
Название|Name
Уведомлять в Telegram|Send Telegram alerts
Сверять домен с реестром РКН|Check against the RKN registry
Доступен|Available
Ожидает проверки|Awaiting check
Выключено|Disabled
Ошибка соединения|Connection error
Скоро истекает|Expiring soon
Ошибка сертификата|Certificate error
Пауза|Pause
Возобновить|Resume
Журнал событий|Event log
Суточные сводки|Daily summaries
Пересчитать сводки|Rebuild summaries
Более ранние записи →|Older entries →
`.trim().split('\n').map(line=>line.split('|')));
  const patterns=[
    [/^Показано (\d+) из (\d+)$/u,'Showing $1 of $2'],
    [/^Заполненность дисков · (.+)$/u,'Disk usage · $1'],
    [/^Отмечено «Всё окей»: (\d+)$/u,'Acknowledged: $1'],
    [/^(\d+)[\u00a0 ]мс$/u,'$1 ms'],
  ];
  const root=document.documentElement;
  const originals=new WeakMap();
  const attributes=['aria-label','title','placeholder'];
  const excluded='script,style,pre,code,textarea,[data-no-translate]';
  let language='ru';

  function translated(value) {
    if(language==='ru')return value;
    const plain=value.trim().replace(/\s+/g,' ');
    let result=translations.get(plain);
    if(!result){
      for(const [pattern,replacement] of patterns){
        if(pattern.test(plain)){result=plain.replace(pattern,replacement);break}
      }
    }
    return result ? value.match(/^\s*/)[0]+result+value.match(/\s*$/)[0] : value;
  }

  function update(node,slot,value,write) {
    let record=originals.get(node);
    if(!record){record={};originals.set(node,record)}
    const previous=record[slot];
    const source=previous?.applied===value?previous.source:value;
    const next=translated(source);
    record[slot]={source,applied:next};
    if(next!==value)write(next);
  }

  function visit(node) {
    if(node.nodeType===3){
      const parent=node.parentElement;
      if(!parent||parent.closest(excluded)||!node.data.trim())return;
      if(parent.tagName==='OPTION'&&!parent.hasAttribute('value'))parent.value=parent.textContent;
      update(node,'text',node.data,value=>{node.data=value});
    }else if(node.nodeType===1&&!node.closest(excluded)){
      for(const attribute of attributes){
        if(node.hasAttribute(attribute))update(node,attribute,node.getAttribute(attribute),value=>node.setAttribute(attribute,value));
      }
      for(const child of node.childNodes)visit(child);
    }
  }

  function apply(choice) {
    language=choice==='en'?'en':'ru';
    root.lang=language;
    for(const control of document.querySelectorAll('[data-language-choice]'))control.value=language;
    visit(document.body);
  }

  let choice;
  try{choice=localStorage.getItem(key)}catch(_){}
  apply(choice);
  const observer=new MutationObserver(records=>{
    for(const record of records){
      if(record.type==='characterData')visit(record.target);
      else if(record.type==='attributes'){
        const attr=record.attributeName,node=record.target;
        if(!node.closest(excluded)&&node.hasAttribute(attr))update(node,attr,node.getAttribute(attr),value=>node.setAttribute(attr,value));
      }else for(const node of record.addedNodes)visit(node);
    }
  });
  observer.observe(document.body,{childList:true,subtree:true,characterData:true,attributes:true,attributeFilter:attributes});
  document.addEventListener('change',event=>{
    if(!event.target.matches('[data-language-choice]'))return;
    apply(event.target.value);
    try{localStorage.setItem(key,language)}catch(_){}
  });
  window.addEventListener('storage',event=>{if(event.key===key||event.key===null)apply(event.newValue)});
})();
