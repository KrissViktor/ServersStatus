(() => {
  const dialog=document.getElementById('chart-detail');if(!dialog)return;
  const plot=dialog.querySelector('#detail-chart-plot'),status=dialog.querySelector('#detail-chart-status'),countLabel=dialog.querySelector('#detail-chart-count'),info=dialog.querySelector('#detail-point-info');
  let center=0,count=30,metric='cpu',name='',points=[],unit='%',pending=null,version=0,domain=[0,1],drag=null;
  const tooltip=document.getElementById('detail-chart-tooltip'),snapshotButton=document.getElementById('detail-snapshot'),snapshotContent=document.getElementById('detail-snapshot-content');
  let selected=null,wanted=null,snapshotPending=null,active=false,renderFrame=null,wheelTimer=null,wheelDelta=0,pinchStart=null,wheelDomain=null,wheelCount=30,keepSnapshot=false;
  const dateFormat=new Intl.DateTimeFormat('ru-RU',{timeZone:'Europe/Moscow',dateStyle:'short',timeStyle:'medium',hour12:false});
  const interaction=document.createElement('p');interaction.className='plot-interaction-status';plot.before(interaction);
  function activate(value){active=value;plot.classList.toggle('plot-locked',!value);plot.setAttribute('aria-label',value?'График активен. Колесо или щипок — масштаб':'График зафиксирован. Нажмите для управления');interaction.textContent=value?'◉ Управление графиком: колесо или щипок — масштаб, перетаскивание — время':'◌ График зафиксирован · Нажмите на него для управления. Колесо прокручивает страницу.'}
  function scheduleRender(offset=0){if(renderFrame)cancelAnimationFrame(renderFrame);renderFrame=requestAnimationFrame(()=>{renderFrame=null;render(offset)})}
  const svgNS='http://www.w3.org/2000/svg';
  function node(tag,attributes={},text=''){const n=document.createElementNS(svgNS,tag);for(const [k,v] of Object.entries(attributes))n.setAttribute(k,v);if(text)n.textContent=text;return n}
  const stamp=t=>dateFormat.format(t*1000)+' МСК';
  function size(v){if(v==null)return '—';let i=0;const units=['Б','Кб','Мб','Гб','Тб'];while(Math.abs(v)>=1024 && i<4){v/=1024;i++}return v.toLocaleString('ru-RU',{maximumFractionDigits:1})+' '+units[i]}
  const format=v=>v==null?'—':unit==='%'?v.toFixed(1)+'%':unit==='bytes/s'?size(v)+'/с':v.toFixed(1)+' оп/с';
  function describe(p){return stamp(p.timestamp)+' · '+format(p.value)+'\nCPU '+(p.cpu==null?'—':p.cpu.toFixed(1)+'%')+' · RAM '+(p.ram==null?'—':p.ram.toFixed(1)+'%')+' · Память '+size(p.ram_used_bytes)+' / '+size(p.ram_total_bytes)+'\nИсходный отчёт #'+p.report_id}
  function selectPoint(p,clientX=null,clientY=null,commit=true){
    if(!p)return;
    if(commit){
      if(selected?.report_id!==p.report_id){snapshotPending?.abort();if(keepSnapshot&&!snapshotContent.hidden){snapshotContent.style.minHeight=snapshotContent.getBoundingClientRect().height+'px';snapshotContent.textContent='Загрузка соседнего снимка…';delete snapshotContent.dataset.reportId}else{snapshotContent.hidden=true;delete snapshotContent.dataset.reportId;snapshotContent.replaceChildren()}}
      selected=p;wanted=p.report_id;snapshotButton.disabled=!p.report_id;for(const button of dialog.querySelectorAll('[data-report-step]'))button.disabled=!p.report_id;
      document.getElementById('detail-selected-label').textContent='Выбран отчёт: '+stamp(p.timestamp);
      for(const circle of plot.querySelectorAll('.detail-report-point')){const active=circle.dataset.reportId===String(p.report_id);circle.setAttribute('r',active?'5':'3.5');circle.classList.toggle('is-selected',active)}
    }
    info.textContent=describe(p);
    if(clientX!=null){tooltip.textContent=describe(p);tooltip.hidden=false;tooltip.style.left=Math.max(10,Math.min(innerWidth-tooltip.offsetWidth-10,clientX+14))+'px';tooltip.style.top=Math.max(10,Math.min(innerHeight-tooltip.offsetHeight-10,clientY-48))+'px'}
  }
  function nearestPoint(clientX){const box=plot.getBoundingClientRect(),fraction=Math.max(0,Math.min(1,(clientX-box.left-85)/Math.max(1,box.width-103))),time=domain[0]+fraction*(domain[1]-domain[0]);return points.filter(p=>p.value!=null).reduce((a,b)=>!a||Math.abs(b.timestamp-time)<Math.abs(a.timestamp-time)?b:a,null)}
  function render(offset=0){
    const w=Math.max(300,plot.clientWidth),h=Math.max(220,plot.clientHeight),left=85,right=w-18,top=20,bottom=h-42;
    const start=domain[0]+offset,end=domain[1]+offset,span=Math.max(1,end-start);
    const maximum=unit==='%'?100:Math.max(1,...points.map(p=>p.value==null?0:p.value*1.1));
    const x=t=>left+(t-start)/span*(right-left),y=v=>bottom-v/maximum*(bottom-top);
    const color=metric==='ram'?'#b9a0ff':'#7dbbff';
    const svg=node('svg',{viewBox:`0 0 ${w} ${h}`,role:'img','aria-label':'Исходные отчёты сервера'});
    for(const ratio of [0,.25,.5,.75,1]){
      const v=maximum*ratio;svg.append(node('line',{x1:left,x2:right,y1:y(v),y2:y(v),class:'chart-grid'}),node('text',{x:left-8,y:y(v)+4,'text-anchor':'end',class:'chart-label'},format(v)));
    }
    const axisStamp=t=>w<700?new Date(t*1000).toLocaleTimeString('ru-RU',{timeZone:'Europe/Moscow',hour12:false}):stamp(t);
    for(const f of [0,.5,1])svg.append(node('text',{x:left+f*(right-left),y:h-12,'text-anchor':f===0?'start':f===1?'end':'middle',class:'chart-label'},axisStamp(start+span*f)));
    if(unit==='%'){svg.append(node('rect',{x:left,y:top,width:right-left,height:y(85)-top,fill:'#e4b56b','fill-opacity':.025}),node('line',{x1:left,x2:right,y1:y(95),y2:y(95),class:'resource-threshold'}))}
    let segment=[];const fillSegment=()=>{if(segment.length>1){const line=window.portalGeometry.path(segment.map(p=>[x(p.timestamp),y(p.value)]));const d=line+` L ${x(segment.at(-1).timestamp)},${bottom} L ${x(segment[0].timestamp)},${bottom} Z`;svg.append(node('path',{d,fill:color,'fill-opacity':.075,class:'resource-area'}));svg.append(node('path',{d:line,fill:'none',stroke:color,'stroke-width':1.7,class:'resource-line'}))}segment=[]};
    for(const p of points){if(p.value==null||p.timestamp<start||p.timestamp>end){fillSegment();continue}if(segment.length&&p.timestamp-segment.at(-1).timestamp>180)fillSegment();segment.push(p)}fillSegment();
    let previous=null,lastMarker=-Infinity;
    for(const p of points){
      if(p.value==null){previous=null;continue}
      if(p.timestamp<start || p.timestamp>end){previous=null;continue}
      if(x(p.timestamp)-lastMarker<4&&p.report_id!==selected?.report_id)continue;lastMarker=x(p.timestamp);
      const circle=node('circle',{cx:x(p.timestamp),cy:y(p.value),r:3.5,fill:color,tabindex:'0',class:'detail-report-point','data-report-id':p.report_id});
      let title=stamp(p.timestamp)+' · '+format(p.value);
      if(metric==='ram')title+=' · занято '+size(p.ram_used_bytes)+' из '+size(p.ram_total_bytes);
      circle.append(node('title',{},title));circle.addEventListener('focus',()=>{activate(true);selectPoint(p)});svg.append(circle);previous=p;
    }
    plot.replaceChildren(svg);
    if(selected){for(const circle of plot.querySelectorAll('.detail-report-point'))if(circle.dataset.reportId===String(selected.report_id)){circle.classList.add('is-selected');circle.setAttribute('r','5')}}
  }
  async function load(first=null,last=null){
    if(pending)pending.abort();const controller=new AbortController();pending=controller;const current=++version;
    const url=new URL(dialog.dataset.url,location.origin);for(const [key,value] of Object.entries({center,count,metric,name}))url.searchParams.set(key,value);
    if(first!=null && last!=null){url.searchParams.set('first',first);url.searchParams.set('last',last)}
    if(wanted!=null)url.searchParams.set('report_id',wanted);
    tooltip.hidden=true;snapshotButton.disabled=true;
    status.textContent='Загрузка исходных отчётов…';plot.classList.add('plot-working');plot.setAttribute('aria-busy','true');
    try{
      const response=await fetch(url,{signal:controller.signal,credentials:'same-origin',cache:'no-store'});if(!response.ok)throw new Error();
      const data=await response.json();if(current!==version || !dialog.open)return;
      points=data.points;unit=data.unit;
      if(points.length){
        const first=points[0].timestamp,last=points[points.length-1].timestamp;
        domain=first===last?[first-15,last+15]:[first,last];center=(domain[0]+domain[1])/2;
        status.textContent=stamp(first)+' — '+stamp(last);render();
      }else{plot.replaceChildren();status.textContent='Сохранённых отчётов нет.'}
      countLabel.textContent=`Показано ${data.count} · масштаб ${count} отчётов · максимум 900`;
      dialog.querySelector('[data-zoom="out"]').disabled=count>=900;dialog.querySelector('[data-zoom="in"]').disabled=count<=3;
      const available=points.filter(p=>p.value!=null);
      const target=points.find(p=>p.report_id===wanted)||available.reduce((best,p)=>!best||Math.abs(p.timestamp-center)<Math.abs(best.timestamp-center)?p:best,null);
      if(target)selectPoint(target);else{selected=null;wanted=null;info.textContent='Нет измерений выбранной метрики.';snapshotContent.hidden=true}
      for(const kind of ['min','max']){const button=dialog.querySelector('[data-view-extreme="'+kind+'"]');button.disabled=!available.length;if(available.length){const p=available.reduce((a,b)=>(kind==='min'?b.value<a.value:b.value>a.value)?b:a);button.textContent=(kind==='min'?'Минимум: ':'Максимум: ')+format(p.value)}}
    }catch(error){if(error.name!=='AbortError' && current===version)status.textContent='Не удалось загрузить отчёты. Повторите изменение масштаба.'}
    finally{if(current===version){pending=null;plot.removeAttribute('aria-busy');plot.classList.remove('plot-working');activate(false)}}
  }
  function zoom(out,anchor=.5){
    const next=out?Math.min(900,Math.ceil(count*1.5)):Math.max(3,Math.round(count/1.5));if(next===count)return;
    const span=domain[1]-domain[0];center=Math.max(0,center+(anchor-.5)*span*(1-next/count));count=next;wanted=null;load();
  }
  function pan(direction){wanted=null;center=Math.max(0,center+direction*Math.max(10,domain[1]-domain[0])*.6);load()}
  document.addEventListener('click',event=>{
    let point=event.target.closest('[data-detail-metric]');
    if(!point){
      const svg=event.target.closest('.history-chart,.task-graph,.comparison-chart');let nearest=19;
      if(svg)for(const candidate of svg.querySelectorAll('[data-detail-metric]')){
        const box=candidate.getBoundingClientRect(),distance=Math.hypot(event.clientX-box.x-box.width/2,event.clientY-box.y-box.height/2);
        if(distance<nearest){nearest=distance;point=candidate}
      }
    }
    if(!point)return;
    const card=point.closest('[data-server-id]');if(card)dialog.dataset.url='/api/history/'+encodeURIComponent(card.dataset.serverId)+'/detail';
    metric=point.dataset.detailMetric;name=point.dataset.detailName||'';
    const first=Number(point.dataset.detailFirst),last=Number(point.dataset.detailLast);
    wanted=point.dataset.detailReport?Number(point.dataset.detailReport):null;selected=null;tooltip.hidden=true;snapshotContent.hidden=true;delete snapshotContent.dataset.reportId;snapshotContent.replaceChildren();snapshotPending?.abort();
    center=(first+last)/2;count=Math.min(900,Math.max(30,Number(point.dataset.detailCount)||30));points=[];
    dialog.querySelector('h2').textContent=point.dataset.detailTitle||'Подробный график';plot.replaceChildren();plot.style.height='';plot.style.flex='';if(!dialog.open)dialog.showModal();activate(false);load(first,last);
  });
  document.addEventListener('keydown',event=>{if((event.key==='Enter'||event.key===' ') && event.target.matches('[data-detail-metric]')){event.preventDefault();event.target.dispatchEvent(new MouseEvent('click',{bubbles:true}))}});
  dialog.querySelector('[data-detail-close]').addEventListener('click',()=>dialog.close());
  dialog.addEventListener('close',()=>{version++;pending?.abort();pending=null;drag=null;dialog.style.paddingBottom='';tooltip.hidden=true;snapshotPending?.abort();clearTimeout(wheelTimer);if(renderFrame)cancelAnimationFrame(renderFrame)});
  dialog.addEventListener('click',event=>{const zoomButton=event.target.closest('[data-zoom]'),panButton=event.target.closest('[data-pan]');if(zoomButton)zoom(zoomButton.dataset.zoom==='out');if(panButton)pan(Number(panButton.dataset.pan));const extreme=event.target.closest('[data-view-extreme]');if(extreme){const candidates=points.filter(p=>p.value!=null);if(candidates.length)selectPoint(candidates.reduce((a,b)=>(extreme.dataset.viewExtreme==='min'?b.value<a.value:b.value>a.value)?b:a))}});
  async function stepReport(direction){if(!selected||pending)return;const before=selected.report_id,restore=!snapshotContent.hidden;const url=new URL(dialog.dataset.url.replace(/\/detail$/,'/report-step'),location.origin);url.searchParams.set('report_id',before);url.searchParams.set('direction',direction);status.textContent='Загрузка соседнего отчёта…';try{const response=await fetch(url,{credentials:'same-origin',cache:'no-store'});if(!response.ok)throw Error('Отчёт недоступен');const target=await response.json();if(!dialog.open||selected?.report_id!==before)return;if(!target.report_id){status.textContent=direction<0?'Это первый сохранённый отчёт':'Это последний сохранённый отчёт';return}wanted=target.report_id;center=target.timestamp;keepSnapshot=restore;await load(target.timestamp,target.timestamp);if(restore&&selected?.report_id===target.report_id)await showSnapshot()}catch(error){status.textContent=error.message}finally{keepSnapshot=false}}
  dialog.addEventListener('click',event=>{const step=event.target.closest('[data-report-step]');if(step)stepReport(Number(step.dataset.reportStep));if(event.target.closest('[data-detail-reset]')){count=30;center=selected?.timestamp||center;load()}});
  dialog.addEventListener('keydown',event=>{if(event.target.closest('input,textarea,select,#detail-snapshot-content'))return;if(event.key==='ArrowLeft'||event.key==='ArrowRight'){event.preventDefault();stepReport(event.key==='ArrowLeft'?-1:1)}});
  plot.addEventListener('wheel',event=>{if(!active||pending)return;event.preventDefault();if(!wheelDomain){wheelDomain=[...domain];wheelCount=count}wheelDelta=Math.max(-600,Math.min(600,wheelDelta+event.deltaY));const ratio=Math.exp(wheelDelta*.003),box=plot.getBoundingClientRect(),fraction=Math.max(0,Math.min(1,(event.clientX-box.left)/box.width)),anchor=wheelDomain[0]+fraction*(wheelDomain[1]-wheelDomain[0]),span=(wheelDomain[1]-wheelDomain[0])*ratio;domain=[anchor-span*fraction,anchor+span*(1-fraction)];center=(domain[0]+domain[1])/2;count=Math.max(3,Math.min(900,Math.round(wheelCount*ratio)));scheduleRender();clearTimeout(wheelTimer);wheelTimer=setTimeout(()=>{wheelDelta=0;wheelDomain=null;wanted=null;load()},150)},{passive:false});
  plot.addEventListener('pointerleave',()=>{tooltip.hidden=true;if(selected)info.textContent=describe(selected)});
  plot.addEventListener('pointerdown',event=>{if(event.button!==0 || !points.length||pending||pinchStart)return;if(event.pointerType==='touch'&&!active){drag={x:event.clientX,y:event.clientY,offset:0,lockedTouch:true,moved:false};return}const activationOnly=!active;activate(true);event.preventDefault();drag={x:event.clientX,offset:0,activationOnly};plot.setPointerCapture(event.pointerId)});
  plot.addEventListener('pointermove',event=>{
    if(!drag){if(!active||!points.length || pending)return;const nearest=nearestPoint(event.clientX);if(nearest)selectPoint(nearest,event.clientX,event.clientY,false);return}
    if(drag.lockedTouch){drag.moved=drag.moved||Math.hypot(event.clientX-drag.x,event.clientY-drag.y)>8;return}
    tooltip.hidden=true;drag.offset=-(event.clientX-drag.x)/Math.max(1,plot.clientWidth-103)*(domain[1]-domain[0]);scheduleRender(drag.offset);
  });
  plot.addEventListener('pointerup',event=>{
    if(!drag)return;if(drag.lockedTouch){if(!drag.moved)activate(true);drag=null;return}const offset=drag.offset,moved=Math.abs(event.clientX-drag.x)>4,activationOnly=drag.activationOnly;drag=null;
    if(moved){wanted=null;center=Math.max(0,center+offset);load()}
    else if(!activationOnly){selectPoint(nearestPoint(event.clientX));scheduleRender()}
  });
  plot.addEventListener('pointercancel',()=>{if(drag&&!drag.lockedTouch)scheduleRender();drag=null});
  async function showSnapshot(){
    if(!selected?.report_id)return;const identifier=selected.report_id;activate(false);
    if(snapshotContent.dataset.reportId===String(identifier)&&!snapshotContent.hidden){snapshotContent.scrollIntoView({block:'start',behavior:window.portalMotion?.reduced()?'instant':'smooth'});return}
    const height=plot.getBoundingClientRect().height;plot.style.flex='0 0 auto';plot.style.height=height+'px';
    snapshotPending?.abort();const controller=new AbortController();snapshotPending=controller;
    snapshotContent.hidden=false;snapshotContent.textContent='Загрузка снимка…';
    const url=new URL(dialog.dataset.url.replace(/\/detail$/,'/snapshot'),location.origin);url.searchParams.set('report_id',identifier);
    try{
      const response=await fetch(url,{signal:controller.signal,credentials:'same-origin',cache:'no-store'});
      if(!response.ok){let text='Не удалось получить снимок';try{text=(await response.json()).detail||text}catch(_){}throw new Error(text)}
      const data=await response.json();if(selected?.report_id!==identifier || !dialog.open)return;
      const update=()=>{snapshotContent.innerHTML=data.html;snapshotContent.dataset.reportId=identifier;window.initServerInformation?.(snapshotContent);window.initTaskManagers?.(snapshotContent)};update();status.textContent='Снимок открыт ниже. Верхний график зафиксирован.';if(!keepSnapshot)snapshotContent.scrollIntoView({block:'start',behavior:window.portalMotion?.reduced()?'instant':'smooth'});
    }catch(error){if(error.name!=='AbortError' && selected?.report_id===identifier)snapshotContent.textContent=error.message}
  }
  snapshotButton.addEventListener('click',showSnapshot);
  window.addEventListener('load',()=>window.portalGeometry.pinch(plot,{start:g=>{activate(true);drag=null;pinchStart={domain:[...domain],count,center};},move:g=>{if(!pinchStart)return;const box=plot.getBoundingClientRect(),fraction=Math.max(0,Math.min(1,(g.x-box.left)/box.width)),span=(pinchStart.domain[1]-pinchStart.domain[0])/g.scale,anchor=pinchStart.domain[0]+fraction*(pinchStart.domain[1]-pinchStart.domain[0]);domain=[anchor-span*fraction,anchor+span*(1-fraction)];count=Math.min(900,Math.max(3,Math.round(pinchStart.count/g.scale)));center=(domain[0]+domain[1])/2;scheduleRender()},end:()=>{if(!pinchStart)return;pinchStart=null;drag=null;wanted=null;load()}}));
  new ResizeObserver(()=>{if(dialog.open && points.length && !drag)render()}).observe(plot);
})();
