"""Fifteen-page evidence-bound AIC report. Rebuild after the frozen study."""
import argparse
from datetime import datetime
import html
import hashlib
import json
from pathlib import Path
import re
from statistics import median
import subprocess

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib.font_manager import FontProperties
from reportlab.pdfgen import canvas
from reportlab.lib import colors
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import Paragraph,Table,TableStyle
from reportlab.lib.styles import ParagraphStyle

ROOT=Path(__file__).resolve().parents[1];E=ROOT/'docs/evidence/aic-final-20261029'
FONT_PATH='/Library/Fonts/Arial Unicode.ttf';FONT='AICUnicode'
pdfmetrics.registerFont(TTFont(FONT,FONT_PATH));FP=FontProperties(fname=FONT_PATH)
NAVY=colors.HexColor('#12283d');TEAL=colors.HexColor('#007c83');GRAY=colors.HexColor('#586a7c')
W,H=595.276,841.89;LEFT=53;WIDTH=W-2*LEFT


def fmt(value,d=3):return 'UNKNOWN' if value is None else f'{value:.{d}f}'
def pct(value):return 'NOT_RUN' if value is None else f'{value*100:.1f}%'
def test_result(name):
    path=E/name
    if not path.exists():return 'NOT_RUN'
    text=path.read_text();n=re.search(r'Ran (\d+) tests',text);end='PASS' if re.search(r'^OK',text,re.M) else 'FAIL_OR_RUNNING'
    skip=re.search(r'skipped=(\d+)',text)
    return (n[1]+' 项 / '+end+(' / '+skip[1]+' skipped' if skip else '')) if n else end


class Report:
    def __init__(self,path):self.c=canvas.Canvas(str(path),pagesize=(W,H));self.page=0;self.y=0
    def begin(self,title):
        if self.page:self.c.showPage()
        self.page+=1;self.y=747
        self.c.setFillColor(GRAY);self.c.setFont(FONT,8.5);self.c.drawString(LEFT,804,'localpilot  /  大肥鱼队  /  AIC 2026 · AI+开源')
        self.c.setStrokeColor(colors.HexColor('#d5e1e5'));self.c.line(LEFT,790,W-LEFT,790)
        self.c.setFont(FONT,21);self.c.setFillColor(NAVY);self.c.drawString(LEFT,762,title)
        self.c.setFont(FONT,8);self.c.setFillColor(GRAY);self.c.drawString(LEFT,29,'独立候选 · 证据不足不作提升结论 · 2026-10-29')
        self.c.drawRightString(W-LEFT,29,f'{self.page} / 15')
    def p(self,text,size=10.7,leading=17,color=NAVY,space=11):
        style=ParagraphStyle('p',fontName=FONT,fontSize=size,leading=leading,textColor=color,wordWrap='CJK')
        p=Paragraph(html.escape(text).replace('\n','<br/>'),style);_,height=p.wrap(WIDTH,1000)
        if self.y-height<58:raise ValueError(f'Page {self.page} overflow: {text[:30]}')
        p.drawOn(self.c,LEFT,self.y-height);self.y-=height+space
    def h(self,text):self.p(text,13,20,TEAL,8)
    def table(self,values,widths=None,size=8.5):
        style=ParagraphStyle('cell',fontName=FONT,fontSize=size,leading=size+4,wordWrap='CJK',textColor=NAVY)
        data=[[Paragraph(html.escape(str(x)),style) for x in row] for row in values]
        t=Table(data,colWidths=widths or [WIDTH/len(values[0])]*len(values[0]),hAlign='LEFT')
        t.setStyle(TableStyle([('BACKGROUND',(0,0),(-1,0),colors.HexColor('#edf4f5')),('VALIGN',(0,0),(-1,-1),'TOP'),
            ('FONTNAME',(0,0),(-1,-1),FONT),('LINEBELOW',(0,0),(-1,0),.6,TEAL),('LINEBELOW',(0,1),(-1,-1),.3,colors.HexColor('#d9e2e6')),
            ('LEFTPADDING',(0,0),(-1,-1),6),('RIGHTPADDING',(0,0),(-1,-1),6),('TOPPADDING',(0,0),(-1,-1),7),('BOTTOMPADDING',(0,0),(-1,-1),7)]))
        _,height=t.wrap(WIDTH,1000)
        if self.y-height<58:raise ValueError(f'Page {self.page} table overflow')
        t.drawOn(self.c,LEFT,self.y-height);self.y-=height+14
    def image(self,path,height):
        if self.y-height<58:raise ValueError('image overflow')
        self.c.drawImage(str(path),LEFT,self.y-height,width=WIDTH,height=height,preserveAspectRatio=True,anchor='c',mask='auto');self.y-=height+12
    def flow(self,labels,height=160):
        if self.y-height<58:raise ValueError('diagram overflow')
        top=self.y;boxw=140;boxh=46;xs=[LEFT,LEFT+(WIDTH-boxw)/2,LEFT+WIDTH-boxw]
        points=[(xs[0],top-boxh),(xs[1],top-boxh),(xs[2],top-boxh),
                (xs[2],top-height+15),(xs[1],top-height+15),(xs[0],top-height+15)]
        self.c.setLineWidth(.8)
        for (x,y),label in zip(points,labels):
            self.c.setFillColor(colors.HexColor('#edf4f5'));self.c.setStrokeColor(TEAL);self.c.rect(x,y,boxw,boxh,stroke=1,fill=1)
            self.c.setFillColor(NAVY);self.c.setFont(FONT,10)
            for j,line in enumerate(label.split('\n')):self.c.drawCentredString(x+boxw/2,y+boxh-17-j*15,line)
        for i in range(5):
            x1,y1=points[i];x2,y2=points[i+1]
            if y1==y2:
                a=x1+boxw if x2>x1 else x1;b=x2 if x2>x1 else x2+boxw;yy=y1+boxh/2
                self.c.line(a,yy,b,yy);direction=1 if b>a else -1;self.c.line(b,yy,b-4*direction,yy+3);self.c.line(b,yy,b-4*direction,yy-3)
            else:
                xx=x1+boxw/2;self.c.line(xx,y1,xx,y2+boxh);self.c.line(xx,y2+boxh,xx-3,y2+boxh+4);self.c.line(xx,y2+boxh,xx+3,y2+boxh+4)
        self.y-=height+13
    def finish(self):
        if self.page!=15:raise ValueError('Expected fifteen report pages')
        self.c.setTitle('localpilot 技术报告');self.c.setAuthor('大肥鱼队');self.c.save()


