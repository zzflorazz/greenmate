// Bundled Node Playwright: no project dependency or build tool is installed.
// The vendor response adds an observer around render() ONLY in this test. This
// records the actual Three scene/GPU draws without changing application behavior.
const {chromium}=require('/Users/xiaoyi/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/playwright');
const assert=require('node:assert/strict'),fs=require('node:fs');
const base='http://127.0.0.1:18116';
const wait=ms=>new Promise(resolve=>setTimeout(resolve,ms));
(async()=>{
 const browser=await chromium.launch({headless:true,args:['--enable-unsafe-swiftshader'],executablePath:'/Users/xiaoyi/Library/Caches/ms-playwright/chromium_headless_shell-1243/chrome-headless-shell-mac-arm64/chrome-headless-shell'});
 const context=await browser.newContext({viewport:{width:1440,height:1000}}),page=await context.newPage();
 const errors=[];page.on('pageerror',e=>errors.push(e.message));page.on('console',m=>{if(m.type()==='error')errors.push(m.text())});
 const report={mode:'real_webgl_real_local_api_model_scenarios_rag_isolated_db_explicit_external_weather_llm_fixtures',checks:[]};
 const check=name=>report.checks.push(name);
 async function snap(){return page.evaluate(()=>{const p=window.__sceneProbe,s=p.scene,w=s.children.find(o=>o.type==='Group'),sun=s.children.find(o=>o.isDirectionalLight),glass=[];w.traverse(o=>{if(o.isMesh&&o.material.isMeshPhysicalMaterial)glass.push(o)});const plants=w.children.filter(o=>o.type==='Group'&&o.children.length===9);return {frames:p.frames,rotation:w.rotation.y,leaves:plants.flatMap(o=>o.children.slice(1,6).map(l=>l.rotation.z)),sun:sun.intensity,color:sun.color.getHex(),fog:s.fog.density,glass:glass[0].material.opacity,plants:plants.length,glassMeshes:glass.length,ribs:w.children.filter(o=>o.isLine&&o.geometry.attributes.position.count===25).length,look:p.camera.getWorldDirection(new p.camera.position.constructor()).toArray()}})}
 async function idleButton(id){await page.waitForFunction(id=>!document.getElementById(id).disabled,id,{timeout:90000})}
 try{
 await page.route('**/vendor/three.module.min.js',async route=>{const response=await route.fetch(),source=await response.text(),name=source.match(/(\w+) as WebGLRenderer/)[1];await wait(300);await route.fulfill({response,body:source.replace(name+' as WebGLRenderer','ObservedRenderer as WebGLRenderer')+`\nclass ObservedRenderer extends ${name}{constructor(...args){super(...args);const observedRender=this.render;this.render=function(scene,camera){const frames=(window.__sceneProbe?.frames||0)+1;window.__sceneProbe={scene,camera,frames};return observedRender.call(this,scene,camera);};}}`})});
 await page.goto(base);await page.waitForLoadState('networkidle');await page.locator('.stage.is-live').waitFor();await page.waitForFunction(()=>window.__gmState&&window.updateGreenhouseScene);
 assert.equal(await page.locator('main > :first-child').getAttribute('id'),'home');assert.equal(await page.locator('#hero-temperature').textContent(),await page.locator('#temperature').textContent());
 assert.equal((await snap()).plants,6);assert.equal((await snap()).ribs,9);assert.equal((await snap()).glassMeshes,5);check('local_r160_real_webgl_six_plants_nine_ribs_first_state_race');
 assert(!(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth)));assert.equal(await page.locator('.intro h2').textContent(),'工作台');
 const nav=await page.locator('nav a').first().getAttribute('href');assert.equal(nav,'#home');
 await page.locator('.hero-actions a').first().focus();await page.keyboard.press('Tab');assert.equal(await page.evaluate(()=>document.activeElement.getAttribute('href')),'#analysis-archive');check('desktop_layout_and_two_keyboard_focusable_hero_links');
 await page.screenshot({path:'verification/hero_desktop.png'});
 const a=await snap();await page.waitForTimeout(200);const b=await snap();assert.notEqual(a.rotation,b.rotation);assert(a.leaves.some((v,i)=>v!==b.leaves[i]));check('automatic_rotation_and_leaf_motion');
 await page.emulateMedia({reducedMotion:'reduce'});await page.waitForTimeout(120);const c=await snap();await page.waitForTimeout(180);const d=await snap();assert.equal(c.rotation,d.rotation);assert(c.leaves.every(v=>v===.18));assert.deepEqual(c.leaves,d.leaves);check('live_prefers_reduced_motion_stops_auto_rotation_and_leaf_sway');
 // Actual API mutation + original renderState bridge, not a synthetic scene setter.
 await page.evaluate(async()=>{await fetch('/api/state',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({temperature:14,humidity:0,light:0})});await refreshState()});
 await page.waitForFunction(()=>Math.abs(window.__sceneProbe.scene.fog.density-.012)<.0001);const cold=await snap();assert(Math.abs(cold.sun-.3)<.02);assert(Math.abs(cold.glass-.11)<.002);assert.equal(await page.locator('#hero-light').textContent(),'0');
 await page.evaluate(async()=>{await fetch('/api/state',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({temperature:34,humidity:100,light:24000})});await refreshState()});
 const immediate=await snap();assert(immediate.sun<2.65,'smooth transition must not jump');
 await page.waitForFunction(()=>Math.abs(window.__sceneProbe.scene.fog.density-.032)<.0001);const hot=await snap();assert(Math.abs(hot.sun-2.7)<.02);assert(Math.abs(hot.glass-.23)<.002);assert.notEqual(cold.color,hot.color);report.mapping={cold,hot};check('actual_state_api_drives_linear_light_color_fog_glass_with_smoothing');
 await page.locator('#fetch-weather').click();await idleButton('fetch-weather');await page.locator('nav a[href="#home"]').click();await page.waitForFunction(()=>document.querySelector('#hero-source-type').textContent.includes('REAL_WEATHER'));
 assert.equal(await page.locator('#hero-temperature').textContent(),'34');assert.equal(await page.locator('#hero-humidity').textContent(),'95');assert(await page.locator('#hero-source-type').evaluate(n=>n.classList.contains('real')));check('weather_button_updates_hero_state_source_and_scene_fixture');
 await page.emulateMedia({reducedMotion:'no-preference'});await page.locator('#home').scrollIntoViewIfNeeded();
 const bounds=await page.locator('#greenhouse-canvas').boundingBox();await page.mouse.move(bounds.x+bounds.width*.4,bounds.y+bounds.height*.5);await page.mouse.down();await page.mouse.move(bounds.x+bounds.width*.65,bounds.y+bounds.height*.5,{steps:7});const drag=await snap();await page.mouse.up();await page.waitForTimeout(120);assert.notEqual((await snap()).rotation,drag.rotation);check('pointer_rotation_and_release_inertia');
 await page.locator('#knowledge').scrollIntoViewIfNeeded();await page.waitForTimeout(120);const paused=(await snap()).frames;await page.waitForTimeout(200);assert.equal((await snap()).frames,paused);
 await page.evaluate(()=>{window.__qaHidden=true;Object.defineProperty(document,'hidden',{configurable:true,get:()=>window.__qaHidden});document.dispatchEvent(new Event('visibilitychange'))});
 await page.evaluate(()=>{window.__qaHidden=false;document.dispatchEvent(new Event('visibilitychange'))});await page.waitForTimeout(160);assert.equal((await snap()).frames,paused);check('offscreen_raf_stops_and_visibility_restore_does_not_restart_offscreen');
 await page.evaluate(()=>scrollTo(0,0));await page.waitForFunction(frames=>window.__sceneProbe.frames>frames,paused);
 await page.evaluate(()=>{window.__qaHidden=true;document.dispatchEvent(new Event('visibilitychange'))});await page.waitForTimeout(100);const hidden=(await snap()).frames;await page.waitForTimeout(150);assert.equal((await snap()).frames,hidden);
 await page.evaluate(()=>{window.__qaHidden=false;document.dispatchEvent(new Event('visibilitychange'))});await page.waitForFunction(frames=>window.__sceneProbe.frames>frames,hidden);check('hidden_tab_raf_pauses_and_visible_in_view_resumes');
 for(const width of [850,450,390]){await page.setViewportSize({width,height:844});await page.waitForTimeout(120);assert(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth));assert.equal(Math.round((await page.locator('.stage').boundingBox()).height),width<=450?230:270)}
 await page.evaluate(()=>scrollTo(0,0));await page.screenshot({path:'verification/hero_mobile.png'});await page.locator('.hero').screenshot({path:'verification/hero_mobile_full.png'});check('responsive_850_450_390_no_overflow_scene_heights');
 await page.setViewportSize({width:1440,height:1000});
 // Keep existing ordinary/agent answer rendering checks isolated from upstream.
 await page.route('**/api/ask',r=>r.fulfill({json:{answer:'页面夹具：普通问答保留。',source_type:'SIMULATED'}}));await page.locator('#question').fill('当前需要关注什么？');await page.locator('#ask-button').click();await idleButton('ask-button');assert((await page.locator('#answer').textContent()).includes('普通问答保留'));
 await page.route('**/api/agent',r=>r.fulfill({json:{answer:'页面夹具：工具回答保留。',iterations:2,tool_calls:[{sequence:1,tool:'get_current_environment',arguments:{},status:'ok',elapsed_ms:1,result:{status:'ok',source:'SIMULATED',time:new Date().toISOString(),data:{temperature:30},error:null}}]}}));
 await page.locator('#mode-agent').click();await page.locator('#ask-button').click();await idleButton('ask-button');assert((await page.locator('#agent-tool-list').textContent()).includes('get_current_environment'));
 await page.locator('#knowledge-query').fill('绿萝浇水');await page.locator('#search-button').click();await idleButton('search-button');assert(await page.locator('.knowledge-item').count()>0);
 await page.locator('#run-s1').click();await idleButton('run-s1');await page.locator('#run-s2').click();await idleButton('run-s2');assert(!(await page.locator('#scenario-comparison-result').isHidden()));assert((await page.locator('#scenario-rows').textContent()).includes('rising'));
 await page.locator('#predict-button').click();await idleButton('predict-button');assert((await page.locator('#prediction-version').textContent()).includes('attention_v1'));
 await page.locator('#run-s3-without').click();await idleButton('run-s3-without');await page.locator('#run-s3-with').click();await idleButton('run-s3-with');assert((await page.locator('#s3-match').textContent()).includes('内部状态与历史窗口完全相同'));
 await page.locator('#run-s4').click();await idleButton('run-s4');assert.equal(await page.locator('#s4-evidence article').count(),5);assert((await page.locator('#s4-tools').textContent()).includes('search_plant_knowledge'));check('original_ask_agent_knowledge_prediction_s1_s2_s3_s4_controls_still_work');
 assert.deepEqual(errors,[]);report.normal_page_errors=errors;
 // A missing module still leaves the SVG and all standard card JS available.
 const missing=await context.newPage();await missing.route('**/vendor/three.module.min.js',r=>r.abort('failed'));await missing.goto(base);await missing.waitForLoadState('networkidle');assert(await missing.locator('.stage-fallback').isVisible());assert(!(await missing.locator('.stage').evaluate(n=>n.classList.contains('is-live'))));assert.notEqual(await missing.locator('#hero-temperature').textContent(),'—');await missing.close();check('module_load_failure_retains_svg_and_live_readings');
 const fallback=await context.newPage();await fallback.addInitScript(()=>{const get=HTMLCanvasElement.prototype.getContext;HTMLCanvasElement.prototype.getContext=function(type,...args){return /webgl/.test(type)?null:get.call(this,type,...args)}});await fallback.goto(base);await fallback.waitForLoadState('networkidle');assert(await fallback.locator('.stage-fallback').isVisible());await fallback.locator('.hero').screenshot({path:'verification/hero_fallback.png'});await fallback.close();check('no_webgl_retains_matching_svg_greenhouse');
 report.passed=true;
 }finally{fs.writeFileSync('verification/hero_ui.json',JSON.stringify(report,null,2));await browser.close()}
 console.log(JSON.stringify(report,null,2));
})().catch(error=>{console.error(error);process.exit(1)});
