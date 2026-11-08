(() => {
  const dialog=document.getElementById('chart-detail');if(!dialog)return;
  const plot=dialog.querySelector('#detail-chart-plot'),status=dialog.querySelector('#detail-chart-status'),countLabel=dialog.querySelector('#detail-chart-count'),info=dialog.querySelector('#detail-point-info');
  let center=0,count=30,metric='cpu',name='',points=[],unit='%',pending=null,version=0,domain=[0,1],drag=null;
  const svgNS='http://www.w3.org/2000/svg';
  function node(tag,attributes={},text=''){const n=document.createElementNS(svgNS,tag);for(const [k,v] of Object.entries(attributes))n.setAttribute(k,v);if(text)n.textContent=text;return n}
  const stamp=t=>new Date(t*1000).toLocaleString('ru-RU',{timeZone:'Europe/Moscow',hour12:false})+' МСК';
  function size(v){if(v==null)return '—';let i=0;const units=['Б','Кб','Мб','Гб','Тб'];while(Math.abs(v)>=1024 && i<4){v/=1024;i++}return v.toLocaleString('ru-RU',{maximumFractionDigits:1})+' '+units[i]}
  const format=v=>unit==='%'?v.toFixed(1)+'%':unit==='bytes/s'?size(v)+'/с':v.toFixed(1)+' оп/с';
  function render(offset=0){
    const w=Math.max(300,plot.clientWidth),h=Math.max(220,plot.clientHeight),left=85,right=w-18,top=20,bottom=h-42;
    const start=domain[0]+offset,end=domain[1]+offset,span=Math.max(1,end-start);
    const maximum=unit==='%'?100:Math.max(1,...points.map(p=>p.value==null?0:p.value*1.1));
    const x=t=>left+(t-start)/span*(right-left),y=v=>bottom-v/maximum*(bottom-top);
    const svg=node('svg',{viewBox:`0 0 ${w} ${h}`,role:'img','aria-label':'Исходные отчёты сервера'});
    for(const ratio of [0,.25,.5,.75,1]){
      const v=maximum*ratio;svg.append(node('line',{x1:left,x2:right,y1:y(v),y2:y(v),class:'chart-grid'}),node('text',{x:left-8,y:y(v)+4,'text-anchor':'end',class:'chart-label'},format(v)));
    }
    const axisStamp=t=>w<700?new Date(t*1000).toLocaleTimeString('ru-RU',{timeZone:'Europe/Moscow',hour12:false}):stamp(t);
    for(const f of [0,.5,1])svg.append(node('text',{x:left+f*(right-left),y:h-12,'text-anchor':f===0?'start':f===1?'end':'middle',class:'chart-label'},axisStamp(start+span*f)));
    let previous=null;
    for(const p of points){
      if(p.value==null){previous=null;continue}
      if(p.timestamp<start || p.timestamp>end){previous=null;continue}
      if(previous && p.timestamp-previous.timestamp<=180)svg.append(node('line',{x1:x(previous.timestamp),y1:y(previous.value),x2:x(p.timestamp),y2:y(p.value),stroke:'#83c4ff','stroke-width':1.7}));
      const circle=node('circle',{cx:x(p.timestamp),cy:y(p.value),r:3.5,fill:'#83c4ff',tabindex:'0',class:'detail-report-point'});
      let title=stamp(p.timestamp)+' · '+format(p.value);
      if(metric==='ram')title+=' · занято '+size(p.ram_used_bytes)+' из '+size(p.ram_total_bytes);
      circle.append(node('title',{},title));circle.addEventListener('pointerenter',()=>info.textContent=title);circle.addEventListener('focus',()=>info.textContent=title);svg.append(circle);previous=p;
    }
    plot.replaceChildren(svg);
  }
  async function load(first=null,last=null){
    if(pending)pending.abort();const controller=new AbortController();pending=controller;const current=++version;
    const url=new URL(dialog.dataset.url,location.origin);for(const [key,value] of Object.entries({center,count,metric,name}))url.searchParams.set(key,value);
    if(first!=null && last!=null){url.searchParams.set('first',first);url.searchParams.set('last',last)}
    status.textContent='Загрузка исходных отчётов…';plot.setAttribute('aria-busy','true');
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
      info.textContent='Наведите на точку для просмотра исходного отчёта.';
    }catch(error){if(error.name!=='AbortError' && current===version)status.textContent='Не удалось загрузить отчёты. Повторите изменение масштаба.'}
    finally{if(current===version){pending=null;plot.removeAttribute('aria-busy')}}
  }
  function zoom(out,anchor=.5){
    const next=out?Math.min(900,count*3):Math.max(3,Math.round(count/3));if(next===count)return;
    const span=domain[1]-domain[0];center=Math.max(0,center+(anchor-.5)*span*(1-next/count));count=next;load();
  }
  function pan(direction){center=Math.max(0,center+direction*Math.max(10,domain[1]-domain[0])*.6);load()}
  document.addEventListener('click',event=>{
    let point=event.target.closest('[data-detail-metric]');
    if(!point){
      const svg=event.target.closest('.history-chart,.task-graph');let nearest=19;
      if(svg)for(const candidate of svg.querySelectorAll('[data-detail-metric]')){
        const box=candidate.getBoundingClientRect(),distance=Math.hypot(event.clientX-box.x-box.width/2,event.clientY-box.y-box.height/2);
        if(distance<nearest){nearest=distance;point=candidate}
      }
    }
    if(!point)return;
    const card=point.closest('[data-server-id]');if(card)dialog.dataset.url='/api/history/'+encodeURIComponent(card.dataset.serverId)+'/detail';
    metric=point.dataset.detailMetric;name=point.dataset.detailName||'';
    const first=Number(point.dataset.detailFirst),last=Number(point.dataset.detailLast);
    center=(first+last)/2;count=Math.min(900,Math.max(30,Number(point.dataset.detailCount)||30));points=[];
    dialog.querySelector('h2').textContent=point.dataset.detailTitle||'Подробный график';plot.replaceChildren();dialog.showModal();load(first,last);
  });
  document.addEventListener('keydown',event=>{if((event.key==='Enter'||event.key===' ') && event.target.matches('[data-detail-metric]')){event.preventDefault();event.target.dispatchEvent(new MouseEvent('click',{bubbles:true}))}});
  dialog.querySelector('[data-detail-close]').addEventListener('click',()=>dialog.close());
  dialog.addEventListener('close',()=>{version++;pending?.abort();pending=null;drag=null});
  dialog.addEventListener('click',event=>{const zoomButton=event.target.closest('[data-zoom]'),panButton=event.target.closest('[data-pan]');if(zoomButton)zoom(zoomButton.dataset.zoom==='out');if(panButton)pan(Number(panButton.dataset.pan))});
  dialog.addEventListener('keydown',event=>{if(event.key==='ArrowLeft'||event.key==='ArrowRight'){event.preventDefault();pan(event.key==='ArrowLeft'?-1:1)}});
  plot.addEventListener('wheel',event=>{event.preventDefault();if(!pending)zoom(event.deltaY>0,Math.max(0,Math.min(1,(event.clientX-plot.getBoundingClientRect().left)/plot.clientWidth)))},{passive:false});
  plot.addEventListener('pointerdown',event=>{if(event.button!==0 || !points.length)return;event.preventDefault();drag={x:event.clientX,offset:0};plot.setPointerCapture(event.pointerId)});
  plot.addEventListener('pointermove',event=>{if(!drag)return;drag.offset=-(event.clientX-drag.x)/Math.max(1,plot.clientWidth-103)*(domain[1]-domain[0]);render(drag.offset)});
  plot.addEventListener('pointerup',()=>{if(!drag)return;const offset=drag.offset;drag=null;if(Math.abs(offset)>1){center=Math.max(0,center+offset);load()}else render()});
  plot.addEventListener('pointercancel',()=>{drag=null;render()});
  new ResizeObserver(()=>{if(dialog.open && points.length && !drag)render()}).observe(plot);
})();
