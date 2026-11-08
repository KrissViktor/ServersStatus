(() => {
  const panel=document.getElementById('remote-console'),form=panel?.querySelector('#console-form'),input=form?.querySelector('textarea[name=command]');
  if(!input)return;
  const list=panel.querySelector('#console-completions'),count=panel.querySelector('#console-editor-count');
  const windows=panel.dataset.shell==='powershell';
  const catalog=/*CONSOLE_CATALOG*/{};
  const {commands,parameters,examples}=catalog[windows?'windows':'linux'];
  let items=[],selected=0,range=null,composing=false;
  const node=(tag,text)=>{const n=document.createElement(tag);n.textContent=text;return n};
  function hide(){list.hidden=true;input.setAttribute('aria-expanded','false');input.removeAttribute('aria-activedescendant')}
  function updateCount(){const lines=input.value?input.value.split('\n').filter(s=>s.trim()).length:0;count.textContent='Строк: '+lines+' · '+input.value.length+'/4000';}
  function context(){
    const end=input.selectionStart,before=input.value.slice(0,end),match=before.match(/[\p{L}\p{N}_./:$%=-]*$/u),token=match?.[0]||'',start=end-token.length;
    const segment=before.slice(0,start).split(/[\n;|&]/).at(-1).trim();
    return {start,end,token,command:segment.split(/\s+/)[0].toLowerCase(),first:!segment};
  }
  function paint(){
    list.replaceChildren();items.forEach((item,i)=>{const option=node('div','');option.id='console-completion-'+i;option.role='option';option.setAttribute('aria-selected',String(i===selected));option.append(node('strong',item.label),node('small',item.help));option.addEventListener('mousedown',e=>e.preventDefault());option.addEventListener('click',()=>choose(i));list.append(option)});
    list.hidden=!items.length;input.setAttribute('aria-expanded',String(!!items.length));
    if(items.length){input.setAttribute('aria-activedescendant','console-completion-'+selected);const option=list.children[selected];if(option.offsetTop<list.scrollTop)list.scrollTop=option.offsetTop;else if(option.offsetTop+option.offsetHeight>list.scrollTop+list.clientHeight)list.scrollTop=option.offsetTop+option.offsetHeight-list.clientHeight}else hide();
  }
  function suggest(force=false){
    updateCount();if(composing||input.selectionStart!==input.selectionEnd){hide();return}
    range=context();if(!force&&!range.token&&range.first){hide();return}
    const q=range.token.toLocaleLowerCase('ru');
    const candidates=range.first?[...commands.map(([label,help])=>({label,insert:label,help})),...examples]:
      (parameters[range.command]||[]).map(label=>({label,insert:label,help:'Параметр / аргумент '+range.command}));
    const rank=v=>{const name=v.label.toLocaleLowerCase('ru');return !q?0:name===q?0:name.startsWith(q)?1:name.includes(q)?2:3};
    items=candidates.filter(v=>(!q||v.label.toLocaleLowerCase('ru').includes(q)||v.help.toLocaleLowerCase('ru').includes(q))&&v.insert!==range.token).sort((a,b)=>rank(a)-rank(b));
    count.textContent+=' · Подсказок: '+items.length;

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
