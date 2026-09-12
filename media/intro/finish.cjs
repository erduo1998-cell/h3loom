/* Assemble original Blender frames, original synthesized audio and text overlays. */
const {createCanvas,loadImage,GlobalFonts}=require('@napi-rs/canvas');
const {spawn,spawnSync}=require('node:child_process');
const {once}=require('node:events');
const fs=require('node:fs');
const path=require('node:path');
const OUT=path.resolve(__dirname,'../../outputs',process.env.H3LOOM_RENDER_DIR||'promo-v2-final');
const cn=process.env.H3LOOM_CHINESE_FONT||'/System/Library/Fonts/Supplemental/Arial Unicode.ttf';
if(!fs.existsSync(cn))throw Error('Set H3LOOM_CHINESE_FONT to an installed font containing Chinese glyphs.');
GlobalFonts.registerFromPath(cn,'FilmChinese');
const FPS=30, W=1920,H=1080;
const count=Number(process.env.H3LOOM_FRAME_COUNT||720),duration=count/FPS;
const clamp=(x,a=0,b=1)=>Math.max(a,Math.min(b,x));
const cuts=[0,2.6,3.35,4.6,7.4,8.45,12.4,14.2,17,20.1];
function audio(){
 const rate=48000,N=Math.round(duration*rate),buf=Buffer.alloc(44+N*4);
 buf.write('RIFF');buf.writeUInt32LE(buf.length-8,4);buf.write('WAVEfmt ',8);
 buf.writeUInt32LE(16,16);buf.writeUInt16LE(1,20);buf.writeUInt16LE(2,22);
 buf.writeUInt32LE(rate,24);buf.writeUInt32LE(rate*4,28);buf.writeUInt16LE(4,32);buf.writeUInt16LE(16,34);buf.write('data',36);buf.writeUInt32LE(N*4,40);
 let seed=73129,low=0;
 for(let i=0;i<N;i++){
  const t=i/rate,beat=t%(60/138),hat=t%(60/138/2);
  seed=(Math.imul(seed,1664525)+1013904223)|0;
  const noise=seed/2147483648;low=.94*low+.06*noise;
  let v=Math.sin(2*Math.PI*(46*beat+4.5*(1-Math.exp(-beat*28))))*Math.exp(-beat*15)*.30;
  v+=(noise-low)*Math.exp(-hat*140)*.035;
  const freq=[55,55,65.406,49][Math.floor(t/3.48)%4];
  v+=Math.sin(2*Math.PI*freq*t)*.05*Math.exp(-beat*5);
  for(const cut of cuts){
   const d=t-cut;
   if(d>=0&&d<.8) v+=Math.sin(2*Math.PI*(60*d+3*(1-Math.exp(-d*20))))*Math.exp(-d*9)*.24;
   if(d>-.27&&d<0) v+=(noise-low)*Math.pow(1+d/.27,2)*.07;
  }
  // The camera dive is a rising filtered sweep; final signature resolves in a chord.
  for(const start of [6.7,11.7]) {const d=t-start;if(d>=0&&d<.7)v+=low*Math.pow(d/.7,2)*.24;}
  if(t>20.1){const d=t-20.1;v+=.06*(Math.sin(2*Math.PI*220*d)+.4*Math.sin(2*Math.PI*329.627*d)+.3*Math.sin(2*Math.PI*440*d))*Math.exp(-d*1.2);}
  const gain=clamp(t/.03)*clamp((duration-t)/.55);
  const value=Math.tanh(v)*gain;
  for(let ch=0;ch<2;ch++)buf.writeInt16LE(Math.round(clamp(value*(1+(ch?1:-1)*.018*Math.sin(t*2)),-.98,.98)*32767),44+i*4+ch*2);
 }
 const p=path.join(OUT,'sound-v2.wav');fs.writeFileSync(p,buf);return p;
}
const captions=[
 [4.85,6.55,'先设计，再确认。','四格故事板 · 分阶段审核'],
 [8.8,10.8,'把创作，交给自己的云端。','MiniMax H3 · AutoDL'],
 [17.3,19.9,'生成 · 下载 · 恢复','独立素材，交由你筛选。'],
 [20.65,24,'从字幕，到自己的视频素材。','SRT → STORYBOARD → CLOUD → 4K']
];
async function main(){
 for(let i=0;i<count;i++)if(!fs.existsSync(path.join(OUT,`frame-${String(i).padStart(5,'0')}.png`)))throw Error(`Frame ${i} missing; refusing partial final export.`);
 const c=createCanvas(W,H),ctx=c.getContext('2d');
 const dest=path.join(OUT,count===720?'h3loom-intro-v2.mp4':'motion-preview.mp4');
 const enc=spawn('ffmpeg',['-hide_banner','-loglevel','error','-y','-f','rawvideo','-pixel_format','rgba','-video_size',`${W}x${H}`,'-framerate',String(FPS),'-i','-','-i',audio(),'-c:v','libx264','-preset','medium','-crf','17','-pix_fmt','yuv420p','-c:a','aac','-b:a','192k','-shortest','-movflags','+faststart',dest],{stdio:['pipe','inherit','inherit']});
 let failure;enc.on('error',e=>failure=e);enc.stdin.on('error',e=>failure=e);
 for(let i=0;i<count;i++){
  if(failure)throw failure;
  const img=await loadImage(path.join(OUT,`frame-${String(i).padStart(5,'0')}.png`));
  const t=i/FPS;
  ctx.fillStyle='#000';ctx.fillRect(0,0,W,H);
  const boardScale=t>=4.6&&t<7.4 ? .9+.1*clamp((t-6.7)/.7) : 1;
  ctx.drawImage(img,(W-W*boardScale)/2,0,W*boardScale,H*boardScale);
  for(const [start,end,zh,en]of captions)if(t>=start&&t<end){
   const a=Math.min(clamp((t-start)/.15),clamp((end-t)/.15));
   ctx.save();ctx.globalAlpha=a;ctx.textAlign='center';
   ctx.shadowColor='#000';ctx.shadowBlur=8;
   ctx.font='400 34px FilmChinese';ctx.fillStyle='#d7d9df';ctx.fillText(zh,960,1002);
   ctx.font='400 20px FilmChinese';ctx.fillStyle='#858a98';ctx.fillText(en,960,1040);ctx.restore();
  }
  if(!enc.stdin.write(c.data()))await once(enc.stdin,'drain');
  if(i===645)fs.writeFileSync(path.join(OUT,'poster-v2.png'),c.toBuffer('image/png'));
 }
 enc.stdin.end();const [code]=await once(enc,'close');if(code)throw Error('FFmpeg failed');
 const check=spawnSync('ffprobe',['-v','error','-show_entries','format=duration:stream=codec_name,width,height,r_frame_rate','-of','json',dest],{encoding:'utf8'});
 if(check.status)throw Error(check.stderr);fs.writeFileSync(path.join(OUT,'encode-receipt.json'),check.stdout);console.log(dest);console.log(check.stdout);
}
main().catch(e=>{console.error(e);process.exitCode=1});
