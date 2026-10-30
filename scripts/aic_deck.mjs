import fs from 'node:fs/promises';
import path from 'node:path';
import {fileURLToPath,pathToFileURL} from 'node:url';
const root=fileURLToPath(new URL('../',import.meta.url));
const runtime='/Users/localpilot-user/.cache/codex-runtimes/codex-primary-runtime/dependencies';
process.env.RUNTIME_NODE_MODULES=runtime+'/node/node_modules';
const {Presentation,PresentationFile}=await import(pathToFileURL(runtime+'/node/node_modules/@oai/artifact-tool/dist/artifact_tool.mjs').href);
const skill='/Users/localpilot-user/.codex/plugins/cache/openai-primary-runtime/presentations/26.1026.10807/skills/presentations';
const {finalizePresentation,applyPresentationChartFont}=await import(pathToFileURL(skill+'/container_tools/artifact_tool_utils.mjs').href);
const summary=JSON.parse(await fs.readFile(process.env.AIC_SUMMARY_FILE??root+'output/aic-20261029/summary.json','utf8'));
const final=path.resolve(process.argv[2]??root+'output/aic-20261029/materials/localpilot-答辩-final.pptx');
const qa=path.join(root,'.aic-runtime/qa',path.basename(final,'.pptx'));await fs.mkdir(qa,{recursive:true});
const deck=Presentation.create({slideSize:{width:1280,height:720}});
const font='Arial Unicode MS',navy='#12283d',teal='#007c83',muted='#586a7c',pale='#edf4f5';deck.theme.defaultFont=font;
const fmt=(x,d=2)=>x===null||x===undefined?'UNKNOWN':Number(x).toFixed(d);
const pct=x=>x===null||x===undefined?'NOT_RUN':(x*100).toFixed(1)+'%';
const independentN=summary.protocol?.evaluation_ids?.length??0;
const diagnostic=summary.cohort_role==='pre-fix diagnostic cohort';
const cohortLabel=diagnostic?'修复前诊断队列；修复后独立评估尚未完成':'修复后独立评估队列';
function text(s,v,x,y,w,h,size=29,color=navy,bold=false){const a=s.shapes.add({geometry:'textbox',position:{left:x,top:y,width:w,height:h},fill:'none',line:{fill:'none',width:0}});a.text=String(v);a.text.insets=0;a.text.style={typeface:font,fontSize:size,color,bold};return a;}
function slide(title,sub=''){
 const s=deck.slides.add();s.background.fill='#ffffff';text(s,title,56,52,1168,96,46,navy);
 if(sub)text(s,sub,56,152,1168,56,25,muted);
 text(s,'localpilot · 大肥鱼队 · 独立候选 · 2026-10-29',56,671,1100,25,16,muted);
 text(s,String(deck.slides.items.length),1172,671,52,25,16,muted);
 s.speakerNotes.text='证据来自本轮 summary.json、冻结协议及逐请求轨迹。数值为实际运行或明确 NOT_RUN，不是目标值。\n代码与来源：https://github.com/www080327-glitch/LocalPilot （比赛期间 private，提供受限源码包）\n本材料不构成消费者发行、公证或跨设备资格。';return s;
}
function body(s,values,y=225,gap=116,size=30){values.forEach((v,i)=>text(s,v,56,y+i*gap,1160,gap-20,size));}
function table(s,values,widths,y=230,height=340,size=25){
 const t=s.tables.add({rows:values.length,columns:values[0].length,left:56,top:y,width:1168,height,columnWidths:widths,values});
 t.borders.assign({style:'solid',fill:'#d9e2e6',width:1});
 for(let r=0;r<values.length;r++)for(let c=0;c<values[0].length;c++){const x=t.getCell(r,c);x.fill=r===0?pale:'#ffffff';x.text.style={typeface:font,fontSize:size,color:navy,bold:r===0};}return t;
}
function chart(s,title,series,format='0.0'){
 const data=summary.benchmark.filter(r=>r.n);
 if(!data.length){text(s,'独立评估尚未运行 · NOT_RUN',56,300,1168,100,43,teal);return;}
 const c=s.charts.add('bar',{position:{left:56,top:222,width:1168,height:350},title,titleTextStyle:{fontSize:26,fill:navy},
  categories:data.map(r=>r.arm),series:series.map(q=>({name:q.name,values:data.map(r=>Number(q.value(r).toPrecision(12))),fill:q.fill})),
  hasLegend:series.length>1,legend:{position:'bottom',textStyle:{fontSize:22,fill:muted}},
  dataLabels:{showValue:format!=='0.0000',position:'outEnd',numberFormatCode:format,textStyle:{fontSize:20,fill:muted}},
  xAxis:{textStyle:{fontSize:22,fill:muted}},
  yAxis:{numberFormatCode:format,min:0,...(title.startsWith('Strict success')?{max:100,majorUnit:25}:{}),textStyle:{fontSize:20,fill:muted},majorGridlines:{style:'solid',fill:'#e5edef',width:1}},
  chartFill:'#ffffff',plotAreaFill:'#ffffff'});
 applyPresentationChartFont(c,{fontFamily:font});return c;
}
let s=slide('localpilot');
text(s,'本地与云端协同智能体',56,228,1168,105,62,navy,true);
text(s,'质量、API 费用与真实执行证据',56,356,1168,70,37,teal);
text(s,'大肥鱼队\nMIT · 比赛期间私有，赛后计划公开',56,485,1168,120,28,muted);

