(() => {
  const make=(tag,text,cls)=>{const node=document.createElement(tag);if(text!=null)node.textContent=text;if(cls)node.className=cls;return node};
  const detail=document.querySelector('.server-detail');
  if(detail){
    const live=detail.querySelector('#server-live');const controls=make('div',null,'detail-tabs');controls.setAttribute('role','tablist');controls.setAttribute('aria-label','Разделы сервера');
    const tabs=[['overview','Обзор'],['performance','Производительность'],['services','Службы и бэкапы'],['hardware','Оборудование'],['events','События']];
    if(detail.querySelector('.terminal-panel'))tabs.push(['actions','Консоль']);
    let active='overview';try{const saved=sessionStorage.getItem('server-tab:'+detail.dataset.detailServer);if(tabs.some(([id])=>id===saved))active=saved}catch(_){}
    const category=title=>/Доступность|Лента|История инцидентов|Журнал загрузок|Изменения комплектации/.test(title)?'events':/Службы|Резервные копии|Отклик приложений/.test(title)?'services':/Диски|Сетевые интерфейсы|Дисковые операции/.test(title)?'performance':'hardware';
    function apply(){
      detail.dataset.detailTab=active;
      const extra=detail.querySelector(active==='performance'?'.task-manager':active==='actions'?'.terminal-panel':'.detail-tabs');
      if(extra?.closest('.server-fold'))extra.closest('.server-fold').open=true;
      const folds=[...live.querySelectorAll('.section-fold')];
      for(const fold of folds)fold.dataset.detailGroup=category(fold.querySelector(':scope>summary')?.textContent||'');
      const picker=live.querySelector('.section-picker');
      if(picker)for(const button of picker.querySelectorAll('button')){const fold=folds.find(f=>f.dataset.foldKey===button.dataset.sectionKey);button.hidden=!fold||fold.dataset.detailGroup!==active}
      if(!['overview','actions'].includes(active)){
        const candidate=folds.find(f=>f.dataset.detailGroup===active&&f.open)||folds.find(f=>f.dataset.detailGroup===active);
        if(candidate&&picker){const button=[...picker.querySelectorAll('button')].find(b=>b.dataset.sectionKey===candidate.dataset.foldKey);if(button&&button.getAttribute('aria-pressed')!=='true')button.click()}
      }
      for(const button of controls.querySelectorAll('button[data-detail-tab]')){const selected=button.dataset.detailTab===active;button.setAttribute('aria-selected',String(selected));button.tabIndex=selected?0:-1}
    }
    for(const [id,label] of tabs){const button=make('button',label);button.type='button';button.dataset.detailTab=id;button.setAttribute('role','tab');button.addEventListener('click',()=>{active=id;try{sessionStorage.setItem('server-tab:'+detail.dataset.detailServer,id)}catch(_){}const change=()=>{apply();window.portalMotion?.reveal(live);window.portalMotion?.indicator(controls,button)};window.portalMotion?window.portalMotion.preserve(change):change()});controls.append(button)}
    controls.addEventListener('keydown',event=>{if(!['ArrowLeft','ArrowRight','Home','End'].includes(event.key))return;event.preventDefault();const buttons=[...controls.querySelectorAll('button[data-detail-tab]')];let index=buttons.indexOf(document.activeElement);index=event.key==='Home'?0:event.key==='End'?buttons.length-1:(index+(event.key==='ArrowRight'?1:-1)+buttons.length)%buttons.length;buttons[index].click();buttons[index].focus({preventScroll:true})});
    detail.prepend(controls);apply();new MutationObserver(records=>{if(records.some(r=>r.target===live||[...r.addedNodes].some(n=>n.nodeType===1&&(n.matches?.('.server-information,.section-fold')||n.querySelector?.('.server-information')))))apply()}).observe(live,{childList:true,subtree:true});
  }
  function list(container,rows,type){
    if(!rows.length)return;
    const toolbar=make('div',null,'collection-toolbar'),search=make('input');search.type='search';search.placeholder='Найти по названию или ID';search.setAttribute('aria-label','Поиск в списке');
    const filter=make('select');filter.setAttribute('aria-label','Состояние списка');const filters=type==='agents'?[['all','Все агенты'],['offline','Нет связи'],['important','Важные'],['inactive','Неактивные']]:type==='users'?[['all','Все пользователи'],['enabled','Включённые'],['disabled','Отключённые'],...Array.from(new Map(rows.map(row=>[row.dataset.userRole,row.querySelector('.muted')?.textContent||row.dataset.userRole])))]:[['all','Все группы']];
    for(const [value,label] of filters){const option=make('option',label);option.value=value;filter.append(option)}
    const size=make('select');size.setAttribute('aria-label','Строк на странице');for(const n of [10,25,50]){const option=make('option',n+' на странице');option.value=n;size.append(option)}
    const footer=make('div',null,'collection-pages'),count=make('span',null,'muted'),previous=make('button','← Назад'),next=make('button','Далее →');previous.type=next.type='button';footer.append(count,previous,next);toolbar.append(search);if(filters.length>1)toolbar.append(filter);toolbar.append(size);
    container.before(toolbar);container.after(footer);container.classList.add('managed-collection');let page=0;
    function render(){
      const query=search.value.trim().toLocaleLowerCase('ru'),visible=rows.filter(row=>{
        const name=row.dataset.listName||row.querySelector('h2,h3,strong')?.textContent||row.textContent;
        if(!name.toLocaleLowerCase('ru').includes(query))return false;
        const state=filter.value;if(state==='all')return true;
        if(type==='agents')return state==='offline'?(row.dataset.received!==''&&Date.now()/1000-Number(row.dataset.received)>=180):state==='important'?!!row.querySelector('[name=flag][value=important]')?.form.querySelector('[type=checkbox]')?.checked:!row.querySelector('[name=flag][value=active]')?.form.querySelector('[type=checkbox]')?.checked;
        return state==='enabled'?row.dataset.userEnabled==='1':state==='disabled'?row.dataset.userEnabled==='0':row.dataset.userRole===state;
      });
      const pages=Math.max(1,Math.ceil(visible.length/Number(size.value)));page=Math.min(page,pages-1);const shown=new Set(visible.slice(page*Number(size.value),(page+1)*Number(size.value)));
      for(const row of rows)row.hidden=!shown.has(row);previous.disabled=page===0;next.disabled=page>=pages-1;count.textContent='Найдено: '+visible.length+' · Страница '+(page+1)+' из '+pages;
    }
    for(const control of [search,filter,size])control.addEventListener(control===search?'input':'change',()=>{page=0;render()});previous.addEventListener('click',()=>{page--;render()});next.addEventListener('click',()=>{page++;render()});document.addEventListener('portal-list-refresh',render);render();
  }
  const agents=document.querySelector('.agent-grid');if(agents)list(agents,[...agents.querySelectorAll('.agent-card')],'agents');
  const users=document.querySelector('.user-grid');if(users)list(users,[...users.querySelectorAll('.user-card')],'users');
  const groups=[...document.querySelectorAll('.group-card')];if(groups.length){const wrap=make('div',null,'group-collection');groups[0].before(wrap);wrap.append(...groups);list(wrap,groups,'groups')}
  const compare=document.querySelector('#compare-filter .fleet-selection');
  if(compare){
    const search=make('input');search.type='search';search.placeholder='Найти сервер';search.setAttribute('aria-label','Найти сервер для сравнения');const count=make('p',null,'picker-count');count.setAttribute('role','status');compare.prepend(search);compare.append(count);
    const labels=[...compare.querySelectorAll('label.check')];for(const label of labels){const input=label.querySelector('input'),name=label.textContent.trim();label.classList.add('group-server-option');label.dataset.pickerName=name;const copy=make('span',null,'group-server-copy');copy.append(make('strong',name),make('small',input.value));label.replaceChildren(input,copy,make('span','✓','group-server-mark'))}
    function update(){const query=search.value.trim().toLocaleLowerCase('ru');for(const label of labels){label.hidden=!(label.dataset.pickerName+' '+label.querySelector('input').value).toLocaleLowerCase('ru').includes(query);label.classList.toggle('is-selected',label.querySelector('input').checked)}count.textContent='Выбрано: '+labels.filter(l=>l.querySelector('input').checked).length+' из 6'}
    search.addEventListener('input',update);compare.addEventListener('change',event=>{if(labels.filter(l=>l.querySelector('input').checked).length>6){event.target.checked=false;update();count.textContent+=' · Можно выбрать не более шести серверов'}else update()});update();
  }
  const seed=document.getElementById('dependency-seed');
  if(seed){
    let data;try{data=JSON.parse(seed.textContent)}catch(_){return}
    const svg=document.querySelector('.dependency-diagram'),canvas=svg.closest('.dependency-canvas'),search=document.querySelector('[data-dependency-search]'),focus=document.querySelector('[data-dependency-focus]'),chain=document.querySelector('[data-dependency-chain]'),isolated=document.querySelector('[data-dependency-isolated]'),status=document.querySelector('[data-dependency-status]');let zoom=1,onlyChain=false,hideIsolated=false;
    const connected=new Set(data.edges.flatMap(e=>[e.dependent,e.provider]));const width=svg.viewBox.baseVal.width;
    function render(center=false){
      const allowed=new Set(focus.value?[focus.value]:data.nodes.map(n=>n.id));if(onlyChain&&focus.value)for(const direction of ['dependent','provider']){const reached=new Set([focus.value]),other=direction==='dependent'?'provider':'dependent';let changed=true;while(changed){changed=false;for(const edge of data.edges)if(reached.has(edge[direction])&&!reached.has(edge[other])){reached.add(edge[other]);changed=true}}for(const id of reached)allowed.add(id)}
      const visible=new Set();let bottom=0,found=0;const query=search.value.trim().toLocaleLowerCase('ru');
      for(const node of data.nodes){const group=[...svg.querySelectorAll('[data-node-id]')].find(g=>g.dataset.nodeId===node.id);if(!group)continue;const show=(!onlyChain||!focus.value||allowed.has(node.id))&&(!hideIsolated||connected.has(node.id));group.parentElement.style.display=show?'':'none';const match=(node.name+' '+node.id).toLocaleLowerCase('ru').includes(query);group.classList.toggle('node-search-match',!!query&&match);group.classList.toggle('node-focused',node.id===focus.value);group.classList.toggle('node-dimmed',!!query&&!match);if(show){visible.add(node.id);bottom=Math.max(bottom,group.getBBox().y+90);if(match)found++}}
      for(const edge of svg.querySelectorAll('[data-dependent]'))edge.style.display=visible.has(edge.dataset.dependent)&&visible.has(edge.dataset.provider)?'':'none';
      const height=Math.max(200,bottom);svg.setAttribute('viewBox','0 0 '+width+' '+height);svg.setAttribute('width',width*zoom);svg.setAttribute('height',height*zoom);
      chain.setAttribute('aria-pressed',String(onlyChain));isolated.setAttribute('aria-pressed',String(hideIsolated));isolated.textContent=(hideIsolated?'Показать без связей':'Скрыть без связей')+' ('+(data.nodes.length-connected.size)+')';document.querySelector('[data-diagram-zoom=reset]').textContent=Math.round(zoom*100)+'%';status.textContent='Показано: '+visible.size+(query?' · Найдено: '+found:'');
      if(center&&focus.value){const node=[...svg.querySelectorAll('[data-node-id]')].find(n=>n.dataset.nodeId===focus.value);if(node){const box=node.getBBox();canvas.scrollTo({left:Math.max(0,box.x*zoom-canvas.clientWidth/2+95*zoom),top:Math.max(0,box.y*zoom-canvas.clientHeight/2+34*zoom),behavior:'smooth'})}}
    }
    search.addEventListener('input',()=>render());focus.addEventListener('change',()=>render(true));chain.addEventListener('click',()=>{if(!focus.value){status.textContent='Сначала выберите сервер';focus.focus();return}onlyChain=!onlyChain;render(true)});isolated.addEventListener('click',()=>{hideIsolated=!hideIsolated;render()});for(const button of document.querySelectorAll('[data-diagram-zoom]'))button.addEventListener('click',()=>{zoom=button.dataset.diagramZoom==='reset'?1:Math.max(.5,Math.min(2,zoom+(button.dataset.diagramZoom==='in'?.25:-.25)));render()});render();
  }
  const heatmap=document.querySelector('.heatmap-table');if(heatmap){
    const panel=make('section',null,'heat-day-panel');panel.hidden=true;panel.setAttribute('aria-live','polite');heatmap.closest('.heatmap-scroll').after(panel);
    heatmap.addEventListener('click',event=>{const cell=event.target.closest('[data-heat-day]');if(!cell||event.ctrlKey||event.metaKey||event.shiftKey||event.altKey)return;event.preventDefault();panel.hidden=false;const title=make('h3',cell.dataset.heatServer+' · '+cell.dataset.heatDay),text=make('p',cell.title),link=make('a','Открыть события этого дня →','nav-link');link.href=cell.href;panel.replaceChildren(title,text,link);panel.scrollIntoView({block:'nearest',behavior:'smooth'})});
  }
  const password=document.querySelector('.login input[name=password]');if(password){const wrap=make('div',null,'password-field');password.before(wrap);wrap.append(password);const toggle=make('button','Показать');toggle.type='button';toggle.setAttribute('aria-pressed','false');toggle.addEventListener('click',()=>{const reveal=password.type==='password';password.type=reveal?'text':'password';toggle.textContent=reveal?'Скрыть':'Показать';toggle.setAttribute('aria-pressed',String(reveal))});wrap.append(toggle);const warning=make('p','Включён Caps Lock','caps-lock-warning');warning.hidden=true;wrap.after(warning);password.addEventListener('keydown',event=>warning.hidden=!event.getModifierState('CapsLock'));password.addEventListener('blur',()=>warning.hidden=true)}
  const ai=document.querySelector('main>.ai-chat');if(ai){document.body.classList.add('full-ai-page');const input=ai.querySelector('#ai-internet'),options=ai.querySelector('.ai-search-options');if(input&&options){const update=()=>options.hidden=!input.checked;input.addEventListener('change',update);update()}}
})();
