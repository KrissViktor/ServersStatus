/* Monotone cubic interpolation: passes through samples without inventing peaks. */
(() => {
  function path(points){
    if(!points.length)return '';
    let result=`M ${points[0][0]},${points[0][1]}`;if(points.length===1)return result;
    const slopes=points.slice(1).map((p,i)=>(p[1]-points[i][1])/(p[0]-points[i][0]||1)),tangent=points.map((_,i)=>i===0?slopes[0]:i===points.length-1?slopes.at(-1):slopes[i-1]*slopes[i]<=0?0:2*slopes[i-1]*slopes[i]/(slopes[i-1]+slopes[i]));
    for(let i=0;i<slopes.length;i++){
      const a=points[i],b=points[i+1],dx=b[0]-a[0],s=slopes[i];if(dx<=0){result+=` L ${b[0]},${b[1]}`;continue}
      let m=tangent[i],n=tangent[i+1];if(!s)m=n=0;else{const magnitude=Math.hypot(m/s,n/s);if(magnitude>3){m*=3/magnitude;n*=3/magnitude}}
      result+=` C ${a[0]+dx/3},${a[1]+m*dx/3} ${b[0]-dx/3},${b[1]-n*dx/3} ${b[0]},${b[1]}`;
    }
    return result;
  }
  function pinch(element,callbacks){
    let gesture=null,frame=null,latest=null;const pointers=new Set();
    element.addEventListener('pointerdown',event=>{if(event.pointerType==='touch')pointers.add(event.pointerId)},{passive:true});
    const geometry=touches=>{const a=touches[0],b=touches[1];return {distance:Math.max(1,Math.hypot(a.clientX-b.clientX,a.clientY-b.clientY)),x:(a.clientX+b.clientX)/2,y:(a.clientY+b.clientY)/2}};
    element.addEventListener('touchstart',event=>{if(event.touches.length!==2)return;event.preventDefault();gesture=geometry(event.touches);for(const id of pointers)try{element.setPointerCapture(id)}catch(_){}callbacks.start?.(gesture)},{passive:false});
    element.addEventListener('touchmove',event=>{if(!gesture||event.touches.length!==2)return;event.preventDefault();const current=geometry(event.touches);latest={scale:current.distance/gesture.distance,x:current.x,y:current.y};if(!frame)frame=requestAnimationFrame(()=>{frame=null;if(gesture&&latest)callbacks.move?.(latest)})},{passive:false});
    const end=()=>{if(!gesture)return;if(frame){cancelAnimationFrame(frame);frame=null;if(latest)callbacks.move?.(latest)}callbacks.end?.();gesture=latest=null;for(const id of pointers)try{if(element.hasPointerCapture(id))element.releasePointerCapture(id)}catch(_){}pointers.clear()};
    element.addEventListener('pointerup',event=>{pointers.delete(event.pointerId);if(gesture)end()},{passive:true});
    element.addEventListener('pointercancel',event=>{pointers.delete(event.pointerId);if(gesture)end()},{passive:true});
    element.addEventListener('touchend',end,{passive:true});element.addEventListener('touchcancel',end,{passive:true});
  }
  window.portalGeometry={path,pinch};
})();
