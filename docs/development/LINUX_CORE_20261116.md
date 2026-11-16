# Linux Core：宿主 Shell、验收进程与真实 CPU 模型

日期：2026-11-16（Asia/Shanghai）。基线为 `0cc99d57990e81302b941b6f5a160093dd298d4b`。

## 本轮实现

Linux 原先在 `agent.host_tools.shell` 入口直接被拒绝。现在复用既有工具注册、Permission Gateway、进程组取消、Task、SQLite 与 UNKNOWN 收据，按当前授权选择执行方式：

| 授权 | Linux 执行 |
| --- | --- |
| `isolated` | Bubblewrap 将宿主文件系统只读挂载；不能升级到 Full。读权限与网络语义保持既有合同。 |
| `workspace` | 宿主文件系统只读，工作区及既有 OS 临时目录可写；符号链接不能让只读挂载变成可写。 |
| `request` | 仍由现有 Gateway 对具体 Shell 命令审批；获准命令使用当前 OS 用户权限。 |
| `full` 或已批准的 Full scope | 当前 OS 用户直接执行；不要求 Bubblewrap，也没有额外的 APP 审批层。 |

受限 Shell 需要支持 `--disable-userns` 的 `bwrap`、Linux 用户/挂载/PID namespace，以及系统允许创建这些 namespace。没有这些条件时返回实际错误，不回退为无约束 Shell。网络仍按现有文件权限合同可用；“只读”并不代表断网。收据中的 `network: available` 描述工具合同，不证明互联网或 DNS 可达。

Bubblewrap 为受限命令创建独立 PID namespace；取消复用现有进程组终止与等待逻辑。测试实际启动 `sleep` 后取消并等待所有子进程退出。已经发生的写入仍保留，取消后的收据仍是 UNKNOWN，重启不会自动重放。

`localpilot-core doctor` 新增 `host_shell`：区分后端名、启动程序是否存在和 `scoped_execution: NOT_PROBED`。仅找到可执行文件不冒充当前内核允许沙箱运行。

## Linux 宿主断言

`HostPythonAcceptance` 已增加 Linux 启动器。它使用 `unshare --user --map-root-user --net` 创建不配置 loopback 的网络 namespace，再通过 Bubblewrap 仅只读开放 Python 运行库、指定工作区和断言文件。运行仍使用 `-I -B`、最小环境、既有超时及输出限制。断言文本、预期答案和子进程输出不进入 Agent 反馈。

选择不配置 loopback 是实际环境约束的结果：此处 Bubblewrap 自己的 `--unshare-net` 在创建 `NETLINK_ROUTE` socket 时被宿主拒绝，而 util-linux 新建网络 namespace 可以工作。验证实际检查了无法连接宿主 loopback 服务、无法读取未挂载的同级宿主文件、无法改写工作区和断言。没有取消网络隔离要求。

依赖为系统 Bubblewrap 与 util-linux；本轮实测版本分别是 **0.12.0** 和 **2.41.5**，Debian 13.6、Linux 6.18.57、x86_64、CPython 3.12.14。这里的结果不代替其他发行版的 native desktop、Wayland 或 GPU 验收。

## 硬件与生命周期

- Linux CPU 名称从 `/proc/cpuinfo` 获取，内存使用既有 psutil，DMI 不可用时明确返回 Linux host；不把 CPU 检测当作 GPU/加速资格。
- `external_power()` 保留 psutil 的实际电池状态优先级，并补充 sysfs 的系统级 Mains/USB 供电观测；外设自身充电不算整机 AC，缺少可观察电源仍是 UNKNOWN。
- Linux Core 继续使用既有 detached 服务，不暗中注册开机启动。`service-unregister` 原来错误调用 `/bin/launchctl`，现在返回 detached 未注册状态；Linux 配置显式 `launchd` 时给出明确平台错误。
- Shell 的历史工具描述与 Full 权限固定提示保持原文，以保留已存 Session 的严格配置指纹与 V5 固定系统指令。Linux 实际平台、Bash、Bubblewrap 和当前权限说明写入当前 Host state；通过既有 `qualified_shell` 核验实际注册函数，给任意同名工具配置 scope policy 也不会附加宿主权限声明。V5 只在请求视图中附加这项数据；非 V5 的 `service_cache_stable_prefix` 模式继续按既有合同保存完整已批准的请求快照，包含当时的 Linux 事实，冻结系统指令与配置指纹不变。

