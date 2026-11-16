# Linux Companion：系统接入、只读活动与本地会议转写

日期：2026-11-16（Asia/Shanghai）。从 `main` 的 `0cc99d57990e81302b941b6f5a160093dd298d4b` 继续；本说明描述新增 Linux 实现，不把既有 macOS 结果改记为 Linux 验收。

## 支持范围

| 路径 | 本轮实现 | 实际验证边界 |
| --- | --- | --- |
| 后台服务、文件/Codex/提供的会议文字、SQLite、HTTP 模型 | 复用现有 Companion；默认数据目录采用 XDG | 已有真实服务、文件、HTTP、恢复测试继续运行 |
| 电源和系统资源 | sysfs 电源、power-profiles-daemon/ACPI profile、电池功率 | 真实读取实现与临时 sysfs 材料测试；当前容器无电池，实际返回 UNKNOWN |
| 用户登录启动 | 显式 `systemd --user` 注册/移除，保留现有直接 start/stop | 实际 systemd 单元解析通过；受控 CLI 进程覆盖文件事务，真实用户 manager/登录尚未验收 |
| 桌面通知 | 已安装的 `notify-send`，遵守现有静音/勿扰/去重 | 成功提交仍不等于用户看见；本轮不向用户桌面发送测试通知 |
| 原生只读来源 | X11 前台元数据、logind 会话提示、可用的 AT-SPI 前台静态文字 | GI 真实绑定及协议/检索通过；隔离 GTK 实测被环境 D-Bus Unix socket 阻止 |
| 麦克风/系统音轨 | 用户选择 PulseAudio 或 PipeWire-Pulse 的来源；本机 whisper.cpp | 真实 FFmpeg PCM、真实 whisper.cpp 推理及取消通过；真实声卡、Pulse 服务录音尚未验收 |

Linux 不启动 Swift helper、MLX worker 或 launchctl。AT-SPI 只覆盖注册并暴露相应信息的应用；Wayland 没有因此获得通用全局窗口读取能力。UI 文本采集不等于完整浏览器历史，也不把“窗口聚焦”解释成完成了编辑或任务。

## 安装后的服务与数据

根 README 的 Python 安装包含 Companion。Linux 未显式设置 `data_dir` 时使用 `$XDG_DATA_HOME/LocalPilotCompanion`，若 XDG 变量未设置或不是绝对路径，则使用 `~/.local/share/LocalPilotCompanion`。现有配置中的明确路径保持原值。

```bash
companion --config /absolute/path/companion.json start
companion --config /absolute/path/companion.json --json status
companion --config /absolute/path/companion.json stop
```

本地模型仍通过现有 `local-http` 配置或 Suite 的本机端点设置接入。`low_power_policy=system` 读取 `powerprofilesctl get`，其不可用时读取 ACPI platform profile；未知模式继续保守处理。`off` 只关闭这一低功耗策略，电池授权仍是独立选项。没有电池对象或可读供电来源不被推定为接电。

电池 `power_now` 使用微瓦；只提供电压/电流时按微伏、微安换算。多个电池存在缺项时返回 UNKNOWN，充电功率不标为放电功率。外围 USB 设备的 `scope=Device` 不视为主机供电。没有瓦数时不从 CPU 百分比估算能耗。

## 显式 systemd 用户服务

普通 `start` 不安装登录项目。先生成可读的单元，再按需显式安装：

```bash
companion --config /absolute/path/companion.json systemd render
companion --config /absolute/path/companion.json stop
companion --config /absolute/path/companion.json systemd install --confirm
companion --config /absolute/path/companion.json systemd status
companion --config /absolute/path/companion.json --json status
```

需要 Core/提供方凭据时，使用仅含 Companion 所需身份的私有环境文件，权限 `0600`，并添加 `--environment-file /absolute/path/companion.env`。不要把包含所有身份的整个 Core 凭据文件复制成 Companion 环境。单元仅记录文件路径，不写入令牌明文。

安装目标为 `$XDG_CONFIG_HOME/systemd/user/localpilot-companion.service`，或 `~/.config/systemd/user/`。实现不使用 sudo、不启用 linger、不自动无限重启。已有启动项保留；`enable --now` 失败会保留实际单元及其摘要收据，便于检查和显式移除，不把部分完成报为成功。unit 已启用不表示 Companion HTTP 已就绪，仍需检查上面的 `status`。

```bash
companion --config /absolute/path/companion.json systemd uninstall --confirm
```

移除前必须与该配置私有收据中的路径和 SHA-256 一致；用户后来修改的单元保留。服务停止失败时不会删除单元。移除不删除记忆、模型或配置。

