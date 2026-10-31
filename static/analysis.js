(() => {
'use strict';
const {request,post,action,notice,badge,errorText}=window.GM;
const nodes={};
for(const id of ["analysis-archive", "analysis-heading", "analysis-question", "analysis-form", "analysis-time", "analysis-location", "analysis-weather", "analysis-knowledge", "run-analysis", "analysis-status", "analysis-run-id", "analysis-evidence", "analysis-judgment", "analysis-raw", "analysis-json", "analysis-answer", "refresh-runs", "analysis-list-status", "analysis-runs", "lookup-run", "lookup-run-id", "lookup-run-button", "s3-comparison", "s3-question", "run-s3-without", "run-s3-with", "s3-status", "s3-match", "s3-results", "s3-without", "s3-with", "s4-conflict", "s4-heading", "s4-question", "run-s4", "run-s4-without", "s4-status", "s4-result", "s4-run-id", "s4-level", "s4-evidence", "s4-tools", "s4-conflicts", "s4-answer", "scenario-comparison", "scenario-heading", "scenario-question", "run-s1", "run-s2", "scenario-status", "scenario-run-ids", "scenario-comparison-result", "scenario-question-match", "scenario-anchor", "scenario-rows", "scenario-changed-summary", "scenario-changed", "scenario-unchanged-summary", "scenario-unchanged", "scenario-coverage", "scenario-notes"]){const node=window.GM.$(id);if(!node)return;nodes[id]=node;}
const $=id=>nodes[id];
function displayText(text){return String(text).replace(/B0[1-8](?:第[123]步)?/g,'').replace(/S1_stable/g,'稳定环境').replace(/S2_ramp/g,'持续升温').replace(/S4_conflict/g,'多源对照').replace(/S[1-4]/g,'场景').replace(/教学演示/g,'模拟示例').replace(/教材/g,'设计说明');}
function renderAnalysis(run){
 if(run.judgment.evidence_by_type||run.judgment.evidence_records)renderS4(run);
 $('analysis-run-id').textContent='run_id：'+run.run_id;
 $('lookup-run-id').value=run.run_id;
 $('analysis-evidence').replaceChildren(...Object.entries(run.evidence_status).map(([key,value])=>badge(key+' · '+value,value==='ok'?'sim':'')));
 const box=$('analysis-judgment');box.replaceChildren();box.className='analysis-summary';
 const paragraph=text=>{const p=document.createElement('p');p.textContent=displayText(text);box.append(p);};
 paragraph('时间锚点：'+run.analysis_time+'；地点：'+run.location+'。');
 const current=run.judgment.current_state;
 paragraph(current?`当前状态：${current.temperature}°C / ${current.humidity}% / ${current.light} lux · ${current.source_type}；快照时间：${current.timestamp}`:'当前状态证据不可用，请查看完整记录中的原因。');
 paragraph(`历史窗口：${run.history_window.start} 至 ${run.history_window.end}，${run.history_window.count} 个点（${run.history_window.status}）。`);
 const trend=run.judgment.recent_trend;
 if(trend.status==='ok')for(const [key,value] of Object.entries(trend.metrics))paragraph(`${key}：${value.direction}；首点 ${value.first}，末点 ${value.last}，delta ${value.delta}，范围 ${value.min}–${value.max}。`);
 else paragraph('趋势不可判断：'+trend.reason);
 const prediction=run.prediction;
 paragraph(prediction.status==='ok'?`MODEL_OUTPUT：${prediction.prediction}，P(WATCH)=${(prediction.probability*100).toFixed(2)}%，model_version=${prediction.model_version}。`:'预测证据不可用：'+prediction.error);
 if(prediction.status==='ok')paragraph(`预测目标：${prediction.target_start} 至 ${prediction.target_end}；输入末点：${prediction.window_end}。`);
 if(run.judgment.weather_evidence){const weather=document.createElement('p');weather.textContent='外部天气：'+run.judgment.weather_evidence.status+'；'+run.judgment.weather_expectation+' / '+run.judgment.attention_adjustment+'。'+run.judgment.adjustment_reason;box.append(weather);}
 const heading=document.createElement('h3');heading.className='analysis-subtitle';heading.textContent='判断限制';box.append(heading);
 const limits=document.createElement('ul');limits.className='analysis-limits';for(const text of run.judgment.judgment_limits){const li=document.createElement('li');li.textContent=displayText(text);limits.append(li);}box.append(limits);
 $('analysis-answer').textContent=run.answer||'LLM解释暂不可用；本次结构化判断与证据已保存，可以按run_id回查。';
 $('analysis-json').textContent=JSON.stringify(run,null,2);$('analysis-raw').hidden=false;
 notice('analysis-status',run.judgment.explanation_status==='ok'?'分析已归档；LLM解释与程序判断分开保存。':'证据已归档，LLM解释未取得。请检查网络或配置后再运行；已有档案不会丢失。',run.judgment.explanation_status!=='ok');
}
async function loadRuns(){const data=await request('/api/analyze');$('analysis-question').textContent=data.question;$('scenario-question').textContent=data.question;$('s3-question').textContent=data.question;$('s4-question').textContent=data.question;$('analysis-runs').replaceChildren(...data.items.map(run=>{const button=document.createElement('button');button.type='button';button.className='analysis-run';const id=document.createElement('span');id.textContent=run.run_id;const info=document.createElement('span');info.textContent=run.analysis_time+' · '+run.location;button.append(id,info);button.onclick=()=>action(button,'analysis-status',async()=>renderAnalysis(await request('/api/analyze/'+encodeURIComponent(run.run_id))));return button;}));notice('analysis-list-status',data.items.length?'点击编号查看当时保存的完整证据。':'还没有分析档案，点击“运行一次分析”开始。');}
$('analysis-form').onsubmit=event=>{event.preventDefault();action($('run-analysis'),'analysis-status',async()=>{const payload={location:$('analysis-location').value.trim(),include_weather:$('analysis-weather').checked,include_knowledge:$('analysis-knowledge').checked};if($('analysis-time').value.trim())payload.analysis_time=$('analysis-time').value.trim();renderAnalysis(await post('/api/analyze',payload));await loadRuns();});};
$('refresh-runs').onclick=()=>action($('refresh-runs'),'analysis-list-status',loadRuns);
$('lookup-run').onsubmit=event=>{event.preventDefault();if(!$('lookup-run-id').value.trim()){notice('analysis-status','请填写完整run_id后回查。',true);return;}action($('lookup-run-button'),'analysis-status',async()=>renderAnalysis(await request('/api/analyze/'+encodeURIComponent($('lookup-run-id').value.trim()))));};
const scenarioRuns={};let scenarioAnchor=null;
function describeComparison(field,value){
 if(value===null||value===undefined)return '未取得（unavailable）';
 if(field==='Current')return `${value.temperature}°C / ${value.humidity}% / ${value.light} lux · ${value.source_type}`;
 if(field==='Recent trend')return Object.entries(value).map(([key,item])=>`${key}：${item.direction}；${item.first}→${item.last}；delta=${item.delta}；mean=${item.mean}`).join('\n');
 if(field==='Predicted attention')return `${value.prediction||'unavailable'} · P(WATCH)=${typeof value.probability==='number'?(value.probability*100).toFixed(5)+'%':'—'} · ${value.model_version}`;
 if(field==='Structured judgment')return `程序判断：温度${value.recent_trend.temperature?.direction||'unavailable'}；模型标签${value.predicted_attention.prediction||'unavailable'}。判断限制保留。`;
 if(field==='Evidence status')return Object.entries(value).map(([key,status])=>key+'：'+status).join('\n');
 return String(value);
}
function renderComparison(data){
 $('scenario-comparison-result').hidden=false;
 notice('scenario-question-match',data.same_question&&data.fixed_question_match?'两次提问完全相同':'提问不一致，请核对档案。',!(data.same_question&&data.fixed_question_match));
 $('scenario-question').textContent=typeof data.question==='string'?data.question:JSON.stringify(data.question);
 $('scenario-anchor').textContent=data.same_analysis_time?'共同分析时间：'+data.window_coverage.run_a.analysis_time:'两次锚点不同，请核对完整窗口。';
 $('scenario-rows').replaceChildren(...data.rows.map(row=>{const tr=document.createElement('tr');const title=document.createElement('th');title.scope='row';title.textContent=row.field;tr.append(title);for(const key of ['run_a','run_b']){const td=document.createElement('td');td.style.whiteSpace='pre-wrap';const text=document.createElement('div');text.textContent=describeComparison(row.field,row[key]);td.append(text);if(row[key]&&typeof row[key]==='object'){const detail=document.createElement('details');const head=document.createElement('summary');head.textContent='查看归档字段';const pre=document.createElement('pre');pre.textContent=JSON.stringify(row[key],null,2);detail.append(head,pre);td.append(detail);}tr.append(td);}const changed=document.createElement('td');changed.textContent=row.changed?'有变化':'未变化';tr.append(changed);return tr;}));
 for(const kind of ['changed','unchanged']){const items=data.structured_delta[kind];$('scenario-'+kind+'-summary').textContent=(kind==='changed'?'变化字段':'不变字段')+'（'+items.length+'）';$('scenario-'+kind).replaceChildren(...items.map(item=>{const li=document.createElement('li');li.textContent=kind==='changed'?`${item.field}：${JSON.stringify(item.run_a)} → ${JSON.stringify(item.run_b)}`:`${item.field}：${JSON.stringify(item.value)}`;return li;}));}
 $('scenario-coverage').textContent=JSON.stringify(data.window_coverage,null,2);
 $('scenario-notes').replaceChildren(...data.notes.map(text=>{const p=document.createElement('p');p.textContent=text;return p;}));
 if(data.evidence_records){const detail=document.createElement('details');const title=document.createElement('summary');title.textContent='两次证据记录（含 unavailable）';const pre=document.createElement('pre');pre.textContent=JSON.stringify(data.evidence_records,null,2);detail.append(title,pre);$('scenario-notes').append(detail);}
}
async function runScenario(name){
 $('run-s1').disabled=true;$('run-s2').disabled=true;notice('scenario-status','正在准备场景、运行同一条分析链并归档，请稍候…');
 try{const payload={name};if(scenarioAnchor)payload.analysis_time=scenarioAnchor;const data=await post('/api/analyze/scenario',payload);scenarioAnchor=data.scenario.analysis_time;scenarioRuns[name]=data.run_id;renderAnalysis(data.run);
 $('scenario-run-ids').textContent=`稳定环境：${scenarioRuns.S1_stable||'待运行'}；持续升温：${scenarioRuns.S2_ramp||'待运行'}`;
 await loadRuns();
 if(scenarioRuns.S1_stable&&scenarioRuns.S2_ramp){const comparison=await request('/api/analyze/compare?run_a='+encodeURIComponent(scenarioRuns.S1_stable)+'&run_b='+encodeURIComponent(scenarioRuns.S2_ramp));renderComparison(comparison);notice('scenario-status','两份结构化档案已自动对比；模型原始标签与概率如实保留。');}
 else notice('scenario-status',(name==='S1_stable'?'稳定环境':'持续升温')+'已归档；运行另一场景后自动对比。'+(data.run.judgment.explanation_status==='ok'?'':'本次LLM解释未取得，结构化证据仍可比较。'));
 }catch(error){notice('scenario-status',errorText(error),true);}finally{$('run-s1').disabled=false;$('run-s2').disabled=false;}
}
$('run-s1').onclick=()=>runScenario('S1_stable');$('run-s2').onclick=()=>runScenario('S2_ramp');
const s3Runs={};let s3Anchor=null;
function renderS3(run,enabled){
 const box=$(enabled?'s3-with':'s3-without');box.replaceChildren();box.className='analysis-summary';
 const heading=document.createElement('h3');heading.textContent=enabled?'包含外部天气':'不含天气';box.append(heading);
 const fields=[['run_id',run.run_id],['分析锚点',run.analysis_time],['当前状态',JSON.stringify(run.judgment.current_state)],['历史趋势',run.judgment.recent_trend.metrics.temperature?.direction||'unavailable'],['模型原始预测',run.prediction.model_version+' · '+run.prediction.prediction+' / P(WATCH)='+run.prediction.probability],['weather_expectation',run.judgment.weather_expectation],['attention_adjustment',run.judgment.attention_adjustment],['变化依据',run.judgment.adjustment_reason]];
 for(const [label,value] of fields){const p=document.createElement('p');p.textContent=label+'：'+value;box.append(p);}
 const evidence=run.judgment.weather_evidence;const metadata=document.createElement('p');metadata.textContent='天气证据：'+evidence.status+'；provider：'+(evidence.provider||'未获取')+'；retrieved_at：'+(evidence.retrieved_at||'未获取')+'；forecast_time：'+(evidence.forecast_time?evidence.forecast_time.start+' 至 '+evidence.forecast_time.end:'无可采用区间')+(evidence.error?'；'+evidence.error:'');box.append(metadata);
 const detail=document.createElement('details');const title=document.createElement('summary');title.textContent='展开完整天气证据与逐小时预报';const pre=document.createElement('pre');pre.textContent=JSON.stringify(run.judgment.weather_evidence,null,2);detail.append(title,pre);box.append(detail);
 const answer=document.createElement('div');answer.className='answer';answer.textContent=run.answer||'LLM解释暂不可用；天气证据及结构化判断已归档。';box.append(answer);
 const link=document.createElement('button');link.type='button';link.className='secondary';link.textContent='按编号回查此档案';link.onclick=()=>action(link,'analysis-status',async()=>renderAnalysis(await request('/api/analyze/'+encodeURIComponent(run.run_id))));box.append(link);
}
async function runS3(enabled){
 $('run-s3-with').disabled=true;$('run-s3-without').disabled=true;
 notice('s3-status','正在分析同一稳定环境；天气与LLM均可能需要等待…');
 try{
 const payload={name:'S1_stable',include_weather:enabled};if(s3Anchor)payload.analysis_time=s3Anchor;
 const data=await post('/api/analyze/scenario',payload);s3Anchor=data.run.analysis_time;s3Runs[enabled?'with':'without']=data.run;
 renderS3(data.run,enabled);renderAnalysis(data.run);await loadRuns();
 const a=s3Runs.without,b=s3Runs.with;
 if(a&&b){const same=JSON.stringify(a.judgment.current_state)===JSON.stringify(b.judgment.current_state)&&JSON.stringify(a.history_window)===JSON.stringify(b.history_window)&&a.analysis_time===b.analysis_time;
 $('s3-match').textContent=(a.question===b.question?'两次提问完全相同。':'问题不一致。')+(same?'内部状态与历史窗口完全相同；只加入外部天气。':'内部证据存在差异，请核对归档JSON。');}
 const w=data.run.judgment.weather_evidence;
 notice('s3-status',(enabled&&w.status!=='ok'?'天气未采用：'+w.error+'；其他证据照常归档。':'本次已归档；两列分别保留天气证据、程序判断与LLM解释。')+(data.run.answer?'':' LLM解释暂不可用。'),enabled&&w.status!=='ok');
 }catch(error){notice('s3-status',errorText(error),true);}finally{$('run-s3-with').disabled=false;$('run-s3-without').disabled=false;}
}
$('run-s3-without').onclick=()=>runS3(false);$('run-s3-with').onclick=()=>runS3(true);

function renderS4(run){
 const j=run.judgment;const records=j.evidence_by_type||j.evidence_records;if(!records)return;
 const adopted=new Set((j.evidence_records||[]).filter(e=>e.status==='ok').map(e=>e.source_type));
 $('s4-result').hidden=false;$('s4-run-id').textContent='run_id：'+run.run_id;
 $('s4-level').textContent='conclusion_level = '+j.conclusion_level+'；已采用 '+adopted.size+' 类证据。'+(j.conclusion_level==='conflicting'?'分歧尚未消解，保留各自范围内的判断。':j.conclusion_level==='insufficient'?'核心证据不足，请核对缺失项。':'支持现有范围内的描述，不保证未来结果。');
 $('s4-evidence').replaceChildren(...records.map(e=>{
  const card=document.createElement('article');const title=document.createElement('h4');title.textContent=e.source_type;card.append(title,badge('adopted='+adopted.has(e.source_type),adopted.has(e.source_type)?'sim':''));
  for(const [key,value] of [['source',e.source],['time',e.time],['status',e.status],['provider',e.provider],['forecast_time',e.forecast_time],['model_version',e.model_version],['citation',e.citation],['error',e.error]]){if(value===undefined)continue;const line=document.createElement('p');line.className='small';line.textContent=key+'：'+(typeof value==='object'?JSON.stringify(value):value);card.append(line);}
  const detail=document.createElement('details');detail.open=true;const summary=document.createElement('summary');summary.textContent='result';const result=document.createElement('pre');result.textContent=JSON.stringify(e.result,null,2);detail.append(summary,result);card.append(detail);return card;
 }));
 $('s4-tools').replaceChildren(...(run.tool_trace||[]).map(call=>{const li=document.createElement('li');const name=document.createElement('strong');name.textContent=call.tool+' · status='+call.status+' · adopted='+call.adopted;const reason=document.createElement('p');reason.textContent=call.adopt_reason;const detail=document.createElement('details');const summary=document.createElement('summary');summary.textContent='实际调用参数';const pre=document.createElement('pre');pre.textContent=JSON.stringify(call.arguments,null,2);detail.append(summary,pre);li.append(name,reason,detail);return li;}));
 $('s4-conflicts').replaceChildren(...(j.conflicts.length?j.conflicts.map(c=>{const li=document.createElement('li');li.textContent=c.between.join(' ↔ ')+' · '+c.type+'：'+c.description;return li;}):[Object.assign(document.createElement('li'),{textContent:'本次未识别到上述类型的分歧；不人为制造冲突。'})]));
 $('s4-answer').textContent=run.answer||'LLM解释未取得或未通过输出校验；原始证据、工具记录与程序结论已归档。';
}
async function runS4(includeKnowledge){
 $('run-s4').disabled=true;$('run-s4-without').disabled=true;notice('s4-status','正在准备模拟内部历史，调用真实天气与可选知识工具，并生成解释…');
 try{const data=await post('/api/analyze/scenario',{name:'S4_conflict',include_weather:true,include_knowledge:includeKnowledge});renderAnalysis(data.run);await loadRuns();notice('s4-status','已归档 '+data.run_id+'；conclusion_level='+data.run.judgment.conclusion_level+'。'+(data.run.judgment.explanation_status==='ok'?'LLM解释已取得。':'LLM解释未取得，见档案错误原因。'));}
 catch(error){notice('s4-status',errorText(error),true);}finally{$('run-s4').disabled=false;$('run-s4-without').disabled=false;}
}
$('run-s4').onclick=()=>runS4(true);$('run-s4-without').onclick=()=>runS4(false);

loadRuns().catch(error=>notice('analysis-list-status',errorText(error),true));

})();
