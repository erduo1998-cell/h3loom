import http from 'node:http';
import {createReadStream} from 'node:fs';
import {stat} from 'node:fs/promises';
import path from 'node:path';
import {fileURLToPath} from 'node:url';

export const projectRoot = path.dirname(fileURLToPath(import.meta.url));
export const repositoryRoot = path.resolve(projectRoot, '../..');
const types = {'.html':'text/html; charset=utf-8','.js':'text/javascript; charset=utf-8','.mjs':'text/javascript; charset=utf-8','.css':'text/css; charset=utf-8','.json':'application/json','.ttf':'font/ttf','.woff2':'font/woff2','.png':'image/png','.jpg':'image/jpeg','.webp':'image/webp','.mp4':'video/mp4','.svg':'image/svg+xml'};
const fonts = {
  '/fonts/display.ttf': '/System/Library/Fonts/Supplemental/DIN Condensed Bold.ttf',
  '/fonts/label.ttf': '/System/Library/Fonts/Supplemental/Arial.ttf'
};

export async function startServer({port=8790, host='127.0.0.1'}={}) {
  const server = http.createServer(async(req,res)=>{
    try {
      const pathname = decodeURIComponent(new URL(req.url,'http://localhost').pathname);
      let filename = fonts[pathname];
      if (!filename) {
        const isOutput = pathname.startsWith('/outputs/intro-three/');
        const root = isOutput ? path.join(repositoryRoot,'outputs/intro-three') : projectRoot;
        const relative = isOutput ? pathname.slice('/outputs/intro-three/'.length) : pathname.slice(1);
        filename = path.resolve(root,relative || 'index.html');
        if (filename !== root && !filename.startsWith(root + path.sep)) {res.writeHead(403).end();return;}
      }
      const info = await stat(filename);
      if (!info.isFile()) {res.writeHead(404).end();return;}
      const headers = {'Content-Type':types[path.extname(filename)] || 'application/octet-stream','Cache-Control':'no-store','Accept-Ranges':'bytes'};
      const range = req.headers.range?.match(/^bytes=(\d+)-(\d*)$/);
      if (range) {
        const start = Number(range[1]);
        const end = range[2] ? Math.min(Number(range[2]),info.size-1) : info.size-1;
        if(start>end || start>=info.size) {res.writeHead(416,{'Content-Range':`bytes */${info.size}`}).end();return;}
        res.writeHead(206,{...headers,'Content-Length':end-start+1,'Content-Range':`bytes ${start}-${end}/${info.size}`});
        createReadStream(filename,{start,end}).pipe(res);
      } else {
        res.writeHead(200,{...headers,'Content-Length':info.size});
        if(req.method==='HEAD')res.end();else createReadStream(filename).pipe(res);
      }
    } catch (error) {res.writeHead(error.code==='ENOENT'?404:500).end('Local asset unavailable');}
  });
  await new Promise((resolve,reject)=>{server.once('error',reject);server.listen(port,host,resolve);});
  const address=server.address();
  return {server,url:`http://${host}:${address.port}`};
}

if (process.argv[1] && path.resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  const {url}=await startServer({port:Number(process.env.PORT || 8790)});
  console.log(`Three.js study: ${url}`);
}
