> 2026-10-18 独立Companion补丁：可选稳定前缀/minimal纯推理、缓存35B的宿主生命周期、owner-only推理停止/心跳、resource-only例外票据。默认旧部署不自动启用managed模型。见[本轮合同/限制/证据](COMPANION_V044_CACHE_RESOURCE_REPORT.md)，OpenAPI已同步。原版下文保留历史语义。

# 独立部署与接入

服务包版本 `4.9.1rc2` 是候选包标识，不自动创建 Git tag。只需 Python 3.10+ 标准库；真实模型服务独立运行。`pyproject.toml` 提供 localpilot-service/localpilot-adapter 安装入口，OpenAPI 是 package data。无需安装 vLLM、下载模型或研究 Runtime 内部。

## 五步启动

1. 准备一个已有模型 API 的实际 model ID，以及独立 task workspace。服务 data/config/log 目录放在 workspace 外。
2. 在解压后的发行包根目录运行配置向导：

```bash
python3 -m localpilot_service.configure \
  --workspace /absolute/task-workspace \
  --directory ~/.local/share/localpilot-service \
  --base-url http://127.0.0.1:1234/v1 --model EXACT_MODEL_ID
```

向导独占创建 0600 service.json 和 clients.env，随机生成 codex/dsh/companion/http/operator 五个互异 token，不打印 token，不覆盖既有文件。模型提供方的 credential 不复制到此环境文件。若选择 DeepSeek，改用 `--deepseek-key-file /existing/private/deepseek.key --model deepseek-flash`；默认 cloud REQUIRES_APPROVAL。

3. 在自己的 trusted terminal 加载客户端环境与启动服务：

```bash
source ~/.local/share/localpilot-service/clients.env
python3 -m localpilot_service --config ~/.local/share/localpilot-service/service.json --check
python3 -m localpilot_service --config ~/.local/share/localpilot-service/service.json
```

check 校验服务配置/已存 checkpoint，不执行推理。健康 status=ready 表示 listener/Runtime 可用，model_health=NOT_PROBED；不等于模型已通过能力验证。可选在独立虚拟环境 `pip install .` 后使用 `localpilot-service --config ...`；打包构建不需要原生编译。不要把 clients.env 发给调用模型，分别只传入所需普通客户端 token。

4. 普通 HTTP 客户端提交：

```bash
export LOCALPILOT_TOKEN="$LOCALPILOT_HTTP_TOKEN"
curl --noproxy '*' -sS http://127.0.0.1:8765/healthz \
  -H "Authorization: Bearer $LOCALPILOT_TOKEN"
curl --noproxy '*' -sS http://127.0.0.1:8765/localpilot/v1/tasks \
  -H "Authorization: Bearer $LOCALPILOT_TOKEN" -H 'Content-Type: application/json' \
  -H 'Idempotency-Key: inspect-readme-001' \
  -d '{"input":"Read README.md and explain it","timeout_seconds":300}'
```

保存返回 ID。GET 同 task、读取 native SSE、显式 cancel；不要重新提交新键来查询进度。不同目标使用新键。OpenAI Responses/Chat 同样需要 Idempotency-Key 并检查 localpilot 状态。

5. 遇到审批时由独立 operator terminal 查询与操作：

```bash
python3 -m examples.service_operator resp_TASK_ID approve
```

它展示当前 ticket 与 scope，再等本人输入 yes。普通 token、Skill 和模型输出不能批准；UNKNOWN 的 continue/resume 仍拒绝。先 cancel/drain 或等待 worker yield 再停止服务。Ctrl-C/SIGTERM 只处理本服务：yielded 状态用原 suspend 保存；in-flight 状态无法安全 suspend 时按原 shutdown 取消并 drain。未对正在执行的系统操作提供强杀/撤销保证。

## Python / JavaScript / GUI / Companion

```python
import os
from localpilot_service.sdk import Client
c = Client(token=os.environ["LOCALPILOT_TOKEN"])
t = c.submit("Read README.md", idempotency_key="readme-001")
for event in c.events(t["id"]):
    print(event)
result = c.status(t["id"])
print(result["status"], result["verification_summary"])
```

`examples/service_client.mjs` 是可运行 Node fetch 示例；`service_client.ts` 是无依赖 typed client 示例，Node 18+/native bridge 使用，浏览器 Origin 默认拒绝。`python3 -m examples.service_gui` 提供 Tk 原生 Submit/Status/Cancel；不存 token 到浏览器。`python3 -m examples.service_companion "message" --key EVENT_KEY --session sess_ID` 展示独立 Companion 调用；--events/--status/--cancel/--recover 对应观察与交还。它们不实现后台消息监听或 Companion 模型路由。

## Codex Skill / Adapter

