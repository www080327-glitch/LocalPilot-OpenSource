# Linux AT-SPI 修复与 Companion 0.5.7b6 复测

日期：2026-11-16。集成基线为 main `d846fef0f4b442d57e6e37f856a59c5a1a1337de`，本报告对应最终集成树中的 **Companion 0.5.7b6**。生产源码、测试和模块元数据见 [SOURCE_SHA256.json](SOURCE_SHA256.json)；原生产缺陷版本见 [PRE_FIX_SOURCE_SHA256.json](PRE_FIX_SOURCE_SHA256.json)。提交 SHA 由承载本报告的 Git 提交确定，不能用旧基线 SHA 冒充最终受测源码。

**结论：真实 Linux X11/GTK/AT-SPI 只读窗口观察已通过本轮受控原生验收；完整 Linux 桌面、Wayland、音轨和系统睡眠唤醒仍不能据此宣布完成。**

## 最终结果与去重口径

| 运行 | 结果 | 范围 |
| --- | --- | --- |
| Companion 全量 `final-full-r1` | **720 项：687 PASS、33 SKIP、0 FAIL/ERROR，32.925 秒** | 既有 unittest 发现入口，真实文件、HTTP、子进程、SQLite 与脚本模型协议测试 |
| 最终生产树原生 `final-r5` | **8 PASS、0 SKIP，1.526 秒** | 实际 Linux CUA 图形会话，owned Xvfb + 私有 D-Bus + GTK/AT-SPI 及 7 项观察回归 |
| 离线可选补验 `final-optional-r1` | **7 PASS、0 SKIP，18.755 秒** | 既有固定依赖环境中的 5 项真实 tiny CPU 训练和 2 项公开 JFK ASR 测试 |
| 三组去重后的覆盖 | **720 项：695 已通过、25 仍 SKIP** | 原生组中 7 项重复、1 项补验 GUI；离线补验覆盖此前另外 7 项跳过；剩余 25 项均需要 macOS Swift |
| 集成前独立副本 `candidate-r4` | **8 PASS，1.516 秒** | 原生产树保持冻结时，在独立 Companion 副本验证最小补丁；不替代最终生产树复测 |

全量日志未出现 Warning、Traceback、FAIL 或 ERROR。全量执行前后核对的 **152 个 Companion Python 源码、测试和模块元数据哈希完全一致**。

全量原始 SKIP 保留原样：

| 原因 | 数量 | 本轮处理 |
| --- | ---: | --- |
| macOS Swift 编译与原生 helper | 25 | Linux 环境不能替代；保留 SKIP |
| exec 环境没有可用 Xvfb/D-Bus 图形工具 | 1 | 在真实 CUA 图形环境单独完成最终原生用例 |
| 没有显式指定已识别的 whisper.cpp、模型和公开语音样本 | 2 | 全量当时保留 SKIP；后续使用核验后的既有材料完成独立补验，不用历史测试代替 |
| 可选固定版本 Torch/Transformers/PEFT 训练环境未配置 | 5 | 全量当时保留 SKIP；等待 Qwen 停稳后，在既有固定依赖环境完成独立补验 |

机器为 Linux x86_64，exec 回归使用既有 CPython 3.12.14 venv；GTK/AT-SPI helper 使用图形环境中的系统 Python 3.13 与 GI。全量依赖包括 watchdog 6.0.0、pypdf 6.21.4、psutil 7.2.2。完整解释器与来源记录保存在 `companion-final-full-r1.summary.json.gz`。

## 追加补验：现有材料可执行的 7 项

在原 Qwen 任务及其 owned Core/Provider 停止后，单独运行 `companion.tests.test_portable_training` 和 `companion.tests.test_linux_whisper`，**7/7 通过，18.755 秒，无 SKIP/FAIL/ERROR**，没有重跑完整 720 项。全量当时的 33 项 SKIP 日志及统计保持原样，只有当前去重覆盖更新为 695 PASS / 25 macOS SKIP。