s=slide('任务质量与单位成功成本','节费目标需要严格成功率共同约束');
body(s,['让本地模型承担更多工作，同时尽量保持 Agent 任务质量。',
 '失败、重试、切换、复核和重复上下文都要计入费用。',
 '零 API 费用、零成功不能证明经济价值；提升必须来自独立对照。']);

s=slide('推荐器、Router 与执行权限','一套 Core；模型建议不会自动取得工具权限');
const boxes=[{x:56,y:238,w:335,h:100,t:'硬件与本地目录\nMLP 排序 / 规则回退'},
 {x:472,y:238,w:335,h:100,t:'宿主配置与部署\n兼容性 / 来源许可'},
 {x:889,y:238,w:335,h:100,t:'五档 Router\n已部署后端与预算'},
 {x:889,y:455,w:335,h:100,t:'AgentSession\n持久任务与义务'},
 {x:472,y:455,w:335,h:100,t:'Gateway / Tools\n目录、能力与动作边界'},
 {x:56,y:455,w:335,h:100,t:'收据与独立验证\nUNKNOWN 不盲目重放'}];
for(const b of boxes){s.shapes.add({geometry:'rect',position:{left:b.x,top:b.y,width:b.w,height:b.h},fill:pale,line:{fill:teal,width:1.5}});text(s,b.t,b.x+16,b.y+16,b.w-32,b.h-22,26);}
for(const a of [[391,288,472,288],[807,288,889,288],[1057,338,1057,455],[889,505,807,505],[472,505,391,505]]){
 const[x1,y1,x2,y2]=a;s.shapes.add({geometry:'connector',kind:'straight',position:{left:Math.min(x1,x2),top:Math.min(y1,y2),width:Math.abs(x2-x1),height:Math.abs(y2-y1),horizontalFlip:x2<x1,verticalFlip:y2<y1},line:{fill:teal,width:2},tail:{type:'arrow',width:'sm',length:'sm'}});
}

s=slide('MLP 的真实能力与回退边界','当前目标是预测吞吐量；尚不能代表 Agent 任务质量');
const candidateScores=(summary.selector_candidate_metrics??[]).map(x=>`${x.successes}/${x.n}`).join('、');
const oracleStatus=summary.selector_quality?.methods?.mlp?.known_oracle_tasks?'候选观测 oracle 见报告':'成功 oracle 未定义';
const selectorDiagnostic=(summary.selector_quality_execution?.run==='selector-quality2')?`留模型 MARE 46.7%；两候选追加 ${candidateScores}，${oracleStatus}`:'平均相对误差 46.7%；泛化证据不足';
table(s,[['项目','证据'],['数据','历史有效测速 33 条，失败/停止 17 条；单台 M1 Max / 64GB'],['独立诊断',selectorDiagnostic],['产品接入','速度目标尝试 MLP；内存、上下文、allowlist 与异常回退保留'],['质量替换','NO_GO；quality / balanced 等目标缺少任务质量校准']],[250,918],230,285,25);
text(s,'未通过质量证据前，不硬编码评估答案，不宣称已完成全面替换。',56,557,1168,65,27,teal);

