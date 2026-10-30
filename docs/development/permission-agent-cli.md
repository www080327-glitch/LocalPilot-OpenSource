# 文件权限与外部 Agent 使用说明

最终本地构建：Desktop `5.0.0-beta.3-dev.11`，Core `5.0.0b12`，Suite `0.2.0b9`；Companion 仍为独立的 `0.5.6b2`。没有下载模型、修改稳定 tag 或推送。

## GUI 文件整理

1. 新建会话，选择日常文件路由 `desktop-file-agent-v1`（或已配置且具备所需工具能力的本地 Agent 路由）。旧 `deepseek-read` / `deepseek-approval` 是保留历史所需的验收路由。
2. 点「授权文件夹」→选择读取、整理或修改范围→用系统选择器选择确切目录。整理范围支持列目录、元数据、建目录、移动、重命名、安全复制，关闭 Shell。修改范围另允许文本补丁。
3. 云端披露独立选择。每行一个精确相对路径；`.` 只允许当前目录清单，文件内容与文件身份/校验元数据需要对应文件路径授权。移动/复制的源和目标路径都加入披露清单，可让云端看到完整的操作元数据。选择目录本身不授予云端披露。
4. 选择「帮我批准（高风险）」：确定 SAFE 自动、确定 UNCERTAIN 自动、RISKY 仍需人类审批。没有有效风险证据不等于 UNCERTAIN。所有硬限制先检查。
5. 在「证据」中分别查看任务验证与「文件位置与内容校验」。后者 PASS 是文件事实；通用任务语义验证可以仍为 not_run / unverified。
6. 「立即撤销此授权」立即阻止该 grant 的新调用；历史收据保留。应用升级改变实际执行主体时需重新选择目录。macOS 如重新询问 Desktop 访问，请自行核对系统提示；也可在「系统设置 → 隐私与安全性 → 文件与文件夹」检查实际 LocalPilot 执行主体。程序不会改写 TCC 数据库或申请整个 Home/磁盘的工具权限。

专用工具只处理目录内的普通文件（移动/复制上限 64 MiB），拒绝覆盖、越界、符号链接写入与多重硬链接。跨卷移动可能返回明确失败，不自动退化为复制后删除。undo 字段是带身份与版本的撤销信息，不是自动回滚许可。UNKNOWN 后不得重放。

## 安装与诊断

已有 `localpilot` 必须来自本轮 Suite；也可直接使用最终 APP 的离线 CLI：

```sh
LP_CLI="$HOME/Applications/LocalPilot.app/Contents/Resources/bundled-backends/localpilot"
LP_DATA="$HOME/.local/share/localpilot-desktop-e2e"
LP_PROJECT="/absolute/path/to/project"
"$LP_CLI" --home "$LP_DATA" integrations install codex --project "$LP_PROJECT"
"$LP_CLI" --home "$LP_DATA" integrations install dsh --project "$LP_PROJECT"
"$LP_CLI" --home "$LP_DATA" integrations doctor --project "$LP_PROJECT"
```

这里的历史数据目录名称含 e2e，目录没有被重新初始化；日常路由已与保留的 fixture 路由分离。其他安装请填自己的服务目录，不要照抄该目录。服务凭据保存在原服务和每宿主独立的私有凭据文件中，不进入项目或提示词。Operator / Provider 凭据不交给宿主 MCP 子进程。

安装仅配置项目 Skill/MCP，不授权目录。不覆盖已有同名 Server；其他 Server 保留。用户级安装必须显式指定 `--scope user --confirm-user`。不要用项目安装指向 Home 来间接修改全局配置。

由可信人类单独授权一个外部宿主的文件夹：

```sh
"$LP_CLI" --home "$LP_DATA" integrations authorize dsh \
  --project "$LP_PROJECT" --folder "/absolute/test-folder" \
  --access organize --permission-mode uncertain --model desktop-file-agent-v1 \
  --cloud-paths-json '[".","source.txt","sorted/source.txt","copy.txt"]' --confirmed
```

只读分析使用 `--access read --permission-mode safe`。这条管理命令使用独立 Operator 身份；普通 Codex/DSH 模型不得执行它来自行扩大权限。能力查询会返回已授权 Session，Parent 显式携带该 ID 提交。关闭/取消后的 Session 需要重新建立授权 Session，不得自动重放旧任务。

Codex 在可信项目中加载 `.agents/skills/localpilot-agent` 与 `.codex/config.toml`。本机 Headless 的只读能力查询成功，但实际 MCP submit 被宿主 `approval policy=never` 拒绝；需要人在允许审批的宿主里复验，不能换 Shell/HTTP/身份绕过该拒绝。

DSH 使用官方 MCP 客户端覆盖配置：

```sh
dsh headless --patch "$LP_PROJECT/.localpilot/dsh.patch.json" --json \
  '使用 localpilot-agent Skill，让 LocalPilot 整理已授权测试文件夹。'
```

DSH 的模型 Provider 凭据由其自己的可信启动方式提供，不写进 MCP 配置。当前安装版 DSH `0.2.1-rc.2` 已实际加载 Skill、调用 MCP 并执行文件工具。

`doctor` 检查身份认证、API、客户端作用域、Skill 版本、Adapter 与工具 schema；连接健康不等于宿主模型已获批准。真实宿主轨迹见验收报告。

卸载：`integrations uninstall HOST --project "$LP_PROJECT"`。仅删除未被编辑的安装器自有配置与 Skill；改过的内容保留并给出说明。服务器任务、原始客户端身份和目录授权有独立生命周期；卸载插件配置不冒充撤销这些服务端对象。

MCP 提供 stdio；HTTP 使用既有认证 Agent API 与 SSE。本轮没有新增 Streamable HTTP MCP 监听器。协议、所有权、审批及 UNKNOWN 规则见 `docs/architecture/subagent-contract.md`。