训练环境为 Torch **2.9.1+cpu**、Transformers **4.57.3**、PEFT **0.18.1**、safetensors **0.7.0**。5 项测试在临时目录生成随机初始化的两层 tiny Qwen2 和测试自有的三条来源数据，实际验证 LoRA/全参梯度更新、限定层、重新加载、仅回答 token 参与损失、留出集不进入训练，以及不可用 CUDA 的明确失败。没有使用用户观察记录，没有训练或替换用户模型，也没有声称 PA 质量提升。

2 项 ASR 使用既有 whisper.cpp **v1.9.5**，源码 commit `d1be6fde11ac6e0407606b4e42fe72d34add8037`。实际可执行文件、`ggml-tiny.en.bin`、上游公开 JFK WAV 和 LICENSE 的 SHA-256 都与原资格记录匹配。通过生产 `Capture.transcribe` 的内存描述符路径完成真实 CPU 转写，并验证取消后子进程退出、不返回迟到文本。没有采集麦克风、系统音轨或私人会议；二进制、权重和音频均未复制进本证据目录。

补验保持离线和 `nice +15`，OMP/BLAS/MKL 为 1，现有生产训练与 ASR worker 各使用固定 2 线程。执行前后，原 **152 个**源码/元数据哈希全匹配。递归快照额外看到先前 wheel 构建留下的 **99 个 `companion/build/lib/companion/` 副本**，初次比较完整字典时因键集合扩大而不相等；核对原作用域后确认源码未变，扩大的 251 项在本次运行前后也一致。该检查差异单独保存在 `final-optional-r1.source-comparison.json.gz`，没有误记为产品测试失败或删除生成物。

此组训练 fixture 的 Companion 后端关闭、Core endpoint 为空，不启动 Core 或模型服务。它**不覆盖同时进行的 Core 子 Agent 默认预算与工具 wire schema 修改**；相关修复必须使用自己的新运行证明。

## 缺陷一：静态正文调用了同名的错误 GI 接口

`linux_helper.read_atspi_tree()` 原来先调用 `get_text_iface()`，再执行 `text_interface.get_text(start, end)`。在实际 PyGObject 对象上，返回值的具体类型仍是 `Atspi.Accessible`，它的旧 `get_text(self)` 方法返回 Text 接口，并遮蔽了 `Atspi.Text.get_text(self, start, end)`。

原生诊断 r3 对同一个 owned GTK Label 取得以下结果：

```text
class: gi.repository.Atspi.Accessible
method: get_text(self) -> Atspi.Text
old_error: TypeError('Atspi.Accessible.get_text() takes exactly 1 argument (3 given)')
explicit_interface_call: Owned Linux receipt 7492
```

原有异常处理把这个 TypeError 计入 `read_error_count`，使窗口和容器节点正常出现、正文始终为空。r2 中真实窗口已经 ACTIVE/SHOWING，仍只有 2 个结构节点、1 项读取错误和 0 个静态文字节点，因此不能归因于模型大小或等待不足。

修复显式调用 `Atspi.Text.get_text(text_interface, start, end)`。只有这一处接口调用改变；正文范围、前台判定、节点和字符预算、可编辑和密码控件排除均未放宽。代码注释解释 PyGObject 的同名接口约束。

## 缺陷二：丢失明确的桌面 Accessibility Bus 地址

原 helper 的精简环境保留 `DBUS_SESSION_BUS_ADDRESS`，却丢弃 `AT_SPI_BUS_ADDRESS`。云图形桌面实际设置了后者：GTK 继承并注册到该 accessibility bus，helper 则从新 `dbus-run-session` 发现另一条 bus。诊断 r1 即使等待 35 秒，仍无法获得 owned GTK application，`application_count=-1`。

