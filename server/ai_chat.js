window.initializeAIChat = (panel=document.querySelector('.ai-chat')) => {
  if(!panel||panel.dataset.initialized)return;panel.dataset.initialized='true';
  const form=panel.querySelector('#ai-form'),input=panel.querySelector('#ai-question'),history=panel.querySelector('#ai-messages'),list=panel.querySelector('#ai-chats'),send=panel.querySelector('#ai-send'),cancel=panel.querySelector('#ai-cancel'),fresh=panel.querySelector('#ai-new'),remove=panel.querySelector('#ai-delete'),message=panel.querySelector('#ai-message'),state=panel.closest('.ai-widget')?.querySelector('#ai-state')||document.querySelector('#ai-state');
  const portal=panel.querySelector('#ai-portal'),internet=panel.querySelector('#ai-internet'),searchBox=panel.querySelector('#ai-search-box'),query=panel.querySelector('#ai-search-query');
  internet.addEventListener('change',()=>{searchBox.hidden=!internet.checked});
  const labels={queued:'В очереди',running:'Печатает…',completed:'Готово',failed:'Ошибка',cancelled:'Остановлено'};
  let chat=null,busy=false,active=false,configured=false,timer=null,signature='',attempt=null;
  const id=()=>Array.from(crypto.getRandomValues(new Uint8Array(16)),n=>n.toString(16).padStart(2,'0')).join('');
  const node=(tag,text)=>{const n=document.createElement(tag);if(text!=null)n.textContent=text;return n};
  function controls(){send.disabled=busy||active||!configured;cancel.hidden=!active;cancel.disabled=busy;fresh.disabled=busy||active;list.disabled=busy||active;remove.disabled=!chat||busy;state.textContent=!configured?'Не настроено':active?'Модель отвечает':'Локальная модель';state.className='badge '+(active?'warning':configured?'normal':'neutral')}
  async function request(url,options={}){
    const response=await fetch(url,{credentials:'same-origin',cache:'no-store',...options});
    if(response.status===401||response.status===403){clearTimeout(timer);configured=false;controls();throw Error('Сеанс завершён или доступ изменён. Войдите в портал снова.')}
    let result;try{result=await response.json()}catch(_){throw Error('Не удалось получить ответ портала')}
    if(!response.ok)throw Error(typeof result.detail==='string'?result.detail:'Запрос не выполнен');return result;
  }
  function post(url,body){return request(url,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({csrf:panel.dataset.aiCsrf,...body})})}
  function empty(){history.replaceChildren();const block=node('div');block.className='ai-empty';block.append(node('span','✦'),node('h2','Чем помочь?'),node('p','Спросите о состоянии серверов или найдите решение в интернете.'),node('small','Метрики и журнал — только чтение. Интернет включён по умолчанию.'));history.append(block)}
  function render(turns){
    const next=JSON.stringify(turns);active=turns.some(t=>['queued','running'].includes(t.status));controls();if(next===signature)return;signature=next;
    const follow=history.scrollHeight-history.clientHeight-history.scrollTop<70,top=history.scrollTop,fragment=document.createDocumentFragment();
    for(const turn of turns){
      const q=node('article');q.className='ai-bubble ai-user';q.append(node('span','Вы'),node('p',turn.question));fragment.append(q);
      const answer=node('article');answer.className='ai-bubble ai-assistant';const header=node('header'),label=node('span','✦ Помощник'),status=node('small',labels[turn.status]||turn.status);header.append(label,status);answer.append(header);
      const text=node('div',turn.reply||(['queued','running'].includes(turn.status)?'Ожидаем ответ…':'Ответ отсутствует'));text.className='ai-answer';answer.append(text);
      if(turn.tools?.length){
        const details=node('details'),summary=node('summary','Источники и действия · '+turn.tools.length);details.className='ai-sources';details.append(summary);
        for(const t of turn.tools){const row=node('div'),label=node('span','[S'+t.id+'] '+t.label);row.append(label,node('small',t.status==='running'?'Чтение…':t.status==='failed'?(t.error||'Ошибка'):t.name==='web_search'?'Получены результаты':'Прочитано'));
          if(t.url&&t.status==='completed'){try{const url=new URL(t.url,location.origin);if(['http:','https:'].includes(url.protocol)){const link=node('a','Открыть источник ↗');link.href=url.href;link.target='_blank';link.rel='noopener noreferrer';row.append(link)}}catch(_){}}
          details.append(row);
        }answer.append(details);
      }
      if(turn.error){const error=node('p',turn.error);error.className='text-danger';answer.append(error)}
      if(turn.reply){const copy=node('button','Копировать');copy.type='button';copy.className='ai-copy';copy.addEventListener('click',async()=>{try{await navigator.clipboard.writeText(turn.reply);copy.textContent='Скопировано'}catch(_){message.textContent='Не удалось скопировать. Выделите нужный текст.'}});answer.append(copy)}
      fragment.append(answer);
    }
    history.replaceChildren(fragment);history.scrollTop=follow?history.scrollHeight:top;
  }
  async function load(){
    clearTimeout(timer);const wanted=chat;if(!wanted||document.hidden){if(wanted)timer=setTimeout(load,2000);return}
    try{const result=await request('/api/ai/chat/'+wanted);if(chat!==wanted)return;render(result.turns);if(active)timer=setTimeout(load,1000)}catch(error){message.textContent=error.message;if(chat===wanted&&configured)timer=setTimeout(load,5000)}
  }
  async function chats(initial=false){
    const result=await request('/api/ai/chats');configured=result.configured;
    if(initial)chat=result.active||result.chats[0]?.chat||null;
    list.replaceChildren();const option=node('option','Новый диалог');option.value='';list.append(option);
    for(const c of result.chats){const n=node('option',c.title);n.value=c.chat;list.append(n)}
    if(chat&&!result.chats.some(c=>c.chat===chat)){const n=node('option','Текущий диалог');n.value=chat;list.append(n)}
    list.value=chat||'';controls();if(!configured)message.textContent='Администратор ещё не настроил подключение локальной модели.';
  }
  form.addEventListener('submit',async event=>{
    event.preventDefault();if(busy||active||!configured||!input.value.trim()||!form.reportValidity())return;
    busy=true;controls();message.textContent='Отправляем…';
    const text=input.value.trim(),target=chat||attempt?.chat||id(),options={portal_access:portal.checked,internet_access:internet.checked,web_query:internet.checked?query.value.trim():''};
    if(!attempt||attempt.question!==text||attempt.chat!==target||Object.keys(options).some(k=>attempt[k]!==options[k]))attempt={chat:target,nonce:id(),question:text,...options};
    try{const result=await post('/api/ai/ask',attempt);chat=result.chat;if(input.value.trim()===text)input.value='';attempt=null;message.textContent='';await chats();await load()}
    catch(error){message.textContent=error.message}
    finally{busy=false;controls()}
  });
  input.addEventListener('keydown',event=>{if(event.key==='Enter'&&!event.shiftKey&&!event.isComposing){event.preventDefault();if(!send.disabled)form.requestSubmit()}});
  fresh.addEventListener('click',()=>{clearTimeout(timer);chat=null;attempt=null;active=false;signature='';list.value='';empty();message.textContent='';controls();input.focus({preventScroll:true})});
  list.addEventListener('change',()=>{chat=list.value||null;attempt=null;signature='';message.textContent='';active=false;controls();if(chat)load();else{clearTimeout(timer);empty()}});
  cancel.addEventListener('click',async()=>{if(!chat||busy)return;busy=true;controls();try{await post('/api/ai/chat/'+chat+'/cancel',{});await load()}catch(e){message.textContent=e.message}finally{busy=false;controls()}});
  remove.addEventListener('click',async()=>{if(!chat||busy||!confirm('Удалить этот диалог и его историю?'))return;busy=true;controls();try{await post('/api/ai/chat/'+chat+'/delete',{});clearTimeout(timer);chat=null;attempt=null;active=false;signature='';empty();await chats();message.textContent='Диалог удалён'}catch(e){message.textContent=e.message}finally{busy=false;controls()}});
  busy=true;controls();
  chats(true).then(()=>chat?load():controls()).catch(e=>{message.textContent=e.message}).finally(()=>{busy=false;controls()});
};
window.initializeAIChat();
