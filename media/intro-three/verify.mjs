import {chromium} from 'playwright-core';
import {spawnSync} from 'node:child_process';
import {createHash} from 'node:crypto';
import {mkdir,readFile,writeFile} from 'node:fs/promises';
import path from 'node:path';
import {startServer,projectRoot,repositoryRoot} from './serve.mjs';

// Necessary render-contract check: arbitrary seeking must reproduce identical pixels.
// This is not an aesthetic comparison against the reference advertisement.
const width=1920,height=1080;
const options=Object.fromEntries(process.argv.slice(2).map(arg=>{
  const index=arg.indexOf('=');return [arg.slice(2,index<0?undefined:index),index<0?true:arg.slice(index+1)];
}));
const timeList=(key,fallback)=>{
  if(options[key]===undefined)return fallback;
  const values=String(options[key]).split(',').map(Number);
  if(!values.length || String(options[key]).trim()==='' || values.some(value=>!Number.isFinite(value)||value<0))throw Error(`Invalid --${key}`);
  return values;
};
const times=timeList('times',[6.25,6.42,9,13.62,14.1,16,21]);
const detours=timeList('detours',[23.75,0.1,11.3]);
const name=String(options.name || 'seek-verification');
if(!/^[a-zA-Z0-9_-]+$/.test(name))throw Error('--name accepts letters, digits, underscores and hyphens only.');
const outputRoot=path.join(repositoryRoot,'outputs/intro-three');
const imageRoot=path.join(outputRoot,name);
await mkdir(imageRoot,{recursive:true});
const hash=buffer=>createHash('sha256').update(buffer).digest('hex');
const decode=png=>{
  const result=spawnSync(process.env.FFMPEG || 'ffmpeg',['-v','error','-i','pipe:0','-frames:v','1','-f','rawvideo','-pix_fmt','rgb24','pipe:1'],{input:png,maxBuffer:width*height*3+1024*1024});
  if(result.status!==0||result.stdout.length!==width*height*3)throw Error(`PNG decode failed: ${result.error?.message || result.stderr.toString()}`);
  return result.stdout;
};
const pixelStats=rgb=>{
  let max=0,nonBlackPixels=0;
  for(let p=0;p<rgb.length;p+=3){
    const brightest=Math.max(rgb[p],rgb[p+1],rgb[p+2]);
    max=Math.max(max,brightest);if(brightest>8)nonBlackPixels++;
  }
  return {maxChannel:max,nonBlackPixels,nonBlackFraction:nonBlackPixels/(width*height),unexpectedBlack:nonBlackPixels===0};
};
const errors=[],records=[],sources={};
for(const file of ['index.html','scene.js','motion-score.js','type-kit.js'])sources[file]=hash(await readFile(path.join(projectRoot,file)));
const {server,url}=await startServer({port:0});
let browser;
const report={checkedAt:new Date().toISOString(),width,height,times,detours,sources,records,errors,passed:false};
try {
  browser=await chromium.launch({executablePath:process.env.CHROME_EXECUTABLE || '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome',headless:true,args:['--use-angle=metal','--hide-scrollbars','--disable-background-timer-throttling','--disable-renderer-backgrounding']});
  report.browser=browser.version();
  const page=await browser.newPage({viewport:{width,height},deviceScaleFactor:1});
  page.on('pageerror',error=>errors.push(error.message));
  page.on('console',message=>{if(message.type()==='error')errors.push(`Console: ${message.text()}`);});
  await page.route('**/*',route=>{
    const request=new URL(route.request().url());
    if(request.origin===url || ['blob:','data:'].includes(request.protocol))return route.continue();
    errors.push(`External dependency blocked: ${request.origin}${request.pathname}`);return route.abort('blockedbyclient');
  });
  await page.goto(`${url}/?render=1&width=${width}&height=${height}`,{waitUntil:'networkidle'});
  await page.waitForFunction(()=>window.film?.ready===true,{},{timeout:60000});
  const duration=await page.evaluate(()=>window.film.duration);
  if([...times,...detours].some(time=>time>=duration))throw Error(`Requested time is outside film duration ${duration}.`);
  report.gpu=await page.evaluate(()=>{
    const gl=document.querySelector('canvas').getContext('webgl2');
    const ext=gl.getExtension('WEBGL_debug_renderer_info');
    return gl.getParameter(ext?ext.UNMASKED_RENDERER_WEBGL:gl.RENDERER);
  });
  const session=await page.context().newCDPSession(page);
  const capture=async time=>{
    const clip=await page.evaluate(async time=>{
      await window.film.renderAt(time);
      const rect=document.querySelector('canvas').getBoundingClientRect();
      return {x:rect.left+scrollX,y:rect.top+scrollY,width:rect.width,height:rect.height,scale:1};
    },time);
    if(clip.width!==width||clip.height!==height)throw Error(`Unexpected canvas CSS size ${clip.width}x${clip.height}`);
    const {data}=await session.send('Page.captureScreenshot',{format:'png',clip,fromSurface:true,captureBeyondViewport:true,optimizeForSpeed:true});
    return Buffer.from(data,'base64');
  };
  const baselines=new Map();
  for(const time of times){
    const png=await capture(time),rgb=decode(png);
    const filename=path.join(imageRoot,`baseline-${time.toFixed(3)}.png`);
    await writeFile(filename,png);
    baselines.set(time,{pngHash:hash(png),rgbHash:hash(rgb),rgb,filename,stats:pixelStats(rgb)});
  }
  for(const time of times){
    const baseline=baselines.get(time);
    const record={time,baseline:baseline.filename,pngSHA256:baseline.pngHash,pixelsSHA256:baseline.rgbHash,...baseline.stats,returns:[]};
    for(const detour of detours){
      await page.evaluate(async time=>{await window.film.renderAt(time);},detour);
      const png=await capture(time),rgb=decode(png);
      const pngSHA256=hash(png),pixelsSHA256=hash(rgb);
      let changedPixels=0,maxDifference=0;
      for(let p=0;p<rgb.length;p+=3){
        const difference=Math.max(Math.abs(rgb[p]-baseline.rgb[p]),Math.abs(rgb[p+1]-baseline.rgb[p+1]),Math.abs(rgb[p+2]-baseline.rgb[p+2]));
        if(difference)changedPixels++;maxDifference=Math.max(maxDifference,difference);
      }
      const returned={detour,pngSHA256,pixelsSHA256,pngIdentical:pngSHA256===baseline.pngHash,pixelsIdentical:pixelsSHA256===baseline.rgbHash,changedPixels,maxChannelDifference:maxDifference,...pixelStats(rgb)};
      if(!returned.pngIdentical){
        returned.image=path.join(imageRoot,`returned-${time.toFixed(3)}-from-${detour.toFixed(3)}.png`);
        await writeFile(returned.image,png);
      }
      record.returns.push(returned);
    }
    records.push(record);
    console.log(`${time.toFixed(3)} s: ${record.returns.every(r=>r.pngIdentical)?`PNG identical across all ${detours.length} detours`:'DIFFERENT'}; ${baseline.stats.nonBlackPixels} non-black pixels`);
  }
  const currentSources={};
  for(const file of Object.keys(sources))currentSources[file]=hash(await readFile(path.join(projectRoot,file)));
  report.sourcesUnchanged=Object.keys(sources).every(file=>sources[file]===currentSources[file]);
  if(!report.sourcesUnchanged)errors.push('Scene source changed during verification; rerun against the final source.');
  report.passed=errors.length===0 && records.length===times.length && records.every(record=>!record.unexpectedBlack && record.returns.every(result=>result.pngIdentical && result.pixelsIdentical && !result.unexpectedBlack));
} catch(error){errors.push(error.stack || String(error));}
finally {
  if(browser)await browser.close();
  await new Promise(resolve=>server.close(resolve));
  const reportFile=path.join(outputRoot,`${name}.json`);
  await writeFile(reportFile,JSON.stringify(report,null,2)+'\n');
  console.log(`${report.passed?'PASS':'FAIL'} ${reportFile}`);
  if(!report.passed)process.exitCode=1;
}
