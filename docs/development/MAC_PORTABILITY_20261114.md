# macOS 测试应用安装、Intel 接入与缓存核对

基线：公开 PR #1 的 `94e0e6ff2c8da974d20530d7a0faa50844d052f4`。
本轮修改在 Linux x86_64 / Python 3.12.14 上验证。下述 PASS 是源码和临时文件系统回归，不是原生 macOS APP 安装、Intel 真机或真实模型资格。

## 已修复的具体问题

1. `desktop/scripts/install-local-app.py` 原来只接受日常 Bundle ID。新增显式 `--test-app`，只接受 `io.localpilot.desktop.test`，安装目标固定为 `~/Applications/LocalPilot Test.app`，测试归档独立保存。默认日常身份和目标不变，不能用测试身份替换日常应用。
2. 原安装器在 `stage → target` 后验签失败时，因目标已经存在而不会恢复旧 APP；LaunchServices 注册失败也在原回滚范围之外。现在这两种失败均保留失败候选到 Trash，再将旧 bundle 还原。首次安装失败则还原为目标不存在。失败状态、回滚结果和保留路径可以写入独立 receipt。
3. 升级仍调用 Suite 既有 `archive()`，实际解压比对树摘要；同时检查其返回的验签退出码。提供 `--plan` 将执行绑定到此前 dry-run 的源、目标、身份与新旧树摘要，实际复制后的 stage 也必须与计划摘要一致。不会自动清理备份、任务或用户数据。
4. `package-release.py` 原来把任意 bundle 在 DMG 内改名成 `LocalPilot.app`。现在保留源 bundle 名称和对应卷名，隔离测试包内为 `LocalPilot Test.app`。DMG 原生重建仍为 NOT_RUN。
5. `hardware.py` 原来把 x86_64 报成 Unknown，且 import 时直接执行 macOS 专用程序。现在保留真实架构、识别 Intel Processor Name，设备查询失败可以返回未知；没有通过 CPU 名称推断 MPS 可用性。
6. `suite/localpilot_suite/product_control.py` 原来把 Intel 的 `deferred` 推荐结果当作实际模型访问 `r['model']`，会触发 KeyError。现在返回 `recommendation: null` 与独立 `recommendation_status`，明确可使用既有 `local-openai` 端点；不会给 Intel 推荐 MLX 权重。

## 实际验证

```bash
python -m unittest tests.test_pa_macos_install tests.test_pa_macos_hardware tests.test_recommender -v
```

结果：32 项 PASS，0 FAIL，0 ERROR，0 SKIP。

安装测试使用真实临时 bundle、真实文件复制/重命名、Info.plist 与树摘要。codesign、ditto 与 LaunchServices 的 macOS 命令边界被替代，因此不能据此认定签名/Gatekeeper/原生安装通过。测试覆盖隔离身份、日常应用字节不变、首次安装、旧 bundle 保留、替换后验签失败、注册失败回滚、回滚归档验签拒绝以及计划和 receipt 的完整性。

Intel 测试运行真实硬件解析、推荐器和 Suite hardware 控制器，并通过已有 Core CLI 在临时目录生成 `local-openai` 配置；没有发送模型请求，没有下载或启动任何权重。`model_health` 保持 `NOT_PROBED`。

## Mac Work：测试身份安装与恢复

先读取这次 PR 的实际 HEAD 和 `desktop/AGENTS.md`，在隔离工作树构建新 APP，核对 `io.localpilot.desktop.test` / `LocalPilot Test`。确认进程、模型服务、可用磁盘和已有引用；仅退出测试 APP 与其明确拥有的服务，保留日常安装和外部 oMLX。

从仓库根目录执行以下模式。`CANDIDATE` 必须是新生成、验签通过的 `LocalPilot Test.app`，`RUN` 是新的本机证据目录；不要使用这两个占位符作为实际路径。

```bash
python desktop/scripts/install-local-app.py \
  --source "$CANDIDATE" --test-app \
  --receipt "$RUN/install-plan.json"

python desktop/scripts/install-local-app.py \
  --source "$CANDIDATE" --test-app --execute \
  --plan "$RUN/install-plan.json" \
  --receipt "$RUN/install-result.json"
```

检查源/目标 Bundle ID、`codesign --verify --deep --strict`、实际安装路径、首次启动向导、已有隔离配置恢复和独立任务执行。测试安装不会修改日常 `~/Applications/LocalPilot.app`，分别记录安装前后的树摘要核对。

升级验收使用第二个已验证、独立构建的测试 bundle，按同样流程生成新 plan/receipt。检查 `rollback_archive` 真正解压后与升级前摘要一致、旧 bundle 位于 Trash。仅对测试槽做一次故障注入，验证替换后的验签失败和注册失败确实恢复旧 APP；异常发生后读 receipt 与原始错误，不能重复执行未确认状态的升级。

