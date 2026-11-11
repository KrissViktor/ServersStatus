(() => {
  const form = document.querySelector('.searchbar');
  if (!form || !window.fetch || !window.AbortController) return;
  const input = form.elements.q;
  const view = form.elements.view;
  const status = document.querySelector('.search-status');
  const results = document.getElementById('server-results');
  let timer, pending, version = 0;

  const navigation=new URL(location.href);
  const resetFilters=navigation.searchParams.get('reset')==='1';
  const scope='serversstatus.'+(form.dataset.preferenceScope||'local')+'.';
  const keys=['name','status','cpu','ram','disk','availability','age','problems'];
  let pins=new Set(),savedFilters=null;
  try{if(resetFilters)localStorage.removeItem(scope+'filters');const savedPins=JSON.parse(localStorage.getItem(scope+'pins')||'[]');if(Array.isArray(savedPins))pins=new Set(savedPins.filter(id=>typeof id==='string').slice(0,10000));savedFilters=JSON.parse(localStorage.getItem(scope+'filters')||'null')}catch(_){}
  let layout=new URLSearchParams(location.search).get('layout');
  let sortKey='name',sortDescending=false;
  try{layout=layout||localStorage.getItem(scope+'layout');const saved=JSON.parse(localStorage.getItem(scope+'sort')||'null');if(saved && keys.includes(saved.key)){sortKey=saved.key;sortDescending=!!saved.descending}}catch(_){}
  layout=layout==='table'?'table':'cards';
  function presentation(){
    results.dataset.layout=layout;
    document.querySelectorAll('[data-server-layout]').forEach(button=>button.setAttribute('aria-pressed',String(button.dataset.serverLayout===layout)));
    const compare=(a,b)=>{
      const aid=a.dataset.serverId||a.dataset.tableServerId,bid=b.dataset.serverId||b.dataset.tableServerId;
      const pinned=Number(pins.has(bid))-Number(pins.has(aid));if(pinned)return pinned;
      const av=a.getAttribute('data-sort-'+sortKey),bv=b.getAttribute('data-sort-'+sortKey);
      if(av===''||av==null)return bv===''||bv==null?aid.localeCompare(bid):1;
      if(bv===''||bv==null)return -1;
      const result=sortKey==='name'?av.localeCompare(bv,'ru',{sensitivity:'base'}):Number(av)-Number(bv);
      return (sortDescending?-result:result)||aid.localeCompare(bid);
    };
    for(const container of results.querySelectorAll('[data-server-group],.fleet-table tbody'))container.append(...[...container.children].sort(compare));
    for(const button of document.querySelectorAll('[data-pin-server]')){
      const pinned=pins.has(button.dataset.pinServer);button.setAttribute('aria-pressed',String(pinned));button.textContent=pinned?'★':'☆';button.title=pinned?'Открепить сервер':'Закрепить сервер';button.setAttribute('aria-label',button.title);
    }
    const table=results.querySelector('.fleet-table');
    table?.querySelectorAll('th').forEach(th=>{const key=th.querySelector('[data-server-sort]')?.dataset.serverSort,active=key===sortKey;th.setAttribute('aria-sort',active?(sortDescending?'descending':'ascending'):'none');const indicator=th.querySelector('.sort-indicator');if(indicator)indicator.textContent=active?(sortDescending?'↓':'↑'):'↕'});
    const selector=document.querySelector('[data-overview-sort]');if(selector)selector.value=sortKey;
    const direction=document.querySelector('[data-overview-direction]');if(direction){direction.dataset.direction=sortDescending?'desc':'asc';const label=direction.querySelector('[data-direction-label]');if(label)label.textContent=sortDescending?'Убывание':'Возрастание';direction.title=sortDescending?'Сейчас по убыванию — переключить на возрастание':'Сейчас по возрастанию — переключить на убывание';direction.setAttribute('aria-label',direction.title)}
    const shortcut=document.querySelector('.overview-problem-shortcut');if(shortcut){const url=new URL('/',location.origin);url.searchParams.set('view','problems');if(form.elements.group?.value)url.searchParams.set('group',form.elements.group.value);if(input.value)url.searchParams.set('q',input.value);shortcut.href=url.pathname+url.search}
    document.querySelectorAll('[data-fleet-page]').forEach(link=>{const url=new URL(link.dataset.fleetPage,location.origin);if(form.elements.group?.value)url.searchParams.set('group',form.elements.group.value);link.href=url.pathname+url.search});
  }
  function saveSort(){try{localStorage.setItem(scope+'sort',JSON.stringify({key:sortKey,descending:sortDescending}))}catch(_){}presentation()}
  document.addEventListener('click',event=>{
    const pin=event.target.closest('[data-pin-server]');
    if(pin){const id=pin.dataset.pinServer;if(pins.has(id))pins.delete(id);else pins.add(id);try{localStorage.setItem(scope+'pins',JSON.stringify([...pins]))}catch(_){}presentation();return}
    if(event.target.closest('[data-overview-direction]')){sortDescending=!sortDescending;saveSort();return}
    const toggle=event.target.closest('[data-server-layout]'),sort=event.target.closest('[data-server-sort]');
    if(toggle){layout=toggle.dataset.serverLayout;try{localStorage.setItem(scope+'layout',layout)}catch(_){}const url=new URL(location.href);if(layout==='table')url.searchParams.set('layout','table');else url.searchParams.delete('layout');history.replaceState(null,'',url.pathname+url.search);presentation()}
    if(sort){const key=sort.dataset.serverSort;sortDescending=sortKey===key?!sortDescending:false;sortKey=key;try{localStorage.setItem(scope+'sort',JSON.stringify({key:sortKey,descending:sortDescending}))}catch(_){}presentation()}
  });
  document.querySelector('[data-overview-sort]')?.addEventListener('change',event=>{if(keys.includes(event.target.value)){sortKey=event.target.value;sortDescending=['cpu','ram','disk','problems','age'].includes(sortKey);saveSort()}});
  presentation();

  function updateResults(next,background) {
    const existing=new Map([...results.querySelectorAll('[data-server-id]')].map(card=>[card.dataset.serverId,card]));
    const wanted=new Set();
    for(const group of ['active','inactive']){
      const oldGrid=results.querySelector('[data-server-group="'+group+'"]'),newGrid=next.querySelector('[data-server-group="'+group+'"]');
      if(!oldGrid || !newGrid){results.replaceChildren(...next.childNodes);return}
      let cursor=oldGrid.firstElementChild;
      for(const card of [...newGrid.children]){
        const id=card.dataset.serverId;wanted.add(id);
        let current=existing.get(id);
        if(!current)current=card;
        else if(current.outerHTML!==card.outerHTML && !current.contains(document.activeElement)){
          window.keepCpuCores?.(current,card);current.replaceWith(card);if(cursor===current)cursor=card;current=card;
        }
        if(current!==cursor)oldGrid.insertBefore(current,cursor);
        cursor=current.nextElementSibling;
      }
    }
    for(const [id,card] of existing)if(!wanted.has(id))card.remove();
    const inactive=results.querySelector('#inactive-servers'),fresh=next.querySelector('#inactive-servers');
    if(inactive && fresh){
      inactive.hidden=fresh.hidden;inactive.querySelector('summary').innerHTML=fresh.querySelector('summary').innerHTML;
      if(!background)inactive.open=fresh.open;
    }
    const table=results.querySelector('#server-table-view'),freshTable=next.querySelector('#server-table-view');if(table&&freshTable)table.innerHTML=freshTable.innerHTML;
    const empty=results.querySelector('.empty-results');if(empty)empty.hidden=next.querySelector('.empty-results').hidden;
  }

  async function search(background = false) {
    clearTimeout(timer);
    if (background && (pending || document.hidden || form.contains(document.activeElement))) return;
    if (pending) pending.abort();
    const current = ++version;
    const controller = new AbortController();
    pending = controller;
    const url = new URL('/', window.location.origin);
    if(layout==='table')url.searchParams.set('layout','table');
    if (input.value) url.searchParams.set('q', input.value);
    if (form.elements.group?.value) url.searchParams.set('group',form.elements.group.value);
    if (view.value !== 'all') url.searchParams.set('view', view.value);
    if(!background){try{localStorage.setItem(scope+'filters',JSON.stringify({q:input.value,view:view.value,group:form.elements.group?.value||''}))}catch(_){}}
    if (!background) status.textContent = 'Обновляем список…';
    results.setAttribute('aria-busy', 'true');
    try {
      const response = await fetch(url, {
        signal: controller.signal, credentials: 'same-origin', cache: 'no-store'
      });
      if (!response.ok) throw new Error('Search failed');
      const nextPage = new DOMParser().parseFromString(await response.text(), 'text/html');
      if (current !== version) return;
      const next = nextPage.getElementById('server-results');
      if (!next) {
        status.textContent = 'Сессия завершена. Обновите страницу для входа.';
        return;
      }
      const x = window.scrollX, y = window.scrollY;
      // Removing filtered cards must not clamp the viewport to the page bottom.
      document.body.style.minHeight = Math.max(window.innerHeight, y + window.innerHeight) + 'px';
      updateResults(next,background);presentation();
      for (const id of ['overview-alerts', 'overview-stats', 'overview-tools']) {
        const target = document.getElementById(id), source = nextPage.getElementById(id);
        if (target && source && target.innerHTML !== source.innerHTML){const expanded=target.querySelector('.problem-more')?.open;target.innerHTML=source.innerHTML;if(expanded && target.querySelector('.problem-more'))target.querySelector('.problem-more').open=true;}
      }
      document.querySelector('.result-count').textContent =
        nextPage.querySelector('.result-count').textContent;
      if (!background) history.replaceState(null, '', url.pathname + url.search);
      status.textContent = '';
      window.scrollTo({left: x, top: y, behavior: 'instant'});
    } catch (error) {
      if (error.name !== 'AbortError' && current === version) {
        status.textContent = 'Не удалось обновить список. Повторите ввод или обновите страницу.';
      }
    } finally {
      if (current === version) {
        results.removeAttribute('aria-busy');
        pending = null;
      }
    }
  }

  document.addEventListener('click',event=>{
    if(event.target.closest('[data-overview-reset]')){event.preventDefault();input.value='';view.value='all';if(form.elements.group)form.elements.group.value='';search(false);return}
    const filter=event.target.closest('[data-overview-view]');
    if(!filter || event.button!==0 || event.metaKey || event.ctrlKey || event.shiftKey || event.altKey)return;
    event.preventDefault();view.value=filter.dataset.overviewView;search(false);
  });
  input.addEventListener('input', () => {
    if (pending) pending.abort();
    pending = null;
    ++version;
    clearTimeout(timer);
    timer = setTimeout(() => search(false), 180);
  });
  view.addEventListener('change', () => search(false));
  form.elements.group?.addEventListener('change',()=>search(false));
  form.addEventListener('submit', event => { event.preventDefault(); search(false); });
  if(resetFilters){
    const filtered=!!(input.value||view.value!=='all'||form.elements.group?.value);
    input.value='';view.value='all';if(form.elements.group)form.elements.group.value='';
    navigation.searchParams.delete('reset');navigation.searchParams.delete('q');navigation.searchParams.delete('view');navigation.searchParams.delete('group');
    history.replaceState(null,'',navigation.pathname+navigation.search);
    if(filtered)search(false);
  }
  if(!resetFilters && !location.search && savedFilters && typeof savedFilters==='object'){
    input.value=typeof savedFilters.q==='string'?savedFilters.q.slice(0,200):'';
    if([...view.options].some(option=>option.value===savedFilters.view))view.value=savedFilters.view;
    if(form.elements.group && [...form.elements.group.options].some(option=>option.value===savedFilters.group))form.elements.group.value=savedFilters.group;
    if(input.value||view.value!=='all'||form.elements.group?.value)search(false);
  }
  setInterval(() => search(true), 10000);
})();
