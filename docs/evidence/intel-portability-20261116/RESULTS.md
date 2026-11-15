# Intel 优先适配与 Linux 服务验证

日期：**2026-11-16（Asia/Shanghai）**。环境：Linux x86_64、Python 3.12.14。基线：PR #11 的 **`47e39faf3e97fbd13a562a9ec74efa30dfcc7b42`**。本轮源码从该提交继续，包含之前 PR #1/#9/#10/#11 的祖先工作；用户已授权同步到 `main`。这里记录实际测试和限制，不把源码合入当作新的 Release 或 Intel 原生验收。

当前组件：Desktop 5.0.1-rc.7、Core **5.0.0b22**、Suite **0.2.0b27**、Companion **0.5.7b4**、Channels 0.1.0a3。历史 evidence、旧 534 队列和 PR #11 的签名/隐私说明修复均保留。

## 结果

**可在当前环境完成的源码、真实 HTTP/子进程/SQLite 和安装态检查已经完成。Intel 物理机、macOS 原生构建及真实模型能力尚未验证。**

| 项目 | 本轮最终结果 | 范围 |
| --- | --- | --- |
| Core 全量 | **1416 PASS、110 SKIP、0 FAIL、0 ERROR / 1526**；218.368 秒 | 当前源码；提供 PR #1 / PR #9 兼容基线 |
| Companion 全量 | **654 PASS、25 SKIP、0 FAIL、0 ERROR / 679**；42.438 秒 | 含实际 Core/HTTP 委派、文件读取、取消与 SQLite 恢复 |
| Suite 全量 | **111 PASS、1 SKIP、0 FAIL、0 ERROR / 112**；54.653 秒 | 首次设置、端点保存/激活、历史保持、升级回滚及备份 |
| OpenAI SDK 独立环境 | **42 PASS**；4.058 秒 | SDK 3.51.0，与实际 Core HTTP 交互 |
| Harbor 固定环境 | **72 PASS、4 SKIP / 76**；27.714 秒 | Harbor 0.26.0，固定源码 `ec6aeab7fe0eb51df52b4e72c524daf5ea9cc5f4`；没有运行正式模型 study |
| 已安装 Suite/Channels | **12 PASS**；9.882 秒 | 仓库之外使用真实新 wheel，进程启动、SIGINT/SIGTERM、重开、SQLite、失败诊断 |
| 前端 Vitest | **72 PASS / 13 文件** | 包含端点配置组件 |
| TypeScript / Vite | **PASS** | 生产构建和新增 Intel UI 夹具独立类型检查 |
| 原生资源生成器 | **9 PASS** | wheel ABI/架构/系统版本、来源、锁、许可证与 RECORD |
| Playwright | **执行 BLOCKED；最终收集 38 项** | 指定浏览器未安装、CDN 安装失败、系统 Chromium 被容器拒绝 Unix socket；不是 38 PASS |
| 四个真实组件 wheel | **PASS，257 个 Python 文件与源码一致** | 无重复 Python 所有权、实际许可证、Swift 资源、仓库外导入与文件工具 |
| README 快速安装 | **PASS** | 全新环境执行 `pip install . ./companion ./suite`，再实际启动、提问、读文件、停止/重开；另验证四 wheel 安装环境 |
| Intel 官方依赖材料 | **35 份哈希通过；33 个兼容 wheel、2 个源码包** | 总 11,831,279 字节；两项待 Intel 原生编译；完整 Intel 锁没有生成 |
| 版本一致性、文档与历史字节、diff | **PASS** | 当前组件标识、文档链接、既有不可变归档和空白检查 |
| Rust / Swift / Intel APP / 原生音轨 | **NOT_RUN** | 当前环境缺少对应编译工具、macOS 与 Intel 设备；不能套用旧 Mac 结果 |

各组包含重叠用例，不能将所有 PASS 数相加当作唯一总数。Core 的 110 SKIP 中，42 个 SDK、17 个 Harbor 和 12 个安装态用例已在相应独立环境补跑；其余为 20 个 macOS 原生、4 个真实模型和 15 个缺失历史研究材料的测试或模块。Companion 的 25 SKIP 为 macOS 原生范围，Suite 的 1 SKIP 需要 macOS 安装环境。跳过仍保留在原始全量报告中。

## 本轮修复与真实执行

### Intel / Linux 入口

