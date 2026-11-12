/* Small, cancellable transitions. Background refresh never animates whole lists. */
(() => {
  const reduced=()=>matchMedia('(prefers-reduced-motion: reduce)').matches;
  const animations=new WeakMap();
  function animate(node,frames,options={}){if(!node||reduced()||!node.animate)return;animations.get(node)?.cancel();const animation=node.animate(frames,{duration:180,easing:'cubic-bezier(.2,.7,.2,1)',...options});animations.set(node,animation);animation.onfinish=()=>animations.delete(node);return animation}
  function preserve(change,position=null){
    const x=position?.x??scrollX,y=position?.y??scrollY,modal=document.querySelector('dialog[open]'),modalY=modal?.scrollTop;
    document.body.style.minHeight=(innerHeight+y)+'px';document.body.dataset.scrollHeld='true';
    change();
    const restore=()=>{scrollTo({left:x,top:y,behavior:'instant'});if(modal&&modal.open){const maximum=modal.scrollHeight-modal.clientHeight;if(maximum<modalY)modal.style.paddingBottom=(parseFloat(getComputedStyle(modal).paddingBottom)+modalY-maximum)+'px';modal.scrollTop=modalY}};restore();requestAnimationFrame(restore);
  }
  let queued=false;window.addEventListener('scroll',()=>{if(queued||!document.body.dataset.scrollHeld)return;queued=true;requestAnimationFrame(()=>{queued=false;const main=document.querySelector('main');if(main&&main.getBoundingClientRect().bottom>=innerHeight){document.body.style.minHeight='';delete document.body.dataset.scrollHeld}})},{passive:true});
  function indicator(nav,button,initial=false){
    if(!nav||!button||!button.getClientRects().length)return;
    let mark=nav.querySelector(':scope>.selection-indicator');if(!mark){mark=document.createElement('span');mark.className='selection-indicator';mark.setAttribute('aria-hidden','true');nav.prepend(mark);initial=true}
    const y=button.offsetTop,x=button.offsetLeft,old={x:parseFloat(mark.style.left)||x,y:parseFloat(mark.style.top)||y};
    mark.style.width=button.offsetWidth+'px';mark.style.height=button.offsetHeight+'px';mark.style.left=x+'px';mark.style.top=y+'px';
    if(!initial)animate(mark,[{transform:`translate(${old.x-x}px,${old.y-y}px)`},{transform:'translate(0,0)'}],{duration:230});
  }
  window.portalMotion={animate,preserve,indicator,reduced,reveal:node=>animate(node,[{opacity:.25,transform:'translateY(4px)'},{opacity:1,transform:'translateY(0)'}])};
  document.addEventListener('pointerdown',event=>{const button=event.target.closest('button');if(button&&!button.disabled)animate(button,[{transform:'scale(1)'},{transform:'scale(.97)'},{transform:'scale(1)'}],{duration:190})},{passive:true});
  document.addEventListener('change',event=>{const input=event.target;if(input.matches('input[type=checkbox],input[type=radio]'))animate(input.closest('label')||input,[{filter:'brightness(1)'},{filter:'brightness(1.3)'},{filter:'brightness(1)'}],{duration:230})});
  let corePosition=null;document.addEventListener('pointerdown',event=>{if(event.target.closest('[data-cpu-cores]>summary'))corePosition={x:scrollX,y:scrollY}},{capture:true,passive:true});
  document.addEventListener('click',event=>{const summary=event.target.closest('[data-cpu-cores]>summary');if(!summary)return;event.preventDefault();const details=summary.parentElement;preserve(()=>{details.open=!details.open},corePosition);corePosition=null;if(details.open)window.portalMotion.reveal(details.querySelector('.cpu-cores-content'))},true);
})();