def plots(s,out):
    out.mkdir(parents=True,exist_ok=True)
    plt.rcParams.update({'axes.spines.top':False,'axes.spines.right':False,'font.size':10,'axes.unicode_minus':False})
    data=s['benchmark'];labels=[r['arm'] for r in data]
    for kind in ['quality','cost','latency']:
        fig,ax=plt.subplots(figsize=(8.1,3.4),dpi=180)
        if not any(r['n'] for r in data):
            ax.axis('off');ax.text(.5,.58,'七组独立评估尚未运行',ha='center',fontproperties=FP,fontsize=17)
            ax.text(.5,.35,'NOT_RUN · 不以开发集或历史样本代替独立评估',ha='center',fontproperties=FP,fontsize=10)
        else:
            for i,r in enumerate(data):
                if not r['n']:ax.text(i,.03,'NOT_RUN',ha='center',rotation=90,fontsize=8,transform=ax.get_xaxis_transform());continue
                if kind=='cost':
                    ax.bar(i-.18,r['api_known_usd_peak_standard'],color='#007c83',width=.34,label='Known usage portion (lower)' if i==0 else None)
                    ax.bar(i+.18,r['api_upper_usd_peak_standard'],color='#b48a55',width=.34,label='Conservative upper' if i==0 else None)
                    continue
                value=r['strict_success_rate']*100 if kind=='quality' else r['api_upper_usd_peak_standard'] if kind=='cost' else r['p50_seconds']
                ax.bar(i,value,color='#007c83' if i else '#596c7d',width=.62)
                if kind=='quality':
                    lo,hi=r['wilson_95'];ax.errorbar(i,value,yerr=[[value-lo*100],[hi*100-value]],fmt='none',color='#263b50',capsize=4)
                    ax.text(i,hi*100+3,f"{r['successes']}/{r['n']}",ha='center',fontsize=9)
                else:ax.text(i,value,f'{value:.4f}' if kind=='cost' else f'{value:.1f}',ha='center',va='bottom',fontsize=8)
            ax.set_xticks(range(7),labels);ax.grid(axis='y',alpha=.16);ax.set_axisbelow(True)
            if kind=='quality':ax.set_ylim(0,115);ax.set_ylabel('Strict success (%) · Wilson 95% CI')
            elif kind=='cost':ax.set_ylabel('USD · common peak standard bounds');ax.legend(frameon=False,fontsize=8)
            else:ax.set_ylabel('P50 wall time (seconds)')
        fig.tight_layout();fig.savefig(out/(kind+'.png'),bbox_inches='tight');fig.savefig(out/(kind+'.svg'),bbox_inches='tight');plt.close(fig)
    cv=(s.get('selector') or {}).get('historical_cross_validation',[])
    if cv:
        data=cv[-1]['predictions'];actual=[r['actual_tps'] for r in data];predicted=[r['predicted_tps'] for r in data]
        fig,ax=plt.subplots(figsize=(8.1,3.2),dpi=180);ax.scatter(actual,predicted,s=22,color='#007c83',alpha=.75)
        limit=max(actual+predicted)*1.05;ax.plot([0,limit],[0,limit],color='#93a5b1',linestyle='--')
        ax.set(xlim=(0,limit),ylim=(0,limit),xlabel='Observed decode TPS',ylabel='Held-out-model predicted TPS')
        ax.set_title('Historical leave-model-out diagnostic · n=33 · MARE=46.7%');ax.grid(alpha=.15)
        fig.tight_layout();fig.savefig(out/'selector-diagnostic.png',bbox_inches='tight');fig.savefig(out/'selector-diagnostic.svg',bbox_inches='tight');plt.close(fig)
    data=[r for r in s['cloud_cache'] if r['run']=='cloud-cache-v5' and r['cold_ttft_seconds'] and r['warm_p50_ttft_seconds']]
    if data:
        fig,ax=plt.subplots(figsize=(8.1,3.1),dpi=180);x=list(range(len(data)))
        ax.bar([v-.18 for v in x],[r['cold_ttft_seconds'] for r in data],width=.36,label='Cold new prefix',color='#8da1af')
        ax.bar([v+.18 for v in x],[r['warm_p50_ttft_seconds'] for r in data],width=.36,label='Warm median',color='#007c83')
        ax.set_xticks(x,[r['kind'] for r in data]);ax.set_ylabel('Client TTFT (s)')
        ax.set_ylim(0,max(max(r['cold_ttft_seconds'],r['warm_p50_ttft_seconds']) for r in data)*1.3)
        ax.legend(frameon=False,ncol=2,loc='upper center');ax.grid(axis='y',alpha=.15)
        fig.tight_layout();fig.savefig(out/'cloud-cache.png',bbox_inches='tight');fig.savefig(out/'cloud-cache.svg',bbox_inches='tight');plt.close(fig)


