> 2026-10-18 独立Companion补丁：可选稳定前缀/minimal纯推理、缓存35B的宿主生命周期、owner-only推理停止/心跳、resource-only例外票据。默认旧部署不自动启用managed模型。见[本轮合同/限制/证据](COMPANION_V044_CACHE_RESOURCE_REPORT.md)，OpenAPI已同步。原版下文保留历史语义。

# Model Manager Contract v1

Model Manager 独立于 Agent Runtime 和客户端 Skill。`localpilot_service.model_manager` 提供 HTTPModelManager transport 与 ControlledModelManager 测试适配器。模拟器只推进受控 job 状态，**从不下载、加载代码、安装环境或运行 vLLM**。

## 模型 Registry 与状态

注册记录至少包含 id、固定 source/revision、license、trust_remote_code=false、hardware、capabilities、context estimate、resource_estimate(memory_bytes/disk_bytes)、downloaded 与 deployment_status。未来实际实现要区分估算和实测，不能用模型 ID 推测硬件适配。

状态建议 not_deployed → downloading → loading → ready；也可 unloading/unavailable/failed。job 为 queued/running/downloading/loading/completed/failed/cancelled，带 progress、failure_reason 与模型版本。下载进度、load 进度和 inference health 分开报告。

| 方法 | HTTP contract |
|---|---|
| list_models | GET `/model-manager/v1/models` |
| model/capabilities/deployment/resource_estimate | GET `/model-manager/v1/models/{encoded_model_id}` |
| health | GET `/model-manager/v1/health`；区分 manager/vLLM readiness |
| ensure/download/load/unload | POST `/model-manager/v1/jobs` `{model_id, operation, grant_id}` + Idempotency-Key |
| job/progress/failure | GET `/model-manager/v1/jobs/{id}` |

HTTP transport 只接受固定服务 origin，loopback HTTP 或 HTTPS，带独立 Bearer token，禁止 redirect。manager mutation token 只交给 trusted host；本服务没有向普通 Agent 暴露这些 endpoints。

## 权限与资源策略

模型必须事先注册，普通 Agent 任意 model ID 返回 model_not_registered。Host ResourceGrant 明确 allowed_models、allow_download、max_download_bytes、disk_bytes、memory_bytes、hardware、approved_sources/approved_licenses。默认 allow_download=false 和零预算。

每次 ensure 依次检查：授权模型、来源与不可变 revision、许可证、拒绝 remote code、硬件与完整资源估算、磁盘/内存预算、下载授权与上限。未知不是通过。失败原因分别保留：model_permission_denied、source_revision_not_approved、license_not_approved、untrusted_code_forbidden、hardware_incompatible_or_unknown、resource_estimate_unknown、resource_budget_exceeded、download_not_authorized、model_not_downloaded。Operation 白名单没有任意 shell、URL 或安装参数。

同 grant/model/operation/key 返回同 job；改变参数或 grant 冲突拒绝。真实部署应在下载和加载边界再次核对可用资源、校验 artifact digest、使用可信 revision、拒绝 symlink/路径穿越、保存持久 job/receipt，并给 unload 独立的使用者/活跃推理 lease 检查。ControlledModelManager 没有这些真实系统副作用，不声称生产模型管理完成。

## Router 接入顺序

LocalPilot Router 选择 host 注册模型 → Registry 返回能力/部署状态 → ready 后进行推理；未部署时明确 model_not_deployed。未来 trusted host 可提交 ensure job，经 Model Manager grant 与资源检查后，job ready、health ready，再刷新 Registry 并继续。Agent 不能通过“自动模式”开启下载。

本轮只完成合同、策略负例、可测试状态适配器和认证 HTTP transport。真实 vLLM、真实下载、load/unload 和资源测量均 NOT_RUN；不要求安装 vLLM。未来接入不需要改 AgentSession 工具执行循环。
