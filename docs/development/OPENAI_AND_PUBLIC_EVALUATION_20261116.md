# OpenAI 云端接入与公开对照状态（2026-11-16）

## 已完成与实际未运行

Core 新增显式 `openai` 后端，Harbor 的 LocalPilot 适配器也可选择该后端。它继续使用产品 `AgentSession`、工具收据、持久会话、五档来源策略和云端数据出口策略。现有 `remote-openai`、DeepSeek 和本地配置的请求参数及持久身份不变；不会因为余额不足而在一次任务或冻结研究中暗换 provider。

续作补齐 Companion 两处仍只识别 DeepSeek 的准入判断，并给新 backend 明确设置 `provider="openai"`，使子 Agent/协作用量记录保留提供方。控制窗也显示实际 OpenAI 模型；local-only 拒绝云端及原问题单独授权的边界保持。62 项针对性合同测试通过，见[续作证据](../evidence/native-continuation-20261116/RESULTS.md)。GUI 的一键云端配置仍是 DeepSeek 专用；OpenAI 使用下文独立路由配置，没有宣称已新增 OpenAI 设置向导。

本次用真实 TLS、JSON/SSE、服务 HTTP API、文件工具和恢复流程测试接口合同，没有向 OpenAI 或 DeepSeek 发出真实推理请求。测试服务器是明确的协议夹具，不计为模型能力或公开基准成绩。最终定向结果和中间失败均见 [验收证据](../evidence/openai-public-eval-20261116/RESULTS.md)。

当前云端环境没有 Docker 客户端、指定 Docker socket，也没有可用的 `OPENAI_API_KEY` / `DEEPSEEK_API_KEY`。因此新增 Docker study、付费 API、余额及官方榜单提交均未运行。ChatGPT 订阅、赠送额度和 API project 的可用余额在这里都未核实，不能据订阅名称将 API 费用记为零。

