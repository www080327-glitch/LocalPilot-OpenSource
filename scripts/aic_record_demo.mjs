import fs from 'node:fs/promises';
import {createRequire} from 'node:module';
import {fileURLToPath} from 'node:url';
const require=createRequire('/Users/localpilot-user/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/playwright/package.json');
const root=fileURLToPath(new URL('../',import.meta.url));
process.env.PLAYWRIGHT_BROWSERS_PATH=root+'.aic-runtime/browser-cache';
await fs.mkdir(process.env.PLAYWRIGHT_BROWSERS_PATH,{recursive:true});
try{await fs.symlink('/Users/localpilot-user/Library/Caches/ms-playwright/ffmpeg-1013',process.env.PLAYWRIGHT_BROWSERS_PATH+'/ffmpeg-1011','dir');}catch(e){if(e.code!=='EEXIST')throw e;}
const {chromium}=require('playwright');
const out=root+'.aic-runtime/video-recording'+(process.argv[2]??'6');await fs.mkdir(out,{recursive:true});
await fs.mkdir(out+'/frames',{recursive:true});
const config=JSON.parse(await fs.readFile(root+'.aic-runtime/video-url.json','utf8'));
const browser=await chromium.launch({headless:true,executablePath:'/Users/localpilot-user/Library/Caches/ms-playwright/chromium_headless_shell-1248/chrome-headless-shell-mac-arm64/chrome-headless-shell'});
const context=await browser.newContext({viewport:{width:1280,height:720},deviceScaleFactor:1});
const page=await context.newPage();await page.goto(config.url);await page.screenshot({path:out+'/initial.png'});
await page.request.get(config.url+'/start');
const started=Date.now();let done=false;const frames=[];let index=0,lastCheck=0;
while(Date.now()-started<260000){
  const frameStart=Date.now();
  const frame=out+'/frames/'+String(index++).padStart(5,'0')+'.jpg';
  await page.screenshot({path:frame,type:'jpeg',quality:80});
  frames.push({path:frame,seconds:(frameStart-started)/1000});
  if(Date.now()-lastCheck>1000){
    const s=await (await page.request.get(config.url+'/state')).json();lastCheck=Date.now();
    if(s.done){done=true;break;}
  }
  await new Promise(r=>setTimeout(r,Math.max(0,333-(Date.now()-frameStart))));
}
await page.screenshot({path:out+'/final.png'});await context.close();await browser.close();
await fs.writeFile(out+'/recording.json',JSON.stringify({frames,done,durationSeconds:(Date.now()-started)/1000,scope:'live SDK event viewer; not native desktop GUI',capture:'timestamped browser screenshots at approximately 3 fps',realTime:true},null,2));
console.log(JSON.stringify({frames:frames.length,done}));