[GNOME 的 atspi_get_a11y_bus 实现](https://gnome.pages.gitlab.gnome.org/at-spi2-core/coverage/atspi/atspi-misc.c.html)按显式 `AT_SPI_BUS_ADDRESS`、X11 root 属性、session D-Bus 的顺序发现地址。过滤掉显式地址会改变所连接的桌面来源。

生产修复仅将 `AT_SPI_BUS_ADDRESS` 加入 helper 环境允许列表。新增真实环境构造函数测试同时确认该地址保留、模型 API key 与 HTTP proxy 仍未传入 helper。

原生 fixture 另有明确的环境隔离缺口：它新建 session bus，却沿用外部 accessibility bus 和 runtime directory；同时在 bus 启动后改 DISPLAY，D-Bus 激活服务仍可能继承旧显示器。现测试在启动 `dbus-run-session` 前移除外部地址并设置私有 `XDG_RUNTIME_DIR`，在 Xvfb 创建后同步该 session bus 的 DISPLAY 激活环境。没有连接或读取其他用户应用，也没有修改系统桌面配置。

## 失败历史完整保留

| 阶段 | 实际结果 | 证据与解释 |
| --- | --- | --- |
| 最初原生 r1 | FAIL | 15 秒内没有静态 Label，仅 session 与 app.activated |
| 诊断 r1 | FAIL | 延长到 35 秒仍失败；GTK 与 helper 使用不同 bus |
| 诊断 r2 | FAIL | 私有 bus 与 Registry 成功；找到唯一 owned ACTIVE/SHOWING GTK，仍有正文接口读取错误 |
| 诊断 r3 | 原产品断言按预期 FAIL | 同一个真实 Label 上旧 API 抛 TypeError，明确接口 API 返回正确文字；不是放宽断言 |
| 独立源码副本 r4 | PASS | 两处生产修复与 fixture 修复后，8 项通过；原始冻结目录不改 |
| 最终集成树 r5 | PASS | 同一套真实原生与观察回归 8 项通过；原生等待期限仍为原来的 15 秒 |
| 最终 Companion 全量 r1 | PASS / SKIP | 720 项，详细口径见上表；没有删除失败用例或改为 SKIP |
| 离线可选补验 r1 | PASS | 既有模型、公开样本与固定依赖核验后，7 项真实训练/ASR 通过；与原始 SKIP 记录分开保留 |

最终原生用例仍断言：能得到 `Owned Linux receipt 7492`；不能得到输入框或密码框的 synthetic 标记；事件来源为 `linux_accessibility`；pause 后 helper 进程已经停止。原生运行不发送模型推理请求。

## 可复跑命令

在仓库根目录，沿现有 venv 和 unittest 流程：

```sh
OMP_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 MKL_NUM_THREADS=1 \
  nice -n 15 /path/to/existing/venv/bin/python \
  -m unittest discover -s companion/tests -t . -v
```

在具有 Xvfb、dbus-run-session、gdbus 和系统 Python GI Atspi/Gtk 的 Linux 图形环境：

```sh
/path/to/existing/venv/bin/python -m unittest \
  companion.tests.test_linux_native \
  companion.tests.test_linux_runtime.LinuxObservationTests -v
```

本机实际运行脚本、解释器路径、日志和诊断脚本一并留档。全量只启动一个低调度优先级测试进程，没有编译原生大包或运行训练；追加 7 项仅在 Qwen 停止后执行上述 tiny 训练和公开样本转写。

## 证据与边界

[LOG_MANIFEST.json](LOG_MANIFEST.json)列出 **29 个**日志、命令和诊断材料的原始 SHA-256、公开文本 SHA-256 与压缩 SHA-256。公开副本仅移除 ANSI 并把 workspace 前缀替换为 `<WORKSPACE>`，gzip mtime 固定为 0；不改写结果。诊断脚本中的路径是当次执行位置，供核对来源，不是假设用户机器存在相同路径。模型权重、API key、私人文档、SQLite 或音频均未收入本目录。

最终源码已更新 Companion 版本和 Suite 最低依赖为 0.5.7b6，同时同步当前版本说明；历史报告不修改。这里的源码复测不自动证明此前已构建 APP 或 wheel 含新修复，必须重新构建、核对资源身份并分别记录。

尚未由本目录证明：Wayland 窗口观察、Pulse/PipeWire-Pulse 音轨、logind 睡眠唤醒、DEB 安装升级与回滚、物理 Intel Mac、macOS WebKit profile/TCC、全天候监视覆盖、真实模型回答质量或使用用户审阅数据完成 LoRA 训练。旧 Qwen 冻结源码的模型结果仍属于原版本来源，不由本次静态读取修复追认。