s=slide('七组公开基准改编对照',diagnostic?'修复前诊断；DSH 云端上下文目录偏差，详见报告':cohortLabel);
table(s,[['组','配置'],...summary.benchmark.map(r=>[r.arm,r.name])],[95,1073],222,365,25);
text(s,`BFCL V4：开发 2 例，独立评估 ${independentN} 例；每例 32 请求 / 64 工具 / 180 秒。`,56,605,1168,45,24,muted);
s.speakerNotes.text+='\n固定 BFCL 源码：https://github.com/ShishirPatil/gorilla/tree/6ea57973c7a6097fd7c5915698c54c17c5b1b6c8\nAdapted benchmark；非官方榜单总分。Terminal-Bench 2.0 / SWE-bench Verified 缺少容器环境，NOT_RUN。';
if(diagnostic)s.speakerNotes.text+='\n旧队列DSH云端模型目录仍宣告1M上下文，defaultContextWindow未覆盖已知模型；LP64K。新协议显式覆盖64K。旧队列不具备严格固定上下文对照资格，不能代替新候选独立评估。';

s=slide('严格成功率',cohortLabel+'；失败保留在分母中');
chart(s,'Strict success (%)',[{name:'严格成功率',value:r=>100*r.strict_success_rate,fill:teal}],'0.0');
text(s,`Wilson 95% 区间与配对差异见报告。${independentN} 个独立实例不能证明统计非劣效。`,56,592,1168,62,25,muted);

s=slide('API 总费用',cohortLabel+'；共同峰值标准');
chart(s,'USD · common standard',[{name:'已知用量部分',value:r=>r.api_known_usd_peak_standard,fill:teal},
 {name:'含未知用量的保守上界',value:r=>r.api_upper_usd_peak_standard,fill:'#b48a55'}],'0.0000');
text(s,'失败与重试计费；不把谷时折扣、免费额度或未记录费用当作架构节省。',56,592,1168,62,25,muted);
s.speakerNotes.text+='\n官方费率：https://api-docs.deepseek.com/quick_start/pricing/\n实际扣款账单 UNKNOWN。标准峰值单价 USD/1M：未命中输入0.30，命中0.006，输出1.20。';

s=slide('耗时与本地资源',cohortLabel+'；延迟使用同一实例预算');
chart(s,'Wall time (seconds)',[{name:'P50',value:r=>r.p50_seconds,fill:teal},{name:'P95',value:r=>r.p95_seconds,fill:'#8ea2b1'}],'0');
text(s,'本地请求墙钟、进程 CPU 与 RSS 另报；RSS 不等于唯一 GPU / 统一内存峰值。',56,592,1168,62,25,muted);

s=slide('Prompt / KV Cache：命中与提速分开','长期前缀复用由实际 Usage 或 provider 指标证明');
const cloud=summary.cloud_cache.filter(r=>r.run==='cloud-cache-v5');
table(s,[['云端场景','冷 TTFT 秒','热 P50 秒','冷/热比'],...cloud.map(r=>[r.kind,fmt(r.cold_ttft_seconds),fmt(r.warm_p50_ttft_seconds),fmt(r.cold_over_warm_observed_ratio)])],[400,260,260,248],230,230,24);
const localLong=summary.local_cache.filter(r=>r.tag==='long_repeat');
if(summary.local_cache_primary_run==='local-cache2'&&localLong.length===2){
 text(s,`本地长前缀重复 TTFT：oMLX ${fmt(localLong[0].observed_ttft_speedup)} 倍，vLLM ${fmt(localLong[1].observed_ttft_speedup)} 倍（各2次）。`,56,486,1168,62,25);
 text(s,'命中：8192/8341 与 7392/8341 Token；48次输出检查通过。',56,553,1168,52,25);
 text(s,'固定 OFF→ON，波动大；短提示/重启有退步。云端未文档化 OFF，不主张永久缓存。',56,615,1168,42,20,muted);
}else{
 text(s,'DeepSeek 没有文档化 Cache OFF 开关；冷/热请求不是严格 OFF/ON 消融。',56,492,1168,66,27);
 text(s,'本地 oMLX / vLLM 的 OFF/ON、重启与正确性另见报告；不主张永久缓存。',56,578,1168,62,25,muted);
}
s.speakerNotes.text+='\n缓存规则：https://api-docs.deepseek.com/guides/kv_cache/\n冷/热比小于1表示这组热请求更慢。小样本不构成稳定加速资格。';

