(() => {
  const panel=document.getElementById('remote-console'),form=panel?.querySelector('#console-form'),input=form?.querySelector('textarea[name=command]');
  if(!input)return;
  const list=panel.querySelector('#console-completions'),count=panel.querySelector('#console-editor-count');
  const windows=panel.dataset.shell==='powershell';
  const commands=windows?[
    ['Get-Process','Процессы и потребление ресурсов'],['Get-Service','Службы и их состояния'],['Get-ComputerInfo','Сведения о Windows'],['Get-Volume','Тома и свободное место'],['Get-Disk','Физические диски'],['Get-NetAdapter','Сетевые адаптеры'],['Get-NetIPConfiguration','IP, шлюзы и DNS'],['Get-NetTCPConnection','TCP-подключения'],['Get-WinEvent','Журнал событий'],['Get-HotFix','Установленные обновления'],['Get-Item','Сведения о файле'],['Get-ChildItem','Файлы и папки'],['Get-Content','Содержимое файла'],['Get-Location','Текущая папка'],['Set-Location','Перейти в папку'],['Get-Date','Текущее время'],['Get-Help','Справка команды'],['Get-Command','Доступные команды'],['Select-Object','Выбрать поля / первые строки'],['Where-Object','Фильтр объектов'],['Sort-Object','Сортировка объектов'],['Format-Table','Вывести таблицу'],['Measure-Object','Подсчитать значения'],['Write-Output','Вывести текст'],['Read-Host','Прочитать ответ'],['Test-Connection','Проверить доступность узла'],['Test-NetConnection','Проверить порт/соединение'],['whoami','Учётная запись выполнения'],['hostname','Имя компьютера'],['ipconfig','Конфигурация сети'],['Resolve-DnsName','Проверить DNS']
  ]:[
    ['uptime','Время работы и средняя нагрузка'],['df','Свободное место файловых систем'],['du','Размер файлов и папок'],['free','Использование оперативной памяти'],['ps','Список процессов'],['top','Процессы: используйте -b -n 1 для разового отчёта'],['systemctl','Состояние и управление systemd'],['journalctl','Журналы systemd'],['ip','Интерфейсы, адреса и маршруты'],['ss','Сетевые соединения'],['ls','Список файлов'],['pwd','Текущая папка'],['cd','Перейти в папку'],['cat','Содержимое файла'],['head','Первые строки'],['tail','Последние строки'],['grep','Поиск в тексте'],['find','Поиск файлов'],['sort','Сортировка строк'],['wc','Подсчёт строк/слов'],['date','Текущее время'],['uname','Сведения о ядре'],['hostname','Имя компьютера'],['whoami','Учётная запись выполнения'],['id','Пользователь и группы'],['printf','Вывести текст'],['read','Прочитать ответ'],['lsblk','Блочные устройства'],['lscpu','Сведения о CPU'],['getent','Системные справочники'],['command','Найти команду: command -v имя']
  ];
  const parameters=windows?{
    'get-process':['-Name','-Id','-IncludeUserName'], 'get-service':['-Name','-DisplayName'], 'get-content':['-Path','-Tail','-Wait','-Encoding','-Raw'], 'get-childitem':['-Path','-Filter','-Recurse','-Force'], 'get-winevent':['-LogName','-MaxEvents','-FilterHashtable'], 'select-object':['-First','-Last','-Property','-ExpandProperty'], 'sort-object':['-Property','-Descending','-Unique'], 'where-object':['-Property','-EQ','-Like'], 'get-help':['-Name','-Examples','-Detailed'], 'test-netconnection':['-ComputerName','-Port','-InformationLevel'], 'test-connection':['-ComputerName','-Count'], 'format-table':['-AutoSize','-Property']
  }:{
    systemctl:['status','list-units','list-unit-files','show','is-active','is-enabled','--type=service','--all','--no-pager'],journalctl:['-u','-n','--since','--until','--no-pager','-b'],df:['-h','-T','-i'],du:['-h','-s','--max-depth=1'],free:['-h','-m'],ps:['aux','-ef','-eo','--sort=-%cpu','--sort=-%mem'],top:['-b','-n'],ip:['address','route','link','-brief'],ss:['-tulpn','-tun'],ls:['-lah','-l','-a'],tail:['-n','-f'],head:['-n'],grep:['-i','-n','-r','-E'],uname:['-a','-r'],lsblk:['-f','-o']
  };
  const examples=windows?[
    {label:'Пример: состояние сервера',insert:"Get-Date\nGet-Process | Sort-Object CPU -Descending | Select-Object -First 10\nGet-Service | Where-Object Status -eq 'Running'\nGet-Volume",help:'Несколько диагностических команд одним запуском'},
    {label:'Пример: последние события',insert:'Get-WinEvent -LogName System -MaxEvents 20 | Select-Object TimeCreated, Id, LevelDisplayName, Message',help:'Последние 20 системных событий'}
  ]:[
    {label:'Пример: состояние сервера',insert:'date\nuptime\nfree -h\ndf -h /\nps aux --sort=-%cpu | head -n 11',help:'Несколько диагностических команд одним запуском'},
    {label:'Пример: службы',insert:'systemctl list-units --type=service --all --no-pager',help:'Службы systemd без интерактивного просмотрщика'}
  ];
  let items=[],selected=0,range=null,composing=false;
  const node=(tag,text)=>{const n=document.createElement(tag);n.textContent=text;return n};
  function hide(){list.hidden=true;input.setAttribute('aria-expanded','false');input.removeAttribute('aria-activedescendant')}
  function updateCount(){const lines=input.value?input.value.split('\n').filter(s=>s.trim()).length:0;count.textContent='Строк: '+lines+' · '+input.value.length+'/4000';}
  function context(){
    const end=input.selectionStart,before=input.value.slice(0,end),match=before.match(/[\w./:$-]*$/u),token=match?.[0]||'',start=end-token.length;
    const segment=before.slice(0,start).split(/[\n;|]/).at(-1).trim();
    return {start,end,token,command:segment.split(/\s+/)[0].toLowerCase(),first:!segment};
  }
  function paint(){
    list.replaceChildren();items.forEach((item,i)=>{const option=node('div','');option.id='console-completion-'+i;option.role='option';option.setAttribute('aria-selected',String(i===selected));option.append(node('strong',item.label),node('small',item.help));option.addEventListener('mousedown',e=>e.preventDefault());option.addEventListener('click',()=>choose(i));list.append(option)});
    list.hidden=!items.length;input.setAttribute('aria-expanded',String(!!items.length));
    if(items.length){input.setAttribute('aria-activedescendant','console-completion-'+selected);const option=list.children[selected];if(option.offsetTop<list.scrollTop)list.scrollTop=option.offsetTop;else if(option.offsetTop+option.offsetHeight>list.scrollTop+list.clientHeight)list.scrollTop=option.offsetTop+option.offsetHeight-list.clientHeight}else hide();
  }
  function suggest(force=false){
    updateCount();if(composing||input.selectionStart!==input.selectionEnd){hide();return}
    range=context();if(!force&&!range.token){hide();return}
    const q=range.token.toLowerCase();
    items=(range.first?commands.map(([label,help])=>({label,insert:label,help})): (parameters[range.command]||[]).map(label=>({label,insert:label,help:'Параметр / аргумент '+range.command}))).filter(v=>v.label.toLowerCase().startsWith(q)&&v.insert!==range.token).slice(0,12);
    if(force&&range.first&&!q)items.push(...examples);
    selected=0;paint();
  }
  function choose(index=selected){
    const item=items[index];if(!item||!range)return;
    const size=input.value.length-(range.end-range.start)+item.insert.length;
    if(size>input.maxLength){count.textContent='Не помещается: лимит 4000 символов';hide();return}
    input.setRangeText(item.insert,range.start,range.end,'end');input.focus({preventScroll:true});hide();input.dispatchEvent(new Event('input',{bubbles:true}));hide();
  }
  input.addEventListener('input',()=>suggest());input.addEventListener('click',()=>hide());
  input.addEventListener('compositionstart',()=>{composing=true;hide()});input.addEventListener('compositionend',()=>{composing=false;suggest()});
  input.addEventListener('blur',()=>setTimeout(()=>{if(document.activeElement!==input&&!list.contains(document.activeElement))hide()},120));
  input.addEventListener('keydown',event=>{
    if(event.isComposing||composing)return;
    if((event.ctrlKey||event.metaKey)&&event.key==='Enter'){event.preventDefault();hide();if(!form.querySelector('button[type=submit]').disabled)form.requestSubmit();return}
    if(event.ctrlKey&&event.code==='Space'){event.preventDefault();suggest(true);return}
    if(event.key==='Escape'&&!list.hidden){event.preventDefault();event.stopPropagation();hide();return}
    if(list.hidden)return;
    if(['ArrowDown','ArrowUp'].includes(event.key)){event.preventDefault();selected=(selected+(event.key==='ArrowDown'?1:-1)+items.length)%items.length;paint()}
    else if((event.key==='Tab'&&!event.shiftKey)||(event.key==='Enter'&&!event.shiftKey)){event.preventDefault();choose()}
    else if(['ArrowLeft','ArrowRight','Home','End','PageUp','PageDown'].includes(event.key))hide();
  });
  panel.querySelector('#console-show-hints').addEventListener('click',()=>{input.focus({preventScroll:true});suggest(true)});
  form.addEventListener('submit',hide);updateCount();
})();
