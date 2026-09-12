// Original local synthesis, authored against the picture's actual edit points.
// No sampled commercial music, speech synthesis, or generated media service.
const fs=require('node:fs'),path=require('node:path');
const root=path.resolve(__dirname,'../..'),out=path.join(root,'outputs/intro-three');fs.mkdirSync(out,{recursive:true});
const SR=48000,D=24,N=SR*D,L=new Float64Array(N),R=new Float64Array(N);let seed=20260912;
const rand=()=>{seed=(1664525*seed+1013904223)>>>0;return seed/4294967296*2-1};
function voice(start,dur,fn,pan=0){const a=Math.round(start*SR),n=Math.ceil(dur*SR),lg=Math.sqrt((1-pan)/2),rg=Math.sqrt((1+pan)/2);for(let j=0;j<n;j++){let k=a+j;if(k<0||k>=N)continue;const v=fn(j/SR,j/n);L[k]+=v*lg;R[k]+=v*rg}}
function kick(t,amp=.40){voice(t,.32,(x)=>amp*Math.sin(2*Math.PI*(48*x+9*(1-Math.exp(-x*25))))*Math.exp(-x*14)*(1-Math.exp(-x*650)))}
function click(t,amp=.1,pan=0){voice(t,.08,x=>amp*(rand()*.42+Math.sin(x*2*Math.PI*2100)*.3)*Math.exp(-x*95)*(1-Math.exp(-x*1200)),pan)}
function whoosh(t,dur,amp=.09){let z=0;voice(t,dur,(x,u)=>{z=.77*z+.23*rand();return z*amp*Math.pow(Math.sin(Math.PI*u),2)},-.15)}
// A restrained bass pulse gives the holds momentum without covering each edit.
const beat=60/144;for(let t=0;t<19.4;t+=beat){const i=Math.round(t/beat);kick(t,i%4===0?.22:.15);if(i%2===1)click(t+.5*beat,.055,.28);const freq=[55,55,65.406,49][Math.floor(i/8)%4];voice(t+.01,.33,(x)=>.072*(Math.sin(2*Math.PI*freq*x)+.18*Math.sin(2*Math.PI*freq*2*x))*Math.exp(-x*11)*(1-Math.exp(-x*300)),0)}
for(const t of [.95,2.82,3.30,4.7,5.25,5.92,8.20,10.60,11.2,12.98,17.32,18.13,18.78,19.52]){kick(t,.30);click(t,.12);whoosh(t-.085,.11,.11)}
// Rapid reflow accents follow the actual motion bursts, independent of the beat.
for(const [i,t] of [13.575,13.95,15.45,15.7,15.95,16.2].entries()){click(t,.15,i%2?.25:-.25);voice(t,.12,x=>.11*Math.sin(2*Math.PI*(130*x+4*(1-Math.exp(-x*25))))*Math.exp(-x*35))}
whoosh(6.11,.50,.2);whoosh(8.55,1.6,.05);whoosh(12.95,.26,.14);
// Sparse final cadence under the signature.
for(const [i,f] of [110,164.8138,220,261.6256].entries())voice(19.4,4.6,(x,u)=>.065*(Math.sin(2*Math.PI*f*x)+.12*Math.sin(2*Math.PI*f*2*x))*Math.exp(-x*.72)*Math.min(1,x/.016)*Math.min(1,(1-u)*8),(i-1.5)*.18);
let peak=0;for(let i=0;i<N;i++)peak=Math.max(peak,Math.abs(L[i]),Math.abs(R[i]));const gain=.67/peak;
const buffer=Buffer.alloc(44+N*4);buffer.write('RIFF',0);buffer.writeUInt32LE(36+N*4,4);buffer.write('WAVEfmt ',8);buffer.writeUInt32LE(16,16);buffer.writeUInt16LE(1,20);buffer.writeUInt16LE(2,22);buffer.writeUInt32LE(SR,24);buffer.writeUInt32LE(SR*4,28);buffer.writeUInt16LE(4,32);buffer.writeUInt16LE(16,34);buffer.write('data',36);buffer.writeUInt32LE(N*4,40);
for(let i=0;i<N;i++){let fade=Math.min(1,i/(SR*.005),(N-1-i)/(SR*.08));buffer.writeInt16LE(Math.round(Math.max(-1,Math.min(1,L[i]*gain*fade))*32767),44+i*4);buffer.writeInt16LE(Math.round(Math.max(-1,Math.min(1,R[i]*gain*fade))*32767),46+i*4)}
const target=path.join(out,'score-connected.wav');fs.writeFileSync(target,buffer);console.log(JSON.stringify({path:target,duration:D,sampleRate:SR,peakDB:20*Math.log10(.67),provenance:'original deterministic oscillator/noise synthesis; seed 20260912'}));