## 验证记录

Core 全量命令：

```bash
.venv/bin/python -m unittest discover -s tests -t . -v
```

首次 Core 全量为 **1539 项：1444 PASS、95 SKIP、0 FAIL、0 ERROR**（144.343 秒）。未发现 `ResourceWarning`。其中新增 13 项，并使既有适用于 POSIX 的 Shell/断言测试在实际 Linux 上运行；macOS 专用的无效标志等测试仍显式跳过。SDK、Harbor、安装环境、真实模型和未公开的历史 benchmark 等分组仍按各自条件记录，不把 SKIP 当作通过。

定向 90 项为 **89 PASS、1 macOS SKIP**。另有实际 Core 子进程 → HTTP → Bubblewrap Shell → SQLite 的取消/重开测试：先执行真实写入，再取消长命令，验证 UNKNOWN 收据、同一个 task/session 与原文件内容在重启及同幂等键重提后保留。该新测试首次作者运行使用了错误的摘要字段名，产生 1 ERROR；改为现有 `unknown_effects` 后通过，旧失败日志保留。

### 真实历史版本兼容

从固定 PR9 `0a7fdff36f45a471130293b508b5d008f40cecf9` 实际生成 Desktop SQLite 会话及已完成对话，再由当前源码恢复，覆盖五档本地/云端政策。逐项核对原配置指纹、历史消息、固定系统指令，显式调用 `_refresh_prompt()` 后继续请求，并确认 Linux 指导只进入当前 Host state。修改宿主 read capability 仍被严格拒绝；没有忽略字段、改写旧指纹或放宽恢复门槛。模型生成在该兼容测试中使用明确的 transport fixture，服务发现使用真实 loopback HTTP；真实推理由独立资格程序验证。

与实际 PR1 Skill 迁移及任意同名 Shell 的负例合跑，共 **4 PASS、0 SKIP**（5.087 秒），日志 `core/real-legacy-migration-r4.log`。先前失败均保留：r1 发现 Linux 改写历史 Shell 描述造成真实指纹回归；r2 新测试忘记显式提供 TaskRequest route；r3 新测试未启动本地健康检查 fixture，且负例最初断言了包装前的异常文本。后两次是新增测试夹具错误，修正后执行完整流程，没有降低断言。

随后全量回归发现新条件对未设置宿主 scope 的子 Agent 使用了 `None.get`，导致 51 FAIL、14 ERROR（`core/core-full-r2.log`）。修复可选值后，中间全量为 **1541 项：1448 PASS、93 SKIP**（162.112 秒，`core/core-full-r3.log`）。独立复查又确认：仅检查 scope policy 不足以识别宿主 Shell；同名自定义工具必须被排除。最终改用现有 `qualified_shell`，覆盖不存在、显式 None、有 scope 但非宿主实现三种负例，并保留非 V5 缓存快照语义。新增缓存测试最初把 JSON 内嵌文本误当外层未转义文本，r6 的 1 FAIL 保留；现改为核对实际保存的完整消息与请求快照一致。

最终定向 **59 PASS、0 SKIP**（11.638 秒，`core/real-legacy-migration-r7.log`），包括实际历史恢复、所有异步子任务测试、既有缓存前缀测试及新增的 legacy 恢复负例。独立复查在 `companion/core-compat-review-r2.json` 复验相同生产源码，并另外运行实际 PR9 五档恢复/继续/权限变更拒绝测试通过；源码哈希见 `core/core-final-source-files.json`。

**最终冻结源码全量：1542 项，1449 PASS、93 SKIP、0 FAIL、0 ERROR**（160.806 秒，`core/core-full-r4.log`）。该轮同时设置实际 PR1、PR9 checkout，启用原先因缺少历史源码而跳过的恢复测试；新增测试也包括在总数中。未出现 `ResourceWarning`，15 个生产/资格程序/测试文件的哈希在全量与真实模型运行期间未变。最终命令为：

