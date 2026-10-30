const {chromium}=require('/Users/xiaoyi/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/playwright');
const assert=require('node:assert/strict'),fs=require('node:fs');
(async()=>{
 const browser=await chromium.launch({headless:true,executablePath:'/Users/xiaoyi/Library/Caches/ms-playwright/chromium_headless_shell-1243/chrome-headless-shell-mac-arm64/chrome-headless-shell'});
 const page=await browser.newPage({viewport:{width:1440,height:1050}}),errors=[];page.on('pageerror',e=>errors.push(e.message));
 const base='http://127.0.0.1:18114';const report={mode:'offline_ui_forecast_and_llm_fixtures_real_b05_knowledge_and_b06_model',checks:[]};
 try{
 await page.goto(base);await page.waitForLoadState('networkidle');
 await page.locator('#run-s4').click();await page.waitForFunction(()=>!document.querySelector('#run-s4').disabled,{timeout:90000});
 assert((await page.locator('#s4-level').textContent()).includes('conflicting'));assert.equal(await page.locator('#s4-evidence article').count(),5);
 const content=await page.locator('#s4-result').textContent();for(const text of ['CURRENT_STATE','HISTORY','MODEL_OUTPUT','WEATHER_FORECAST','KNOWLEDGE','source','time','status','result','provider','forecast_time','model_version','citation','tomato_heat_01','adopted=true','search_plant_knowledge','direction_conflict'])assert(content.includes(text),text);
 report.checks.push('five_evidence_cards_identity_citations_adoption_trace_conflict_level_and_explanation');
 const id=(await page.locator('#s4-run-id').textContent()).replace('run_id：','');
 const stored=await(await page.request.get(base+'/api/analyze/'+id)).json();assert.equal(stored.judgment.evidence_records.length,5);assert(stored.tool_trace.some(t=>t.tool==='search_plant_knowledge'&&t.adopted));
 await page.locator('#s4-conflict').screenshot({path:'verification/s4_desktop.png'});
 await page.setViewportSize({width:390,height:844});assert(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth));await page.locator('#s4-conflict').screenshot({path:'verification/s4_mobile.png'});report.checks.push('mobile_no_page_overflow');
 await page.locator('#run-s4-without').click();await page.waitForFunction(()=>!document.querySelector('#run-s4-without').disabled);
 const offText=await page.locator('#s4-evidence').textContent();assert(offText.includes('adopted=false'));assert(!(await page.locator('#s4-tools').textContent()).includes('search_plant_knowledge'));report.checks.push('knowledge_off_unavailable_and_not_called');
 await page.locator('#lookup-run-id').fill(id);await page.locator('#lookup-run-button').click();await page.waitForFunction(id=>document.querySelector('#s4-run-id').textContent.includes(id),id);assert((await page.locator('#s4-tools').textContent()).includes('search_plant_knowledge'));report.checks.push('archive_lookup_restores_original_trace');
 await page.context().setOffline(true);await page.locator('#run-s4').click();await page.waitForFunction(()=>!document.querySelector('#run-s4').disabled);assert((await page.locator('#s4-status').textContent()).includes('无法连接'));assert((await page.locator('#s4-run-id').textContent()).includes(id));report.checks.push('network_failure_preserves_archive_display');
 assert.deepEqual(errors,[]);report.passed=true;report.page_errors=errors;
 }finally{fs.writeFileSync('verification/s4_ui.json',JSON.stringify(report,null,2));await browser.close();}
 console.log(JSON.stringify(report));
})().catch(e=>{console.error(e);process.exit(1)});
