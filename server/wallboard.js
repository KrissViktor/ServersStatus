(()=>{
  const root=document.querySelector('.wallboard');if(!root)return;
  document.body.classList.add('wallboard-page');
  const grid=document.getElementById('wallboard-grid'),summary=document.getElementById('wallboard-summary'),status=document.getElementById('wallboard-status'),clock=document.getElementById('wallboard-clock');
  let prior=new Map(),pending=false,last=0;
  const text=(tag,value,className='')=>{const node=document.createElement(tag);node.textContent=value;node.className=className;return node};
  function render(data){
    const cards=[];let online=0,offline=0,problems=0;
    for(const item of data.items){
      if(item.state==='online')online++;if(item.state==='offline')offline++;if(item.issues.length)problems++;
      const bad=item.state==='offline'||item.issues.length>0,card=text('article','','wallboard-tile wallboard-'+item.state+(bad?' has-problem':'')+(bad&&prior.get(item.id)===false?' new-problem':''));
      const head=text('header','');const link=text('a',item.name);link.href='/servers/'+encodeURIComponent(item.id);head.append(link,text('span',item.state==='online'?'● Онлайн':item.state==='offline'?'● Нет связи':'● Нет данных','badge '+(item.state==='online'?'normal':item.state==='offline'?'danger':'neutral')));card.append(head);
      const metrics=text('div','','wallboard-metrics');for(const [label,value] of [['CPU',item.cpu],['RAM',item.ram],['Диск',item.disk_max]]){const block=text('div','');block.append(text('small',label),text('strong',value==null?'—':Number(value).toFixed(0)+'%'));metrics.append(block)}card.append(metrics);
      for(const problem of item.issues)card.append(text('p',problem,'wallboard-issue'));
      card.append(text('small',item.age_seconds==null?'Ожидаем первый отчёт':(item.state==='offline'?'Устаревшие данные · ':'')+'отчёт '+Math.floor(item.age_seconds)+' с назад','muted'));cards.push(card);prior.set(item.id,bad);
    }
    grid.replaceChildren(...cards);if(!cards.length)grid.append(text('p','В этой группе нет активных серверов.','empty'));
    summary.replaceChildren(text('span','Онлайн '+online,'text-normal'),text('span','Нет связи '+offline,offline?'text-danger':'muted'),text('span','Требуют внимания '+problems,problems?'text-warning':'muted'));last=Date.now();status.textContent='Обновлено '+new Date(data.checked_at*1000).toLocaleTimeString('ru-RU',{timeZone:'Europe/Moscow'})+' МСК · автообновление 10 с';
  }
  render(JSON.parse(document.getElementById('wallboard-seed').textContent));
  setInterval(()=>{clock.textContent=new Date().toLocaleString('ru-RU',{timeZone:'Europe/Moscow',hour12:false})+' МСК';if(last&&Date.now()-last>30000)status.textContent='Нет свежего ответа портала. Показаны последние полученные данные.'},1000);
  setInterval(async()=>{if(pending)return;pending=true;try{const response=await fetch(root.dataset.wallboardUrl,{credentials:'same-origin',cache:'no-store'});if(response.status===401){status.textContent='Сессия завершена. Вернитесь в обзор и войдите снова.';last=0;return}if(!response.ok)throw Error();render(await response.json())}catch(_){status.textContent='Портал не отвечает. Последние данные сохранены на экране.'}finally{pending=false}},10000);
  document.getElementById('wallboard-fullscreen').addEventListener('click',async()=>{try{if(document.fullscreenElement)await document.exitFullscreen();else await document.documentElement.requestFullscreen()}catch(_){status.textContent='Полный экран недоступен в этом браузере.'}});
})();
