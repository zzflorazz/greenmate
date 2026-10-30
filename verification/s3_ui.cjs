const {chromium}=require('/Users/xiaoyi/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/playwright');
const assert=require('node:assert/strict');const fs=require('node:fs');
(async()=>{
 const browser=await chromium.launch({headless:true,executablePath:'/Users/xiaoyi/Library/Caches/ms-playwright/chromium_headless_shell-1243/chrome-headless-shell-mac-arm64/chrome-headless-shell'});
 const context=await browser.newContext({viewport:{width:1440,height:1050}});const page=await context.newPage();const errors=[];page.on('pageerror',e=>errors.push(e.message));
 const base='http://127.0.0.1:18113';const report={mode:'isolated_db_real_api_and_saved_model_with_explicit_weather_and_llm_ui_fixtures',checks:[]};
 try{
 await page.goto(base);await page.waitForLoadState('networkidle');
 await page.locator('#run-s3-without').click();await page.waitForFunction(()=>!document.querySelector('#run-s3-without').disabled);
 assert((await page.locator('#s3-without').textContent()).includes('unknown'));
 await page.locator('#run-s3-with').click();await page.waitForFunction(()=>!document.querySelector('#run-s3-with').disabled);
 assert((await page.locator('#s3-match').textContent()).includes('内部状态与历史窗口完全相同'));
 assert.equal(await page.locator('#s3-question').textContent(),await page.locator('#analysis-question').textContent());report.checks.push('same_question_and_same_internal_s1');
 const text=await page.locator('#s3-with').textContent();
 for(const s of ['warming','raise','provider','retrieved_at','forecast_time','OPEN_METEO_UI_FIXTURE','attention_v1'])assert(text.includes(s),s);
 report.checks.push('side_by_side_future_weather_metadata_adjustment_and_answer');
 const ids=(await page.locator('#s3-results').textContent()).match(/run_\d{8}_\d{6}_[a-f0-9]+/g);assert.equal(ids.length,2);
 const a=await(await page.request.get(base+'/api/analyze/'+ids[0])).json();const b=await(await page.request.get(base+'/api/analyze/'+ids[1])).json();
 assert.deepEqual(a.history_window,b.history_window);assert.deepEqual(a.prediction,b.prediction);assert.deepEqual(a.state.data,b.state.data);
 assert(b.judgment.weather_evidence.result.items.every(p=>Date.parse(p.timestamp)>=Date.parse(b.analysis_time)));report.checks.push('archived_evidence_identical_and_forecast_not_past');
 await page.locator('#s3-comparison').screenshot({path:'verification/s3_compare.png'});
 await page.locator('#s3-with button').click();await page.waitForFunction(id=>document.querySelector('#analysis-run-id').textContent.includes(id),ids[1]);report.checks.push('run_id_lookup');
 await page.setViewportSize({width:390,height:844});assert(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth));await page.locator('#s3-comparison').screenshot({path:'verification/s3_mobile.png'});report.checks.push('mobile_no_page_overflow');
 await context.setOffline(true);await page.locator('#run-s3-with').click();await page.waitForFunction(()=>document.querySelector('#s3-status').textContent.includes('无法连接'));assert((await page.locator('#s3-with').textContent()).includes(ids[1]));report.checks.push('offline_friendly_error_preserves_comparison');
 assert.deepEqual(errors,[]);report.page_errors=errors;report.passed=true;
 }finally{fs.writeFileSync('verification/s3_ui.json',JSON.stringify(report,null,2));await browser.close();}
 console.log(JSON.stringify(report,null,2));
})().catch(e=>{console.error(e);process.exit(1)});
