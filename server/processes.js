(() => {
  const panel = document.querySelector('.process-panel');
  if (!panel) return;
  const select = panel.querySelector('.process-sort'), direction = panel.querySelector('.process-direction');
  const expand = panel.querySelector('.process-expand'), body = panel.querySelector('.process-rows');
  const info = panel.querySelector('.process-info');
  let items = [], expanded = false, descending = true, busy = false, received = null, snapshot = null;
  const text = value => value === null || value === undefined || value === '' ? '—' : String(value);
  const memory = value => value == null ? '—' : (value / 1048576).toLocaleString('ru-RU', {maximumFractionDigits: 1}) + ' Мб';
  function render() {
    const key = select.value;
    const sorted = [...items].sort((a,b) => {
      const x = a[key], y = b[key];
      if (x == null || x === '') return y == null || y === '' ? a.pid-b.pid : 1;
      if (y == null || y === '') return -1;
      const result = typeof x === 'string' ? x.localeCompare(y,'ru',{numeric:true,sensitivity:'base'}) : x-y;
      return (descending ? -result : result) || a.pid-b.pid;
    });
    const visible = expanded ? sorted : sorted.slice(0,10);
    const fragment = document.createDocumentFragment();
    for (const process of visible) {
      const tr = document.createElement('tr');
      const states = {running:'Работает',sleeping:'Ожидает',stopped:'Остановлен',zombie:'Зомби',idle:'Ожидает',disk_sleep:'Ожидает диск'};
      for (const value of [process.pid,text(process.name),text(process.username),process.cpu_percent == null ? '—' : process.cpu_percent.toFixed(1)+'%',memory(process.memory_bytes),states[process.status] || text(process.status)]) {
        const td = document.createElement('td'); td.textContent=value; tr.append(td);
      }
      fragment.append(tr);
    }
    // Preserve the inner scroll and focus; controls are never replaced.
    const scroll = panel.querySelector('.table-scroll'), top = scroll.scrollTop;
    body.replaceChildren(fragment); scroll.scrollTop = top;
    expand.textContent = expanded ? 'Свернуть до 10' : 'Показать все ('+items.length+')';
    expand.setAttribute('aria-expanded',String(expanded));
    expand.disabled = items.length <= 10;
    direction.textContent = descending ? 'По убыванию ↓' : 'По возрастанию ↑';
    if (!snapshot) info.textContent='Список ещё не получен. Обновите агент для сбора процессов.';
    else if (snapshot.status !== 'available') info.textContent='Агент не смог прочитать процессы. Проверьте права службы.';
    else {
      const age = Math.max(0,Math.floor(Date.now()/1000-received));
      info.textContent='Показано '+visible.length+' из '+items.length+' · Обновлено '+age+' с назад'+(age>=30 ? ' · Данные устарели' : '')+(snapshot.truncated ? ' · Список сокращён по лимиту количества или размера' : '')+(snapshot.unreadable ? ' · Ограничены сведения о '+snapshot.unreadable+' процессах' : '');
    }
  }
  select.addEventListener('change',()=>{descending=!['name','username','pid'].includes(select.value);render()});
  direction.addEventListener('click',()=>{descending=!descending;render()});
  expand.addEventListener('click',()=>{expanded=!expanded;render()});
  async function refresh() {
    if (busy || document.hidden) return;
    busy=true;
    try {
      const response=await fetch(panel.dataset.processUrl,{credentials:'same-origin',cache:'no-store'});
      if (!response.ok) throw new Error('request failed');
      const result=await response.json();
      snapshot=result.snapshot; received=result.received; items=snapshot?.items || []; render();
    } catch (_) { info.textContent='Не удалось обновить процессы. Показаны последние полученные данные.'; }
    finally { busy=false; }
  }
  refresh();setInterval(refresh,10000);
})();