s=slide('真实 Core SDK 演示','合成文件、真实模型、真实工具收据与宿主检查');
const demo=summary.demo??{};
body(s,[`真实云端读取、文件哈希与最终标记检查：${demo.pass===true?'PASS':'NOT_RUN / 待重建摘要'}`,
 '相同幂等键返回原 Task；Core 重启后查询原状态；授权目录之外路径直接拒绝。',
 '录像展示实时 SDK 事件视图；不是原生桌面 UI 验收，也不是公开基准分数。'],225,118,29);
s.speakerNotes.text+='\n演示任务：'+(demo.task_id??'NOT_RUN')+'\n所有文件均为本轮公开合成夹具；旁白由macOS语音合成。前期失败与所有API费用保留。';

s=slide('原创性、许可证与开放计划','自有代码 MIT；比赛期间保持私有');
body(s,['自研：持久任务、所有者与幂等、权限修订、意图/收据、UNKNOWN 和独立验证的工程整合。',
 '复用：基础模型、DSH 协议适配、公开基准与基础框架。保留原有 LICENSE、NOTICE 和贡献者归属。',
 '源码包含自训 MLP JSON 参数，排除大模型权重、密钥及日常配置；赛后计划公开。'],225,118,28);

s=slide('完整材料与未证明事项','提交截止：2026-10-30 20:00，北京时间');
body(s,['提交材料：15 页报告、约4分钟真实演示、可编辑 PPT、受限源码、费用账本和原始轨迹。',
 '未证明：显著节费、统计非劣效、MLP 全面质量替换、永久 KV Cache、消费者发行资格。',
 '所有 FAIL / UNKNOWN / NOT_RUN 均保留；报名、签字和平台提交由队伍核对执行。'],225,118,28);
s.speakerNotes.text+='\n官方赛程：https://www.aicomp.cn/notice/notice-3/5435.html\n官方赛道：https://www.aicomp.cn/tracks/tracks-5/4924.html';

for(const[i,sl]of deck.slides.items.entries()){
 const blob=await deck.export({slide:sl,format:'png',scale:1});await fs.writeFile(path.join(qa,'slide-'+String(i+1).padStart(2,'0')+'.png'),new Uint8Array(await blob.arrayBuffer()));
}
await fs.writeFile(path.join(qa,'source-data.json'),JSON.stringify(summary));
const draft=path.join(qa,'draft.pptx');await(await PresentationFile.exportPptx(deck)).save(draft);
const result=await finalizePresentation({workspaceDir:root,candidatePath:draft,finalPath:final,
 pythonExecutable:runtime+'/python/bin/python3',integrityValidatorPath:skill+'/container_tools/inspect_presentation_package_integrity.py',
 layoutValidatorPath:skill+'/container_tools/inspect_presentation_layout_geometry.py',
 layoutArgs:['--expected-slide-size-emu','12192000,6858000','--validate-bullet-geometry','--validate-heading-fit','--require-native-table-slide','4','--require-native-table-slide','5','--require-native-table-slide','9'],
 explicitTotalSlideCount:12,requiredNativeTableOwnerSlides:[4,5,9],fontPolicy:{basis:'design',families:[font]},
 materializeLiteralChartWorkbooks:true,verifyArtifactToolImport:true,receiptPath:path.join(qa,'validation.json')});
console.log(JSON.stringify({slides:12,qa,final,result}));