```bash
LOCALPILOT_PR9_SOURCE=/absolute/path/to/pinned-pr9 \
LOCALPILOT_LEGACY_SOURCE=/absolute/path/to/pinned-pr1 \
.venv/bin/python -W error::ResourceWarning -m unittest discover -s tests -t . -v
```

独立的 `scripts/qualify_linux_model.py` 用已经核验的本地 GGUF 和新建的自有 llama.cpp 进程执行真实推理。它不下载权重，不连接其他模型服务，不使用云密钥，不替换默认模型。新 evidence 目录必须不存在；它保存完整原始 task/usage、CPU 提供方日志、缓存 save/restore 和每项 PASS/FAIL/ERROR/BLOCKED。此程序是产品集成检查，不是公开能力榜单。

```bash
.venv/bin/python scripts/qualify_linux_model.py \
  --server-binary /absolute/path/to/llama-server \
  --model /absolute/path/to/reviewed-model.gguf \
  --model-sha256 REVIEWED_SHA256 \
  --model-revision REVIEWED_HUB_REVISION \
  --server-commit REVIEWED_LLAMA_CPP_COMMIT \
  --evidence /absolute/path/to/new-evidence-directory
```

冷/热/提供方进程重启后的 KV 检查固定使用实际系统提示及已有 `localpilot-agent/SKILL.md`。cache 命中只根据提供方真实 `cached_tokens` 与槽保存/恢复数据判断；不保证所有后端、模板和模型可永久复用。主/子 Agent 即便都调用成功，也只代表本次一个本地模型的父子任务，不等于不同模型或云端协作通过。

## 本轮真实 CPU 结果

使用官方 Qwen2.5-0.5B-Instruct GGUF（Q5_K_M），revision `9217f5db79a29953eb74d5343926648285ec7e67`，权重 SHA256 `041474553fcabfc2a2d67903f9d2c2e50bd92528e670da4f33b5d0ce6e59fd55`。llama.cpp 官方 build 12359，commit `b1b770d90d94cad9e9ea5b993bdbc383a522fb28`；CPU、2 threads、8192 context、单 slot。它是用于验证 Linux 路径的小模型，不是拟参赛的主模型。

第二轮结果为 **9 项：5 PASS、4 FAIL、0 ERROR**，总案例时间 234.414 秒。第一次资格脚本以 50 ms 轮询触发 Core 既有每分钟 120 请求限制，5 项 ERROR；轮询改为 1 秒后重跑，不修改产品限额，第一次结果和模型失败均保留。

| 案例 | 结果 | 实际含义 |
| --- | --- | --- |
| 固定提示与 Skill KV | PASS | 1257 prompt tokens，cold cached=0，hot cached=1256，提供方进程重启并显式恢复后 cached=1256；槽实际保存/恢复 1258 tokens。 |
| 提供方算术 | PASS | 真实回答 `56`，提供方报告 43 input / 3 output tokens。 |
| Core 文件问答 | FAIL | 真实 `read_file` 返回完整文件，但模型最终答案没有引用要求的内容。 |
| Core Shell 完整任务 | FAIL | 真实运行 Shell 三次，模型未正确完成读回，最后任务 `incomplete`。 |
| Core 子 Agent | FAIL | 实际调用 `delegate`，子 Agent 有 1 次真实模型请求，但没有读文件，最终答案未包含事实。只能确认真实调用发生。 |
| Core 流式取消与 SSE | PASS | 实际 TextDelta 后取消、Core 达到 cancelled/quiescent；无效 cursor 返回 HTTP 409。提供方当时仍有 processing slot，不能把 Core 停止写成提供方计算立即停止。 |
| Shell UNKNOWN 与重开 | PASS | 模型实际执行 append+sleep；取消保留 1 个 UNKNOWN effect；Core 重启与同幂等键重提保留相同任务、收据和只写一次的文件。 |
| Companion 轻聊 | PASS | 真实 local-http 后端回答 `56`，提供方报告 191 input / 3 output tokens。 |
| Companion 委派文件问答 | FAIL | Companion Task API 和 Core 通路运行，模型没有调用读取工具，却声称读完；独立 oracle 判失败。 |

