# 2026-11-17 Suite、Channels、Companion 与平台构建审计

## 范围和状态

基线为 `b420b97`。本轮负责 Suite 安装、配置、恢复、渠道协调；独立 Channels Python 后台；Companion 后台模型生命周期；Desktop 平台构建脚本。可见 UI、桌宠窗口和 Core Responses Runtime 由其他审计分支负责人处理。本文件只记录本范围；源码随后已由主负责人统一发布为 `91dd87c`，组件版本、最终构建与交付状态见[总报告](AUDIT_20261117.md)。历史证据未修改。

本轮检查了模块入口、首次准备、模型端点、私有凭据引用、进程恢复、渠道安装与账号准备、模型电源策略、Python 运行时定位和原生打包路径。没有发现现成 `.github/workflows` 或其他 CI 配置，因此沿用仓库已有 `unittest`、依赖锁、轮包和原生构建脚本，不新增 CI 工具或流程。

执行记录见 [平台回归摘要](../evidence/audit-20261117/platform/SUMMARY.json)。测试使用绝对仓库及 Suite `PYTHONPATH`，避免子进程更换工作目录后误导入开发环境中旧版本的 Core。首次回滚故障注入的相对路径问题保留为 [测试环境诊断](../evidence/audit-20261117/platform/test-harness-relative-pythonpath-diagnostic.json)，不记为产品缺陷。

| 较早平台回归快照 | 执行 | PASS | SKIP | 结果与记录 |
| --- | ---: | ---: | ---: | --- |
| Suite 完整测试 | 122 | 121 | 1 | [suite-r2.log](../evidence/audit-20261117/platform/suite-r2.log) |
| Companion 完整测试 | 724 | 691 | 33 | [companion-r1.log](../evidence/audit-20261117/platform/companion-r1.log) |
| 根目录 Channels 测试 | 58 | 52 | 6 | [channels-r1.log](../evidence/audit-20261117/platform/channels-r1.log) |
| macOS artifact 静态/本地文件测试 | 9 | 9 | 0 | [macos-artifacts-r1.log](../evidence/audit-20261117/platform/macos-artifacts-r1.log) |

上述历史四组共执行 913 项，873 PASS、40 SKIP，无失败；不与较早定向测试重复累计，也不能再与涵盖 Channels 的 Core 全量重复累计。首轮 Suite 的两个独立 wheel 导入错误保留在 [suite-r1.log](../evidence/audit-20261117/platform/suite-r1.log)。本范围修改文件身份另见 [SOURCE_SHA256.json](../evidence/audit-20261117/platform/SOURCE_SHA256.json)。

后续整合后的全量日志另行保留：[Suite R2](../evidence/audit-20261117/root/suite-regression-r2.log)为 **123 项 = 122 PASS + 1 SKIP**，[Companion R2](../evidence/audit-20261117/root/companion-regression-r2.log)为 **727 项 = 694 PASS + 33 SKIP**，均无失败。它们是后续源码快照的独立结果，不覆盖原日志，也不与上表相加。

交付前的凭据来源复核又修复 P-B5、P-B6。使用真实 route/backend 工厂、合成密钥以及已有 HTTP/TLS/SQLite 服务用例，定向执行 26 项，26 PASS、0 SKIP、0 失败。该组与上述测试有交集，不累加为全项目去重总数；它对应后续两处生产修改的验证。日志及四个源码/测试文件哈希见 [凭据来源回归](../evidence/audit-20261117/platform/credential-sources-r1/SUMMARY.json)。

## 修复的实际问题

### Bug

| 编号 | 原问题与可观察后果 | 修复及验证 |
| --- | --- | --- |
| P-B1 | Linux 随包 Python 是指向发行版解释器的符号链接。`channel_runtime` 用 `sys.executable.resolve()` 推导资源目录，结果离开 APP 资源，已内置的 Node 包仍被当作不存在，渠道安装转而联网。 | 改用 `sys.prefix` 定位真实隔离运行时。测试启动真实符号链接 venv，读取并提取随包校验归档，确认 `bundled_runtime=true`、`downloaded=false`。 |
| P-B2 | Suite 允许 macOS 系统 `/tmp -> /private/tmp`，Channels 适配器的独立路径实现却把系统 sticky 临时目录视为可写的不可信别名；同一个渠道状态目录在两层结果不一致。 | 对齐已有 Suite 的固定、root 拥有的系统别名规则；用户自建符号链接继续拒绝。新增原生 macOS `/tmp` SQLite 测试；Linux 上明确跳过该原生用例。 |
| P-B3 | `ModelManager` 每次请求及每次 tick 都新建 `LowPowerPolicy`，其 15 秒系统查询缓存始终失效；没有模型进程时也查询宿主电源。 | Manager 保持一个策略实例，每次推理只取一次策略结果；没有模型或适配器时 tick 直接返回。连续请求的宿主查询计数及既有电源切换测试覆盖此行为。 |
| P-B4 | 原云端配置在 Core 重启成功后单独写 Companion 配置；后续 Companion 重启失败时，Core 和 Companion 已部分切换，原配置及新加资源凭据没有一起回滚。 | 配置变更等待服务停止，再保存并恢复两项服务；故障时恢复两份 JSON 与发生变化的资源凭据。真实进程测试在 Companion 恢复边界注入一次故障，验证配置字节与服务恢复。 |
| P-B5 | Suite 新 OpenAI 路由同时声明私有 `key_file` 和默认 `api_key_env`；已有环境变量会盖过用户刚填入的文件。 | 文件配置只声明该文件。真实 Suite 路由工厂生成 agent/reasoning 两条路由，再交给 Core backend 工厂，验证继承的默认环境变量不会覆盖所选文件。 |
| P-B6 | 手写显式 OpenAI `api_key_env` 不存在时，解析器会回退到默认环境密钥或默认密钥文件，静默改变账户来源。 | 显式选择的环境变量不存在或为空时，直接返回 `missing_credentials`；未声明该字段的旧配置继续支持默认环境及文件，默认 Chat 身份不变。真实工厂测试覆盖 Chat 和 Responses。 |