2026-11-16 核查的 [OpenAI 官方赠送额度说明](https://developers.openai.com/api/docs/guides/chatgpt-api-credits)确认：符合条件的 Pro $100 档可领取每月 $100 API 额度，需要关联本人拥有的 API 组织；首次按剩余账期折算，到期不结转。该福利真实存在，但本次未访问用户账户，仍不知道领取状态、组织、余额和到期日。Work 应使用关联组织下的 project key 核验调用与用量；API 标价成本、赠送额度抵扣和新增现金支出分别记录，不把它们混成一个“免费”字段。

## 配置一个独立 OpenAI 路由

以下是 `service.json` 的 `routes` 内新增路由示例；路径、模型 ID、上下文预算是需由操作者核实的输入，示例没有证明该模型已在账户中开通。API key 只通过既有私有凭据机制注入环境，不写入配置、日志、Git 或基准 spec。

```json
{
  "cloud-openai": {
    "workspace": "/absolute/approved-workspace",
    "engine": "v5",
    "backend": {
      "kind": "openai",
      "model": "YOUR_VERIFIED_OPENAI_MODEL_ID",
      "api_key_env": "OPENAI_API_KEY",
      "context_budget": 32768,
      "timeout": 120,
      "capabilities": {"tool_calling": true, "streaming": true},
      "include_stream_usage": true
    },
    "permissions": "approve-mutations",
    "cloud_egress": "REQUIRES_APPROVAL",
    "budgets": {"max_steps": 6, "max_tool_calls": 8, "max_output_tokens": 2048}
  }
}
```

还需按现有服务规则将此路由授予相应 client。保持独立路由名称可保留已有会话的配置身份；不要把旧 DeepSeek 路由原地改成 OpenAI 后再绕过恢复检查。`local_only` 会排除这个云端路由；云端出口仍需满足已授权的 host policy。权限和本地/云端来源是两个独立维度。

`base_url` 缺省为 `https://api.openai.com/v1`，凭据变量缺省为 `OPENAI_API_KEY`；显式覆盖端点仍要求 HTTPS。此后端继承系统代理及证书信任配置，并拒绝 HTTP 重定向。普通本地端点的旧行为保持。

macOS 的 Core 经 launchd 启动时不会继承终端里的任意变量。密钥应通过现有私有 `clients.env` 机制供 `_serve` 读取，遵守该文件已有格式和 owner-only 权限，不只在终端 `export`。现有 launchd 白名单也未传入 shell-only `HTTPS_PROXY/https_proxy/NO_PROXY`；使用系统代理配置，并在真正启动后的 Core 中验证连接。Linux detached 进程沿用启动环境。这里没有新建凭据存储或修改系统代理。

根据 [OpenAI Chat Completions 官方参数](https://developers.openai.com/api/reference/resources/chat/subresources/completions/methods/create)，新适配器发送 `max_completion_tokens`，限制包含可见输出与 reasoning token；流式请求索取 usage。没有猜测采样参数或 reasoning 默认值，也不发送本地 `chat_template_kwargs`。如模型支持特定 reasoning effort，可通过既有 `capabilities.reasoning`、`reasoning_efforts` 和路由 `thinking` 显式声明。实际支持情况须由该模型官方文档及真实请求验证。

服务返回的 token 用量与价格是不同证据；缺失 usage、失败请求的最终用量、价格或账户账单仍记为 UNKNOWN。响应里的缓存命中也不证明通用外部 HTTP 能永久保存 KV。

## AA 可以如何用于本项目

截至核查日，[AA 官方方法页](https://artificialanalysis.ai/methodology/intelligence-benchmarking)为 Intelligence Index v5.0.1。旧 GDPval-AA 已从 v5 综合指数中移出，但仍作为独立评估；v2.1 使用公开 GDPval gold 任务、Stirrup/E2B 执行、盲评与经过校准的 Crowd-BT 评分。自己的 LocalPilot 输出与自建 judge 分数不能直接标注为 AA 官方 Elo。

[OpenAI GDPval 数据集](https://huggingface.co/datasets/openai/gdpval)的公开页面目前列出 220 条任务，包含输入材料、参考交付物及 rubric。若后续做办公能力研究，需固定数据 revision，只将题目与输入材料提供给 Agent；参考交付物与 rubric 留在独立评审侧。当前仓库没有完成 GDPval 的文件交付及盲评适配器，因此这里没有生成一个替代 AA 的自制分数。

[Stirrup](https://github.com/ArtificialAnalysis/Stirrup)允许本地、Docker、E2B 执行，这是可参考的官方开源 harness。采用其本地执行方式并不会自动复现 AA 使用的沙箱、环境和评分。其代码许可也不等于所有评估材料都可按本仓库 Apache-2.0 再发布。

本项目现有可审计路线是固定版本的 Terminal-Bench + 官方 Harbor verifier，参见 [公开评估协议](PUBLIC_AGENT_EVALUATION_20261114.md)。旧版、当前版及自选子集必须分别命名；同模型的 LocalPilot/参考 Agent 配对结果才能较直接地说明调度与工具执行的影响。完整试验前没有“不弱于主流 Agent”的结论。

### 无 Docker 的公开单项

`scripts/public_model_eval.py` 增加了一个固定的 MMLU-Pro 小规模模型探测，复用已有产品 HTTP 后端。作者的[数据卡](https://huggingface.co/datasets/TIGER-Lab/MMLU-Pro)提供公开题目和官方评估入口；MMLU-Pro 也曾用于 AA 综合指数，但当前已退役。这次采用已固定 revision 的 test split，按 seed `20261116` 预选 14 科各 2 题再补 4 题，共 32 题，zero-shot、每题一次、512 输出 token，HTTP 连接/读取超时参数 120 秒（不是整题的硬截止；实际耗时逐题记录），保留全部失败和用量。

这个采样和提示与完整官方研究不同，不能拿 32 题分数同榜单分数排位，也不能证明 Agent 工具能力。作者通常使用 5-shot，部分模型使用 zero-shot；本轮明确选择低资源 zero-shot 探测，并把 32 题全部留在分母。冻结的题 ID、来源与预算见 [本轮证据](../evidence/openai-public-eval-20261116/RESULTS.md)。题目和 gold 保留在独立评估目录；模型只接收题目和选项，不接收 gold 或参考推理。

### OpenAI 接口不降低正式对照门槛

`scripts.localpilot_harbor:LocalPilotHarborAgent` 可设置 `provider_kind: "openai"`、显式 HTTPS `endpoint`、已核实的 `model_name` 和 `api_key_env`，先运行 `purpose: "smoke"`。OpenAI 路径不默认附加 `temperature: 0` 或本地模板开关。

现有 `evaluation` 的 `MATCHED_MODEL_AND_MEASURED_BUDGET` 协议要求相同本地模型、精确 tokenizer、逐请求预留/结算和完整 provider 用量。OpenAI/其他云端还未取得这项资格；添加 provider 并不会绕过 `harbor_budget_audit.py` 和 `harbor_preflight.py` 的检查。若要做云端正式研究，应另行冻结可执行的预算、费用、参考 Agent 和缺失用量处理协议，验证后新建 study，不能将云端 kwargs 塞入原 534 次 study。

## Harbor 的 macOS 路径别名修复

`psutil` 可能将 `/var/...` 报告为 `/private/var/...`。原执行器比较原始 cwd 字符串，会漏检已存在的 launcher，并拒绝继续同一暂停进程。现在只对两侧 cwd 做真实路径解析；UID、完整命令参数、Docker 环境及暂停状态检查保留。Linux 真实目录符号链接复现了相同行为：旧版漏检，新版识别并继续原 PID，重放数为 0。这验证代码路径，不能代替 Intel Mac 或 macOS 系统验收。

续跑旧队列时，使用修复后的控制脚本指向原冻结 runtime checkout。不要修改旧 study 的哈希、预算、原始配置或已落盘结果；如果没有可证实的原进程及冻结环境，继续标记未决并创建独立的新 study。

## 交给本机 Work 的执行提示词

```text
继续 LocalPilot 公开对照和真实 OpenAI 验收。先阅读最新 main、
docs/development/OPENAI_AND_PUBLIC_EVALUATION_20261116.md、
docs/development/PUBLIC_AGENT_EVALUATION_20261114.md，以及上次本机全部失败证据。

1. 审阅本机尚未提交的修改，与最新 main 逐项比较；保留原文件和差异，不清理旧证据。
   不以 Rosetta 或协议夹具替代 Intel、真实模型或 Docker 验收。
2. Mac 本地用已核实 revision/SHA 的 Qwen3.6-35B；先确认现有实例、隔离目录和资源。
   不下载另一套 35B，不接管外部 oMLX 服务，不覆盖运行中的 Test APP。
3. 用户已允许 OpenAI 作为 DeepSeek 之外的云端选择。只从既有私有配置读取 API key，
   不将 key 打印或提交；先核实赠送额度关联的 API organization/project、余额、到期日、
   模型可用性和价格。Pro $100 的赠送 API 福利已获官方文档确认，但用户账户状态尚未核实。
   使用新的 openai 路由、现有 Core Session 和真实工具做小额开发 smoke，保存
   configured/returned model、request ID（可得时）、输入/输出/缓存/reasoning token、
   延迟、错误和实际账单依据。没有证据的费用记 UNKNOWN，不假定 Pro 订阅费用等于 API 余额。
   不在旧任务或冻结研究中自动把 DeepSeek 换成 OpenAI。
4. 用专用已授权 Docker daemon 做只读预检；核验 socket、daemon ID、宿主/guest 磁盘、
   内存、官方任务要求及镜像来源。预检不通过就保留 BLOCKED，不删用户文件或旧失败以腾空间。
5. 对旧 534 队列只做审计和精确续接。修复后的控制脚本指向原冻结 runtime，
   原进程的 UID/argv/cwd/Docker 环境都一致时才继续；UNKNOWN 不重放，FAIL/ERROR 不覆盖。
6. 对新 main、新模型或新预算另建 development smoke 和正式 study，使用仓库已有
   public_agent_eval.py / harbor_study_runner.py / 官方 verifier，不另写简化 Agent。
   正式同模型比较保留全部计划尝试、相同模型身份、输入/输出/请求/时间预算及三次重复。
   现有正式 measured-tokenizer 协议只资格验证本地模型；云端先完成独立协议与真实计量，
   不删除其资格检查，不把 openai smoke 当作正式配对结果。
7. 汇总全部 PASS/FAIL/ERROR/NOT_RUN，报告完整分母、用量缺失和全部失败历史。
   自测不得写成 AA 官方 Elo/排名；不发布 Release，不提交榜单/比赛表单。
   将脱敏日志、模型来源、源码 SHA、哈希清单和剩余限制提交到审查分支。
```
