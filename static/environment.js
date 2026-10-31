(() => {
'use strict';
const {request,post,action,notice,badge,errorText}=window.GM;
const nodes={};
for(const id of ["environment", "environment-title", "source-type", "source-note", "temperature", "humidity", "light", "set-simulated", "fetch-weather", "refresh", "status", "state-time", "load-samples", "sample-status", "sample-summary", "sample-history"]){const node=window.GM.$(id);if(!node)return;nodes[id]=node;}
const $=id=>nodes[id];
function renderState(state){for(const key of ['temperature','humidity','light'])$(key).textContent=state[key];$('source-type').textContent=state.source_type;$('source-type').className='badge '+(state.source_type==='REAL_WEATHER'?'real':'sim');$('source-note').textContent={SIMULATED:'模拟环境，非真实传感器读数。',REAL_WEATHER:'温湿度来自户外天气 API；光照是保留值，并非天气实测。',MANUAL:'手动设置的参数，非真实传感器读数。'}[state.source_type]||'请核对数据来源。';$('state-time').textContent='状态时间：'+state.timestamp;$('set-simulated').setAttribute('aria-pressed',String(state.source_type==='SIMULATED'));$('fetch-weather').setAttribute('aria-pressed',String(state.source_type==='REAL_WEATHER'));}
async function refreshState(){renderState(await request('/api/state'));notice('status','状态已更新。');}
$('refresh').onclick=()=>action($('refresh'),'status',refreshState);
for(const [id,source] of [['set-simulated','SIMULATED'],['fetch-weather','REAL_WEATHER']])$(id).onclick=()=>action($(id),'status',async()=>{renderState(await post('/api/set-source',{source}));notice('status',source==='SIMULATED'?'已恢复模拟数据 24°C / 65% / 12000 lux。':'已更新为真实户外天气。');});
$('load-samples').onclick=()=>action($('load-samples'),'sample-status',async()=>{const data=await request('/api/environment/history');$('sample-summary').textContent=`${data.count} 条样本 · ${data.source} · 最近 ${data.hours} 小时`;$('sample-history').replaceChildren(...data.items.map(row=>{const p=document.createElement('div');p.className='history-message';p.textContent=`${row.timestamp} · ${row.temperature}°C / ${row.humidity}% / ${row.light} lux · ${row.source_type}`;return p;}));notice('sample-status',data.count?'历史样本已加载；seed_demo 为模拟演示数据。':'当前时间范围内暂无样本，请检查演示数据时间。');});
refreshState().catch(error=>notice('status',errorText(error),true));
})();
