> 2026-10-18 独立Companion补丁：可选稳定前缀/minimal纯推理、缓存35B的宿主生命周期、owner-only推理停止/心跳、resource-only例外票据。默认旧部署不自动启用managed模型。见[本轮合同/限制/证据](COMPANION_V044_CACHE_RESOURCE_REPORT.md)，OpenAPI已同步。原版下文保留历史语义。

# Companion Client Contract v1

QQ/WeChat Gateway → Companion → LocalPilot Agent Service API → 原 Runtime。Companion 自行决定简单回复是否需要委派，持有自己的 client identity；LocalPilot 不需要知道渠道名称，不接管监听、消息路由或轻量模型。

Companion 应在自己的事务记录中绑定 conversation/channel owner 与 LocalPilot Session ID；不要把一个用户的 Session 给另一用户。若本机服务面向不同真实用户，配置独立客户端身份/route/workspace；单 Companion token 内的外部用户隔离由 Companion 自己负责。

先持久化 upstream event ID、payload fingerprint 和幂等键，再提交原生 Task；收到 IDs 后保存。消息重投使用完全相同 key/body。Lost submit response 以同键重试；UNKNOWN 交还 operator，不能另建重复任务。Session 下一轮只提交新增消息，取消/关闭 Session 后新建。

观察方式：Task snapshot + native SSE cursor。持久保存 Task ID、Session ID、最后已消费 sequence，断线后续读，过期 cursor 读取快照。将工具进度、审批等待、人工接管和最终四维结果转换为渠道需要的状态；不能把等待或失败回复为“已完成”。状态无需渠道特定逻辑。

审批必须把 exact required_action 交还绑定 operator。Companion token 不含 control；服务端负责校验身份、票据、epoch、权限与 egress。恢复使用原 Task，不由消息模型自己批准。用户取消触发 cancel 并继续查询至 quiescent，再报告可能已发生的 effects。

独立示例 `python -m examples.service_companion` 支持 message/Session/new key、events、status、cancel 和 recover envelope。服务返回 failed 时先报告原因；配置/网络修复后由 operator 判断安全 checkpoint 是否可继续，新目标才使用新键。示例不做自动业务补偿或重放副作用。

多轮、真实异步进度和云端读取由实际示例子进程验证；取消、审批交还与恢复另由同 API 的 control fixtures 覆盖。它不是 Companion 常驻服务，也不证明 QQ/微信 Gateway 集成。