手动恢复时，将 receipt 指向的 rollback ZIP 用 macOS `ditto -x -k` 解到一个全新的独立目录，核验树摘要和签名，再把还原的测试 APP 作为 `--source` 运行相同 dry-run/execute 流程。不要移动或删除日常 APP、模型目录、收据或用户数据库。

原生安装、真实失败注入、GUI 重开、任务恢复、系统权限与 Gatekeeper 结果分别记录 PASS/FAIL/NOT_RUN；当前均 NOT_RUN。发布、合并与替换日常应用不属于本次验证动作。

## Intel 路径与当前边界

Core 的 `local-openai` 已通过 OpenAI-compatible HTTP 接入本地推理服务，不依赖 MLX 或 PyTorch MPS。Intel 的近期可运行路线是复用 CPU 本地服务；可用的 Metal 加速由该服务真实探测，不能按“Intel”或“Mac”推断。

在 Intel 设备或其隔离测试环境里，先准备一个已核实可运行的本机服务和适配的量化模型；复用已下载权重，资源不足时不要盲目下载 35B。使用真实服务返回的 model ID 和 loopback URL，创建新 Core 配置，例如：

```bash
python -m localpilot_service.cli --home "$TEST_CORE_HOME" --json init \
  --workspace "$TEST_WORKSPACE" --model "$MODEL_ID" --base-url "$MODEL_BASE_URL"
```

随后按既有 `doctor → start → models → task` 流程验证文本、工具调用、长上下文、取消和重启，观察实际延迟/吞吐；配置成功不代表模型在线或工具能力合格。

Apple 的当前 PyTorch MPS 页面列出 Apple silicon 要求；PyTorch 用 `is_built()` 与 `is_available()` 区分构建能力和运行时可用性。因此本轮字段是 `mps_availability: NOT_PROBED`，没有引入 torch 作为产品依赖。llama.cpp 官方构建包含 Intel macOS CPU 配置，能够作为后续独立推理服务方案的依据，尚未打入 LocalPilot。

- Apple 官方说明：https://developer.apple.com/metal/pytorch/
- PyTorch 后端探测说明：https://docs.pytorch.org/docs/stable/backends.html
- llama.cpp 官方构建矩阵：https://github.com/ggml-org/llama.cpp/blob/master/.github/workflows/release.yml

目前完整 APP 的构建脚本、部分 cp314 wheel 锁、Node 资源准备和 PKG 仍固定 arm64。没有把它们改成名义上的 universal2；Intel 原生发行物必须逐个核验 Python/扩展/Node/GUI/helper 的实际架构及源码来源，然后在 Intel 真机运行。当前状态：Core HTTP 配置路径通过；Intel 模型推理、GUI、原生辅助功能与整包安装 NOT_RUN。

## KV 与 50 GiB：读码结论

以下是基线实现事实，不能称为“永久 KV 已保证”：

| 位置 | 已有行为 | 未证明的内容 |
|---|---|---|
| `agent/session.py`、V5 context | 稳定指令前缀、工具顺序与动态状态投影；provider usage 单独记账 | 任意 provider 都保存 KV、固定前缀永不失效 |
| `localpilot_service/cached_omlx.py` | 单个受管模型启动参数指定 `prefix-cache`、SSD 最大 `2GB`、hot cache `128MB` | 全项目 50 GiB 总额度；固定 Skills 跨服务重启必命中 |
| `suite/localpilot_suite/product_installer.py` | 新建 oMLX 设置为 SSD cache `8GB` | 外部已有服务遵守此设置；全部缓存统一归属与配额 |
| `suite/localpilot_suite/product_control.py` | 常用模型缓存只是 preference，返回不支持逐模型控制的说明 | 设置偏好等于实际预计算/固定/持久缓存 |
| `companion/model/worker.py` | 每次请求 `make_prompt_cache(model)`，明确 `fresh_per_request` | Companion 小模型已有跨请求永久 KV |
| `localpilot_plugins/skills.py` | 显式审核的 SKILL.md/manifest、依赖加载，按需 `load` | 所有技能自动成为静态前缀或已经被模型使用 |

Work 验收固定 prompt/工具/Skills 的同一 tokenizer、模型 revision、量化和推理后端：记录冷请求、第二次相同前缀、变更尾部、卸载再加载、服务重启、变更 Skill 各情况下的 provider cache hit/miss/输入 token、TTFT、正确性和缓存目录体积。没有 provider 计数的项目记 UNKNOWN。跨模型 KV 不可直接复用；prefix 改变后的失效应与实际 token 前缀一致。不要为追求命中率把时间、观察文本、会话标识放入固定前缀，也不要把低命中原因直接归罪模型质量。

50 GiB 受管额度必须只覆盖明确属于 LocalPilot 的可重建缓存。模型权重、用户记忆、任务/UNKNOWN 收据、凭据、备份和外部 oMLX 缓存不应被静默纳入删除对象。本轮没有修改这些目录或声称总预算已实现。
