"""Declarative fixed Suite/Companion commands. No shell or arbitrary argv IPC."""
import json
from pathlib import Path
ops=[]
def add(id,label,command,fields=(),review='此操作调用已安装的 Suite；结果以 CLI/服务返回为准。',confirm=False):
 ops.append(dict(id=id,label=label,command=command,fields=list(fields),review=review,confirm=confirm))
def text(key,label,**kw):return dict(key=key,label=label,type='text',**kw)
def choice(key,label,values,**kw):return dict(key=key,label=label,type='choice',options=values,**kw)
def flag(key,label,**kw):return dict(key=key,label=label,type='boolean',**kw)
for cmd,label in [('doctor','诊断'),('status','服务状态'),('start','启动 Core'),('stop','停止 Core'),('restart','重启 Core'),('models','模型注册表'),('tasks','任务列表'),('logs','服务日志'),('config','连接配置摘要')]:
 add(cmd,label,[cmd],confirm=cmd in ['stop','restart'],review='Core 拒绝停止含活动任务的服务。关闭桌面应用只是断开连接。' if cmd in ['stop','restart'] else '通过已安装 Suite 的固定命令查询或管理服务。')
add('version','模块版本',['--version'])
add('task-watch','打开任务并跟随事件',['task','show'],[text('task_id','Task ID',id=True)],review='先查询原 Task，再由桌面端按持久游标跟随 SSE；不会重复提交任务。')
for cmd,label in [('show','任务快照'),('watch','任务流'),('cancel','取消任务')]:
 if cmd=='watch':continue # GUI uses native durable SSE, not an unbounded subprocess.
 add('task-'+cmd,label,['task',cmd],[text('task_id','Task ID',id=True)],confirm=cmd=='cancel',review='取消是协作请求，不保证撤销已经发生的副作用。')
for cmd,label in [('start','启动 Companion'),('stop','停止 Companion'),('status','Companion 状态'),('privacy','观察权限'),('ui-snapshot','原生界面快照'),('recent-memories','记忆列表'),('reminders','提醒列表'),('notices','通知列表'),('index','索引状态'),('retention','保留策略'),('escalation-status','升级帮助状态'),('ui','打开 Companion 界面'),('popup','打开 Companion 卡片'),('ui-build','构建 Companion Web UI'),('native-build','构建 Companion 原生 UI')]:
 add('companion-'+cmd,label,['companion',cmd],confirm=cmd in ['stop','ui-build','native-build'])
for cmd,label in [('ask','轻量问答'),('retrieve','检索记忆'),('escalate','准备进一步帮助')]:
 add('companion-'+cmd,label,['companion',cmd],[text('text','文本')])
add('companion-dnd','免打扰',['companion','dnd'],[choice('value','免打扰',['on','off'])],confirm=True)
add('companion-remember','添加记忆',['companion','remember'],[choice('type','记忆类型',['user_fact','preference']),text('text','记忆内容'),text('fact_key','事实键',flag='--fact-key',optional=True),dict(key='expires_days',label='有效天数',type='number',flag='--expires-days',min=1,max=3650,optional=True)],confirm=True)
add('companion-forget','删除一条记忆',['companion','forget'],[text('id','记忆 ID',id=True)],confirm=True)
add('companion-clear-memory','清空记忆',['companion','clear-memory'],[],confirm=True,review='明确确认后清空此 Companion 的记忆。此操作无法通过本桌面端撤销。')
ops[-1]['fixed_flags']=['--confirm']
add('companion-respond','回应通知',['companion','respond'],[text('id','通知 ID',id=True),choice('response','回应',['ignore','not_needed','reply','help','useful','mute','more']),text('text','附加回复',flag='--text',optional=True)],confirm=True)
for cmd,label in [('submit-escalation','确认提交进一步帮助'),('retry-submission','恢复原帮助提交')]:
 add('companion-'+cmd,label,['companion',cmd],[text('review_digest','当前审核摘要',flag='--review-digest'),text('session_id','会话 ID',flag='--session-id',id=True,optional=True),text('conversation_id','对话 ID',flag='--conversation-id',id=True,optional=True),flag('allow_cloud','单次允许云端',flag='--allow-cloud')],confirm=True,review='审核摘要必须来自当前 escalation-status。仅允许当前原问题的明确帮助提交；Host 仍核对摘要、原幂等键与单次云端许可。')
 ops[-1]['fixed_flags']=['--approve']
add('companion-authorize-observation','授权观察范围',['companion','authorize-observation'],[],confirm=True,review='先在“观察权限”检查当前配置。确认会授权已配置的应用与目录观察范围；OS 权限仍由系统决定。')
ops[-1]['fixed_flags']=['--confirm']
add('companion-observe','暂停或恢复观察',['companion','observe'],[choice('value','观察状态',['pause','resume'])],confirm=True)
add('companion-observations','查询观察记录',['companion','observations'],[text('text','查询文本',optional=True)])
add('companion-forget-observation','删除观察记录',['companion','forget-observation'],[text('id','记录 ID',id=True)],confirm=True)
add('companion-exclude-apps','设置排除应用',['companion','exclude-apps'],[text('apps','应用 bundle ID，每行一个',many=True,optional=True)],confirm=True,review='替换 Companion 的排除应用列表。留空将清空此列表；授权范围仍由 Host 和 OS 控制。')
add('companion-proactive','主动帮助策略',['companion','proactive'],[choice('level','帮助频率',['off','low','normal'],flag='--level'),choice('delivery','通知投递',['silent','enabled'],flag='--delivery')],confirm=True,review='仅改变 Companion 主动帮助策略，不授予观察、工具或自动云端权限。')
add('companion-set-reminder','创建提醒',['companion','set-reminder'],[text('text','提醒内容'),dict(key='due_at',label='到期时间（Unix 秒）',type='number',flag='--due-at',min=1,max=32503680000)],confirm=True)
ops[-1]['fixed_flags']=['--confirm']
add('companion-delete-reminder','删除提醒',['companion','delete-reminder'],[text('id','提醒 ID',id=True)],confirm=True)
add('companion-localpilot-health','Core 连接健康',['companion','localpilot-health'],[flag('allow_cloud','单次允许检查云端',flag='--allow-cloud')],confirm=True)
for cmd,label in [('task-status','Companion 任务状态'),('task-cancel','Companion 取消任务'),('task-events','Companion 任务事件')]:
 fields=[text('task_id','Task ID',id=True),flag('allow_cloud','单次允许云端路径',flag='--allow-cloud')]
 if cmd=='task-events':fields.append(dict(key='after',label='事件游标',type='number',flag='--after',min=0,max=9007199254740991,optional=True))
 add('companion-'+cmd,label,['companion',cmd],fields,confirm=cmd=='task-cancel')
 if cmd=='task-cancel':ops[-1]['fixed_flags']=['--approve']
add('companion-launchd','后台启动管理',['companion','launchd'],[choice('operation','后台任务操作',['render','install','uninstall','status'])],confirm=True,review='install/uninstall 改变 Companion 的后台启动注册。render/status 只查询。')
ops[-1]['fixed_flags']=['--confirm']
add('companion-model-smoke','轻量模型真实试运行',['companion','model-smoke'],[text('prompt','公开测试问题',flag='--prompt')],confirm=True,review='这会实际调用已配置的轻量模型并消耗本机资源；电源与 Host 限制继续生效。')
Path('src/cli-tools.json').write_text(json.dumps(ops,ensure_ascii=False,indent=2)+'\n')
