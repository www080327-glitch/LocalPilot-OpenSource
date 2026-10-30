const esbuild = require('../desktop/node_modules/esbuild');
const fs = require('fs'), path = require('path');
const root=path.resolve(__dirname,'../../references/deepseek-harness-parity-20261024');
const old=path.resolve(__dirname,'../../references/deepseek-harness-20261022');
const packageDirs={};
function walk(p,depth=0){if(depth>4)return;for(const e of fs.readdirSync(p,{withFileTypes:true})){if(!e.isDirectory()||['node_modules','lib','.git'].includes(e.name))continue;const d=path.join(p,e.name);if(fs.existsSync(path.join(d,'package.json'))){const m=JSON.parse(fs.readFileSync(path.join(d,'package.json')));packageDirs[m.name]=d;}walk(d,depth+1);}}
walk(path.join(root,'packages'));
esbuild.build({stdin:{contents:`export { seatbeltProfileArgs } from '${root}/packages/sandbox/sandbox-local/src/profiles.ts'; export { approveEscalation } from '${root}/packages/sandbox/sandbox/src/escalation.ts';`,resolveDir:root},outfile:path.resolve(__dirname,'../docs/evidence/desktop-permission-parity-20261024/dsh-pinned.mjs'),bundle:true,platform:'node',format:'esm',packages:'external',plugins:[{name:'pinned-workspace',setup(b){b.onResolve({filter:/^@deepseek-ai\/dsh-(sandbox|util-values)$/},a=>{const d=packageDirs[a.path];return {path:path.join(d,'src/index.ts')};});b.onResolve({filter:/^@deepseek-ai\//},a=>{const importer=a.importer.replace(root,old);try{return {path:require.resolve(a.path,{paths:[path.dirname(importer),old]}),external:true};}catch{return {path:a.path,external:true};}});}}]}).catch(e=>{console.error(e);process.exit(1)});
