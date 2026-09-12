import {chromium} from 'playwright-core';
import {spawn} from 'node:child_process';
import {once} from 'node:events';
import {access,mkdir,writeFile} from 'node:fs/promises';
import path from 'node:path';
import {performance} from 'node:perf_hooks';
import {startServer,repositoryRoot} from './serve.mjs';

const options=Object.fromEntries(process.argv.slice(2).map(arg=>{
  const index=arg.indexOf('=');return [arg.slice(2,index<0?undefined:index),index<0?true:arg.slice(index+1)];
}));
if(options.help){
  console.log('node media/intro-three/render.mjs [--stills=0.5,2] [--start=0] [--duration=4] [--frames=120] [--fps=60] [--width=1920] [--height=1080] [--output=outputs/intro-three/sample.mp4] [--software] [--save-frames]');
  process.exit(0);
}
const number=(key,fallback)=>{
  const value=Number(options[key]??fallback);
  if(!Number.isFinite(value)||value<0)throw Error(`Invalid --${key}`);
  return value;
};
const width=number('width',1920),height=number('height',1080);
if(!Number.isInteger(width)||!Number.isInteger(height)||width<2||height<2||width%2||height%2)throw Error('Dimensions must be positive even integers.');
const output=path.resolve(repositoryRoot,String(options.output || 'outputs/intro-three/h3loom-type-study.mp4'));
await mkdir(path.dirname(output),{recursive:true});
const imageDir=path.join(path.dirname(output),path.basename(output,path.extname(output))+'-frames');
const chrome=process.env.CHROME_EXECUTABLE || '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome';
await access(chrome);
const {server,url}=await startServer({port:0});
let browser,encoder;
const pageErrors=[];
let encoderError,encoderStderr='';
try {
  browser=await chromium.launch({executablePath:chrome,headless:!options.headed,args:[
    '--hide-scrollbars','--disable-background-timer-throttling','--disable-renderer-backgrounding',
    ...(options.software?['--use-angle=swiftshader','--enable-unsafe-swiftshader']:['--use-angle=metal'])
  ]});
  const page=await browser.newPage({viewport:{width,height},deviceScaleFactor:1});
  page.on('pageerror',error=>pageErrors.push(error.message));
  await page.route('**/*',route=>{
    const requestURL=new URL(route.request().url());
    if(requestURL.origin===url || ['data:','blob:'].includes(requestURL.protocol))return route.continue();
    pageErrors.push(`External dependency blocked: ${requestURL.origin}${requestURL.pathname}`);
    return route.abort('blockedbyclient');
  });
  const response=await page.goto(`${url}/?render=1&width=${width}&height=${height}`,{waitUntil:'networkidle'});
  if(!response.ok())throw Error(`Scene failed to load: HTTP ${response.status()}`);
  await page.waitForFunction(()=>window.film?.ready===true,{},{timeout:60000});
  if(pageErrors.length)throw Error(pageErrors.join('\n'));
  const settings=await page.evaluate(()=>({duration:window.film.duration,fps:window.film.fps}));
  const fps=number('fps',settings.fps || 60),start=number('start',0);
  if(fps<=0||fps>120||start>=settings.duration)throw Error('Invalid FPS or start beyond film duration.');
  const duration=Math.min(number('duration',settings.duration-start),settings.duration-start);
  const frameCount=options.frames===undefined?Math.round(duration*fps):number('frames',0);
  if(!Number.isInteger(frameCount)||frameCount<1||start+(frameCount-1)/fps>=settings.duration)throw Error('Invalid frame count or range beyond film duration.');
  const gpu=await page.evaluate(()=>{
    const canvas=document.querySelector('canvas');
    const gl=canvas.getContext('webgl2') || canvas.getContext('webgl');
    if(!gl)return {renderer:'No WebGL context',software:null};
    const ext=gl.getExtension('WEBGL_debug_renderer_info');
    const renderer=gl.getParameter(ext?ext.UNMASKED_RENDERER_WEBGL:gl.RENDERER);
    return {renderer,vendor:gl.getParameter(ext?ext.UNMASKED_VENDOR_WEBGL:gl.VENDOR),version:gl.getParameter(gl.VERSION),software:/swiftshader|llvmpipe|software/i.test(renderer)};
  });
  console.log(JSON.stringify({browser:browser.version(),gpu,width,height,fps,start,frameCount}));
  const session=await page.context().newCDPSession(page);
  await session.send('Page.enable');
  const capture=async time=>{
    const bounds=await page.evaluate(async time=>{
      await window.film.renderAt(time);
      const r=document.querySelector('canvas').getBoundingClientRect();
      return {x:r.left+scrollX,y:r.top+scrollY,width:r.width,height:r.height};
    },time);
    if(bounds.width!==width||bounds.height!==height)throw Error(`Canvas CSS size ${bounds.width}×${bounds.height} differs from export ${width}×${height}`);
    const {data}=await session.send('Page.captureScreenshot',{format:'png',fromSurface:true,captureBeyondViewport:true,optimizeForSpeed:true,clip:{...bounds,scale:1}});
    return Buffer.from(data,'base64');
  };
  const begin=performance.now();
  if(options.stills!==undefined){
    await mkdir(imageDir,{recursive:true});
    const times=String(options.stills).split(',').map(Number);
    for(const time of times){
      if(!Number.isFinite(time)||time<0||time>=settings.duration)throw Error(`Invalid still time ${time}`);
      const filename=path.join(imageDir,`still-${time.toFixed(3).replace('.','-')}.png`);
      await writeFile(filename,await capture(time));console.log(filename);
    }
    if(pageErrors.length)throw Error(`Scene errors occurred: ${pageErrors.join('\n')}`);
    await writeFile(output+'.stills.json',JSON.stringify({gpu,times,elapsedSeconds:(performance.now()-begin)/1000},null,2)+'\n');
  } else {
    if(options['save-frames'])await mkdir(imageDir,{recursive:true});
    encoder=spawn(process.env.FFMPEG || 'ffmpeg',['-hide_banner','-loglevel','warning','-y','-f','image2pipe','-vcodec','png','-framerate',String(fps),'-i','pipe:0','-an','-c:v','libx264','-preset','fast','-crf',String(number('crf',18)),'-pix_fmt','yuv420p','-movflags','+faststart',output],{stdio:['pipe','ignore','pipe']});
    const encoderDone=new Promise(resolve=>{encoder.once('error',error=>{encoderError=error;resolve(-1);});encoder.once('close',resolve);});
    encoder.stdin.on('error',error=>encoderError=error);
    encoder.stderr.on('data',chunk=>encoderStderr=(encoderStderr+chunk).slice(-12000));
    for(let frame=0;frame<frameCount;frame++){
      if(encoderError)throw encoderError;
      const png=await capture(start+frame/fps);
      if(options['save-frames'])await writeFile(path.join(imageDir,`frame-${String(frame).padStart(5,'0')}.png`),png);
      if(!encoder.stdin.write(png))await once(encoder.stdin,'drain');
      if(frame===0||(frame+1)%60===0||frame===frameCount-1)console.log(`frame ${frame+1}/${frameCount}; ${((frame+1)/((performance.now()-begin)/1000)).toFixed(1)} frames/s`);
    }
    encoder.stdin.end();
    const code=await encoderDone;
    if(code!==0||encoderError)throw Error(`FFmpeg failed (${code}): ${encoderError?.message || ''}\n${encoderStderr}`);
    if(pageErrors.length)throw Error(`Scene errors occurred: ${pageErrors.join('\n')}`);
    const elapsedSeconds=(performance.now()-begin)/1000;
    await writeFile(output+'.json',JSON.stringify({output,width,height,fps,start,frameCount,duration:frameCount/fps,gpu,browser:browser.version(),elapsedSeconds,renderFramesPerSecond:frameCount/elapsedSeconds,encodedAt:new Date().toISOString(),audio:false},null,2)+'\n');
    console.log(`Saved ${output}; ${(elapsedSeconds/60).toFixed(2)} min, ${(frameCount/elapsedSeconds).toFixed(1)} frames/s`);
  }
} finally {
  if(encoder && encoder.exitCode===null)encoder.kill('SIGTERM');
  if(browser)await browser.close();
  await new Promise(resolve=>server.close(resolve));
}
