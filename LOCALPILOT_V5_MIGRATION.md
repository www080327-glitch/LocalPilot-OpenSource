# LocalPilot V5 候选引擎接入与迁移

候选包为 `5.0.0a1`；内部策略 revision=2。**默认仍为 Legacy。**
V5 是 AgentSession 内的执行策略；DeepSeek Native 是独立的 Provider。
运行 LocalPilot 候选包不需要安装 DSH、Node 或上游插件。

## Host 配置

以下字段合并到一个新的 Host route，不是完整服务配置：

```json
{
  "engine": "v5",
  "backend": {
    "kind": "deepseek-native",
    "model": "deepseek-flash",
    "key_file": "/operator/protected/existing-deepseek.key",
    "context_budget": 131072,
    "timeout": 45
  },
  "thinking": "high",
  "permissions": "approve-mutations",
  "cloud_egress": "REQUIRES_APPROVAL",
  "cloud_egress_paths": [],
  "capabilities": {"read": true, "write": true, "execute": false},
  "budgets": {
    "max_steps": 12,
    "max_tool_calls": 24,
    "max_token_units": 262144,
    "max_output_tokens": 2048
  }
}
```

替换 workspace、data_dir、受保护凭据引用与客户端身份等既有配置；配置文件保持
0600，私有 data_dir 位于工具 workspace 之外。这里的 key_file 是现有受保护文件的
引用，不要复制凭据到源码、测试证据或普通客户端配置。

`cloud_egress_paths` 只控制指定路径的正文出站，不授予工具权限。普通模型请求、
工具审批和 Cloud Egress 继续分开审批。未批准的额外 Session log、插件清单、
本地记忆和 Companion 观察不会随新 Provider 自动上传。

V5 也可配合既有 `deepseek` Chat、`local-openai` 和 `remote-openai` Provider。
这些组合共享原有路由、权限和持久化；本轮真实新引擎资格主要限于 DeepSeek
Messages，MLX/vLLM 的新引擎真实执行尚未验收。Computer Use 继续使用原有路径
及资格边界；V5 + ComputerRuntime 当前明确拒绝，不能通过换名称扩大能力。

验证 Host 配置和 checkpoint（不进行推理）：

```text
python -m localpilot_service --config /operator/private/service.json --check
```

正常启动沿用同一命令，去掉 `--check`。CLI、SDK、Companion、GUI 仍调用 API 1.0。
新 route 可通过既有 Host 客户端路由映射接入，不需要修改 Companion 或 GUI。

## 验收维度

Execution、Delivery、Verification、Engineering 分开报告。无 trusted verifier 时，
V5 可像 Legacy 一样结束普通 API 对话，但 execution 只为 `settled`、verification
为 `not_run`、engineering 为 `unverified`；API `completed` 不能当严格任务成功。
有 Host verification 配置时，V5 分开运行文件就绪检查和最终交付文本检查；失败、
UNKNOWN、审批、未收集 Child 或不确定副作用不能由模型文字解除。

`max_token_units` 和 context_budget 是 UTF-8 bytes 的保守准入单位，不是实测 tokens。
服务商 tokens、reasoning/cache usage 和费用另行统计。最大输出、步数、工具数、
Child 预算、最终交付次数仍有界；不会为取得成功率自动加额度。

## 迁移、恢复和回滚

1. 合并前审阅本分支相对 RC2 的完整变更；它包含前轮已提交的 DSH 协议优化成果。
   不直接复制单个 Provider 文件而遗漏 Message、Hybrid 来源校验和 SQLite 配置边界。
2. 候选 wheel 安装到独立环境，先使用新的 route 和新的 Session。保留原有 Legacy
   route、服务配置、私有数据目录、发行制品和稳定 tag。
3. 按既有服务流程备份数据库，在离线副本核对恢复与 owner/approval epoch/idempotency。
   不对运行中的数据库执行手工更新或把未完成的 mutation 改成已完成。
4. Legacy checkpoint 保持原配置 fingerprint。V5 policy 或 Provider 改变时必须使用
   新 Session/显式迁移；不能把旧 checkpoint 静默解释成新引擎。开发 revision=1
   到本候选 revision=2 也会被恢复围栏拒绝；旧证据保留，不自动重放。
5. 默认引擎验收先限定明确任务、模型和工具范围，观察失败率、费用与延迟；真实
   本地协同、Computer Use、长时间运行、多平台和大仓库任务分别补充资格。
6. 回滚时停止给 V5 Session 派新工作，收集 Child/处理审批并核对副作用收据，再将
   **后续新 Session** 指向保留的 Legacy route。UNKNOWN 保持隔离。V5 的交付和
   证据仍可检索，不把失败任务复制成新任务重做。

当前建议：合并候选实现供下一阶段有范围的默认引擎验收；不立即切换生产默认。
旧稳定执行路径继续保留。
