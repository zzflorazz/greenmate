
import * as THREE from '../vendor/three.module.min.js';

const canvas=document.getElementById('greenhouse-canvas');
const stage=canvas?.closest('.stage');
const hint=document.getElementById('stage-hint');
const tooltip=document.getElementById('plant-tooltip');
const resetButton=document.getElementById('reset-scene');
if(canvas&&stage){
  try{startGreenhouse();}
  catch{stage.classList.remove('is-live');if(hint)hint.textContent='温室线稿示意 · 当前设备暂不支持三维场景';}
}

function startGreenhouse(){
  const context=canvas.getContext('webgl2',{alpha:true,antialias:true})||canvas.getContext('webgl',{alpha:true,antialias:true});
  if(!context){if(hint)hint.textContent='温室线稿示意 · 当前设备暂不支持三维场景';return;}
  const reduce=window.matchMedia('(prefers-reduced-motion: reduce)');
  const renderer=new THREE.WebGLRenderer({canvas,context,antialias:true,alpha:true});
  renderer.shadowMap.enabled=true;
  renderer.shadowMap.type=THREE.PCFSoftShadowMap;
  renderer.setPixelRatio(Math.min(window.devicePixelRatio||1,2));
  renderer.setClearColor(0x12271f,0);
  renderer.toneMapping=THREE.ACESFilmicToneMapping;
  renderer.toneMappingExposure=1.35;
  const scene=new THREE.Scene();
  // Local 512×256 sky/ground texture: visual reflection only, no new evidence.
  const sky=document.createElement('canvas');sky.width=512;sky.height=256;
  const skyContext=sky.getContext('2d');
  if(skyContext){const gradient=skyContext.createLinearGradient(0,0,0,256);gradient.addColorStop(0,'#6d91a5');gradient.addColorStop(.5,'#d4ddd5');gradient.addColorStop(1,'#82745b');skyContext.fillStyle=gradient;skyContext.fillRect(0,0,512,256);const texture=new THREE.CanvasTexture(sky);texture.mapping=THREE.EquirectangularReflectionMapping;texture.colorSpace=THREE.SRGBColorSpace;scene.environment=texture;}
  scene.fog=new THREE.FogExp2(0x12271f,.02);
  const camera=new THREE.PerspectiveCamera(36,1,.1,100);
  const world=new THREE.Group();world.rotation.y=-.32;scene.add(world);
  const FLOOR=.2,WALL_H=3.2,WALL_W=9.6,WALL_D=6.8,ARCH_H=2.3,BED_TOP=.46;
  const glass=new THREE.MeshPhysicalMaterial({color:0xcdeee0,transparent:true,opacity:.14,roughness:.12,envMapIntensity:.45,side:THREE.DoubleSide,depthWrite:false});
  const frameMat=new THREE.LineBasicMaterial({color:0xc7e3d1,transparent:true,opacity:.65});
  const postMat=new THREE.MeshStandardMaterial({color:0xa2c4b0,roughness:.6});
  const stemMat=new THREE.MeshStandardMaterial({color:0x779b60,roughness:.9,flatShading:true});
  const leafMats=[0x508959,0x70a969].map(color=>new THREE.MeshStandardMaterial({color,roughness:.85,flatShading:true}));
  const fruitMat=new THREE.MeshStandardMaterial({color:0xd96e48,roughness:.65,flatShading:true});
  const soilMat=new THREE.MeshStandardMaterial({color:0x463b30,roughness:1});
  const bedMat=new THREE.MeshStandardMaterial({color:0x685140,roughness:1});
  const plinth=new THREE.Mesh(new THREE.LatheGeometry([[0,-1.1],[6.35,-1.1],[6.6,-.96],[6.6,-.16],[6.4,-.035],[6.2,0],[0,0]].map(([r,y])=>new THREE.Vector2(r,y)),48),new THREE.MeshStandardMaterial({color:0x274a3f,roughness:.95}));
  plinth.receiveShadow=true;
  const soil=new THREE.Mesh(new THREE.CylinderGeometry(5.9,5.9,.4,48),soilMat);
  soil.receiveShadow=true;world.add(plinth,soil);
  for(const z of [-2.1,2.1]){const bed=new THREE.Mesh(new THREE.BoxGeometry(9.2,.26,1.5),bedMat);bed.position.set(0,.33,z);world.add(bed);}

  // Four transparent wall planes, four posts, and explicit door/window outlines.
  const wallY=FLOOR+WALL_H/2;
  for(const z of [-WALL_D/2,WALL_D/2]){const wall=new THREE.Mesh(new THREE.PlaneGeometry(WALL_W,WALL_H),glass);wall.position.set(0,wallY,z);world.add(wall);}
  for(const x of [-WALL_W/2,WALL_W/2]){const wall=new THREE.Mesh(new THREE.PlaneGeometry(WALL_D,WALL_H),glass);wall.rotation.y=Math.PI/2;wall.position.set(x,wallY,0);world.add(wall);}
  for(const x of [-WALL_W/2,WALL_W/2])for(const z of [-WALL_D/2,WALL_D/2]){const post=new THREE.Mesh(new THREE.CylinderGeometry(.055,.055,WALL_H,6),postMat);post.position.set(x,wallY,z);world.add(post);}
  function outline(points){const geometry=new THREE.BufferGeometry().setFromPoints(points.map(p=>new THREE.Vector3(...p)));const line=new THREE.Line(geometry,frameMat);world.add(line);return line;}
  for(const y of [FLOOR,FLOOR+WALL_H])outline([[-WALL_W/2,y,-WALL_D/2],[WALL_W/2,y,-WALL_D/2],[WALL_W/2,y,WALL_D/2],[-WALL_W/2,y,WALL_D/2],[-WALL_W/2,y,-WALL_D/2]]);
  outline([[-1,FLOOR,WALL_D/2+.015],[-1,FLOOR+2.6,WALL_D/2+.015],[1,FLOOR+2.6,WALL_D/2+.015],[1,FLOOR,WALL_D/2+.015]]);
  for(const x of [-3,3])outline([[x-.7,1.5,WALL_D/2+.015],[x-.7,2.7,WALL_D/2+.015],[x+.7,2.7,WALL_D/2+.015],[x+.7,1.5,WALL_D/2+.015],[x-.7,1.5,WALL_D/2+.015]]);

  // Default CylinderGeometry has its axis along Y. Rotate into X, then scale
  // the semicircle in Y/Z: exactly the same equation used by all nine ribs.
  const roofPivot=new THREE.Group();
  const roof=new THREE.Mesh(new THREE.CylinderGeometry(1,1,WALL_W,24,1,true,0,Math.PI),glass);
  roof.rotation.z=Math.PI/2;roofPivot.add(roof);roofPivot.scale.set(1,ARCH_H,WALL_D/2);roofPivot.position.y=FLOOR+WALL_H;world.add(roofPivot);
  for(let rib=0;rib<9;rib++){
    const x=-WALL_W/2+rib*WALL_W/8,points=[];
    for(let step=0;step<=24;step++){const a=step/24*Math.PI;points.push([x,FLOOR+WALL_H+Math.sin(a)*ARCH_H,Math.cos(a)*WALL_D/2]);}
    outline(points); // BufferGeometry polyline; no EdgesGeometry approximation.
  }

  const plants=[];
  for(const z of [-2.1,2.1])for(let col=0;col<3;col++){
    const seed=plants.length*1.7,plant=new THREE.Group(),leaves=[];
    const stem=new THREE.Mesh(new THREE.CylinderGeometry(.05,.075,1.75,5),stemMat);stem.position.y=.875;stem.castShadow=true;plant.add(stem);
    for(let i=0;i<5;i++){const angle=seed+i*2.1,leaf=new THREE.Mesh(new THREE.IcosahedronGeometry(.55,0),leafMats[i%2]);leaf.position.set(Math.cos(angle)*.48,.65+i*.23,Math.sin(angle)*.48);leaf.scale.set(1.35,.4,.9);leaf.rotation.set(.25,angle,.18);leaf.castShadow=i%3===0;plant.add(leaf);leaves.push(leaf);}
    for(let i=0;i<3;i++){const angle=seed*.8+i*2.4,fruit=new THREE.Mesh(new THREE.IcosahedronGeometry(.19,1),fruitMat);fruit.position.set(Math.cos(angle)*.38,1.05+i*.2,Math.sin(angle)*.38);plant.add(fruit);}
    plant.position.set((col-1)*3.2,BED_TOP,z);world.add(plant);plants.push({leaves,seed,plant});
  }
  // Three light support poles and two taut guide wires.
  for(const x of [-3.2,0,3.2]){const pole=new THREE.Mesh(new THREE.CylinderGeometry(.027,.027,3.5,5),postMat);pole.position.set(x,FLOOR+1.75,0);pole.castShadow=true;world.add(pole);}
  for(const z of [-2.1,2.1])outline([[-4.5,3.25,z],[4.5,3.25,z]]);
  const sun=new THREE.DirectionalLight(0xffe3b6,1.5);sun.position.set(7,9,4);sun.castShadow=true;sun.shadow.mapSize.set(1024,1024);Object.assign(sun.shadow.camera,{left:-8,right:8,top:8,bottom:-8,near:.5,far:30});sun.shadow.camera.updateProjectionMatrix();sun.shadow.normalBias=.025;
  const hemi=new THREE.HemisphereLight(0xb9e0cc,0x1c332a,.85);
  const ambient=new THREE.AmbientLight(0x9fc4ae,.18);
  const inner=new THREE.PointLight(0xffc98a,.7,16,2);inner.position.set(0,3.2,0);
  scene.add(sun,hemi,ambient,inner);

  // Each reading controls only its advertised visual properties; values are
  // clamped for the drawing, never altered in the displayed source data.
  const cool=new THREE.Color(0xa9cfe6),warm=new THREE.Color(0xffb877);
  const target={sun:1.5,fog:.02,glass:.16,warmth:.5},smooth={...target};
  const unit=value=>Math.min(1,Math.max(0,value));
  function apply(state){
    if(!state)return;
    const t=Number(state.temperature),h=Number(state.humidity),l=Number(state.light);
    if(![t,h,l].every(Number.isFinite))return;
    target.sun=.3+unit(l/24000)*2.4;
    target.warmth=unit((t-14)/20);
    target.fog=.012+unit(h/100)*.02;
    target.glass=.11+unit(h/100)*.12;
  }
  window.updateGreenhouseScene=apply;
  if(window.__gmState)apply(window.__gmState);

  let spin=-.32,velocity=0,dragging=false,pointerId=null,lastX=0,downX=0,downY=0,hovered=null;
  const raycaster=new THREE.Raycaster(),pointer=new THREE.Vector2();
  function hitPlant(event){
    const rect=canvas.getBoundingClientRect();if(!rect.width||!rect.height)return null;
    pointer.set((event.clientX-rect.left)/rect.width*2-1,-(event.clientY-rect.top)/rect.height*2+1);
    raycaster.setFromCamera(pointer,camera);
    const hit=raycaster.intersectObjects(plants.map(p=>p.plant),true)[0];
    return hit?plants.find(p=>p.plant===hit.object||p.plant.children.includes(hit.object))?.plant:null;
  }
  function showLabel(plant){if(!tooltip)return;tooltip.hidden=!plant;}
  function reset(){spin=-.32;velocity=0;hovered=null;for(const p of plants)p.plant.scale.setScalar(1);showLabel(null);}
  if(resetButton)resetButton.addEventListener('click',reset);
  canvas.addEventListener('dblclick',event=>{event.preventDefault();reset();});
  canvas.addEventListener('pointerdown',event=>{if(!event.isPrimary||event.button!==0)return;pointerId=event.pointerId;lastX=downX=event.clientX;downY=event.clientY;dragging=true;velocity=0;canvas.setPointerCapture(event.pointerId);});
  canvas.addEventListener('pointermove',event=>{
    if(!dragging){hovered=hitPlant(event);return;}
    if(event.pointerId!==pointerId)return;const dx=event.clientX-lastX;lastX=event.clientX;spin+=dx*.007;velocity=reduce.matches?0:dx*.42;
  });
  canvas.addEventListener('pointerleave',()=>{hovered=null;});
  const release=event=>{if(event.pointerId!==pointerId)return;dragging=false;pointerId=null;if(reduce.matches)velocity=0;if(event.type==='pointerup'&&Math.hypot(event.clientX-downX,event.clientY-downY)<6)showLabel(hitPlant(event));if(canvas.hasPointerCapture(event.pointerId))canvas.releasePointerCapture(event.pointerId);};
  for(const type of ['pointerup','pointercancel','lostpointercapture'])canvas.addEventListener(type,release);

  let elapsed=0,frameId=0,lastTime=0,inView=false,lostContext=false;
  function render(){
    sun.intensity=smooth.sun;sun.color.copy(cool).lerp(warm,smooth.warmth);
    scene.fog.density=smooth.fog;glass.opacity=smooth.glass;world.rotation.y=spin;
    renderer.render(scene,camera);
    // The SVG stays until a first successful render, including context recovery.
    stage.classList.add('is-live');
  }
  function resize(){
    const {width,height}=stage.getBoundingClientRect();if(!width||!height)return;
    renderer.setSize(width,height,false);camera.aspect=width/height;
    const distance=Math.max(23,7.4/(Math.tan(THREE.MathUtils.degToRad(18))*Math.min(camera.aspect,1)));
    camera.position.copy(new THREE.Vector3(11.4,5.9,16.2).normalize().multiplyScalar(distance)).add(new THREE.Vector3(0,2.9,0));
    camera.lookAt(0,2.9,0);camera.updateProjectionMatrix();
    if(!lostContext&&!document.hidden)render();
  }
  function frame(now){
    frameId=0;if(!inView||document.hidden||lostContext)return;
    const dt=lastTime?Math.min((now-lastTime)/1000,.05):1/60;lastTime=now;elapsed+=dt;
    const blend=1-Math.exp(-dt*2.4);for(const key in target)smooth[key]+=(target[key]-smooth[key])*blend;
    if(!dragging){spin+=velocity*dt;velocity*=Math.exp(-dt*4.5);if(!reduce.matches)spin+=dt*.07;}
    for(const p of plants)p.plant.scale.setScalar(!reduce.matches&&hovered===p.plant?1.04:1);
    for(const plant of plants)plant.leaves.forEach((leaf,i)=>{leaf.rotation.z=reduce.matches ? .18 : .18+Math.sin(elapsed*.8+i+plant.seed)*.045;});
    render();frameId=requestAnimationFrame(frame);
  }
  function syncLoop(){
    if(inView&&!document.hidden&&!lostContext){if(!frameId){lastTime=0;frameId=requestAnimationFrame(frame);}}
    else{cancelAnimationFrame(frameId);frameId=0;lastTime=0;}
  }
  new IntersectionObserver(entries=>{inView=entries[0].isIntersecting;syncLoop();},{threshold:0}).observe(stage);
  document.addEventListener('visibilitychange',syncLoop);
  canvas.addEventListener('webglcontextlost',event=>{event.preventDefault();lostContext=true;stage.classList.remove('is-live');syncLoop();});
  canvas.addEventListener('webglcontextrestored',()=>{lostContext=false;resize();syncLoop();});
  new ResizeObserver(resize).observe(stage);
  resize();
}
