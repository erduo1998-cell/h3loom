const fs=require('node:fs'),path=require('node:path'),{spawnSync}=require('node:child_process');
const mac='/Applications/Blender.app/Contents/MacOS/Blender';
const blender=process.env.BLENDER_BIN||(fs.existsSync(mac)?mac:'blender');
const args=['--background','--factory-startup','--python-exit-code','1','--python',path.join(__dirname,'film.py'),'--','--engine','eevee','--out','promo-v2-final'];
const stills=process.argv.includes('--stills');if(stills)args.push('--stills');
let r=spawnSync(blender,args,{stdio:'inherit'});if(r.error)throw r.error;if(r.status)process.exit(r.status);
if(!stills){r=spawnSync(process.execPath,[path.join(__dirname,'finish.cjs')],{stdio:'inherit'});if(r.error)throw r.error;process.exit(r.status||0);}
