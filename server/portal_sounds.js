(() => {
  const preference='server-pulse-sounds';
  const patterns={
    ai:[523,659,784],
    offline:[392,294,220],
    telegram:[440,330,440],
    problem:[494,587,494,659],
  };
  const Audio=window.AudioContext||window.webkitAudioContext;
  const buttons=[...document.querySelectorAll('[data-portal-sounds]')];
  let enabled=false, context, nextNote=0, previous;
  try{enabled=localStorage.getItem(preference)==='on'}catch(_){}
  function sync(){
    for(const button of buttons){
      button.hidden=!Audio;
      button.setAttribute('aria-pressed',String(enabled));
    }
  }
  async function unlock(){
    if(!Audio||!enabled)return;
    try{
      context??=new Audio();
      if(context.state!=='running')await context.resume();
    }catch(_){}
  }
  function play(event){
    if(!enabled||context?.state!=='running'||!patterns[event])return;
    const now=Date.now(), key=preference+'-'+event;
    try{
      if(now-Number(localStorage.getItem(key)||0)<3000)return;
      localStorage.setItem(key,String(now));
    }catch(_){}
    const start=Math.max(context.currentTime+.015,nextNote);
    for(const [index,frequency] of patterns[event].entries()){
      const time=start+index*.18;
      const oscillator=context.createOscillator(), envelope=context.createGain();
      oscillator.type='sine';oscillator.frequency.value=frequency;
      envelope.gain.setValueAtTime(.0001,time);
      envelope.gain.exponentialRampToValueAtTime(.07,time+.045);
      envelope.gain.exponentialRampToValueAtTime(.0001,time+.28);
      oscillator.connect(envelope);envelope.connect(context.destination);
      oscillator.start(time);oscillator.stop(time+.29);
    }
    nextNote=start+patterns[event].length*.18+.14;
  }
  function observe(snapshot){
    if(!snapshot)return;
    if(previous){
      let offline=false,problem=false;
      for(const [id,state,issues] of snapshot){
        const old=previous.get(id);
        if(!old)continue;
        if(state==='offline'&&old[0]!=='offline')offline=true;
        if(issues.some(issue=>!old[1].includes(issue)))problem=true;
      }
      if(offline)play('offline');
      if(problem)play('problem');
    }
    previous=new Map(snapshot.map(([id,state,issues])=>[id,[state,issues]]));
  }
  function overview(element){
    if(element?.dataset.soundSnapshot)observe(JSON.parse(element.dataset.soundSnapshot));
  }
  function wallboard(data){
    observe(data.items.map(item=>[item.id,item.state,item.issues.filter(issue=>issue!=='Нет связи с агентом')]));
  }
  window.portalSounds={play,overview,wallboard};
  overview(document.getElementById('server-results'));
  const seed=document.getElementById('wallboard-seed');
  if(seed)wallboard(JSON.parse(seed.textContent));
  sync();
  for(const button of buttons)button.addEventListener('click',async()=>{
    enabled=!enabled;
    try{localStorage.setItem(preference,enabled?'on':'off')}catch(_){}
    sync();
    if(enabled){await unlock();play('ai')}
  });
  document.addEventListener('pointerdown',unlock);
  document.addEventListener('keydown',unlock);
  window.addEventListener('storage',event=>{
    if(event.key===preference){enabled=event.newValue==='on';sync()}
  });
})();
