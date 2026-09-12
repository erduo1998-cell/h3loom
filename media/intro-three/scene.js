import * as THREE from 'three';
import {RoundedBoxGeometry} from 'three/addons/geometries/RoundedBoxGeometry.js';
import {createTypeKit} from './type-kit.js';
import {DURATION,SHOTS,clamp,mix,track,shotAt,sampleMotion} from './motion-score.js';
const params=new URLSearchParams(location.search),isRender=params.has('render');
const W=Number(params.get('width')||1920),H=Number(params.get('height')||1080);
if(isRender){document.body.classList.add('render');document.documentElement.style.setProperty('--width',`${W}px`);document.documentElement.style.setProperty('--height',`${H}px`)}
const renderer=new THREE.WebGLRenderer({antialias:true,alpha:false,preserveDrawingBuffer:true,powerPreference:'high-performance'});
renderer.setSize(W,H,false);renderer.setPixelRatio(1);renderer.outputColorSpace=THREE.SRGBColorSpace;
renderer.toneMapping=THREE.ACESFilmicToneMapping;renderer.toneMappingExposure=1.08;
renderer.localClippingEnabled=true;renderer.setClearColor(0x000000,1);document.querySelector('#stage').prepend(renderer.domElement);
const scene=new THREE.Scene();scene.background=new THREE.Color(0);
const camera=new THREE.PerspectiveCamera(2*Math.atan(4.5/18)*180/Math.PI,16/9,.1,200);camera.position.z=18;
const kit=await createTypeKit(renderer);scene.environment=kit.environment;
scene.add(new THREE.AmbientLight(0xffffff,.18));
const key=new THREE.DirectionalLight(0xf1f3ff,3.8);key.position.set(-4,6,10);scene.add(key);
const rim=new THREE.DirectionalLight(0x859aff,2);rim.position.set(5,-1,6);scene.add(rim);
const fill=new THREE.DirectionalLight(0xffe2d0,1.1);fill.position.set(-5,-3,5);scene.add(fill);
const groups={},words={};
function section(id){const g=new THREE.Group();scene.add(g);groups[id]=g;return g}
function word(parent,text,width,height,x=0,y=0,mat='silver'){
 const root=new THREE.Group();const type=kit.makeWord(text,{width,height,material:mat,depth:.16});root.add(type);root.position.set(x,y,0);parent.add(root);return root;
}
function label(parent,text,width,x,y,color='#b9bac0'){
 const canvas=document.createElement('canvas');canvas.width=1600;canvas.height=140;const ctx=canvas.getContext('2d');ctx.font='500 52px Arial, sans-serif';ctx.textAlign='center';ctx.textBaseline='middle';ctx.fillStyle=color;ctx.fillText(text,800,72);
 const tex=new THREE.CanvasTexture(canvas);tex.colorSpace=THREE.SRGBColorSpace;const mat=new THREE.MeshBasicMaterial({map:tex,transparent:true,depthWrite:false,toneMapped:false});const m=new THREE.Mesh(new THREE.PlaneGeometry(width,width*140/1600),mat);m.position.set(x,y,.13);parent.add(m);return m;
}
const alloy=new THREE.MeshPhysicalMaterial({color:0x969aa3,metalness:1,roughness:.24,clearcoat:.45,clearcoatRoughness:.22});
const graphite=new THREE.MeshPhysicalMaterial({color:0x17171b,metalness:.86,roughness:.3});
const polished=new THREE.MeshPhysicalMaterial({color:0xc7c9d5,metalness:1,roughness:.13});
function box(parent,w,h,d,mat,x=0,y=0,z=0,r=.08){const m=new THREE.Mesh(new RoundedBoxGeometry(w,h,d,4,r),mat);m.position.set(x,y,z);parent.add(m);return m}
function chip(parent){
 const g=new THREE.Group();parent.add(g);const body=new THREE.Group();g.add(body);box(body,4.25,3.9,.20,graphite,0,0,-.12,.11);box(body,3.82,3.47,.19,polished,0,0,-.02,.07);box(body,3.73,3.38,.19,graphite,0,0,.045,.07);
 for(let i=0;i<15;i++){const p=-1.74+i*.249;box(body,.10,.16,.028,alloy,p,1.83,-.015,.013);box(body,.10,.16,.028,alloy,p,-1.83,-.015,.013);}
 const mark=word(g,'H3',2.88,1.39,0,.58);const name=word(g,'LOOM',2.86,1.1,0,-.79);mark.position.z=.2;name.position.z=.2;
 const detail=label(g,'LOCAL IDEAS. CLOUD POWER.',2.8,0,-1.47,'#8d8d93');detail.position.z=.2;
 return {g,body,mark,name,detail};
}
let g=section('from');words.from=word(g,'FROM',13.6,5.9);
g=section('srt');words.srt=word(g,'SRT',13.55,6.6);
g=section('to');words.to=word(g,'TO',9.4,6.5);
g=section('story');words.story=word(g,'STORY',14.2,6.4);
g=section('with');words.with=word(g,'WITH',14.4,8.1,0,0,'silver');
g=section('device');const device=new THREE.Group();g.add(device);
box(device,8.7,4.7,3.5,alloy,0,0,0,.35);box(device,8.1,4.15,.10,alloy,0,0,1.77,.17);
const vents=new THREE.InstancedMesh(new THREE.CircleGeometry(.041,8),new THREE.MeshBasicMaterial({color:0x050507}),420);
const ventTransform=new THREE.Object3D();for(let row=0;row<10;row++)for(let col=0;col<42;col++){ventTransform.position.set(-3.45+col*.168,1.73-row*.17,1.835);ventTransform.updateMatrix();vents.setMatrixAt(row*42+col,ventTransform.matrix)}device.add(vents);
for(let i=0;i<6;i++)box(device,.53,.37,.035,graphite,-2.15+i*.86,-1.12,1.84,.06);
const deviceCaption=label(g,'YOUR CLOUD. YOUR COMPUTE.',6.0,0,-2.65,'#c5c5ca');deviceCaption.visible=false;
g=section('chip');const hero=chip(g);
g=section('render');words.render=word(g,'RENDER',9.45,5.085,0,0,'metal');
g=section('in');words.in=word(g,'IN',5.8,6.2);
g=section('fourk');words.fourk=word(g,'4K',12.8,6.8);const fourkLabel=label(g,'YOUR FOOTAGE. FULL RESOLUTION.',6.8,0,-3.8,'#aaaab1');
g=section('own');const grid=new THREE.Group();g.add(grid);const ownYour=word(grid,'YOUR',10.7,2.34,0,1.55);const ownOwn=word(grid,'OWN',8.47,4.287,3.076,1.82);const ownCloud=word(grid,'CLOUD',14.61,3.39,0,-2.235);const ownDevice=new THREE.Group();box(ownDevice,8.7,4.7,3.5,alloy,0,0,0,.35);box(ownDevice,8.05,3.9,.10,graphite,0,0,1.79,.14);grid.add(ownDevice);ownDevice.scale.setScalar(.70);ownDevice.position.set(0,-1.45,0);
const specs=new THREE.Group();g.add(specs);const specRows=[];
for(const [i,text]of ['FROM SRT TO STORYBOARD','REVIEW BEFORE RENDER','YOUR OWN CLOUD WORKFLOW','EXPORT INDIVIDUAL 4K CLIPS'].entries()){
 const r=word(specs,text,13.9,1.28,0,3.3-i*1.58);specRows.push(r);
}
g=section('design');words.design=word(g,'DESIGN',13.6,6.3);
g=section('review');words.review=word(g,'REVIEW',13.6,6.3);
g=section('create');words.create=word(g,'CREATE',13.6,6.3);
g=section('signature');words.signature=word(g,'H3LOOM',13.15,2.65,0,.44);const sub=label(g,'FROM SUBTITLES TO YOUR OWN FOOTAGE.',9.1,0,-1.75,'#b8b8c0');const url=label(g,'github.com/erduo1998-cell/h3loom',6.8,0,-3.55,'#707078');
const solidPlane=new THREE.Plane(new THREE.Vector3(0,-1,0),99);
const wirePlane=new THREE.Plane(new THREE.Vector3(0,1,0),-99);
const solid4K=kit.materials.metal.clone();solid4K.onBeforeCompile=kit.materials.metal.onBeforeCompile;solid4K.customProgramCacheKey=()=> 'h3loom-4k-reveal-v1';solid4K.clippingPlanes=[solidPlane];
kit.setWordMaterial(words.fourk.children[0],solid4K);
const wire4K=words.fourk.clone(true);const wireMaterial=new THREE.MeshBasicMaterial({color:0xb7c6ff,wireframe:true,transparent:true,opacity:.28,clippingPlanes:[wirePlane],toneMapped:false});wire4K.traverse(o=>{if(o.isMesh)o.material=wireMaterial});groups.fourk.add(wire4K);wire4K.visible=false;
function reset(){hero.mark.visible=true;hero.name.visible=true;grid.visible=true;specs.visible=true;for(const g of Object.values(groups)){g.visible=false;g.position.set(0,0,0);g.rotation.set(0,0,0);g.scale.setScalar(1)}camera.position.set(0,0,18);camera.lookAt(0,0,0);}
function setWord(o,x=0,y=0,sx=1,sy=1,rz=0){o.position.x=x;o.position.y=y;o.scale.set(sx,sy,1);o.rotation.set(0,0,rz)}
function compose(time){
 const t=clamp(time,0,DURATION-1/6000),s=shotAt(t),u=t-s.start;reset();groups[s.id].visible=true;kit.update(s.id==='render' ? sampleMotion(t).value : 0);
 switch(s.id){
 case 'from':{
 const sx=track(u,[[0,.22,5],[.08,.61,4],[.22,.97,.55],[.46,1,0],[.86,1,0],[1.05,1.45,5]]);setWord(words.from,0,0,sx,track(u,[[0,1.7,-5],[.2,1.03,-.7],[.46,1,0],[1.05,1,0]]));break;}
 case 'srt':setWord(words.srt,0,0,track(u,[[0,1.15,-.2],[.16,1.07,-.7],[.4,1.0,-.1],[1.5,1,0],[1.8,1.05,.8]]),track(u,[[0,1.38,-2.7],[.20,1.025,-.35],[.55,1,0],[1.8,1,0]]));break;
 case 'to':setWord(words.to,0,0,1+u*.045,1);break;
 case 'story':setWord(words.story,0,0,track(u,[[0,.40,5.2],[.10,.82,2.8],[.26,.98,.35],[.56,1,0],[1.15,1,0],[1.35,1.05,.6]]),track(u,[[0,1.48,-2.2],[.20,1.02,-.4],[.56,1,0],[1.35,1,0]]));break;
 case 'with':setWord(words.with,0,0,sampleMotion(t).value,1);break;
 case 'device':device.rotation.set(track(u,[[0,.29,-.3],[.67,.015,0]]),0,0);device.scale.setScalar(1.51);break;
 case 'chip':{
 const scale=sampleMotion(t).value;hero.g.scale.setScalar(scale);hero.g.rotation.set(0,0,0);hero.g.position.set(0,0,0);const frameScale=track(u,[[0,2,0],[.16,2,0],[.33,1.85,-3],[.5,1,0],[2.68,1,0]]);hero.body.scale.set(frameScale,frameScale,1);
 // Independent typography compression during the pullback; framing alone cannot reproduce this.
 setWord(hero.mark,0,track(u,[[0,.75,0],[.16,.72,-.3],[.5,.58,0],[2.68,.58,0]]),track(u,[[0,1.75,-.3],[.16,1.60,-1.2],[.33,1.36,-1.5],[.5,1,0],[2.68,1,0]]),track(u,[[0,1.20,0],[.16,1.18,-.3],[.5,1,0],[2.68,1,0]]));
 setWord(hero.name,0,track(u,[[0,-.91,0],[.16,-.87,.3],[.5,-.79,0],[2.68,-.79,0]]),track(u,[[0,1.75,-.3],[.16,1.60,-1.2],[.33,1.34,-1.5],[.5,1,0],[2.68,1,0]]),track(u,[[0,1.36,0],[.16,1.29,-.5],[.5,1,0],[2.68,1,0]]));
 hero.detail.visible=u>.55;
 // The die is initially beyond the frame, then contracts around the same two lines.
 break;}
 case 'render':setWord(words.render,0,0,1,1);if(kit.setReflectionPhase)kit.setReflectionPhase(sampleMotion(t).value);break;
 case 'in':setWord(words.in,0,0,1+u*.06,1);break;
 case 'fourk':{
 const depth=track(u,[[0,-12,75],[.1,-5.4,50],[.22,-1.1,15],[.42,-.13,1.5],[.8,0,0],[1.85,0,0],[2.2,4.5,35]]);words.fourk.position.z=depth;setWord(words.fourk,0,.18,1,1);fourkLabel.material.opacity=track(u,[[0,0,0],[.32,0,0],[.62,1,0],[1.8,1,0],[2.05,0,0]]);break;}
 case 'own':{
 // 24 fps reference: the main reflow happens in 1–2 frames, followed by a long small settle.
 const a=track(u,[[0,0,0],[.375,0,0],[.417,.84,5],[.5,.96,.6],[.75,1,0],[4.2,1,0]]);
 const b=track(u,[[0,0,0],[.75,0,0],[.792,.86,5],[.88,.97,.45],[1.33,1,0],[4.2,1,0]]);
 ownOwn.visible=u>=.375;ownCloud.visible=u>=.75;
 setWord(ownYour,mix(0,-4.39,a),mix(2.55,2.25,a)+b*1.06,mix(1,.552,a),mix(1,.55,a));
 ownDevice.position.set(mix(0,-4.37,a),mix(-1.45,.02,a)+b*1.06,-1.65);ownDevice.scale.set(mix(.88,.70,a),mix(.65,.43,a),mix(.88,.70,a));ownDevice.rotation.set(.035,-.075+u*.016,0);
 setWord(ownOwn,mix(14,3.076,a),.755+b*1.06,mix(1.6,1,a),mix(1.7,1,a));
 setWord(ownCloud,0,mix(-6.4,-2.235,b),1,mix(1.24,1,b));
 const expand=track(u,[[0,1,0],[.88,1,0],[1.33,1.035,0],[2.25,1.035,0],[4.2,1.035,0]]);grid.scale.setScalar(expand);
 // Incoming spec rows push the existing grid DOWN. The reading order is continuous.
 const push=track(u,[[0,0,0],[2.25,0,0],[2.33,-1.6,-2],[2.49,-1.65,0],[2.50,-1.65,0],[2.58,-3.25,-2],[2.74,-3.3,0],[2.75,-3.3,0],[2.83,-4.9,-2],[2.99,-4.95,0],[3.0,-4.95,0],[3.08,-6.55,-2],[3.30,-6.6,0],[4.2,-6.6,0]]);grid.position.y=push;
 for(let i=0;i<4;i++){const q=u-(2.25+i*.25);specRows[i].visible=q>=0;specRows[i].position.y=3.3-i*1.58+track(q,[[0,2.5,-20],[.08,.1,-3],[.23,0,0]]);}
 break;}
 case 'design':case 'review':case 'create':{
 const o=words[s.id],dir=s.id==='review'?-1:1;
 setWord(o,track(u,[[0,dir*1.15,-dir*14],[.10,dir*.12,-dir*2],[.26,0,0],[.65,0,0]]),0,track(u,[[0,1.13,-1.6],[.15,1.006,-.1],[.32,1,0],[.7,1,0]]),1);break;}
 case 'signature':{
 setWord(words.signature,0,.44,track(u,[[0,1.66,-5],[.12,1.21,-2.2],[.3,1.015,-.3],[.6,1,0],[4.6,1,0]]),track(u,[[0,1.25,-1.5],[.3,1.01,-.15],[.6,1,0],[4.6,1,0]]));
 sub.material.opacity=track(u,[[0,0,0],[.3,0,0],[.7,1,0],[4.6,1,0]]);url.material.opacity=track(u,[[0,0,0],[.7,0,0],[1.15,1,0],[4.6,1,0]]);break;}
 }
 return s;
}
// Every connected passage is sampled from absolute time. No transition depends on
// which shot was visited before it; multiple actors can coexist at a handoff.
function composeConnected(time){
 const t=clamp(time,0,DURATION-1/6000);const selected=compose(t);
 wire4K.visible=false;solidPlane.constant=99;wirePlane.constant=-99;
 if(t<4.7){
  for(const g of Object.values(groups))g.visible=false;
  groups.from.visible=true;groups.srt.visible=t>=.73;groups.to.visible=t>=2.62;groups.story.visible=t>=3.10;
  const row=track(t,[[0,0,0],[.73,0,0],[.81,.10,4],[.95,.88,2],[1.13,.98,.2],[1.35,1,0],[4.7,1,0]]);
  const split=track(t,[[0,0,0],[2.62,0,0],[2.68,.1,4],[2.82,.88,2],[3.02,.99,.1],[3.22,1,0],[4.7,1,0]]);
  const arrive=track(t,[[0,0,0],[3.10,0,0],[3.16,.08,4],[3.30,.88,2],[3.50,.99,.1],[3.70,1,0],[4.7,1,0]]);
  const enter=track(t,[[0,.22,5],[.08,.61,4],[.22,.97,.55],[.46,1,0],[4.7,1,0]]);
  setWord(words.from,mix(0,-4.78,split),mix(0,3.26,row),enter*mix(1,.405,split),mix(1,.22,row));
  setWord(words.srt,mix(0,-4.78,split),mix(-8.2,-.81,row),mix(1,.407,split),.88);
  setWord(words.to,mix(14,3.08,split),3.26,.904,.20);
  setWord(words.story,3.08,mix(-8.2,-.81,arrive),.597,.908);
 }
 // The next operation unfolds above the die as the die recedes beneath it.
 // Both actors share the central axis and coexist through the handoff.
 if(t>=7.85&&t<8.88){
  compose(Math.min(t,7.85));groups.render.visible=true;
  const p=track(t,[[7.85,0,0],[7.94,.06,1.5],[8.20,.61,2.4],[8.48,.94,.45],[8.72,.995,.06],[8.88,1,0]]);
  const clear=track(t,[[7.85,0,0],[7.96,.05,2],[8.22,.8,2.3],[8.46,1,0],[8.88,1,0]]);
  hero.mark.position.y=.58;hero.name.position.y=-.79;hero.detail.visible=false;
  hero.mark.visible=clear<.95;hero.name.visible=clear<.95;
  hero.g.position.y=-clear*6.8;hero.g.scale.setScalar(1.09*(1-clear*.5));
  setWord(words.render,0,mix(2.45,0,p),mix(.315,1,p),mix(.02,1,p));
  kit.update(mix(-1.2,-.85,p));
 } else {hero.mark.visible=true;hero.name.visible=true;}
 // RENDER remains in the top row, IN joins below, and 4K resolves from wire to
 // the same blue/silver surface. This is a continuing sentence and material.
 if(t>=10.30&&t<13.2){
  for(const g of Object.values(groups))g.visible=false;groups.render.visible=true;groups.in.visible=t>=10.53;groups.fourk.visible=t>=10.84;
  const p=track(t,[[10.3,0,0],[10.4,.08,2],[10.6,.86,2],[10.82,.995,.1],[10.96,1,0],[13.2,1,0]]);
  setWord(words.render,0,mix(0,2.87,p),mix(1,1.37,p),mix(1,.35,p));
  setWord(words.in,track(t,[[10.53,-9,0],[10.62,-8,20],[10.79,-5.55,3],[10.98,-5.35,0],[13.2,-5.35,0]]),-1.05,.30,.39);
  const reveal=track(t,[[10.84,0,0],[10.98,.12,1.5],[11.32,.87,1],[11.58,1,0],[13.2,1,0]]);
  setWord(words.fourk,1.54,-1.1,.75,.76);words.fourk.position.z=0;fourkLabel.visible=false;
  solidPlane.constant=mix(-3.9,2.2,reveal);wirePlane.constant=-solidPlane.constant;wire4K.visible=true;wire4K.position.copy(words.fourk.position);wire4K.scale.copy(words.fourk.scale);
  kit.update(1.25+(t-10.3)*.25);
  if(t>=12.64){
   // The resolved 4K result becomes the label on the next product cell.
   const q=track(t,[[12.64,0,0],[12.76,.09,2],[12.98,.88,1.6],[13.16,.997,.1],[13.2,1,0]]);
   setWord(words.render,0,2.87+q*7,1.37,.35);words.in.position.y=-1.05+q*9;
   groups.own.visible=true;grid.visible=true;specs.visible=false;ownOwn.visible=false;ownCloud.visible=false;
   grid.position.set(0,0,0);grid.scale.setScalar(1);ownDevice.position.set(0,-1.45,-1.65);ownDevice.scale.set(.88,.65,.88);ownDevice.rotation.set(.035,-.075,0);
   ownDevice.visible=true;ownDevice.position.y=mix(-7,-1.45,q);
   setWord(ownYour,0,mix(7.2,2.55,q),1,1);
   setWord(words.fourk,mix(1.54,0,q),mix(-1.1,-1.45,q),mix(.75,.22,q),mix(.76,.22,q));words.fourk.position.z=.10;
   wire4K.visible=false;solidPlane.constant=99;
  }
 } else {fourkLabel.visible=true;specs.visible=true;}
 if(t>=13.2&&t<17.08){
  groups.fourk.visible=true;fourkLabel.visible=false;grid.visible=true;specs.visible=true;
  ownDevice.updateWorldMatrix(true,false);const p=new THREE.Vector3();ownDevice.getWorldPosition(p);
  setWord(words.fourk,p.x,p.y,.22*(ownDevice.scale.x/.88)*grid.scale.x,.22*(ownDevice.scale.y/.65)*grid.scale.y);words.fourk.position.z=.1;
  solidPlane.constant=99;kit.update(1.975+(t-13.2)*.05);
 }
 // One moving vertical strip carries the final three verbs. No alternating
 // entry direction, per-word reset, or restart of velocity at the cut markers.
 if(t>=17.08){
  compose(17.08);groups.own.visible=true;grid.visible=false;specs.visible=true;
  const y=track(t,[[17.08,0,0],[17.18,.1,4],[17.32,5.8,45],[17.4,8.5,8],[17.62,9,0],[17.98,9,0],[18.03,9.1,4],[18.13,15.8,34],[18.2,17.8,4],[18.4,18,0],[18.63,18,0],[18.7,18.5,18],[18.78,24.3,35],[18.88,26.8,4],[19.10,27,0],[19.28,27,0],[19.4,29.5,36],[19.52,33.9,28],[19.68,35.8,2],[19.98,36,0],[24,36,0]]);
  groups.own.position.y=y;
  for(const [i,id]of ['design','review','create'].entries()){groups[id].visible=true;groups[id].position.y=y-(i+1)*9;setWord(words[id],0,0,1,1)}
  groups.signature.visible=true;groups.signature.position.y=y-36;setWord(words.signature,0,.44,1,1);
  sub.material.opacity=track(t,[[17.08,0,0],[19.65,0,0],[20.1,1,0],[24,1,0]]);url.material.opacity=track(t,[[17.08,0,0],[20,0,0],[20.5,1,0],[24,1,0]]);
 }
 return selected;
}
let current=0,playing=false,last=0,rate=1;
function renderAt(t){current=clamp(t,0,DURATION);const shot=composeConnected(current);renderer.render(scene,camera);if(!isRender)updateUI(shot);return true;}
window.film={duration:DURATION,fps:60,width:W,height:H,renderAt,ready:true,shots:SHOTS,fontInfo:kit.fontInfo};
document.querySelector('#loading').remove();
const seek=document.querySelector('#seek'),timeEl=document.querySelector('#time'),play=document.querySelector('#play');
for(const s of SHOTS){const b=document.createElement('button');b.textContent=s.id.toUpperCase();b.dataset.shot=s.id;b.onclick=()=>{playing=false;renderAt(s.start+.001)};document.querySelector('#chapters').append(b)}
function updateUI(s){
 seek.value=current;timeEl.textContent=`${current.toFixed(2).padStart(5,'0')} / 24.00`;play.textContent=playing?'暂停':'播放';
 document.querySelectorAll('[data-shot]').forEach(b=>b.classList.toggle('active',b.dataset.shot===s.id));
 document.querySelector('#shot-label').textContent=s.label;const pts=[];for(let i=0;i<=100;i++)pts.push(sampleMotion(mix(s.start,s.end-1e-6,i/100)).value);
 const lo=Math.min(...pts),hi=Math.max(...pts),range=Math.max(.001,hi-lo);const p=pts.map((v,i)=>`${i*4.4+5},${72-(v-lo)/range*60}`).join(' ');const x=5+440*(current-s.start)/(s.end-s.start);
 document.querySelector('#curve').innerHTML=`<path d="M5 73H445" stroke="#35353a"/><polyline points="${p}" fill="none" stroke="#d5d5de" stroke-width="1.5"/><path d="M${x} 0V85" stroke="#7d88ff"/>`;
 document.querySelector('#motion-label').textContent=`${sampleMotion(current).parameter} · ${s.start.toFixed(2)}–${s.end.toFixed(2)} s`;
}
play.onclick=()=>{if(current>=DURATION)current=0;playing=!playing;last=performance.now();renderAt(current)};
seek.oninput=()=>{playing=false;renderAt(Number(seek.value))};document.querySelector('#speed').onchange=e=>rate=Number(e.target.value);
function step(d){playing=false;renderAt(current+d/60)}document.querySelector('#previous').onclick=()=>step(-1);document.querySelector('#next').onclick=()=>step(1);
document.addEventListener('keydown',e=>{if(e.target.tagName==='INPUT')return;if(e.code==='Space'){e.preventDefault();play.click()}if(e.code==='ArrowRight')step(1);if(e.code==='ArrowLeft')step(-1)});
function tick(now){if(playing){const dt=Math.min(.1,(now-last)/1000);renderAt(current+dt*rate);if(current>=DURATION){playing=false;play.textContent='重播'}}last=now;requestAnimationFrame(tick)}
renderAt(0);if(!isRender)requestAnimationFrame(tick);
