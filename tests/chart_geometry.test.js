const assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm');const context={window:{}};vm.runInNewContext(fs.readFileSync('server/chart_geometry.js','utf8'),context);const path=context.window.portalGeometry.path;
assert.equal(path([]),'');assert.equal(path([[2,4]]),'M 2,4');
for(const samples of [[[0,0],[1,100],[2,0],[3,50]],[[0,20],[1,20],[2,20]],[[0,100],[1,95],[3,20],[7,0]],[[0,0],[.01,1],[100,3]]]){
 const p=path(samples);assert(!p.includes('NaN'));const parts=[...p.matchAll(/C ([\d.e+-]+),([\d.e+-]+) ([\d.e+-]+),([\d.e+-]+) ([\d.e+-]+),([\d.e+-]+)/g)];assert.equal(parts.length,samples.length-1);
 for(let i=0;i<parts.length;i++){const n=parts[i].slice(1).map(Number),a=samples[i],b=samples[i+1];for(let step=0;step<=100;step++){const t=step/100,v=(1-t)**3*a[1]+3*(1-t)**2*t*n[1]+3*(1-t)*t*t*n[3]+t**3*b[1];assert(v>=Math.min(a[1],b[1])-1e-8&&v<=Math.max(a[1],b[1])+1e-8,'Interpolation invented an overshoot')}}
}
assert(!path([[0,20],[0,40],[1,30]]).includes('NaN'));console.log('Monotone chart interpolation: passed');
// A redraw can remove the original SVG touch target: pointer capture must still
// finish the gesture even when touchend never bubbles back to the chart.
const frames=new Map();let frameId=0;context.requestAnimationFrame=fn=>{frames.set(++frameId,fn);return frameId};context.cancelAnimationFrame=id=>frames.delete(id);
const handlers={},captures=new Set(),element={addEventListener:(name,fn)=>(handlers[name]??=[]).push(fn),setPointerCapture:id=>captures.add(id),hasPointerCapture:id=>captures.has(id),releasePointerCapture:id=>captures.delete(id)};
let starts=0,ends=0,scale=null;context.window.portalGeometry.pinch(element,{start:()=>starts++,move:g=>scale=g.scale,end:()=>ends++});
const emit=(name,event)=>{for(const fn of handlers[name]||[])fn(event)};
emit('pointerdown',{pointerType:'touch',pointerId:1});emit('pointerdown',{pointerType:'touch',pointerId:2});
emit('touchstart',{touches:[{clientX:10,clientY:20},{clientX:30,clientY:20}],preventDefault(){}});
emit('touchmove',{touches:[{clientX:0,clientY:20},{clientX:40,clientY:20}],preventDefault(){}});
emit('pointerup',{pointerId:1});emit('touchend',{});
assert.equal(starts,1);assert.equal(ends,1);assert.equal(scale,2);assert.equal(frames.size,0);
let blocked=false;emit('touchstart',{touches:[{clientX:0,clientY:0}],preventDefault(){blocked=true}});assert.equal(blocked,false);
console.log('Pinch completion without touchend: passed');