- 修复非 Apple Silicon 被 MLX 推荐入口提前退出、且丢失错误退出码的问题。Linux 源码启动器实际完成 HTTP 工具调用、文件写入和读回；Intel 分支使用入口硬件样本验证，不冒充物理 Intel。
- Core 初始化可填写真实上下文、模型 HTTP 超时和显式 stream usage。Linux 名称不再显示 Unknown。无电池 Mac 使用真实 `pmset` 来源；未知电源仍未知，可为前台请求显式授权一次。
- Companion 不会在 Intel/Linux 上因为存在模型目录而误启动 MLX worker；本地 HTTP 不依赖 MLX/MPS。Linux 上不再写无效 launchd 安装项。

### 配置与 Companion 接入

- 新首次向导/模型库表单读取 `/v1/models`，由用户填写真实窗口，保存新模型路由后显式应用。`localhost` 归一化为数字环回地址。
- 新增独立的 Companion 纯推理与标准 Agent 路由；小窗口同时约束输出预算，旧 MLX adapter 引用不遗留到 HTTP 后端。资源确认绑定 **Companion 实际主体**，既有桌面连接使用不同主体时仍保留身份和授权范围。
- 重新打开设置可恢复 pending；新端点立即进入协作选择。实际 Suite CLI 运行 prepare → 保存 → 停止/恢复 → 重开，旧 Session ID、原路由和配置保留。备份/恢复也包含 pending 标记。
- 手动本地推理不再被自动升级开关错误阻断；自动路径仍先呈现现有控制面板。真实生产 Core 测试完成纯推理、受控 `read_file`、一次性电池票据、Companion 重开后恢复原 Task/Session。

### 取消与历史

- 把 oMLX/vLLM 两份重复的响应追踪与请求中止下沉到 LocalHTTP。真实 buffered/streaming 测试发现并修复了取消线程与读取线程同时 close 的错误。
- 请求停止只断开相应客户端响应。通用外部服务不获得虚构的模型 load/unload、自动释放或失联租约能力，`provider_compute_stop` 为 UNKNOWN。
- HTTP 响应头到达前可能没有可关闭的响应对象；控制状态保持 `stopping`，直到任务真正终止且 `quiescent=true`。实际慢 HTTP 测试确认晚到的已授权读工具不执行，原 provider 继续可用。
- Core 实际进程测试覆盖修改审批、真实文件读回、SSE 顺序/重连及实际 HTTP 409、SIGTERM、SQLite 完整性、重启和原幂等键不重放。UNKNOWN/旧收据不因此改写。

所有本轮模型回复均来自明确标注的协议夹具。实际 HTTP、文件、进程和数据库是真实现；Qwen/DeepSeek 模型质量、真实 usage、费用与 Intel 性能不由这些测试证明。`<think>` 文本保留，未报告的 usage 仍 UNKNOWN。

## 安装包与来源

四个 wheel 在全新环境安装，工作目录在仓库之外；导入路径、每个 Python 文件与 wheel 的字节、实际文件工具和 CLI 入口均核对。最后再次与最终源码比对，**257 个文件无构建后漂移**。详见 [wheel 审计](COMPONENT_WHEELS.json)、[安装证明](INSTALLED_PROOF.json)、[最终源码比较](WHEEL_SOURCE_CHECK.json)。

| 组件 | wheel SHA-256 |
| --- | --- |
| Core 5.0.0b22 | `c62fa746a17a1165a832cde11bc29938c27d92b9156345276aac20e407276e4d` |
| Companion 0.5.7b4 | `fdca244b5105acc4a06d8b854c40375bbb922e4f4bbf068097b65d737b699a8a` |
| Suite 0.2.0b27 | `158efcb7c67dc6ed461c2c8e2212855ed16cef11a72effa76fd1f732fd637674` |
| Channels 0.1.0a3 | `c14c98f0782e9e6bb046c45386596c39d9156d2325bb2b5f27cf1b523d22fc8f` |

源码安装命令另在第三个全新环境执行，实际安装 Core/Suite/Companion，不依赖预装 Channels。两个环境都运行了 README 的 `init/start/models/ask/agent/status/stop`，读取真正的工作区 `project.md`，停止/重开后没有再次提交模型请求。[源码安装运行](README_SOURCE_RUN.json)、[四 wheel 环境运行](README_WHEEL_RUN.json)和[可重跑的协议探针](README_QUICKSTART.py)记录了范围；探针不是模型能力测试。

Intel 的原锁不能通过替换架构字段变为合格材料。目标标签现在明确标准 CPython 3.14、macOS 15、x86_64；错误 ABI、free-threaded、PyPy 和最低系统高于目标的 wheel 被拒绝。35 项官方材料见 [获取来源](../../../desktop/docs/evidence/intel-portability-20261116/dependency-acquisition.json) 与 [检查结果](../../../desktop/docs/evidence/intel-portability-20261116/dependency-checks.json)。`watchdog==6.0.0` 和 `cryptography==50.0.2` 尚需真实原生编译，生成器返回 `NEEDS_NATIVE_SOURCE_BUILDS`，不写完整锁。

