(() => {
  document.addEventListener('click',event=>{
    const button=event.target.closest('.agent-disclosure');if(!button)return;
    const body=document.getElementById(button.getAttribute('aria-controls'));
    body.hidden=!body.hidden;button.setAttribute('aria-expanded',String(!body.hidden));
  });
  document.addEventListener('change',async event=>{
    const input=event.target,form=input.closest('.agent-flag-form');if(!form || input.type!=='checkbox')return;
    const status=form.closest('.agent-card').querySelector('.agent-flag-status'),enabled=input.checked;
    input.disabled=true;status.textContent='Сохраняем…';
    const body=new URLSearchParams(new FormData(form));
    // Disabled inputs are omitted by FormData; explicitly send this flag's value.
    if(enabled)body.set('enabled','1');else body.delete('enabled');
    try{
      const response=await fetch(form.action,{method:'POST',credentials:'same-origin',headers:{'Accept':'application/json','Content-Type':'application/x-www-form-urlencoded'},body});
      if(!response.ok)throw new Error();const result=await response.json();if(!result.ok)throw new Error();
      status.textContent='Сохранено';
    }catch(_){input.checked=!enabled;status.textContent='Не удалось сохранить. Повторите изменение.'}
    finally{input.disabled=false}
  });
})();