## 原生只读活动

可选发行版依赖：`python3-gi`、`gir1.2-atspi-2.0`、`at-spi2-core`、`x11-utils`；通知额外使用 `libnotify-bin`。GTK/Xvfb 只用于下面的隔离测试，不是 Core 文件/HTTP 功能的依赖。

只读 helper 使用项目中的固定 Python 源文件，优先采用当前 Python 的 GI；当前环境不含 GI 时可使用具有发行版 GI 的 `/usr/bin/python3`。没有 GI/桌面总线时不伪造文字读取结果。helper 环境只携带桌面与本地运行库相关变量，不复制 API 凭据。

Linux 应用标识为 `linux.<实际 /proc/PID/exe 文件名>`，文件名中非字母数字、下划线或连字符替换为 `_`。例如常见的 `linux.firefox`；实际标识以安装的可执行文件为准，不沿用 macOS bundle ID。

在现有配置中明确设置所需范围，例如：

```json
{
  "native_observation_enabled": true,
  "native_app_allowlist": ["linux.firefox"],
  "native_ax_enabled": true,
  "native_content_app_allowlist": ["linux.firefox"],
  "native_content_window_allowlist": ["用户选定的精确窗口标题"]
}
```

上述片段需合并到现有配置，不能覆盖其他字段。启动服务后调用 `authorize-observation --confirm` 才开始当前范围采集。暂停使用 `observe pause`；恢复使用 `observe resume`。更改应用排除项会撤销旧同意，并按平台重新构造 provider。

X11 仅读取当前前台窗口的 PID/身份；标题需要文字范围或窗口排除规则。AT-SPI 读取授权前台窗口的可见静态文字；输入框、可编辑节点、密码节点及其子树在内容 getter 前跳过。遍历共享既有节点、深度、字符和时间预算。来源分别记为 `linux_desktop` / `linux_accessibility`，沿用已有过滤、引用、TTL、撤销和来源问答；不伪称 macOS AX 来源或完整读取。

logind 的 Active/LockedHint/IdleHint 分别记录会话、锁定和空闲提示。空闲状态不被当作系统睡眠。Linux `CLOCK_BOOTTIME` 与 monotonic 的差值用于识别暂停经过时间并触发现有唤醒去重路径；物理睡眠、解锁和晚间反馈仍需实际桌面验收。

## 本地会议转写

新增路径使用发行版 FFmpeg 的 PulseAudio 输入，兼容提供 Pulse 协议的 PipeWire。用户还需提供 `whisper-cli` 和已核对来源/SHA-256 的本地 whisper.cpp 模型。功能不会自动下载、加载 LLM 或连接云转写。

先只读列出音频来源：

```bash
companion --config /absolute/path/companion.json --json meeting-devices
```

把所选**实际设备名**写入现有配置：

| 字段 | 值 |
| --- | --- |
| `meeting_microphone_source` | 设备列表中 `monitor=false` 的麦克风名称 |
| `meeting_system_source` | `monitor=true` 的输出监视来源名称 |
| `meeting_whisper_command` | `whisper-cli` 可执行文件的绝对路径 |
| `meeting_whisper_model` | 模型文件的绝对路径 |
| `meeting_whisper_model_sha256` | 固定来源核对过的 64 位小写 SHA-256 |

重启 Companion 使配置生效后，可显式开始/停止：

```bash
companion --config /absolute/path/companion.json meeting-start --capture microphone --locale zh-CN
companion --config /absolute/path/companion.json --json meeting-status
companion --config /absolute/path/companion.json meeting-stop
```

`--capture system` 和 `both` 使用各自已选定来源。启动前验证工具、模型哈希、当前本地 Pulse socket 和麦克风/monitor 分类；不会静默把不匹配的设备当成用户选择。

FFmpeg 连续输出 16 kHz 单声道 PCM，15 秒为一段，最多四段等待转写。模型只读内存文件描述符中的 WAV，应用不创建音频文件。转写跟不上时明确失败并停止，不能无限累积内存或把丢失的音频报作成功。停止会终止本次拥有的采集/ASR 子进程，未完成音频缓冲丢弃，不再产生晚到文字；已完成文字沿用现有不可变分段、引用和撤销机制。系统音轨与麦克风分别保留来源标签，不承诺说话人识别。

## 本轮验证与保留失败