### 用户操作简化

| 编号 | 原操作负担 | 结果 |
| --- | --- | --- |
| P-U1 | 使用 OpenAI 需要手改路由 JSON 和凭据环境，Desktop 原云端入口仅能配置 DeepSeek。 | `cloud-configure --provider openai [--model] --key-file PATH` 配置显式 Responses 路由，默认 `gpt-6-luna`。DeepSeek 旧命令兼容。两家路由并存；不同模型新增独立路由。私有 key 文件只保留路径，明文不进入 service JSON、环境文件或返回值。Core 与 Companion 安全重启，失败恢复两份配置和服务。 |
| P-U2 | 本地模型服务常显示服务器根地址，用户必须手补 `/v1`，标准 HTTP 默认端口也被拒绝。 | Suite 接受环回服务器根地址、`/v1`、尾部斜线及粘贴空白，在入口归一化成实际 `/v1` 地址；保留环回限定及凭据、查询参数、跳转限制。真实 HTTP 目录请求验证目标路径。 |
| P-U3 | 已确认登录或发现渠道账号后，仍要求先退出该流程、单独安装可选运行时和渠道组件。 | 相同的 `install_component` 路径自动准备校验过的 Node、随包 Channels wheel 和私有 ingress credential；状态读取仍只读。归档、轮包、源码文件、私有配置与子进程探测使用真实实现验证，不接触真实账号。 |

OpenAI 入口只负责配置，返回 `api_connection=NOT_PROBED`。本范围回归没有使用真实 API key 或发起付费模型请求；真实 Responses 推理证据由 Core 审计单独记录。

### 维护成本

| 编号 | 原重复或分散逻辑 | 调整 |
| --- | --- | --- |
| P-R1 | 首次准备、云端配置和宠物模型配置各自拼接 Companion 子进程命令、过滤环境和解释启动结果，错误及等待行为不一致；首次准备还把合法的 `starting` 立即当作未准备好。 | 三处统一调用现有 `installation.service` 的就绪等待；宠物模型切换失败先停止新实例，再恢复原配置。没有另建进程管理器。 |
| P-R2 | Channels `command` 已在入口把 stop、cancel_login、exit 交给 `stop_owned`，后面仍有不可达的 exit 及重复停止分支。 | 删除不可达路径，保留后段实际可达的 disconnect；现有退出、后台偏好、断开和历史状态测试继续覆盖。 |
| P-R3 | 两处升级回滚测试的独立 wheel 验证子进程没有隔离开发 `PYTHONPATH`，在绝对源码路径环境中导入源码包而非刚恢复的 wheel；产生两个假失败，且无法证明安装结果。 | 与升级实现一致，为独立解释器探测添加 `-I`。保留首轮两项错误的日志，复验真实 pip 安装、失败回滚和独立 wheel 导入。 |

以上每项仅归一种分类，共 6 个 Bug、2 个生产维护问题、1 个测试夹具维护问题、3 个操作简化、3 个重复防御问题。P-R3 仅改善验证可靠性，不占总报告的十项生产维护额度。首次准备的就绪等待归入 P-R1，不另计 Bug；云端入口内部的路由辅助函数也不额外计数。

### 过度防御与重复检查

| 编号 | 原重复检查 | 保留的入口约束 |
| --- | --- | --- |
| P-D1 | Suite 与 Channels 的 `private_json` 先通过 `private_file` 做 lstat 类型、权限、硬链接检查，打开后又以 fstat 重复全部检查。 | 路径归一化后打开一次，在实际文件描述符上校验类型、owner、权限、链接数与读取大小。实际私有文件、权限变更、硬链接和既有符号链接测试验证行为。 |
| P-D2 | 一次渠道状态或安装操作会多次调用 `channels.installed`，重复逐文件读取并校验相同源码哈希。 | 调用入口只验证一次已安装状态，兼容性比较复用已确认的安装前提；改过的源码仍在首次检查时被拒绝。 |
| P-D3 | Channels Store 已在打开 SQLite 前确认私有文件和父目录，又在成功创建自身 DB/WAL 后重扫同一组文件。 | 保留打开前的边界检查及独立 SQLite 所有权锁，删除内部生成文件的重复事后扫描和无意义转发函数。真实 SQLite、只读故障、权限及状态恢复测试覆盖。 |

