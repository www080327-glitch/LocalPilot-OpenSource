// Pinned DSH functions + real macOS Seatbelt processes. Host answers are scripted.
// This is NOT a GUI/model comparison or a measurement of human popups.
import { seatbeltProfileArgs, approveEscalation } from '../docs/evidence/desktop-permission-parity-20261024/dsh-pinned.mjs';
import { spawnSync } from 'node:child_process';
import { mkdirSync, writeFileSync, readFileSync, existsSync, realpathSync } from 'node:fs';
import { resolve } from 'node:path';
import { performance } from 'node:perf_hooks';
const out=resolve('docs/evidence/desktop-permission-parity-20261024');
const fixture=resolve(out,'dsh-boundary-files');mkdirSync(fixture,{recursive:true});
const q=s=>`'${s.replaceAll("'","'\\''")}'`;
const rows=[];
for(const mode of ['read-only','workspace-write','danger-full-access']){
 const base=resolve(fixture,mode);const work=resolve(base,'work');const outside=resolve(base,'outside');
 mkdirSync(work,{recursive:true});mkdirSync(outside,{recursive:true});
 writeFileSync(resolve(work,'source.txt'),'PARITY-PUBLIC-FIXTURE\n');writeFileSync(resolve(outside,'source.txt'),'PARITY-PUBLIC-FIXTURE\n');
 const cases={read_inside:`cat ${q(resolve(work,'source.txt'))}`,read_outside:`cat ${q(resolve(outside,'source.txt'))}`,
 write_inside:`printf parity > ${q(resolve(work,'new.txt'))}`,write_outside:`printf parity > ${q(resolve(outside,'new.txt'))}`,
 organize:`mkdir ${q(resolve(work,'sorted'))} && cp ${q(resolve(work,'source.txt'))} ${q(resolve(work,'copy.txt'))} && mv ${q(resolve(work,'copy.txt'))} ${q(resolve(work,'sorted/renamed.txt'))}`,
 shell:'printf shell-ok'};
 for(const [name,command] of Object.entries(cases)){
  const start=performance.now();const argv=mode==='danger-full-access'?['/bin/bash','-c',command]:['/usr/bin/sandbox-exec',...seatbeltProfileArgs({mode,workspaceRoot:realpathSync(work)}),'--','/bin/bash','-c',command];
  const r=spawnSync(argv[0],argv.slice(1),{encoding:'utf8',timeout:15000});
  rows.push({mode,case:name,exit:r.status,signal:r.signal,stdout:r.stdout,stderr:r.stderr,seconds:(performance.now()-start)/1000,error:r.error?.message,
   evidence_kind:'REAL_OS_PROCESS_PINNED_PROFILE',popups:null,human_interactions:null});
 }
 for(const outcome of ['allowed-once','rejected','cancelled','unavailable']){
  const target=resolve(outside,`escalation-${outcome}.txt`);let prompts=0;
  try{
   const effective=await approveEscalation({requestedMode:'danger-full-access',effectiveMode:mode,justification:'Write only the generated public test file',subject:'operation'},
    {approver:{request:async()=>{prompts++;return outcome;}},agent:{},callId:`test-${mode}-${outcome}`,toolName:'test-file'});
   if(effective==='danger-full-access')writeFileSync(target,'approved fixture');
   rows.push({mode,case:'escalation-'+outcome,completed:existsSync(target),scripted_host_requests:prompts,evidence_kind:'PINNED_APPROVAL_FUNCTION_SCRIPTED_HOST_REAL_FILE'});
  }catch(e){rows.push({mode,case:'escalation-'+outcome,completed:existsSync(target),error:e.message,scripted_host_requests:prompts,evidence_kind:'PINNED_APPROVAL_FUNCTION_SCRIPTED_HOST_REAL_FILE'});}
 }
}
writeFileSync(resolve(out,'dsh-boundary.json'),JSON.stringify({upstream:'22ddee3792402c3e70ec5f86a63c3e3e895a2f60',scope:'Pinned profile/escalation functions; real process/file effects; dependency libraries from reviewed 20261022 checkout; no actual DSH model/UI approval or human timings',rows},null,2)+'\n');
console.log(JSON.stringify(rows.map(({mode,case:c,exit,completed})=>({mode,case:c,exit,completed}))));