将完整 `localpilot-agent/` 放入调用项目的 `.agents/skills/localpilot-agent/`。Codex 本地 Skill 发现与 stdio/env_vars 配置来源：[官方 Skill 文档](https://learn.chatgpt.com/docs/build-skills)、[官方 MCP 文档](https://learn.chatgpt.com/docs/extend/mcp?surface=cli)。

给调用客户端的 adapter 环境仅配置 LOCALPILOT_URL 与该客户端 LOCALPILOT_TOKEN。可在自己的 Codex MCP 配置添加以下模板，将绝对路径换成安装位置：

```toml
[mcp_servers.localpilot]
command = "python3"
args = ["/absolute/localpilot-agent/scripts/localpilot_adapter.py", "--mcp"]
env_vars = ["LOCALPILOT_URL", "LOCALPILOT_TOKEN"]
```

不要在 TOML 写入真实 token。MCP 宿主仍有自身工具审批策略；此轮 Codex 非交互 MCP submit 被宿主审批拒绝，不能称这条路径真实通过。已验证的 Codex 路径使用 Skill 自带 HTTP CLI：

```bash
python3 /absolute/localpilot-agent/scripts/localpilot_adapter.py localpilot_submit \
  --arguments '{"input":"Read README.md","idempotency_key":"codex-read-001"}'
python3 /absolute/localpilot-agent/scripts/localpilot_adapter.py localpilot_status \
  --arguments '{"task_id":"resp_TASK_ID"}'
```

宿主的沙盒需允许连接该服务。真实 Codex 测试使用独立临时 caller workspace 的 workspace-write/network_access=true，并且服务端 token/route 强制 read-only，写入、execute 和 operator control 均不可用；没有修改用户已有 Codex 配置或进程。一般业务按自己的宿主审批/沙盒规则配置，不因 Skill 而扩大权限。

## DSH Skill / MCP

同一 Skill 可放在调用项目 `.agents/skills/localpilot-agent`；本机 DSH filesystem provider 已验证支持这一路径。提供一个项目 extra patch，而不是改用户已有 profile：

```yaml
- insert:
    - id: localpilot-mcp
      name: '@deepseek-ai/dsh-mcp-client'
      config:
        transport: stdio
        serverName: localpilot
        command: python3
        args: [/absolute/localpilot-agent/scripts/localpilot_adapter.py, --mcp]
        env:
          LOCALPILOT_URL: !!js process.env.LOCALPILOT_URL
          LOCALPILOT_TOKEN: !!js process.env.LOCALPILOT_TOKEN
        failOnStartupError: true
```

`dsh headless --patch /absolute/localpilot.patch.yml "Use localpilot-agent to inspect the service workspace"`。插件只桥接四个 MCP 工具；服务端仍执行权限。此轮安装的 DSH headless+Skill+MCP+cloud+trusted verifier 真实通过。DSH shell/MCP subprocess 会 scrub parent env，故通过 patch 显式转发两个服务变量；不转发 provider credentials。

## 状态、诊断、备份与版本

通过 authenticated /healthz 查服务，/model-registry 查配置模型；audit.jsonl 只存时间/主体/request/task/action/route/status/error_code，不存输入文本、Bearer token 或 provider 密钥。模型 wire 原始证据仅由受控验收 driver 针对公开 fixture 单独采集，业务默认不采集。

401 检查普通 token 是否属于该服务；403 检查 scope/Origin/operator binding；404 检查客户端身份和 route map；409 先查同 Task 的票据/UNKNOWN/Session head，勿重新执行；429 降低客户端调用频率/并发；provider failed 先修 Backend 连接，不把失败归为 completed。配置和数据库 fingerprint 不匹配需要显式迁移，禁止自动改权限、Backend 或预算恢复。

```bash
python3 -m localpilot_service.backup backup /private/data/runtime.sqlite3 /new/private/backup.sqlite3
python3 -m localpilot_service.backup restore /private/backup.sqlite3 /new/private/data/runtime.sqlite3
```

backup 用 SQLite snapshot API，包含 journal/checkpoint/owner subject 与收据，保留原数据库；restore 仅写不存在的目标，拒绝 symlink 和非私有源。恢复前停止对应服务并保存精确配置、版本、workspace 文件/版本和凭据引用。环境凭据不包含在 DB backup；workspace 文件需另行备份，否则版本绑定不能恢复。不要手工只复制 WAL 主文件或覆盖正在使用的 DB。

只监听 loopback。远程接入可通过显式 SSH port forwarding 的加密隧道，或由可信部署维护的 TLS reverse proxy 转发到 loopback；每个请求仍验证客户端 token，不信任 X-Forwarded identity，保留 Origin 拒绝规则。不能直接 bind 0.0.0.0，不开放 CORS，不向客户端暴露模型推理/管理端点。

## 运行检查

`python3 -m unittest tests.test_agent_service tests.test_service_contracts -v` 为轻量新合同控制；全量、strict、stabilization 与真实 Harness driver 见 release report。省电期间没有本地模型推理、GPU/Metal、原生构建或压力测试。发布候选的最终准入必须读实测矩阵，不能只看配置/健康或打包成功。
