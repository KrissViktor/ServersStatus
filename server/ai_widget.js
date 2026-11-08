(() => {
  const box=document.querySelector('#ai-widget'),button=document.querySelector('#ai-launcher'),body=document.querySelector('#ai-widget-body');
  if(!box||!button)return;
  let loaded=false,loading=false,previous=null;
  function close(){box.hidden=true;button.setAttribute('aria-expanded','false');(previous?.isConnected?previous:button).focus({preventScroll:true})}
  async function load(){
    if(loaded||loading)return;loading=true;
    body.replaceChildren(Object.assign(document.createElement('p'),{textContent:'Загрузка чата…'}));
    try{
      const response=await fetch('/ai',{credentials:'same-origin',cache:'no-store'});
      if(!response.ok||response.redirected)throw Error('Сеанс завершён или доступ изменён. Войдите в портал снова.');
      const doc=new DOMParser().parseFromString(await response.text(),'text/html'),chat=doc.querySelector('.ai-chat');
      if(!chat)throw Error('Не удалось загрузить чат.');
      // Mount only the trusted same-origin chat section, never page scripts.
      body.replaceChildren(document.importNode(chat,true));window.initializeAIChat(body.querySelector('.ai-chat'));loaded=true;
      if(!box.hidden)body.querySelector('#ai-question')?.focus({preventScroll:true});
    }catch(error){
      const text=document.createElement('p'),retry=document.createElement('button');text.textContent=error.message;retry.type='button';retry.textContent='Повторить';retry.addEventListener('click',load);body.replaceChildren(text,retry);
    }finally{loading=false}
  }
  button.addEventListener('click',()=>{
    if(!box.hidden){close();return}
    previous=document.activeElement;box.hidden=false;button.setAttribute('aria-expanded','true');
    document.querySelector('#ai-widget-close').focus({preventScroll:true});load();
  });
  document.querySelector('#ai-widget-close').addEventListener('click',close);
  box.addEventListener('keydown',event=>{if(event.key==='Escape'){event.preventDefault();event.stopPropagation();close()}});
})();
