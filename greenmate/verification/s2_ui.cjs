const {chromium}=require('/Users/xiaoyi/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/playwright');
const assert=require('node:assert/strict');const fs=require('node:fs');
(async()=>{
 const browser=await chromium.launch({headless:true,executablePath:'/Users/xiaoyi/Library/Caches/ms-playwright/chromium_headless_shell-1243/chrome-headless-shell-mac-arm64/chrome-headless-shell'});
 const context=await browser.newContext({viewport:{width:1440,height:1050}});const page=await context.newPage();const errors=[];page.on('pageerror',e=>errors.push(e.message));
 const base='http://127.0.0.1:18109';const report={mode:'real_scenario_api_history_model_archive_compare_with_existing_scripted_ui_explanation',checks:[]};
 try{
 await page.goto(base);await page.waitForLoadState('networkidle');
 await page.locator('#run-s1').click();await page.waitForFunction(()=>document.querySelector('#scenario-status').textContent.includes('运行另一场景'));
 await page.locator('#run-s2').click();await page.waitForFunction(()=>!document.querySelector('#scenario-comparison-result').hidden);
 assert.equal(await page.locator('#scenario-question-match').textContent(),'两次提问完全相同');
 assert.equal(await page.locator('#scenario-question').textContent(),await page.locator('#analysis-question').textContent());
 assert((await page.locator('#scenario-rows').textContent()).includes('stable'));assert((await page.locator('#scenario-rows').textContent()).includes('rising'));
 assert((await page.locator('#scenario-rows').textContent()).includes('25→30'));
 assert((await page.locator('#scenario-rows').textContent()).includes('30°C / 65% / 12000 lux'));
 report.checks.push('two_buttons_same_question_same_current_distinct_history');
 const ids=(await page.locator('#scenario-run-ids').textContent()).match(/run_\d{8}_\d{6}_[a-f0-9]+/g);assert.equal(ids.length,2);
 const compared=await (await page.request.get(base+'/api/analyze/compare?run_a='+ids[0]+'&run_b='+ids[1])).json();
 assert(compared.same_analysis_time);assert(compared.fixed_question_match);assert.equal(compared.rows.length,6);
 assert(compared.structured_delta.changed.some(item=>item.field==='recent_trend.temperature.direction'));
 assert(compared.structured_delta.unchanged.some(item=>item.field==='current.temperature'));
 report.checks.push('automatic_comparison_changed_and_unchanged_fields');
 assert.equal(await page.locator('#scenario-rows tr').count(),6);
 assert((await page.locator('#scenario-notes').textContent()).includes('两次模型标签相同'));
 assert((await page.locator('#scenario-rows').textContent()).includes('NORMAL'));
 report.checks.push('unchanged_model_labels_reported_honestly');
 await page.locator('#scenario-comparison').screenshot({path:'verification/s2_compare.png'});
 await page.locator('#run-s2').click();await page.waitForFunction(()=>document.querySelector('#scenario-status').textContent.includes('自动对比'));
 assert.equal((await (await page.request.post(base+'/api/scenarios/apply',{data:{name:'S2_ramp',analysis_time:compared.window_coverage.run_b.analysis_time}})).json()).samples_written,0);
 report.checks.push('repeated_scenario_writes_zero_samples');
 const original=await (await page.request.get(base+'/api/analyze/'+ids[0])).json();
 assert.equal(original.judgment.recent_trend.metrics.temperature.direction,'stable');report.checks.push('s1_archive_retained_after_switch');
 await page.setViewportSize({width:390,height:844});assert(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth));await page.locator('#scenario-comparison').screenshot({path:'verification/s2_mobile.png'});report.checks.push('mobile_comparison_scroll_without_page_overflow');
 await context.setOffline(true);await page.locator('#run-s1').click();await page.waitForFunction(()=>document.querySelector('#scenario-status').textContent.includes('无法连接'));assert(!(await page.locator('#scenario-comparison-result').isHidden()));report.checks.push('offline_error_retains_prior_comparison');
 assert.deepEqual(errors,[]);report.page_errors=errors;report.passed=true;report.runs=ids;
 }finally{fs.writeFileSync('verification/s2_ui.json',JSON.stringify(report,null,2));await browser.close();}
 console.log(JSON.stringify(report,null,2));
})().catch(e=>{console.error(e);process.exit(1)});
