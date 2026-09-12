import {spawn} from 'node:child_process';
import {fileURLToPath} from 'node:url';
import path from 'node:path';
const root=path.resolve(path.dirname(fileURLToPath(import.meta.url)),'../..');
async function run(cmd,args){await new Promise((resolve,reject)=>{const p=spawn(cmd,args,{cwd:root,stdio:'inherit'});p.once('error',reject);p.once('exit',code=>code===0?resolve():reject(new Error(`${cmd} exited ${code}`)))})}
if(!process.argv.includes('--mux-only'))await run(process.execPath,['media/intro-three/render.mjs','--fps=60','--output=outputs/intro-three/h3loom-type-connected-silent.mp4']);
await run(process.execPath,['media/intro-three/audio.cjs']);
await run(process.env.FFMPEG||'ffmpeg',['-hide_banner','-loglevel','warning','-y','-i','outputs/intro-three/h3loom-type-connected-silent.mp4','-i','outputs/intro-three/score-connected.wav','-map','0:v:0','-map','1:a:0','-c:v','copy','-c:a','aac','-b:a','160k','-t','24','-movflags','+faststart','outputs/intro-three/h3loom-type-connected.mp4']);
console.log(path.join(root,'outputs/intro-three/h3loom-type-connected.mp4'));
