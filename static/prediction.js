(() => {
'use strict';
const {request,post,action,notice,badge,errorText}=window.GM;
const nodes={};
for(const id of ["prediction", "prediction-title", "prediction-label", "prediction-probability", "prediction-version", "prediction-window", "predict-button", "prediction-status", "load-metrics", "metrics-status", "metrics-summary"]){const node=window.GM.$(id);if(!node)return;nodes[id]=node;}
const $=id=>nodes[id];
async function refreshPrediction(){const data=await request('/api/ml/predict');if(data.status!=='ok')throw new Error(typeof data.error==='string'?data.error:'当前窗口无法预测，请检查最新采样是否连续。');$('prediction-label').textContent=data.prediction==='WATCH'?'建议关注':'暂未触发关注';$('prediction-probability').textContent=`P(WATCH)：${(data.probability*100).toFixed(2)}%`;$('prediction-version').textContent=`model_version：${data.model_version} · ${data.source_type}`;$('prediction-window').textContent=`输入：${data.window_start} 至 ${data.window_end}；预测此后 ${data.horizon_minutes} 分钟。`;notice('prediction-status','已从本地模型读取预测；未重新训练。');}
$('predict-button').onclick=()=>action($('predict-button'),'prediction-status',async()=>{try{await refreshPrediction();}catch(error){$('prediction-label').textContent='预测暂不可用';$('prediction-probability').textContent='P(WATCH)：—';throw error;}});
$('load-metrics').onclick=()=>action($('load-metrics'),'metrics-status',async()=>{const data=await request('/api/ml/metrics');const metric=data.baselines.logistic_regression.test;$('metrics-summary').textContent=`测试集 ${data.test_count} 条\nAccuracy ${(metric.accuracy*100).toFixed(2)}%\nWATCH Recall ${(metric.recall*100).toFixed(2)}%\n${data.recall_comparison}`;notice('metrics-status','读取已保存指标，不触发训练。');});
refreshPrediction().catch(error=>{const node=$('prediction-label');if(!node)return;node.textContent='预测暂不可用';notice('prediction-status',errorText(error),true);});
})();
