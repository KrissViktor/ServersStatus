(() => {
  const ns='http://www.w3.org/2000/svg';
  const graphs=()=>[...document.querySelectorAll('.history-chart[data-chart-start]:not([data-resource-metric]),.comparison-chart[data-chart-start],.server-detail .task-graph[data-chart-start]:not([data-resource-metric])')];
  let frame=null,pending=null;
  function sync(source,clientX,focusPoint){
    const matrix=source.getScreenCTM();if(!matrix)return;
    const point=new DOMPoint(clientX,0).matrixTransform(matrix.inverse());
    const start=Number(source.dataset.chartStart),end=Number(source.dataset.chartEnd),left=Number(source.dataset.chartLeft),right=Number(source.dataset.chartRight);
    const ratio=Math.max(0,Math.min(1,(point.x-left)/(right-left)));
    const selected=focusPoint?((Number(focusPoint.dataset.detailFirst)+Number(focusPoint.dataset.detailLast))/2):start+ratio*(end-start);
    const when=new Date(selected*1000).toLocaleString('ru-RU',{timeZone:'Europe/Moscow'});
    for(const graph of graphs()){
      if(graph.checkVisibility&&!graph.checkVisibility({contentVisibilityAuto:true,visibilityProperty:true}))continue;
      const box=graph.getBoundingClientRect();if(!box.width||box.bottom<0||box.top>innerHeight)continue;
      let line=graph.querySelector('.synced-chart-cursor');if(!line){line=document.createElementNS(ns,'line');line.classList.add('synced-chart-cursor');graph.append(line)}
      const from=Number(graph.dataset.chartStart),to=Number(graph.dataset.chartEnd),min=Number(graph.dataset.chartLeft),max=Number(graph.dataset.chartRight);
      if(selected<from||selected>to){line.style.display='none';continue}
      const x=min+(selected-from)/(to-from)*(max-min);line.style.display='';line.setAttribute('x1',x);line.setAttribute('x2',x);line.setAttribute('y1',graph.dataset.chartTop);line.setAttribute('y2',graph.dataset.chartBottom);
      let label=graph.parentElement.querySelector(':scope > .chart-cursor-info');if(!label){label=document.createElement('p');label.className='chart-cursor-info';graph.after(label)}
      const samples=[...graph.querySelectorAll('circle[data-detail-first]')];let distance=Infinity,closest=[];
      for(const sample of samples){const d=Math.abs(Number(sample.getAttribute('cx'))-x);if(d<distance-.5){distance=d;closest=[sample]}else if(Math.abs(d-distance)<.5)closest.push(sample)}
      label.textContent='Время курсора: '+when+' МСК · '+(distance<=(max-min)*.03?closest.map(sample=>sample.querySelector('title')?.textContent||sample.getAttribute('aria-label')).filter(Boolean).join(' · '):'Рядом нет полученных измерений');
    }
  }
  document.addEventListener('pointermove',event=>{const graph=event.target.closest('svg[data-chart-start]');if(!graph||!graphs().includes(graph))return;pending=[graph,event.clientX,null];if(!frame)frame=requestAnimationFrame(()=>{frame=null;sync(...pending)})});
  document.addEventListener('focusin',event=>{const point=event.target.closest('circle[data-detail-first]'),graph=point?.closest('svg[data-chart-start]');if(graph&&graphs().includes(graph))sync(graph,graph.getBoundingClientRect().left,point)});
})();
