# OpenAI 与公开评估定向验收（2026-11-16）

基础源码为 `d846fef0f4b442d57e6e37f856a59c5a1a1337de`；本目录记录其后本轮补丁的定向验证，文件 SHA 见 [MANIFEST.json](MANIFEST.json)。这些运行有重叠，不与全量回归相加。

## 最终结果

| 验证 | 结果 | 真实执行边界 |
|---|---|---|
| OpenAI、服务合同、Harbor runner | 26 PASS、2 SKIP，共 28 项 | TLS/JSON/SSE、服务 HTTP API、真实文件读取、恢复幂等、代理、五档来源过滤、真实子进程；2 项需独立 Harbor 环境 |
| 独立 Harbor `0.26.0` 合同环境 | 69 PASS、0 SKIP | 官方 schema、BaseAgent/参考适配器、实际 HTTP、预算审计、原进程续接；不代表启动 Docker |
| MMLU-Pro 薄 runner | 4 PASS | 固定选题、严格最终答案、完整 32 次受控 HTTP、错误与截断保留；全部模型回应为协议夹具 |
| OpenAI/DeepSeek 真实付费推理 | NOT_RUN | 当前未提供可用凭据；没有查询账户余额或猜测赠送额度 |
| 新 Docker 正式对照 | BLOCKED | Docker 客户端和两个指定 socket 不存在 |

对应最终日志：[Core 定向](openai-contract-r4.log)、[Harbor 官方合同](harbor-official-r3.log)、[公开子集 runner](mmlu-runner-fixtures-r1.log)。最终三次运行均未记录 ResourceWarning。

命令在仓库根目录执行；`CORE_PYTHON` 表示已有 Core 测试环境，`HARBOR_PYTHON` 表示安装固定 Harbor commit 的独立评估环境：

```bash
PYTHONPATH=. "$CORE_PYTHON" -W error::ResourceWarning -m unittest \
  tests.test_openai_cloud_backend tests.test_service_contracts tests.test_harbor_study_runner -v

PYTHONPATH=. LOCALPILOT_HARBOR_CONTRACT=1 "$HARBOR_PYTHON" -W error::ResourceWarning -m unittest \
  tests.test_harbor_adapter tests.test_harbor_study_runner tests.test_harbor_budget_protocol \
  tests.test_harbor_orchestration tests.test_harbor_budget_audit tests.test_public_agent_eval -v

PYTHONPATH=. "$CORE_PYTHON" -W error::ResourceWarning -m unittest tests.test_public_model_eval -v
```

## 中间失败原样保留

- `openai-contract-r1.log`：6 PASS、1 ERROR。新增测试使用了服务不接受的 `read-only` 权限字符串；改为现有 `approve-mutations` 加只读能力约束。
- `openai-contract-r2.log`：25 PASS、1 ERROR、2 SKIP。新增测试从内部 TaskService 快照读取只有公开服务层才注入的 `route_decision`；改为真正通过服务 HTTP API 提交和查询。
- `openai-contract-r3.log`：25 PASS、1 ERROR、2 SKIP。新增恢复测试先 suspend 后又 shutdown 同一旧服务，导致已关闭 store 的清理错误，并有 ResourceWarning；清理改为仅关闭尚未关闭的服务。真实任务和恢复已在该轮执行，但这一轮整体仍记 ERROR。
- `harbor-official-r1.log`：51 PASS、1 ERROR。命令误写不存在的 `tests.test_harbor_multiagent` 模块；实际模块为 `tests.test_harbor_orchestration`。修正调用后，r2 为 68 PASS；新增云端不能绕过本地预算资格的回归后，r3 为 69 PASS。

没有删除旧日志，没有将错误轮次改写为 PASS。最终夹具调整没有削弱产品权限、持久恢复或正式对照门槛。

## 原进程路径别名问题已直接复现

[public-evaluation-probe.json](public-evaluation-probe.json)保存真实进程 A/B 对照：

- 从 symlink cwd 启动并暂停真实 Python 子进程；psutil 返回 canonical cwd。
- 直接加载基础提交的原始 `harbor_study_runner.py`：旧版漏检重复 launcher，并拒绝继续该原进程。
- 当前补丁：检测到已有 launcher，继续同一 PID，`replayed_trials=0`。
- UID、命令参数、Docker 环境和暂停状态的既有检查保留；子进程由原 Popen 对象等待退出。

这是 Linux 上对 macOS `/var` / `/private/var` 同类路径别名的实现验证，不声称完成了 Mac 原生或 Intel 设备验收。

## MMLU-Pro 公开子集已在推理前冻结

公开作者数据源为 `TIGER-Lab/MMLU-Pro`，revision `b189ec765aa7ed75c8acfea42df31fdae71f97be`，下载的 test Parquet SHA256 为 `0e24a191921c2f453518a537a8b2117bd137e7714d4ef1565e9ba06c1ecb9ad8`。该固定文件含 12,032 test 题和 14 学科。

在 `2026-11-16T09:49:29.771618+00:00`，以选题 seed `20261116`、每学科 2 题再取其余最小哈希 4 题冻结共 32 题。协议文件 SHA256 为 `4ff714d10aff543d318699bd67bbc88b5c08c7496922ce25b024c17044331e07`。选题 ID、完整下载来源及哈希见 [mmlu-SELECTION.json](mmlu-SELECTION.json)；不把题目、gold 或 CoT 放进仓库的 Skills 或训练输入。

冻结设置为 zero-shot、每题一次、无工具、最多 512 输出 token、HTTP 连接/读取超时参数 120 秒（实际耗时逐题记录，不是整题硬截止），不重试、不抽换问题。只接受最后非空行严格为 `Answer: A` 至 `Answer: J` 且与题目选项范围一致；provider 必须以 `stop` 完成。格式不合、长度截断、模型错误均保留在计划 32 的分母。实际 Qwen3.5-2B 推理由独立的受控本地模型资格运行，在九项产品任务之后共用同一个 Provider 实例执行，其逐题结果另行报告；这里的 4 PASS 只是 runner 合同测试。

`scripts/public_model_eval.py` 复用 `ServiceOpenAIBackend`，只增加选题、落盘和判分，不增加 Agent 循环。成功 HTTP 响应的原始 provider JSON（包括 usage/id/timings）和规范化对象分别保存；错误或超时的未获得响应保持未知。源码冻结 SHA256 为 `60f10f2fc22918f2aec0b79da36a48a68a13b359bacb56c1a7888df8920c3a57`。

该评估是小规模模型证据，不是全量 MMLU-Pro、AA 方法复现或 Agent 排名。完整公开对照、OpenAI 配置及 Work 续做提示词见 [开发说明](../../development/OPENAI_AND_PUBLIC_EVALUATION_20261116.md)。
