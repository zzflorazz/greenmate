(() => {
'use strict';
const {request,post,action,notice,badge,errorText}=window.GM;
const nodes={};
for(const id of ["knowledge", "knowledge-title", "plant-list", "knowledge-form", "knowledge-query", "search-button", "knowledge-status", "knowledge-results", "reload-knowledge"]){const node=window.GM.$(id);if(!node)return;nodes[id]=node;}
const $=id=>nodes[id];
function showKnowledge(items){$('knowledge-results').replaceChildren(...items.map(item=>{const box=document.createElement('article');box.className='knowledge-item';const title=document.createElement('h3');title.textContent=item.name;const overview=document.createElement('p');overview.textContent=`光照：${item.light}；浇水：${item.water_freq}`;const tips=document.createElement('p');tips.textContent=item.tips;box.append(title,overview,tips);if(item.citation){const citation=document.createElement('p');citation.className='small';citation.textContent=`citation：${item.citation.id} · ${item.citation.name} · ${item.citation.snippet}`;box.append(citation);}return box;}));}
async function loadKnowledge(){const items=await request('/api/knowledge');$('plant-list').replaceChildren(...items.map(item=>{const button=document.createElement('button');button.type='button';button.textContent=item.name;button.onclick=()=>{showKnowledge([item]);notice('knowledge-status','本地条目 · '+item.name);};return button;}));notice('knowledge-status',`已加载 ${items.length} 种植物，选择条目或搜索。`);}
$('knowledge-form').onsubmit=event=>{event.preventDefault();const query=$('knowledge-query').value.trim();if(!query){notice('knowledge-status','请先填写搜索内容。',true);return;}action($('search-button'),'knowledge-status',async()=>{const data=await request('/api/knowledge/search?query='+encodeURIComponent(query));showKnowledge(data.items);notice('knowledge-status',data.items.length?`语义检索命中 ${data.items.length} 条；模型不可用时自动回退关键词，中文排序仅供参考。`:'查询已完成，未找到匹配知识；这不表示服务故障。');});};
$('reload-knowledge').onclick=()=>action($('reload-knowledge'),'knowledge-status',async()=>{const data=await post('/api/knowledge/reload',{});await loadKnowledge();showKnowledge([]);notice('knowledge-status',data.index_ready?'知识与向量索引已重新加载。':data.message);});
loadKnowledge().catch(error=>notice('knowledge-status',errorText(error),true));
})();
