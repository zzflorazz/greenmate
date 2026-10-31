// Real existing weather endpoint; isolated state DB; no LLM calls.
const {chromium}=require('/Users/xiaoyi/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/playwright');
const fs=require('node:fs'),assert=require('node:assert/strict');
(async()=>{
 const browser=await chromium.launch({headless:true,args:['--enable-unsafe-swiftshader'],executablePath:'/Users/xiaoyi/Library/Caches/ms-playwright/chromium_headless_shell-1243/chrome-headless-shell-mac-arm64/chrome-headless-shell'});
 const report={mode:'real_existing_weather_endpoint_and_webgl_isolated_db_no_llm_calls'};
 try{const page=await browser.newPage({viewport:{width:1440,height:1000}}),errors=[];page.on('pageerror',e=>errors.push(e.message));
 await page.goto('http://127.0.0.1:18116');await page.waitForLoadState('networkidle');await page.locator('.stage.is-live').waitFor();
 report.before=await page.evaluate(()=>window.__gmState);
 await page.locator('#fetch-weather').click();await page.waitForFunction(()=>!document.querySelector('#fetch-weather').disabled);
 report.after=await page.evaluate(()=>window.__gmState);report.message=await page.locator('#status').textContent();
 report.passed=report.after.source_type==='REAL_WEATHER';
 if(report.passed){assert.equal(await page.locator('#hero-temperature').textContent(),String(report.after.temperature));assert.equal(await page.locator('#hero-humidity').textContent(),String(report.after.humidity));assert((await page.locator('#hero-source-type').textContent()).includes('REAL_WEATHER'));await page.locator('nav a[href="#home"]').click();await page.waitForTimeout(2000);await page.screenshot({path:'verification/hero_live_weather.png'});}
 report.page_errors=errors;assert.deepEqual(errors,[]);
 }finally{fs.writeFileSync('verification/hero_live_weather.json',JSON.stringify(report,null,2));await browser.close();}
 console.log(JSON.stringify(report,null,2));
})().catch(e=>{console.error(e);process.exit(1)});
