/* Home owns readings only; evidence and business actions live on their pages. */
(() => {
'use strict';
const {request,notice}=window.GM;
const nodes={};
for(const id of ['home','hero-temperature','hero-humidity','hero-light','hero-source-type','home-status']){const node=window.GM.$(id);if(!node)return;nodes[id]=node;}
const $=id=>nodes[id];
const reduced=matchMedia('(prefers-reduced-motion: reduce)');
let state=null,visible=false,animated=false,frame=0;
function showValues(value){for(const key of ['temperature','humidity','light']){const node=$('hero-'+key);if(!node)return;node.textContent=String(value[key]);}}
function display(){
 if(!state)return;
 if(!visible&&!animated)return;
 if(animated||reduced.matches){cancelAnimationFrame(frame);animated=true;showValues(state);return;}
 animated=true;const start=performance.now();
 function tick(now){if(!state)return;const p=Math.min(1,(now-start)/250);if(p===1||reduced.matches){showValues(state);frame=0;return;}
 for(const key of ['temperature','humidity','light']){const node=$('hero-'+key);if(!node)return;node.textContent=key==='light'?String(Math.round(Number(state[key])*p)):(Number(state[key])*p).toFixed(1);}
 frame=requestAnimationFrame(tick);}
 frame=requestAnimationFrame(tick);
}
function render(value){state=value;const node=$('hero-source-type');if(!node)return;node.textContent={SIMULATED:'SIMULATED · 模拟数据',REAL_WEATHER:'REAL_WEATHER · 户外天气',MANUAL:'MANUAL · 手动设置'}[value.source_type]||value.source_type;node.className='badge '+(value.source_type==='REAL_WEATHER'?'real':'sim');window.__gmState=value;window.updateGreenhouseScene?.(value);display();}
async function refresh(){try{render(await request('/api/state'));notice('home-status','');}catch(error){notice('home-status',error.message,true);}}
new IntersectionObserver(entries=>{visible=entries[0].isIntersecting;if(visible)display();},{threshold:.05}).observe($('home'));
reduced.addEventListener('change',()=>{if(reduced.matches&&state){cancelAnimationFrame(frame);animated=true;showValues(state);}});
addEventListener('pageshow',event=>{if(event.persisted)refresh();});
document.addEventListener('visibilitychange',()=>{if(!document.hidden)refresh();});
refresh();
})();
