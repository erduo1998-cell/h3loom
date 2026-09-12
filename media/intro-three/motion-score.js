// Hand-authored screen-space score. Seconds and frame rates are explicit.
// Hermite tangents are values per second, not generic easing preset names.
export const DURATION = 24;
export const SHOTS = [
 {start:0,end:1.05,id:'from',label:'FROM · 宽度展开',ref:'adaptation'},
 {start:1.05,end:2.85,id:'srt',label:'SRT · 纵向压缩 / 稳定阅读',ref:'adaptation'},
 {start:2.85,end:3.35,id:'to',label:'TO · 硬切',ref:'adaptation'},
 {start:3.35,end:4.7,id:'story',label:'STORY · 轴向重排',ref:'adaptation'},
 {start:4.7,end:5.25,id:'with',label:'WITH · 宽度缓慢增长',ref:'reference 5.00–5.25'},
 {start:5.25,end:5.92,id:'device',label:'云端模块 · 硬切',ref:'reference 5.25–5.92 mechanism'},
 {start:5.92,end:8.6,id:'chip',label:'H3 / LOOM · 型号归入芯片',ref:'reference 5.92–6.92 mechanism'},
 {start:8.6,end:10.6,id:'render',label:'RENDER · 反射流动',ref:'reference RENDER segment'},
 {start:10.6,end:11.0,id:'in',label:'IN · 硬切',ref:'adaptation'},
 {start:11.0,end:13.2,id:'fourk',label:'4K · 深度推进 / 刹停',ref:'adaptation'},
 {start:13.2,end:17.4,id:'own',label:'YOUR / OWN / CLOUD · 拼版与让位',ref:'reference ONE MORE TIME mechanism'},
 {start:17.4,end:18.05,id:'design',label:'DESIGN · 快闪',ref:'adaptation'},
 {start:18.05,end:18.7,id:'review',label:'REVIEW · 快闪',ref:'adaptation'},
 {start:18.7,end:19.4,id:'create',label:'CREATE · 快闪',ref:'adaptation'},
 {start:19.4,end:24,id:'signature',label:'H3LOOM · 收尾',ref:'adaptation'}
];
export const clamp=(x,a=0,b=1)=>Math.max(a,Math.min(b,x));
export const mix=(a,b,x)=>a+(b-a)*x;
// A knot is [time, value, incoming velocity, outgoing velocity].
// Zero tangents at a hold are deliberate; cuts are separate shots.
export function track(t,knots){
 if(t<=knots[0][0])return knots[0][1];
 if(t>=knots.at(-1)[0])return knots.at(-1)[1];
 for(let i=0;i<knots.length-1;i++){
  const a=knots[i],b=knots[i+1];if(t>b[0])continue;
  const dt=b[0]-a[0],u=(t-a[0])/dt,u2=u*u,u3=u2*u;
  return (2*u3-3*u2+1)*a[1]+(u3-2*u2+u)*dt*(a[3]??a[2]??0)+(-2*u3+3*u2)*b[1]+(u3-u2)*dt*(b[2]??0);
 }
}
export function shotAt(t){return SHOTS.find(s=>t>=s.start&&t<s.end)||SHOTS.at(-1)}
export function sampleMotion(t){
 const s=shotAt(t),u=t-s.start;
 if(s.id==='chip')return {parameter:'芯片屏幕宽度',value:track(u,[[0,2.50,-.1],[.16,2.47,-.4],[.33,2.35,-4.8],[.5,1.49,-3.2],[.66,1.17,-.7],[.83,1.10,-.1],[1,1.09,0],[2.68,1.09,0]])};
 if(s.id==='with')return {parameter:'文字横向比例',value:track(u,[[0,1,.065],[.55,1.036,.065]])};
 if(s.id==='render')return {parameter:'反射扫描位置',value:track(u,[[0,-1,.4],[.45,-.6,1.5],[1.1,.65,1.1],[2,1.35,.2]])};
 if(s.id==='own')return {parameter:'右侧新词入场进度',value:track(u,[[0,0,0],[.375,0,0],[.417,.84,5],[.5,.96,.6],[.75,1,0],[4.2,1,0]])};
 return {parameter:'镜头内时间',value:u};
}
