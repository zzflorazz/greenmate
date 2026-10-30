const {chromium}=require('/Users/xiaoyi/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/playwright');
const assert=require('node:assert/strict');const fs=require('node:fs');
(async()=>{
 const browser=await chromium.launch({headless:true,executablePath:'/Users/xiaoyi/Library/Caches/ms-playwright/chromium_headless_shell-1243/chrome-headless-shell-mac-arm64/chrome-headless-shell'});
 const context=await browser.newContext({viewport:{width:1440,height:1080}});
 let page=await context.newPage();const errors=[];const listen=page=>page.on('pageerror',error=>errors.push(error.message));listen(page);
 const base='http://127.0.0.1:18108';const report={mode:'real_api_sqlite_model_program_judgment_with_scripted_explanation_ui_only',checks:[]};
 try{
 await page.goto(base);await page.waitForLoadState('networkidle');
 assert.equal(await page.locator('#analysis-question').textContent(),'分析当前番茄生长环境状态以及接下来值得关注的变化，并说明判断依据。');
 await page.locator('#run-analysis').click();await page.waitForFunction(()=>document.querySelector('#analysis-status').textContent.includes('分析已归档'));
 const runId=(await page.locator('#analysis-run-id').textContent()).replace('run_id：','');
 const run=await (await page.request.get(base+'/api/analyze/'+runId)).json();
 assert.equal(run.history_window.end,run.analysis_time);assert.equal(run.prediction.model_version,'attention_v1');assert.equal(run.history_window.count,6);assert.equal(run.judgment.recent_trend.metrics.temperature.direction,'stable');
 assert((await page.locator('#analysis-judgment').textContent()).includes(run.prediction.prediction));assert((await page.locator('#analysis-answer').textContent()).includes('浏览器测试解释'));
 report.checks.push('fixed_question_complete_analysis_and_evidence_display');
 await page.locator('#analysis-raw summary').click();assert.equal(JSON.parse(await page.locator('#analysis-json').textContent()).run_id,runId);
 report.checks.push('full_snapshot_json_available');
 // Create more than five actual archived runs to exercise the list bound.
 for(let i=0;i<5;i++){const response=await page.request.post(base+'/api/analyze',{data:{}});assert.equal(response.status(),200);}
 await page.locator('#refresh-runs').click();await page.waitForFunction(()=>document.querySelectorAll('.analysis-run').length===5);
 report.checks.push('recent_list_exactly_five');
 await page.close();page=await context.newPage();listen(page);await page.goto(base);await page.waitForLoadState('networkidle');
 await page.locator('#lookup-run-id').fill(runId);await page.locator('#lookup-run-button').click();await page.waitForFunction(id=>document.querySelector('#analysis-run-id').textContent.includes(id),runId);
 assert.deepEqual(JSON.parse(await page.locator('#analysis-json').textContent()),run);report.checks.push('closed_page_original_run_id_recalls_identical_snapshots');
 await page.locator('.analysis-run').first().click();await page.waitForFunction(id=>!document.querySelector('#analysis-run-id').textContent.includes(id),runId);
 report.checks.push('recent_run_click_recall');
 await page.screenshot({path:'verification/s1_desktop.png',fullPage:true});
 await page.locator('#analysis-time').fill('不合法日期');await page.locator('#run-analysis').click();await page.waitForFunction(()=>document.querySelector('#analysis-status').classList.contains('error'));
 assert((await page.locator('#analysis-status').textContent()).includes('analysis_time'));report.checks.push('invalid_anchor_chinese_error');
 await context.setOffline(true);await page.locator('#analysis-time').fill('');await page.locator('#run-analysis').click();await page.waitForFunction(()=>document.querySelector('#analysis-status').textContent.includes('无法连接'));
 assert((await page.locator('#analysis-run-id').textContent()).includes('run_'));report.checks.push('offline_keeps_existing_archive_visible');
 await context.setOffline(false);await page.setViewportSize({width:390,height:844});await page.screenshot({path:'verification/s1_mobile.png',fullPage:true});assert(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth));
 report.checks.push('mobile_no_horizontal_overflow');assert.deepEqual(errors,[]);report.page_errors=errors;report.passed=true;report.example_run_id=runId;
 }finally{fs.writeFileSync('verification/s1_ui.json',JSON.stringify(report,null,2));await browser.close();}
 console.log(JSON.stringify(report,null,2));
})().catch(error=>{console.error(error);process.exit(1)});