## 与其他模块的接口

- `cloud-configure` 默认 provider 仍为 DeepSeek；OpenAI backend 使用 `kind=openai`、`protocol=responses` 和显式 `key_file`，不同时声明默认 `api_key_env`。Core 的新解析器负责提供商凭据装载及 Responses 请求。
- 云端 agent、reasoning、cooperative 路由的组合放在 `_cloud_route_additions`；不会从本地模板继承 managed model、验收或 Computer Use 字段，也不会为尚未配置的本地模型制造可用合作路由。
- Desktop `configure_cloud_key` 可以转发可选 `provider`、`model`；成功配置已经恢复服务，不需要另点本地模型配置的 activate 操作。
- Suite 的 `desktop_session` 转发可选 `execution_budget`；`desktop_profile` 同时转发 `execution_budget` 与 `expected_execution_budget`，省略时保持旧请求兼容。预算与权限的实际 Runtime 行为属于 Core 审计。
- macOS 构建与现有 Linux 构建一致，向 Cargo 传 `--locked`，不在发布构建中隐式更新依赖解析。

## Linux、Apple Silicon 与 Intel 验证入口

### 跨平台源码回归

在已安装仓库锁定开发依赖的解释器中，使用现有入口。必须使用绝对 `PYTHONPATH`，因为服务子进程会更换工作目录。

```sh
LP_AUDIT_ROOT=$(pwd)
export PYTHONPATH="$LP_AUDIT_ROOT:$LP_AUDIT_ROOT/suite"
export OMP_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 MKL_NUM_THREADS=1
python -m unittest discover -s suite/tests -v
python -m unittest discover -s companion/tests -v
python -m unittest discover -s tests -p 'test_channel*.py' -v
python -m unittest discover -s desktop/tests -p test_macos_artifacts.py -v
```

Linux 实际进程安装、配置、重启和 Session 恢复由 Suite 用例执行。macOS 系统别名和平台原生能力用例只在对应平台执行；跳过不等于通过。

### macOS 原生构建

在目标架构的 macOS 上，从最终已提交源码的新 checkout 构建，保留原 `bundled-backends` 和历史 release。使用仓库要求的原生 CPython 3.14 Framework。arm64 与 x86_64 依赖锁及 wheels 分开准备，不能把已有 arm64 锁当作 Intel 合格输入。

```sh
LP_AUDIT_RUN=$(mktemp -d)
python3.14 -m build --wheel --no-isolation --outdir "$LP_AUDIT_RUN/wheels" .
python3.14 -m build --wheel --no-isolation --outdir "$LP_AUDIT_RUN/wheels" companion
python3.14 -m build --wheel --no-isolation --outdir "$LP_AUDIT_RUN/wheels" suite
python3.14 scripts/build_channels_wheel.py --no-isolation --out "$LP_AUDIT_RUN/wheels"
```

给 `LP_AUDIT_DEPS` 指定已经准备并审阅的目标架构依赖 wheel 目录；给 `LP_AUDIT_NODE` 指定相同架构的仓库固定 Node 归档。然后调用已有脚本，不创建新的构建流程：

```sh
LP_AUDIT_ARCH=$(uname -m)
python3.14 desktop/scripts/lock-runtime-dependencies.py \
  --wheels "$LP_AUDIT_DEPS" --arch "$LP_AUDIT_ARCH" \
  --out "$LP_AUDIT_RUN/runtime-dependencies.json"
python3.14 desktop/scripts/prepare-bundled-backends.py \
  --wheels "$LP_AUDIT_RUN/wheels" --dependencies "$LP_AUDIT_DEPS" \
  --arch "$LP_AUDIT_ARCH" --dependency-lock "$LP_AUDIT_RUN/runtime-dependencies.json" \
  --channel-runtime "$LP_AUDIT_NODE"
export LP_GUI_DEPENDENCY_LOCK="$LP_AUDIT_RUN/runtime-dependencies.json"
python3.14 desktop/scripts/check-bundled-backends.py --arch "$LP_AUDIT_ARCH"
cd desktop
LP_GUI_TEST_CONFIG=src-tauri/tauri.test.conf.json npm run release:macos
```

此路径运行既有 wheel 架构、源码身份、Mach-O、签名、归档和 DMG 检查，并产出隔离 Test APP。它不是物理机首次启动、Accessibility、会议采集、模型推理或桌宠长期运行验收。

本云环境是 Linux；本轮不能给出 Apple Silicon/Intel 原生构建或物理设备验收的 PASS。仓库没有可直接 dispatch 的既有 GitHub workflow，因此也没有把这些命令描述为已经执行的 GitHub CI。