- 最终普通环境 Companion 全量回归：719 项，686 PASS、33 SKIP、0 FAIL/ERROR，30.903 秒，记录在 `full-final-r4.log`。跳过项为 25 项 macOS Swift、1 项隔离 Linux GUI、2 项显式 ASR 材料、5 项可选训练环境；实际 ASR 另跑 2 PASS，不把普通环境 SKIP 改写为 PASS。
- 新 Linux 运行时组：28 PASS，覆盖实际 sysfs 文件读取、真实 systemd 单元解析、受控 CLI 进程安装/移除事务、SQLite 来源引用/撤销、FFmpeg PCM、内存 WAV、Pulse JSON 来源分类、采集失败及拥有进程的停止。受控 systemctl/whisper 夹具结果不计为真实 daemon/模型验收。
- 实际 ASR：上游 whisper.cpp `v1.9.5`，提交 `d1be6fde11ac6e0407606b4e42fe72d34add8037`，单 worker 构建；真实 tiny.en 模型的内存转写及运行中取消 **2 PASS**。这只证明该路径和指定样本，不是正式能力榜单或真实会议验收。
- 模型：`ggerganov/whisper.cpp`，Hub revision `5359861c739e955e79d9a303bcbc70fb988958b1`，`ggml-tiny.en.bin`，77,704,715 bytes，SHA-256 `921e4cf8686fdd993dcd081a5da5b6c365bfde1162e72b08d75ac75289920b1f`。这是英语模型；本轮没有据此宣称中文会议质量。
- 公共 WAV 为相同 whisper.cpp 提交的 `samples/jfk.wav`，11 秒，SHA-256 `59dfb9a4acb36fe2a2affc14bacbee2920ff435cb13cc314a08c13f66ba7860e`。
- 初次 systemd 解析发现 `WorkingDirectory` 不接受所用引号形式，已经修正并通过真实解析器复验。首次既有 Intel 回归中一条“非 macOS 均不支持会议”的旧断言随 Linux 新能力更新；未修改其真实恢复/来源断言。
- 独立复核发现：直接向 helper 发送 SIGTERM 时，停止事件虽已设置，正在等待转写结果的主线程未及时终止子进程。已增加等待停止事件的线程，在信号处理器外执行现有进程终止逻辑；真实 helper 的 SIGTERM / SIGINT 子进程回归均验证退出、无残留和无晚到文本。stdin stop 和控制器的进程组兜底保留，真实 whisper.cpp 转写及取消也重新通过。
- 独立复核还发现 PulseAudio JSON 字段假设错误：`pactl list sources` 的 JSON 使用 `monitor_source` 表示所属输出设备，而非 C 结构体中的数值字段名。按官方 v17.0 源码修正为空字符串/null 表示麦克风、非空输出设备名表示 monitor；未知结构报告不可用。新增实际 CLI 协议夹具验证分类和未知结构拒绝，真实声卡列表仍未验收。
- 原生 GTK 资格脚本使用独立 Xvfb、独立 D-Bus、自己创建的窗口，避免读取用户应用。当前环境 D-Bus 返回 `Failed to open socket: Operation not permitted`，原始失败保留；正式测试显式 SKIP/NOT_RUN。真实 GI 方法/枚举检查通过不能替代桌面采集通过。

普通回归：

```bash
python -m unittest companion.tests.test_linux_runtime companion.tests.test_linux_native -v
python -m unittest discover -s companion/tests -t . -v
```

真实 ASR 资格需显式设置 `LOCALPILOT_TEST_WHISPER_CLI`、`LOCALPILOT_TEST_WHISPER_MODEL`、`LOCALPILOT_TEST_WHISPER_SHA256`、`LOCALPILOT_TEST_WHISPER_WAV`，再运行 `python -m unittest companion.tests.test_linux_whisper -v`。普通回归不会自行下载权重；未提供材料时清楚 SKIP。

Linux 真桌面仍需补：AT-SPI 兼容应用、Wayland/X11 会话、真实声卡和 Pulse/PipeWire、通知可见性、systemd 登录、物理睡眠唤醒及实际中文转写。macOS TCC、Intel 真机等旧缺项仍按各自证据保留。

实现参考：[Linux power supply](https://www.kernel.org/doc/html/latest/power/power_supply_class.html)、[systemd.service](https://www.freedesktop.org/software/systemd/man/latest/systemd.service.html)、[loginctl](https://www.freedesktop.org/software/systemd/man/latest/loginctl.html)、[EWMH](https://specifications.freedesktop.org/wm/latest-single/)、[AT-SPI](https://gnome.pages.gitlab.gnome.org/at-spi2-core/libatspi/)、[FFmpeg Pulse 输入](https://ffmpeg.org/ffmpeg-devices.html#pulse)、[whisper.cpp CLI](https://github.com/ggml-org/whisper.cpp/blob/d1be6fde11ac6e0407606b4e42fe72d34add8037/examples/cli/README.md)。