本轮没有发布新 Release。查询时公开下载仍只有 `desktop-v5.0.1-rc.7-chat-20261030` 的 arm64 预发行；`main` 的新代码不会自动进入旧 PKG。

## 失败与阻碍历史

| 记录 | 发生的情况 | 后续 |
| --- | --- | --- |
| Core 旧源码入口 | 新增四项入口/硬件回归在原代码上失败 | 修复平台分派与退出码，最终全量通过 |
| HTTP 取消首测 | 实际读取时双线程 close 导致 `AttributeError` | socket shutdown 由取消线程执行，读取线程负责最终关闭；三个 adapter 的回归通过 |
| Companion 首轮 | 645 PASS、25 SKIP、1 ERROR / 671；旧测试 patch 了重构前的时钟模块 | 修正测试时钟目标，未改生产夜间静默规则；新增用例后的最终 679 项见上表 |
| Suite 新测试初写 | 第一次用了不存在的 route alias（404）；第二次对未部署占位路由建 Session（409） | 使用真实先配置/应用再建 Session 的产品流程；原日志保留 |
| Suite 主体断言 | 新断言将生产 tuple 与 frozenset 比较，1 FAIL | 修正测试预期类型；实际主体/权限断言保留，最终全量通过 |
| Intel 依赖首次获取 | 固定 cryptography 无兼容 Intel wheel，按规则停止 | 补固定源码构建入口，35 份真实来源获取完成，两项原生编译仍待做 |
| UI 额外类型检查首轮 | 命令要求了仓库没有安装的 Node 类型 | 按已有前端配置验证新增夹具，最终类型检查通过 |
| Playwright | 当时 37 项的两次执行均首项浏览器启动错误、36 未执行；指定浏览器下载失败，系统浏览器被容器拒绝 | 最终新增至 38 项，全部收集/类型检查通过；浏览器执行继续 BLOCKED |

公开日志是 UTF-8 的 gzip 文件，统一移除 ANSI 颜色并将当前工作区前缀替换为 `<WORKSPACE>`。每份原始、公开文本及 gzip 的 SHA-256 在 [LOG_MANIFEST.json](LOG_MANIFEST.json)。原始失败没有覆盖成成功；最终全量/SDK/Harbor/安装态日志未发现 ResourceWarning。历史用户模型服务、私有日志和数据不在此目录。

## 主要复现命令

先安装现有测试依赖，在仓库根目录运行。旧源码兼容路径按本机真实 checkout 设置：

```sh
LOCALPILOT_PR9_SOURCE=/absolute/pr9-baseline \
LOCALPILOT_LEGACY_SOURCE=/absolute/pr1-legacy \
  python -W default scripts/run_core_qualification.py --report /fresh/output/core.json
python -W default -m unittest discover -s companion/tests -t . -v
PYTHONPATH=.:suite python -W default -m unittest discover -s suite/tests -v
python scripts/check-candidate-versions.py
python desktop/scripts/check-docs.py
```

前端沿现有 `desktop/package.json` 的 `npm test`、`npm run build`、`npm run test:ui` 执行。SDK/Harbor 使用 [已记录的 SDK 环境](SDK_ENVIRONMENT.json) 和 [固定 Harbor 环境](HARBOR_ENVIRONMENT.json)，不要把当前缺少的依赖写成全部通过。安装态 12 项使用真实 Channels wheel，通过 `LP_TEST_CHANNEL_WHEEL` 指定，在仓库外的实际安装环境运行原测试。

## 剩余工作

**仍不能宣称全部原计划完成。** 物理 Intel、当前 x86_64 APP 和真实 CPU 模型、当前 arm64 原生回归、TCC/真实系统音轨、睡眠唤醒、真实本地/云端子 Agent、LoRA 效果、固定 Skills/KV 冷热实验和完整公开 study 均有缺项。Linux 原生桌面与宿主 Shell 暂缓；RL 执行器未实现，已有 dense 训练不是整个模型所有参数。

旧 534 队列保持 **1 PASS、3 FAIL、13 ERROR、517 无最终结果**，本轮没有继续或改写它。尚不能报告 Agent 排名、非劣、节费幅度或永久 KV。原生系统音轨上轮仍为 TCC 失败；旧安装回滚归档校验也不能代替反向安装回滚。

完整原计划对照见 [平台与计划状态](../../development/PLATFORM_SUPPORT_20261116.md)，仅当前环境无法完成的操作见 [Work 提示词](../../development/WORK_INTEL_20261116.md)。