文件问答中的 `completed` 只描述执行终态，原始 Core 结果仍是 `task_outcome: unverified`、`task_succeeded: false`，没有被当成质量通过。原始任务保存真实模型调用次数、token、缓存命中和父子关系；取消中的不完整提供方 usage 仍保留未知。

兼容修复期间第三轮原始结果为 6 PASS、3 FAIL；逐条复查发现 Shell oracle 仅核对了文件创建和执行终态，却未要求任务中指定的 `read_file` 及答案。该轮模型只运行 Shell，随后虚构读回，因此原始 Shell PASS 被独立复核为 FAIL，实际质量计数仍是 5 PASS、4 FAIL。原 JSON 不改写，纠正记录保留在 `core/real-model-r3-review.json`。最终脚本明确要求对 `computed.txt` 的成功读取收据与包含 `7319` 的答案，模型、任务、生成参数与预算均未调整。

**最终源码第四轮：9 项，5 PASS、4 FAIL、0 ERROR，194.171 秒**（`real-model/qualification-r4/RESULTS.json`）。KV、提供方算术、流式取消/HTTP 409、Shell UNKNOWN/重开/幂等与 Companion 轻聊通过；文件最终答案、Shell 读回、子 Agent 事实答案与 Companion 委派答案失败。Shell 此次正确生成 `7319`，但未调用 `read_file`，并虚构已读回；执行终态为 completed 不会让完整任务通过。子 Agent 确有 1 次真实推理、0 次工具调用；不把模型声称读过文件当作证据。冷/热/重启 KV 命中仍为 0/1256/1256，保存和恢复 1258 tokens。流取消后 Core 已静止，但即时提供方 slot 仍显示 processing，因此计算停止时间仍未确认。

KV 项是资格脚本显式调用自有 llama.cpp 的 save/restore。它没有证明 LocalPilot 对所有 unmanaged HTTP 提供方自动保存 KV。原模型、原服务和旧评测队列均未触碰；资格程序各轮自有的 Core 与 llama.cpp 进程均已退出。没有云调用，本地 API 费用为 $0，能源未测量。

## 独立训练代码复查

复查 `portable_training`、`torch_training_worker`、`reviewed_data`、`evaluation` 时，实际复现了 PEFT 0.18.1 的接口错误：`target_modules='all-linear'` 不能和非空 `layers_to_transform` 同用，原测试的 `layers=-1` 没有覆盖默认的分层 LoRA。已将指定层数时的目标改为模型真实 Linear/Conv1D 模块的后缀名称，由 PEFT 应用层索引；`layers=-1` 和全参数训练的行为保留。

新增真实 CPU 的 `layers=1` 训练，验证二层 Qwen 小模型只有最后一个 Transformer block 生成 14 个 LoRA 矩阵，B 矩阵实际更新，基座权重哈希不变。固定训练环境中的全套 5 项测试通过（18.271 秒），覆盖适配器重载、全参数 embedding/head 更新、标签掩码和拒绝不可用 CUDA。原接口错误与修复后日志分别保留。该随机初始化测试模型只验证训练实现，不代表用户数据训练或产品质量提升。

## 上游依据

- [Bubblewrap 官方说明](https://github.com/containers/bubblewrap/blob/main/README.md)：隔离效果取决于明确传入的 namespace 与挂载参数。
- [util-linux unshare 官方手册](https://kernel.googlesource.com/pub/scm/utils/util-linux/util-linux/+/master/sys-utils/unshare.1.adoc)：用户和网络 namespace。
- [Linux 电源 sysfs ABI](https://github.com/torvalds/linux/blob/master/Documentation/ABI/testing/sysfs-class-power)：type、scope 与 online。
- [本轮固定 llama.cpp Server 文档](https://github.com/ggml-org/llama.cpp/blob/b1b770d90d94cad9e9ea5b993bdbc383a522fb28/tools/server/README.md)：OpenAI 兼容响应、真实 usage、槽缓存 save/restore。
- [PEFT LoRA 官方参数说明](https://huggingface.co/docs/peft/package_reference/lora)：目标模块与指定 Transformer 层。
