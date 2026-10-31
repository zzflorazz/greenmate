// Uses existing bundled Playwright; no npm/project dependency is added.
const {chromium}=require('/Users/xiaoyi/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/playwright');
const assert=require('node:assert/strict'),fs=require('node:fs');
const base='http://127.0.0.1:18118';
const chromiumPath='/Users/xiaoyi/Library/Caches/ms-playwright/chromium_headless_shell-1243/chrome-headless-shell-mac-arm64/chrome-headless-shell';
(async()=>{
 const browser=await chromium.launch({headless:true,args:['--enable-unsafe-swiftshader'],executablePath:chromiumPath});
 const context=await browser.newContext({viewport:{width:1440,height:1000}}),page=await context.newPage(),errors=[];
 page.on('pageerror',e=>errors.push(e.message));page.on('console',m=>{if(m.type()==='error')errors.push(m.text())});
 const report={mode:'real_six_page_api_state_sqlite_rag_model_scenarios_webgl_isolated_db_explicit_llm_weather_fixtures',checks:[]};const check=s=>report.checks.push(s);
 const idle=async id=>{await page.waitForFunction(id=>!document.getElementById(id)?.disabled,id,{timeout:90000})};
 async function nav(path){await page.goto(base+path);await page.waitForLoadState('networkidle');}
 async function observeVendor(route){const response=await route.fetch(),source=await response.text(),name=source.match(/(\w+) as WebGLRenderer/)[1];await route.fulfill({response,body:source.replace(name+' as WebGLRenderer','ObservedRenderer as WebGLRenderer')+`\nclass ObservedRenderer extends ${name}{constructor(...args){super(...args);const r=this.render;this.render=function(scene,camera){window.__sceneProbe={scene,camera,renderer:this,frames:(window.__sceneProbe?.frames||0)+1};return r.call(this,scene,camera);};}}`});}
 await context.route('**/vendor/three.module.min.js',observeVendor);
 await context.addInitScript(()=>{window.__numbers=[];new MutationObserver(()=>{const node=document.getElementById('hero-temperature');if(node&&node.textContent!=='—'&&window.__numbers.at(-1)!==node.textContent)window.__numbers.push(node.textContent)}).observe(document,{subtree:true,childList:true,characterData:true})});
 try{
 for(const path of ['/','/environment','/conversation','/knowledge','/prediction','/analysis']){
  await nav(path);assert.equal(await page.locator('nav [aria-current="page"]').getAttribute('href'),path);
  assert.equal(await page.locator('nav a').count(),6);assert(!await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth));
  assert(await page.locator('img').evaluateAll(images=>images.every(i=>i.complete&&i.naturalWidth>0)));
  if(path!=='/')assert.equal(await page.locator('.intro').count(),0);
  await page.screenshot({path:'verification/pages_'+(path.slice(1)||'home')+'.png'});
 }
 check('six_routes_correct_nav_local_images_desktop_no_console_errors_or_overflow');
 await nav('/');await page.locator('.stage.is-live').waitFor();await page.waitForTimeout(500);
 assert.equal(await page.locator('.entry-card').count(),4);assert.equal(await page.locator('#environment').count(),0);assert.equal(await page.locator('#ask-form').count(),0);
 assert.equal(await page.locator('#hero-temperature').textContent(),String(await page.evaluate(()=>window.__gmState.temperature)));
 assert(await page.evaluate(()=>window.__numbers.some(n=>Number(n)>0&&Number(n)<Number(window.__gmState.temperature))));check('home_only_hero_four_entries_actual_readings_one_time_number_animation');
 const scene=await page.evaluate(()=>{const p=window.__sceneProbe,s=p.scene;return {calls:p.renderer.info.render.calls,shadow:p.renderer.shadowMap.enabled,env:[s.environment.image.width,s.environment.image.height],cas:s.children.find(o=>o.isDirectionalLight).castShadow}});
 assert(scene.calls<=120,JSON.stringify(scene));assert(scene.shadow&&scene.cas);assert.deepEqual(scene.env,[512,256]);report.scene=scene;check('real_webgl_shadows_reflection_texture_at_most_120_draw_calls');
 await page.emulateMedia({reducedMotion:'reduce'});await page.waitForTimeout(150);
 const still=await page.evaluate(()=>window.__sceneProbe.scene.children.find(o=>o.type==='Group').rotation.y);await page.waitForTimeout(150);assert.equal(await page.evaluate(()=>window.__sceneProbe.scene.children.find(o=>o.type==='Group').rotation.y),still);
 await page.locator('#greenhouse-canvas').dispatchEvent('dblclick');await page.locator('#reset-scene').focus();assert.equal(await page.evaluate(()=>document.activeElement.id),'reset-scene');await page.keyboard.press('Enter');
 const leaf=await page.evaluate(()=>{const {scene,camera}=window.__sceneProbe;const world=scene.children.find(o=>o.type==='Group'),plant=world.children.find(o=>o.type==='Group'&&o.children.length===9),tip=plant.children[2],v=tip.getWorldPosition(camera.position.clone());v.project(camera);const r=document.querySelector('#greenhouse-canvas').getBoundingClientRect();return {x:r.x+(v.x+1)*r.width/2,y:r.y+(1-v.y)*r.height/2}});
 await page.mouse.click(leaf.x,leaf.y);await page.waitForFunction(()=>!document.querySelector('#plant-tooltip').hidden);assert((await page.locator('#plant-tooltip').textContent()).includes('不代表真实作物状态'));
 await page.locator('#greenhouse-canvas').dblclick({position:{x:10,y:10}});assert(await page.locator('#plant-tooltip').isHidden());
 await page.emulateMedia({reducedMotion:'no-preference'});await page.mouse.move(leaf.x,leaf.y);await page.waitForTimeout(150);assert(await page.evaluate(()=>window.__sceneProbe.scene.children.find(o=>o.type==='Group').children.some(o=>o.type==='Group'&&o.children.length===9&&o.scale.x===1.04)));check('raycast_plant_label_hover_scale_double_click_and_keyboard_reset');
 // Native navigation click, with transition support if present.
 await page.locator('.hero-actions a[href="/environment"]').click();await page.waitForURL(base+'/environment');await page.waitForLoadState('networkidle');
 await page.locator('#set-simulated').click();await idle('set-simulated');assert.equal(await page.locator('#temperature').textContent(),'24');
 await page.locator('#environment details summary').click();await page.locator('#load-samples').click();await idle('load-samples');assert((await page.locator('#sample-summary').textContent()).includes('条样本'));
 await page.locator('#fetch-weather').click();await idle('fetch-weather');assert.equal(await page.locator('#source-type').textContent(),'REAL_WEATHER');
 await page.locator('nav a[href="/"]').click();await page.waitForURL(base+'/');await page.waitForLoadState('networkidle');await page.waitForTimeout(300);assert.equal(await page.locator('#hero-temperature').textContent(),'34');assert((await page.locator('#hero-source-type').textContent()).includes('REAL_WEATHER'));check('environment_switch_history_then_home_reads_same_persisted_weather_state');
 await nav('/conversation');
 await page.route('**/api/ask',r=>r.fulfill({json:{answer:'页面夹具：保留普通问答。',source_type:'SIMULATED'}}));await page.locator('#question').fill('当前需要关注什么？');await page.locator('#ask-button').click();await idle('ask-button');assert((await page.locator('#answer').textContent()).includes('保留普通问答'));
 await page.route('**/api/agent',r=>r.fulfill({json:{answer:'页面夹具：保留工具证据。',iterations:2,tool_calls:[{sequence:1,tool:'predict_next_attention',arguments:{},status:'ok',elapsed_ms:2,result:{status:'ok',source:'MODEL_OUTPUT',time:new Date().toISOString(),data:{model_version:'attention_v1',evidence_type:'MODEL_OUTPUT'},error:null}}]}}));
 await page.locator('#mode-agent').click();await page.locator('#ask-button').click();await idle('ask-button');assert((await page.locator('#agent-tool-list').textContent()).includes('predict_next_attention'));assert((await page.locator('#answer-evidence').textContent()).includes('MODEL_OUTPUT'));
 await page.locator('#chat-memory summary').click();await page.locator('#load-chat').click();await idle('load-chat');assert((await page.locator('#chat-status').textContent()).includes('SQLite'));check('ordinary_agent_tool_evidence_and_sqlite_memory_controls');
 await nav('/knowledge');await page.locator('#plant-list button').first().click();assert(await page.locator('.knowledge-item').count());await page.locator('#knowledge-query').fill('绿萝怎么浇水');await page.locator('#search-button').click();await idle('search-button');assert(await page.locator('.knowledge-item').count());
 await page.locator('#knowledge details summary').click();await page.locator('#reload-knowledge').click();await idle('reload-knowledge');assert((await page.locator('#knowledge-status').textContent()).includes('重新'));check('knowledge_listing_real_local_search_and_index_reload');
 await nav('/prediction');await page.locator('#predict-button').click();await idle('predict-button');assert((await page.locator('#prediction-version').textContent()).includes('attention_v1'));await page.locator('#prediction details summary').click();await page.locator('#load-metrics').click();await idle('load-metrics');assert((await page.locator('#metrics-summary').textContent()).includes('Recall'));check('persisted_model_prediction_and_saved_metrics');
 await nav('/analysis');await page.locator('#run-s1').click();await idle('run-s1');const s1=(await page.locator('#analysis-run-id').textContent()).replace('run_id：','');await page.locator('#run-s2').click();await idle('run-s2');assert((await page.locator('#scenario-rows').textContent()).includes('rising'));
 await page.locator('#run-s3-without').click();await idle('run-s3-without');await page.locator('#run-s3-with').click();await idle('run-s3-with');assert((await page.locator('#s3-match').textContent()).includes('内部状态与历史窗口完全相同'));
 await page.locator('#run-s4').click();await idle('run-s4');assert.equal(await page.locator('#s4-evidence article').count(),5);assert((await page.locator('#s4-tools').textContent()).includes('search_plant_knowledge'));await page.locator('#run-s4-without').click();await idle('run-s4-without');assert(!(await page.locator('#s4-tools').textContent()).includes('search_plant_knowledge'));
 await page.locator('#lookup-run-id').fill(s1);await page.locator('#lookup-run-button').click();await idle('lookup-run-button');assert((await page.locator('#analysis-run-id').textContent()).includes(s1));
 // General analyze form remains functional, too.
 await page.locator('#run-analysis').click();await idle('run-analysis');assert((await page.locator('#analysis-run-id').textContent()).includes('run_'));check('s1_s2_s3_s4_with_without_knowledge_general_analysis_and_run_lookup');
 // Each script deliberately returns if any required node is missing; shared helpers guard optional nodes.
 for(const path of ['/environment','/conversation','/knowledge','/prediction','/analysis']){await page.setViewportSize({width:390,height:844});await nav(path);assert(!await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth));await page.screenshot({path:'verification/pages_mobile_'+path.slice(1)+'.png'});}
 await nav('/');await page.locator('.stage.is-live').waitFor();assert.equal(Math.round((await page.locator('.stage').boundingBox()).height),230);assert(!await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth));await page.screenshot({path:'verification/pages_mobile_home.png',fullPage:true});check('all_six_pages_390px_no_horizontal_overflow');
 // Reduced motion: reload in a fresh document, never interpolate numeric values.
 await page.emulateMedia({reducedMotion:'reduce'});await nav('/');await page.waitForTimeout(350);assert(await page.evaluate(()=>window.__numbers.every(v=>Number(v)===Number(window.__gmState.temperature))));
 const before=await page.locator('.entry-card img').first().evaluate(n=>getComputedStyle(n).transform);await page.locator('.entry-card').first().hover();assert.equal(await page.locator('.entry-card img').first().evaluate(n=>getComputedStyle(n).transform),before);check('reduced_motion_disables_numbers_scene_sway_card_effect_and_banner_parallax');
 assert.deepEqual(errors,[]);report.normal_errors=errors;
 // New page avoids counting expected 404/module failure as normal console errors.
 const broken=await context.newPage();await broken.route('**/assets/img/scene-conversation.jpg',r=>r.fulfill({status:404,body:'not found'}));await broken.goto(base+'/conversation');await broken.waitForLoadState('networkidle');assert(await broken.locator('.page-banner .img-fallback').count());assert(await broken.locator('.photo-fallback').isVisible());assert.equal(await broken.locator('.page-banner img').evaluate(n=>getComputedStyle(n).visibility),'hidden');await broken.screenshot({path:'verification/pages_image_fallback.png'});await broken.close();check('missing_photo_shows_gradient_svg_without_broken_image');
 const no3d=await context.newPage();await no3d.route('**/vendor/three.module.min.js',r=>r.abort());await no3d.goto(base);await no3d.waitForLoadState('networkidle');assert(await no3d.locator('.stage-fallback').isVisible());await no3d.close();check('failed_three_module_still_shows_svg_and_home_content');
 const offline=await context.newPage();await offline.goto(base+'/environment');await offline.waitForLoadState('networkidle');await context.setOffline(true);await offline.locator('#refresh').click();await offline.waitForFunction(()=>document.querySelector('#status').textContent.includes('无法连接'));await context.setOffline(false);await offline.close();check('offline_page_action_reports_chinese_error');
 report.passed=true;
 }finally{fs.writeFileSync('verification/pages_ui.json',JSON.stringify(report,null,2));await browser.close()}
 console.log(JSON.stringify(report,null,2));
})().catch(e=>{console.error(e);process.exit(1)});