def main():
    p=argparse.ArgumentParser();p.add_argument('--summary',type=Path,required=True);p.add_argument('--output',type=Path,required=True);a=p.parse_args()
    s=json.loads(a.summary.read_text());a.output.mkdir(parents=True,exist_ok=True);charts=a.output.parent/'charts';plots(s,charts)
    r=Report(a.output/'localpilot-技术报告.pdf');bench=s['benchmark'];measured=sum(x['n'] for x in bench)
    selector=s.get('selector') or {};demo=s.get('demo') or {};cost=s['campaign_cost'];protocol=s.get('protocol') or {}
    independent_n=len(protocol.get('evaluation_ids',[]))
    r.begin('localpilot：本地与云端协同智能体')
    r.p('技术报告 · 大肥鱼队',15,23,TEAL)
    r.h('摘要')
    r.p('localpilot 面向个人开发与资料处理，把模型提案、宿主权限、持久任务、工具执行和独立验证组织在同一运行时中。项目提供桌面、CLI、Companion 与外部 Agent 接口，探索让本地模型承担更多工作，在尽量保持任务质量的前提下降低云端 API 成本。')
    r.p('本轮在独立工作树集成 PR #4 的轻量 MLP 推荐器与 PR #5 RC.6。MLP 排序前保留内存、模型与上下文准入，输出再次匹配已准入候选；异常、越域和缺少目标校准时回退旧规则。模型目录推荐器与五档运行时 Router 独立。')
    r.h('证据结论')
    if s.get('cohort_role')=='pre-fix diagnostic cohort':
        r.p('本文主表目前保留工具契约修复前的四例诊断。修复后候选已通过完整控制回归，但新的三例未见评估若因接电条件尚未完成，不能借用旧分数宣称新候选性能通过。',10.2,16,TEAL)
    r.p(f'七组 BFCL V4 adapted 独立评估记录：{measured} 个 trial。每组的独立实例数、失败与置信区间见正文；它们不是官方榜单成绩。Terminal-Bench 2.0 与 SWE-bench Verified 因缺少容器运行环境未运行。小样本不能证明统计非劣效。')
    if s.get('cohort_role')!='pre-fix diagnostic cohort':
        r.p('本轮严格成功：'+ '，'.join(x['arm']+f" {x['successes']}/{x['n']}" for x in bench)+'。这是指定小队列的观察，不能外推质量等效或总体提升；费用存在未知用量，正文同时报告下界与上界。',10,16,TEAL)
    r.p('MLP 目前学习历史吞吐量，缺少可靠任务质量标签；本轮留模型诊断平均相对误差为 46.7%。因此只接入已声明的速度目标，任务质量层面的全面替换仍为 NO_GO。缓存命中与延迟分别报告，既保留加速，也保留退步与无法测量的字段。')
    r.p('自有代码采用 MIT。比赛期间仓库保持私有，准备受限源码供评审；赛后计划公开。本文不宣称已完成消费者发行、公证或跨设备部署资格。')
    r.begin('1  问题、目标与验证范围')
    r.h('具体问题')
    r.p('个人 Agent 的成本不仅来自模型单价，还来自重复上下文、无效工具提案、失败重试、切换和复核。单纯统计 API 调用次数容易忽略失败任务：零费用、零成功不能证明经济价值。项目用“严格成功率”和“每个验证成功任务成本”共同约束优化。')
    r.p('执行可靠性是另一条独立维度。模型文字不能证明文件已正确修改，进程退出码不能证明任务成功，断连后再次提交可能重放副作用。localpilot 用持久任务编号、幂等请求、动作意图、执行收据、UNKNOWN 隔离及宿主检查处理这些边界。')
    r.h('本轮目标与判定')
    r.table([['问题','本轮判据'],['MLP 是否可正式替代人工排序','真实硬件准入、异常回退、独立质量与选择准确率；吞吐预测不能代替质量'],['混合是否节省 API 费用','固定模型、任务、预算与评分器；失败和重试计费；共同标准费率比较'],['缓存是否有实际收益','实测 TTFT、端到端时间、实际命中 Token、资源及输出正确性'],['是否满足材料交付','报告、真实演示、受限源码、原始证据及失败清单']],[120,WIDTH-120])
    r.p('性能目标不是预定结论。完全云端、云端优先、平衡、本地优先和完全本地分别评价；没有显著差异不能解释为已证明等效。测试环境只授权公开合成文件或审查过的基准模拟器，不读取私人资料或日常账号。')
    r.begin('2  架构与权限责任')
    r.h('控制路径')
    r.table([['层','职责与边界'],['入口','Desktop / CLI / Companion / 外部 DSH 使用同一 Core API；凭据与请求所有者在宿主核验'],['模型推荐','读取硬件、候选目录与特征；输出部署建议；不授予目录、网络或云端披露权限'],['五档 Router','对已经部署且获准的后端作来源选择、失败升级与预算控制；不是 MLP 模型目录排序'],['AgentSession','组织消息、调用与证据；工具结果作为数据；保留任务义务与当前控制快照'],['Gateway / Registry','核验能力、授权目录、动作与系统限制；模型不能自行扩大权限'],['持久与验证','SQLite 保存任务、意图和收据；UNKNOWN 不盲目重放；独立检查当前资源版本与交付']],[103,WIDTH-103])
    r.p('模型只提出动作。即使选择“完全权限”，独立测试环境的目录和网络边界仍然有效；越权请求直接失败，不通过自动点击确认窗口绕过。BFCL 仅暴露内存模拟器，没有宿主 Shell 或真实文件 API；原生 DSH 子进程受 deny-default Seatbelt 约束，只能联系本轮 loopback broker。')
    r.p('本轮的 MLP 接入不改写五档来源语义，不自动下载、加载或执行模型。日常 APP、既有模型服务及备份保持原有归属；新的服务进程、端口和状态目录均由本轮创建并单独停止。')
    r.flow(['硬件与本地模型目录','MLP 推荐 / 规则回退','宿主接受并配置后端','五档来源 Router','AgentSession 持久执行','Gateway / 工具 / 验证'])
    r.begin('3  MLP 集成与回退策略')
    r.p('PR #4 的标准库网络为五维输入、八个 tanh 隐单元、单输出；目标为 log(decode TPS)。输入为物理内存预算、模型目录大小、总参数、活跃参数及上下文长度。权重为 JSON，不引入 PyTorch 推理依赖。')
    r.table([['阶段','实现'],['硬准入','Apple Silicon / MLX 兼容性、上下文与输出预留、保守内存包络、禁用模型类别和显式模型 allowlist'],['动态资源','物理内存用于硬件身份和特征；实时可用内存另作准入上限，避免把可用内存误当新设备'],['预测与复核','只向预测器传递候选副本；返回值必须匹配原始已准入候选，吞吐必须有限且大于零'],['异常回退','缺文件、损坏网络、未知硬件、越域模型、异常返回和目标不支持时使用旧规则并记录原因'],['产品接入','main 与 Suite 调用 recommend_primary；打包包含 selector_mlp 模块和 JSON 权重'],['质量边界','速度目标且上下文取舍为 balanced 时尝试 MLP；quality / efficiency / balanced 等未校准目标明确回退']],[106,WIDTH-106])
    r.p('用户本地/云端偏好和执行权限仍由来源 Router、宿主授权与 Gateway 强制控制。推荐函数可以在 local_allowed=False 时直接返回空建议；推荐结果不会直接触发加载。未知输出无法注入新模型、上下文或权限。')
    r.p('该集成是可审查的工程接入；由于没有足够质量标签，不把“默认尝试一个吞吐预测器”包装成“所有偏好的质量推荐已完成替换”。')
    r.p('安全次序：硬准入 → 候选副本 → MLP 预测 → 原始候选复核 → 部署建议。任一步失败都返回旧规则候选；模型文件不控制执行权限。',11.5,19,TEAL)
    r.begin('4  MLP 数据、泛化与实机开销')
    r.p('历史摘要共 33 条有效测速，另保留 17 条失败或停止记录，来自单台 M1 Max / 64GB。原训练为 25 条、同设备上下文留出 8 条。提示协议、缓存与输出条件有缺失，成功记录还存在幸存者偏差。它们不足以证明跨设备泛化或 Agent 任务质量。')
    quality=s.get('selector_quality') or {};methods=quality.get('methods',{})
    task_text='UNKNOWN：历史数据没有独立任务质量或最优选择标签'
    if methods:
        old=methods['rules'];mlp=methods['mlp']
        if (s.get('selector_quality_execution') or {}).get('run')=='selector-quality2':
            accuracy=(str(mlp['correct_selections'])+'/'+str(mlp['known_oracle_tasks'])) if mlp['known_oracle_tasks'] else 'UNKNOWN（无已定义oracle）'
            candidate_scores='、'.join(str(x['successes'])+'/'+str(x['n']) for x in s.get('selector_candidate_metrics',[]))
            task_text=f"新提示词/oMLX同三例：规则{old['successes']}/{old['tasks']}、MLP {mlp['successes']}/{mlp['tasks']}，同选35B、共享实测。两候选评估{candidate_scores}；成功优先oracle选对{accuracy}。不增加独立样本数。"
        else:
            task_text=f"补充旧提示词/oMLX 对照：规则 {old['successes']}/{old['tasks']}，MLP {mlp['successes']}/{mlp['tasks']}，两者同选35B并共享同一实测；另一候选评估未完成，选择准确率 UNKNOWN。这不是改进后提示词的成绩。"
    r.table([['诊断','实测或状态'],['留上下文验证 MARE','12.53%（按整组上下文留出）'],['留模型验证 MARE','46.68%（按整个模型留出；超出部署推断范围的诊断）'],['任务成功率 / 选择准确率',task_text],['新增对抗控制','外部模型注入、非有限预测、运行时异常、allowlist、内存预算、来源禁止、最小上下文'],['正式质量替换','NO_GO：需补真实任务标签、失败标签及校准，不能硬编码测试答案']],[170,WIDTH-170])
    timings=selector.get('decision_latency',[])
    r.table([['选择器','P50 ms','P95 ms','进程峰 RSS MiB']]+[[x['selector'],fmt(x['p50_ms']),fmt(x['p95_ms']),fmt(x['process_peak_rss_bytes']/1024**2,2)] for x in timings],[110,90,90,WIDTH-290])
    r.p('计时在真实 M1 Max / 64GB 上执行，每种方法独立进程、预热 10 次、记录 100 次；没有启动语言模型。该限定场景两者都选择 35B-A3B，因此只能说明推荐器的计算开销，不能推出模型推理加速或任务成功率提升。后续应优先扩充独立开发数据，按设备、模型与任务组划分训练和评估，选择模型后仍需报告置信区间。')
    if (s.get('selector_quality_execution') or {}).get('run')=='selector-quality2':
        execution=s['selector_quality_execution'];r.p(f"追加模型任务完成{execution['observed_model_trials']}/{execution['expected_model_trials']}，云端调用{execution['api_attempts']}。只在声明的oMLX/Cache OFF/预算下解释；主表使用vLLM，不能混合两后端的数据。新标签未回灌权重，选择准确率和任务成功率区间、任务墙钟与资源另附JSON。",9,14,GRAY)
    r.p('补充训练在原训练 25 行内比较 4/8 隐单元和四档 L2，再按训练侧整组上下文验证选择。当前仍选原 8 单元、L2=0，原历史 8 行留出 MARE 同为14.74%，未见收益。没有将旧留出集冒充新独立测试，也没有晋升新权重。',9.5,15,GRAY)
    if not quality and (charts/'selector-diagnostic.png').exists():r.image(charts/'selector-diagnostic.png',170)
    r.begin('5  七组公平对照协议')
    r.table([['组别','配置'],['A','原生 DSH + DeepSeek-V4.1-Flash-1017（wire alias deepseek-flash）'],['B','LocalPilot 完全云端，同一 DeepSeek'],['C','LocalPilot 云端优先'],['D','LocalPilot 平衡'],['E','LocalPilot 本地优先'],['F','LocalPilot 完全本地'],['G','原生 DSH + 与 LocalPilot 相同的 Qwen3.6-35B-A3B-4bit']],[48,WIDTH-48])
    r.p(f'BFCL V4 multi_turn_base 固定源码 6ea57973c7a6097fd7c5915698c54c17c5b1b6c8。只使用已审查的 GorillaFileSystem 内存模拟器；按预定哈希顺序选择，排除先前见过的实例，开发集 2 个、当前预定独立评估集 {independent_n} 个。首轮旧提示词诊断为4例；工具契约修复后只剩3例未见样本，分别报告、不合并样本量。答案仅在生成后由原 checker 读取，不进入模型可读路径。')
    r.p('每实例总体上限：32 次 provider 请求、64 次工作工具调用、每次 1024 输出 Token、180 秒墙钟；瞬时请求错误最多重试一次，仍占总预算并计费。云端思考关闭；本地 enable_thinking=False、temperature=0、seed=25。所有组保留各自原生系统指令，因此比较的是 Agent 系统整体。')
    r.p('DSH固定安装版0.2.1-rc.2，记录app.asar与二进制哈希；同名源码标签687f282e，不声称已重建相同二进制。Qwen固定revision 38740b84…。云端版本依官方映射，响应仅回传alias，不暴露不可变服务端构建号。运行时、缓存和电源另留记录。Terminal-Bench 2.0 / SWE-bench Verified缺少容器环境，标为BLOCKED / NOT_RUN。',10,16)
    r.p('本地基准统一关闭Prefix Cache，专项缓存另测；云端默认缓存无法文档化关闭。组别顺序转动并交替反转，但小队列不是完整交叉平衡，缓存费用与延迟仍含顺序及服务波动，只作本队列观察。',9.2,14,GRAY)
    if s.get('cohort_role')=='pre-fix diagnostic cohort':
        r.p('旧队列还有上下文配置偏差：DSH 云端已知模型目录仍宣告 1M，defaultContextWindow 未覆盖该条目，LP 为64K。修复后协议显式覆盖为64K。旧结果仅作诊断，不能宣称已完成严格固定上下文的公平对照。',9.2,14,TEAL)
    r.begin('6  严格成功率与不确定性')
    r.image(charts/'quality.png',220)
    r.table([['组','严格成功','95% Wilson 区间','状态']]+[[x['arm'],f"{x['successes']}/{x['n']}" if x['n'] else 'NOT_RUN',('['+pct(x['wilson_95'][0])+', '+pct(x['wilson_95'][1])+']') if x['wilson_95'] else 'NOT_RUN',x['status']] for x in bench],[45,100,188,WIDTH-333])
    r.p('评估以完整多轮实例为统计单位。同一实例运行七种配置不会增加独立样本量。图中的区间描述单组比例；配对差异另给保守 Hoeffding 区间。所有非劣效结论均为 NOT_ESTABLISHED，不能用“差异不显著”替代“质量等效”。')
    r.p('严格成功要求所有 Agent 轮次完成且 upstream checker 通过。审计发现旧驱动的 generated 标志会覆盖末轮 error，汇总统一按原始轮次记录重核，原始结果和状态分另存；未修改评分器或执行轨迹。权限、基础设施、超时和模型失败均留在分母。adapted 只覆盖此工具子集，不是 BFCL 官方总分。')
    r.begin('7  API 费用与成功任务成本')
    r.image(charts/'cost.png',220)
    r.table([['组','已知 / 上界 USD','每成功任务 USD','节省范围']]+[[x['arm'],(fmt(x['api_known_usd_peak_standard'],5)+' / '+fmt(x['api_upper_usd_peak_standard'],5)) if x['n'] else 'NOT_RUN',fmt(x.get('api_cost_per_verified_success_lower_usd'),5)+' / '+fmt(x['api_cost_per_verified_success_upper_usd'],5) if x['successes'] else '未定义 / 未测',pct(x['api_saving_fraction']) if x['api_saving_fraction'] is not None else (pct(x['api_saving_bounds'][0])+' 至 '+pct(x['api_saving_bounds'][1]) if x.get('api_saving_bounds') else 'UNKNOWN')] for x in bench],[30,155,155,WIDTH-340])
    r.p('共同峰值标准：每百万缓存命中输入 0.006 美元、未命中输入 0.30 美元、输出 1.20 美元。官方谷时价格为一半。统一费率剥离时段折扣；按请求时间的标准估算另附账本。免费额度、优惠、赠金和未核对的扣款不记作架构节省。')
    unknown_arms='/'.join(x['arm'] for x in bench if x.get('usage_unknown_calls'))
    r.p(('费用范围来自缺失用量的保守预留，不是统计置信区间。'+unknown_arms+' 有未知用量，不能以已知部分充当实际总额，也不能把其费用差异宣称为已经确认的架构节省。') if unknown_arms else '本评估队列记录到的用量完整，统一峰值标准估算可直接比较；它仍不是扣款发票，也不能由小样本外推稳定的架构节费。其他开发、探针与失败调用的未知用量继续保留在整轮账本中。',9.5,15,GRAY)
    r.p(f"整轮账本含开发、探针、录像调试及评估共 {cost['requests']} 次云端请求尝试/预留。已知用量折合共同峰值标准 {cost['known_usd_peak_standard']:.6f} 美元；含未知用量的保守上界 {cost['upper_usd_peak_standard']:.6f} 美元。实际账单 UNKNOWN。未完成的预留不冒充已扣款，未知用量不按零费用处理。")
    r.begin('8  耗时、本地资源与运行错误')
    r.image(charts/'latency.png',205)
    r.table([['组','P50 / P95 秒','本地请求墙钟秒','错误完成']]+[[x['arm'],fmt(x['p50_seconds'],1)+' / '+fmt(x['p95_seconds'],1),fmt(x['local_compute_wall_seconds'],1),str(x['false_completed']) if x['n'] else 'NOT_RUN'] for x in bench],[35,167,169,WIDTH-371])
    r.p('本地时间为本地请求墙钟之和，包含排队、Prefill、Decode与传输；不冒充设备纯计算时间。任务总时长不含共享本地服务启动/卸载，批次墙钟及启动计时另附JSON。实验共用预载本地服务；A/B无本地推理，但未采样本地RSS不代表零驻留内存。进程树CPU/RSS另留；RSS可能重复共享页，不是唯一统一内存/GPU峰值；电费未测。',9.5,15)
    r.p('“错误完成”在本表定义为 Agent 已结束所有轮次而独立严格评分失败，不等同于证明宿主可信验证器失效。副作用重放未做逐项独立归因时保留 UNKNOWN。缓存命中比例、本地→云端主路由升级次数、失败类别和原始事件见 JSON/逐请求轨迹，不能用未观测到替代实测零。')
    r.begin('9  路由与成本优化的实现边界')
    r.h('已落实的控制')
    r.p('本轮在禁用通用协调器的任务中收窄工具描述：只有一个合规后端时，不再提供不可能完成的 request_model_switch；至少两个获准候选时保留切换能力。启用完整协调器的既有历史协议保持兼容。该变化减少无用上下文和无效提案；宿主切换、来源及云端披露检查仍然独立执行。')
    r.p('既有 CooperativePolicy 使用有界本地尝试、工具/验证失败升级、上下文预算与单向迟滞，避免在同一任务内反复切回本地。云端优先和平衡的本地质量分流需要绑定准确后端身份的开发集校准；没有足够证据时保持质量优先，而不是虚构置信度以制造节费。')
    if all(x.get('local_provider_attempts')==0 for x in bench if x['arm'] in {'C','D'}):
        r.p('本队列云端优先和平衡均未实际调用本地模型，保守回退为云端执行。因此，即使这两组出现费用差异，也不能作为“本地承担更多工作”已经达成的证据。',9.5,15,TEAL)
    r.table([['检查项','处理及证据边界'],['不必要云端调用','逐请求记录 provider、原因、思考、用量；预算在发送前持久预留'],['反复本地失败','有界尝试与升级；实际次数由事件计算，是否经济仍看独立成绩'],['重复上下文 / 复核','保留关键义务、权限、资源版本及工具配对；不以删减关键上下文制造速度'],['重复执行','幂等返回原 Task；UNKNOWN 隔离；不可把不确定副作用当作安全重试'],['缓存和思考','思考档固定；缓存以服务端计数衡量，不把预热或折扣当作持久架构收益']],[120,WIDTH-120])
    r.p('这些机制说明实现了哪些约束，不自动证明它们提高总体成功率或单位成功成本。性能结论只引用本轮实际数据；目标未达到时保留 FAIL / UNKNOWN，不调整评估答案、评分器或挑选成功例。')
    r.begin('10  DeepSeek 长期前缀缓存')
    cloud=[x for x in s['cloud_cache'] if x['run']=='cloud-cache-v5']
    r.table([['场景','冷 TTFT s','热 P50 s','冷/热比','命中比例']]+[[x['kind'],fmt(x['cold_ttft_seconds']),fmt(x['warm_p50_ttft_seconds']),fmt(x['cold_over_warm_observed_ratio']),pct(x['known_token_hit_ratio'])] for x in cloud],[139,77,87,82,WIDTH-385],8)
    r.p('本表来自完整标准 V5 系统提示词探针：标准基础提示加 V5 权限/证据指令，覆盖长前缀、真实工具提案与结果、多轮和新 HTTP 客户端。命中 Token 来自 DeepSeek Usage；TTFT 包含第一个有效工具生成事件。早期两轮仅使用标准基础提示词，单独保留；它们不能证明完整 V5 的收益，录像中的早期示例也属这个范围。')
    r.p('DeepSeek 的缓存默认开启，没有已文档化的请求级 OFF 开关。因此云端比较标为新前缀冷请求与实际命中的重复请求，不冒充严格 Cache OFF/ON 消融。长前缀可命中大量 Token，但延迟仍受网络与服务调度影响；本轮出现热请求更慢的记录，不能据此宣称稳定加速。')
    r.p('服务端缓存为 best-effort，长期不用会在数小时至数日内清理。新客户端命中只能说明 provider 保留了前缀，不能证明永久缓存；无法控制 DeepSeek 服务端重启，相关项为 NOT_RUN。云端 device Prefill 与服务端内存未暴露，均 UNKNOWN。')
    delayed=s.get('cloud_cache_delayed') or {}
    if delayed.get('usage'):
        u=delayed['usage'];r.p(f"最新延迟复用：距本客户端最后已知完成 {delayed['gap_seconds_since_last_known_use']/60:.1f} 分钟，新进程命中 {u['prompt_cache_hit_tokens']} / {u['prompt_tokens']} 输入Token，TTFT {delayed['ttft_seconds']:.3f}秒，正确性 {delayed.get('correct')}。前次98.9分钟也命中9856/10099。均为同一冻结前缀的观察，不是永久保留承诺。",9.5,15,TEAL)
    r.h('正确性与费用')
    r.p('每次请求保留完整公开提示、实际回答和正确性判据。冷、热失败和重试均留账。稳定系统提示与同一模型可复用前缀，不跨不同模型转移不兼容 KV。可命中但不更快、无法关闭缓存及无法测量的指标都作为结果公开。')
    if (charts/'cloud-cache.png').exists():r.image(charts/'cloud-cache.png',160)
    r.begin('11  oMLX / vLLM 本地缓存')
    if s.get('local_cache_primary_run')=='local-cache1':
        r.p('本表为早期16K客户端预算队列：短请求已测，12个长前缀请求在客户端保守准入检查被拒绝，没有进入推理。64K同内容重测若因未接电尚未完成，长上下文项保持NOT_RUN；两种容量队列不交叉配对计算提速。',9.5,15,TEAL)
    cache_names={'warm_standard':'短前缀重复','long_repeat':'长前缀重复','tool_followup':'工具结果重复','after_owned_service_restart':'服务重启后'}
    r.table([['后端 / 场景','OFF TTFT s','ON TTFT s','观察倍数','ON 命中率']]+[[x['engine']+' / '+cache_names.get(x['tag'],x['tag']),fmt(x['off_ttft_seconds']),fmt(x['on_ttft_seconds']),fmt(x['observed_ttft_speedup']),pct(x.get('on_cache_hit_ratio'))] for x in s['local_cache']],[160,85,85,75,WIDTH-405],7.8)
    if s.get('local_cache_primary_run')=='local-cache2':
        r.p('64K为容量配置，实际长夹具8341 Token。48/48响应与正确性通过；表为全部预定重复中位数，前三场景各OFF/ON两次，重启各一次。oMLX每次长重复实报命中8192，vLLM串行计数增量7392。oMLX长提示OFF范围26.80–106.69秒、ON 1.094–1.150秒，波动大；固定先OFF后ON，未做ABBA，倍数仅为本夹具观察。短提示oMLX更快但命中0，不能归因KV复用。',9,14,TEAL)
    r.p('专项只使用本轮独立服务、端口和状态目录，读取相同固定 Qwen 权重，不改变日常模型服务。北京时间 2026-10-29 09:30 前未运行本地大模型；用户随后明确选择接电后的正常性能模式，最终批次逐例核验 AC Power 且省电关闭。早期电源切换中断单独留存。内存不足直接阻塞，不卸载用户模型。')
    r.p('Cache OFF/ON、首请求、连续重复、长前缀、工具结果、不同 HTTP 会话及本轮服务重启分别保留。比较完整输出或规范化工具提案；有返回 Token ID 时另保留。没有暴露实际缓存 Token 时写 UNKNOWN，不根据预期前缀长度估算命中。')
    r.p('TTFT 为客户端观察值。另附oMLX Usage的prompt_eval_duration与vLLM串行Prefill直方图增量、端到端、CPU和RSS；这些是provider阶段计时，不等同于纯设备耗时。重启后本短提示两后端均无命中，不能把预热称为永久缓存。当前串行小样本未完成ABBA、长压力与内部KV/GDN数值资格，保持NOT_RUN。',9.5,15)
    r.begin('12  持久化、权限与真实 E2E')
    r.p('最终演示是一段实时 Core SDK 事件视图录像，不是原生桌面 UI 录像，也不是公开 Benchmark。真实 DeepSeek 读取本轮随机标记文件，返回 alpha=7、beta=11 与和 18；宿主检查文件原始哈希、真实 read_file 收据和最终标记。模型未在任务问题中获得文件内容。')
    q=s.get('core_qualification') or {};qualified=f"{q.get('tests_run','NOT_RUN')} 项 / "+('PASS' if q.get('successful') else 'FAIL_OR_NOT_RUN')+f" / {q.get('skips','UNKNOWN')} skipped"
    r.table([['检查','本轮结果'],['当前候选 SDK 快验任务编号',demo.get('task_id','NOT_RUN')],['当前真实运行',str(demo.get('pass','NOT_RUN'))],['相同请求与幂等键',str(demo.get('checks',{}).get('idempotent_same_task','NOT_RUN'))],['停止并重建 Core 后查询',str(demo.get('checks',{}).get('restart_same_task','NOT_RUN'))],['授权目录之外路径拒绝',str(demo.get('checks',{}).get('outside_denied','NOT_RUN'))],['安装候选 / 官方 SDK 全量',qualified],['Suite / Companion',test_result('suite-regression2.log')+' / '+test_result('companion-regression2.log')],['推荐与训练 / 路由与历史兼容',test_result('selector-training-tests.log')+' / '+test_result('hybrid-final-tests.log')]])
    r.p('回归测试含脚本模型与真实 HTTP、SQLite、文件和权限控制，不是模型能力成功率。录像来自较早真实 SDK 运行，当前工具契约提示词另有快速真实 E2E，包含字段值、幂等、重启和越界检查；不把录像称作当前原生 GUI 验收。依赖缺失、失败录制、错误计分和修复记录均保留，所有实际 API 调用计费。长期无人值守、真实 QQ/微信、干净 Mac/VM、Intel、公证与升级回滚仍未准入。')
    r.begin('13  代码、许可证与开源计划')
    r.p('仓库保持私有，开发分支基于 RC.6，合入 PR #4 的提交 785618d6；未合并 main、替换 Latest、安装日常 APP 或发布正式 Release。评审交付包含候选源码、固定提交身份、复现入口、实验协议、费用账本及运行轨迹。自训MLP的JSON参数随代码提供；大模型权重、账号凭据、私有SQLite和日常配置不随包分发。')
    r.table([['组件','许可证与归属处理'],['自有 LocalPilot 代码','MIT，保留贡献者与 Git 归属；比赛期间受限访问，赛后计划公开'],['DeepSeek Harness 适配','MIT；保留 third_party/deepseek-harness/LICENSE 与 NOTICE；原生 DSH 仅用于对照'],['BFCL 数据与评分代码','Apache-2.0；固定 upstream commit，保留改编标记与独立判分来源'],['oMLX / vLLM / MLX','按其各自许可证使用；外部运行时与大模型权重不包含在受限源码包内'],['文档及制作工具','ReportLab、Matplotlib、Artifact Tool 与 macOS 语音合成用于材料；不构成模型性能证据']],[138,WIDTH-138])
    r.p('原创性说明：团队主张任务/所有者/幂等、权限修订、意图与收据、UNKNOWN 和宿主验证的工程整合；不主张持久化、路由或 KV Cache 概念的首次发明。PR #4 的贡献归属保留。基础模型、DSH 与公开数据集不作为团队自研成果。')
    r.p('AI 辅助用于代码审查、测试驱动、实验脚本、材料整理与合成旁白。实验请求由真实外部或独立本地 provider 处理；数值来自原始记录。报告和参赛声明仍须由团队核对并负责；本工作未冒签声明或代提交。')
    r.begin('14  提交映射、限制与参考来源')
    r.table([['交付项','文件 / 状态'],['技术报告','本 PDF，15 页；与图表、JSON 摘要及来源一并提供'],['真实演示','MP4，目标 3-5 分钟、≤300MB；实时 SDK 视图，合成旁白另披露'],['受限源码','自有 MIT 源码与必要 NOTICE；不含模型、凭据、私有数据或 APP 安装替换'],['证据','七组逐实例结果、请求用量、费用上下界、事件、缓存、回归及失败记录'],['仍未证明','统计非劣效、显著节费、MLP 质量全面替换、永久 KV Cache、消费者发行资格']],[103,WIDTH-103])
    r.p('官方 AI+开源报名、缴费和作品提交截止：2026-10-30 20:00（北京时间）。报告≤10MB、视频原则上 3-5 分钟 MP4 且≤300MB。队伍名为大肥鱼队；学校、校徽和指导教师信息不进入评审材料。报名、缴费、签字与平台上传由团队执行，本工作未代为完成。',10,16)
    refs=[
        'AIC 赛程：https://www.aicomp.cn/notice/notice-3/5435.html',
        'AIC 赛道：https://www.aicomp.cn/tracks/tracks-5/4924.html',
        'DeepSeek 价格：https://api-docs.deepseek.com/quick_start/pricing/',
        'DeepSeek 缓存：https://api-docs.deepseek.com/guides/kv_cache/',
        'DSH：https://github.com/deepseek-ai/deepseek-harness/tree/dsh-v0.2.1-rc.2',
        'BFCL：https://github.com/ShishirPatil/gorilla/tree/6ea57973c7a6097fd7c5915698c54c17c5b1b6c8',
        'SWE-bench Verified 数据 revision：c104f840cc67f8b6eec6f759ebc8b2693d585d4a',
        '模型：https://huggingface.co/mlx-community/Qwen3.6-35B-A3B-4bit']
    for ref in refs:r.p(ref,7.5,11,GRAY,4)
    r.finish()
    intro='localpilot 是大肥鱼队开发的本地与云端协同智能体，提供统一 Core、持久任务、目录权限、幂等请求、执行收据与独立验证。轻量 MLP 在硬约束内推荐本地模型，五档 Router 管理已部署后端。作品用真实请求账本和公开基准改编对照验证质量、费用与缓存表现，完整保留失败和证据限制；自有代码采用 MIT，比赛期间私有，赛后计划公开。'
    (a.output/'作品介绍.txt').write_text('作品名称：localpilot\n队伍：大肥鱼队\n\n'+intro+'\n',encoding='utf-8')
    (a.output/'声明与开源计划.txt').write_text('localpilot / 大肥鱼队\n自有代码采用 MIT；比赛期间保持私有，按需向评审受限提供源码；赛后计划公开。\n保留贡献者、第三方 LICENSE 与 NOTICE。模型、公开基准和 DSH 不作为自研。\nAI 辅助用于代码、脚本和材料；视频旁白由 macOS 语音合成。\n本文件是待团队核对的说明，不是已签字声明，不代替平台要求的资格或权属证明。\n')
    (a.output.parent/'report-validation.json').write_text(json.dumps({'pages':15,'intro_characters':len(intro),'all_charts_from_summary':True,'benchmark_trials':measured,'native_gui_video':False,
        'source_summary_sha256':hashlib.sha256(a.summary.read_bytes()).hexdigest(),
        'generator_sha256':hashlib.sha256(Path(__file__).read_bytes()).hexdigest()},indent=2))
    print(json.dumps({'report':str(a.output/'localpilot-技术报告.pdf'),'pages':15,'benchmark_trials':measured,'intro_characters':len(intro)}))


if __name__=='__main__':main()
