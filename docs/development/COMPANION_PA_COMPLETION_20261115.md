# Companion PA：来源、会议转写与训练准备

本轮基线为 PR #9 的 `0a7fdff`。此前 Mac 的晨间问候与授权 AX 摘录验收，继续以 [既有原生记录](../evidence/nationals-20261115-completion/PROGRESS_20261115_065014.md) 为准。本轮开发环境为 Linux x86_64；下文的协议与存储回归不能替代 macOS 编译、TCC、音频或真实模型验收。

## 完成的代码

`companion/runtime/service.py` 从 1706 行缩到约 542 行，保留生命周期、主线程事件循环和原有公开接口。观察、对话、Agent 任务及命令分派分别由 `ObservationController`、`DialogueController`、`TaskController`、`CommandRouter` 负责。它们使用组合，未创建另一个 Agent Runtime，也未用继承链拆分文件。原来的大段命令条件链改为显式 handler 表，移除了重复的命令判断。SQLite 仍只由服务线程写入。

在这一结构上，新增了显式来源连接、可溯源 Codex/会议摘录、会议音频转写控制器，以及人工审阅样本导出和本地训练启动器。普通复杂分析继续使用既有本地默认 Agent Service；宠物工具请求继续通过 Desktop 交接。此前 `accepted` → 异步执行 → 持久终态反馈的链路没有另造协议。

### 授权来源

| 来源 | 实际读取范围 | 不代表的能力 |
|---|---|---|
| Codex JSONL/JSON | 用户明确选择的单文件或目录中的可见用户/助手消息；CLI `event_msg` 或 `response_item` 消息，以及 `messages` 数组 | 不扫描默认私人目录；不读取未选择的隐藏历史；不导入已标识的 reasoning/analysis、系统环境、工具参数或执行收据 |
| 会议 TXT/MD/VTT/SRT | 用户明确选择的文字与字幕，保留行号及字幕 cue 时间 | 不证明会议发生日期、说话者身份或任务完成 |
| 本机会议 JSONL | 本轮会议 helper 的最终自动转写片段，标注 mic/system、分段及起止时间 | 自动转写可能误识别、重复或遗漏；不能作为事实核验或完整会议记录 |
| 既有 AX/文件观察 | 已授权且当前可读的静态窗口文字、既有观察目录 | 不保证所有应用通过 AX 暴露正文；既有排除项和 OS 权限继续生效 |

注册来源即表示对该选定范围的持续只读授权。默认每 60 秒利用现有循环检查一次；`follow=false` 只在显式同步时读取。暂停观察会同时阻止采集和检索，恢复后已有来源不要求重复授权。单次同步最多导入 500 个支持格式的文件、32 MiB 内容，每文件使用现有 `max_file_bytes`，每文件最多 2000 条有界记录；返回结果明确标注截断、错误、缓存命中与记录数量。

来源使用文件内容哈希和版本绑定，读取前后核对文件状态，拒绝符号链接和已有敏感文件名规则。文件变化、删除、停用或撤销会使旧摘录停止检索；损坏的新版本不会退回旧文本作答。来源撤销会删除对应观察及其依赖样本，不修改用户原始文件。已生成的独立导出文件需另行删除；清空 Companion 记忆会额外删除本程序生成的会议转写目录。

历史消息仍按原始时间归档；没有原始时间的导出明确使用文件修改时间，并提示这不能证明活动日期。原文保留期按实际导入时间开始计算，之后压缩仍保留来源定位、版本、时间依据和 epistemic。特别修复了一个状态失真：助手声明在压缩后仍为 `reported_unverified_text` / `MODEL_INFERRED`，不会因为正文被压缩而变成已核验事实。

“我今天在 Codex 做了什么？”、“会议讨论了什么？”等明确概览问法直接返回当前获准记录的可核对摘录，不调用模型。今天/昨天使用真实保留的 occurrence 时间；同一窗口跨日出现不会把昨天的问题答成今天的时间。更复杂的综合分析仍走已有模型和正式 Task API。

### 可运行的来源入口

Desktop 设置中的“Companion 已授权来源”提供来源类型、选文件/目录、同步、停用、恢复、撤销和覆盖报告。这个 UI 的原生文件选择与正式安装包整链路仍需本机验收。

下面以已有的隔离 Companion 配置为例，`CONFIG` 只指配置文件，不自动读取真实私人目录：

```sh
python -m companion --config "$CONFIG" --json source-connect codex /path/to/selected-rollout.jsonl --label '已选择的项目对话'
python -m companion --config "$CONFIG" --json source-connect meeting /path/to/selected-meeting.vtt --once
python -m companion --config "$CONFIG" --json source-list
python -m companion --config "$CONFIG" --json source-sync SOURCE_ID
python -m companion --config "$CONFIG" --json ask '我今天在 Codex 做了什么？'
python -m companion --config "$CONFIG" --json source-enable SOURCE_ID off
python -m companion --config "$CONFIG" --json source-enable SOURCE_ID on
python -m companion --config "$CONFIG" --json source-revoke SOURCE_ID
python -m companion --config "$CONFIG" --json source-coverage
```

JSON 命令名称为 `source_connect`、`source_list`、`source_sync`、`source_set_enabled`、`source_revoke`、`source_coverage`。连接参数为 `{kind,path,label?,follow?}`；同步/撤销使用 `{source_id}`；停用/恢复使用 `{source_id,enabled}`。同步结果区分 `ok/partial/empty/paused/disabled/unavailable`。

## 显式本机会议转写

已编写 `MeetingTranscriber.swift`，使用系统 Speech、AVAudioEngine 和 ScreenCaptureKit。用户明确开始时可选择麦克风、系统音轨或两者；双路分别转写并保留来源标签，不进行未经说明的混音。系统声模式在运行时要求 macOS 13 及相应系统录制权限，麦克风模式按 helper 的基础系统能力检查。独立 helper bundle 配置最低 macOS 11、Speech、麦克风与系统采集用途说明，构建目标也明确为本机架构的 macOS 11。没有切换日常 APP 的身份或签名。

每一路必须同时通过 `supportsOnDeviceRecognition` 检查，并设置 `requiresOnDeviceRecognition=true`。没有相应语言的本地识别能力、OS 拒绝或系统采集失败时，返回明确终态；没有云转写回退，也不会自动下载语音模型。只保存最终文字，不把 partial 片段写入记忆，不持久化音频或视频；ScreenCaptureKit 不注册屏幕图像输出。

50 秒轮转用于分段输出和限制 final 等待，不是宣称本地识别有官方“一分钟硬限制”。正常停止先停止采集，再给当前片段最多 10 秒返回 final；Python 等待 13 秒后才终止自己持有的 helper 进程。任何一路失败会结束整个会话，不悄悄从双路降为单路。自动转写的记录明确为未核验报告，无法独立验证发言人或内容真实性。

`meeting_stop`、暂停观察、当前来源停用/撤销以及确认清空记忆，在进入服务队列时就向 helper 发出停止请求。因此即使主线程正在等待模型，采集停止也不依赖模型先完成。正常结束会冲刷已采集的 final；暂停、撤销和清空会丢弃排队中的转写。清空会停止进程并删除本程序的会议文字文件，用户选入的外部原文件保持只读。服务重开只保留已有文字和状态，遗留活动会话标为 `interrupted`，不自动重新采集。

Desktop 设置提供显式开始/停止；设置关闭后，活动会话仍有全局可停止状态条。CLI 对应：

```sh
python -m companion --config "$CONFIG" --json meeting-build
python -m companion --config "$CONFIG" --json meeting-start --capture microphone --locale zh-CN --label '测试麦克风'
python -m companion --config "$CONFIG" --json meeting-status
python -m companion --config "$CONFIG" --json meeting-stop
python -m companion --config "$CONFIG" --json meeting-start --capture both --locale zh-CN --label '测试双路会议'
python -m companion --config "$CONFIG" --json meeting-stop
```

`meeting_start` 参数为 `{capture:'microphone'|'system'|'both',locale?,label?}`；另外两个 JSON 命令不需要参数。会话状态区分 `idle/starting/recording/stopping/stopped/unavailable/denied/failed/interrupted`。`status=active` 表示仍需在 UI 保留停止入口；失败并不等于已经取得真实会议完整记录。

**本轮原生编译、ad-hoc bundle 的真实 TCC 行为、麦克风/系统声采集、分段识别准确率及 Intel 机器运行均为 NOT_RUN。** Python 测试只验证真实子进程协议与存储生命周期，没有发出音频或冒充 Apple Speech。

Apple 官方接口依据：

- [requiresOnDeviceRecognition](https://developer.apple.com/documentation/speech/sfspeechrecognitionrequest/requiresondevicerecognition) 与 [supportsOnDeviceRecognition](https://developer.apple.com/documentation/Speech/SFSpeechRecognizer/supportsOnDeviceRecognition)。
- [Speech 授权说明](https://developer.apple.com/documentation/Speech/asking-permission-to-use-speech-recognition)。
- [ScreenCaptureKit capturesAudio](https://developer.apple.com/documentation/screencapturekit/scstreamconfiguration/capturesaudio) 与 [sampleRate](https://developer.apple.com/documentation/screencapturekit/scstreamconfiguration/samplerate)。
- [ScreenCaptureKit 框架说明](https://developer.apple.com/documentation/screencapturekit.md) 对应 `NSScreenCaptureUsageDescription`；helper 与 Desktop 主 APP 都包含用途声明，实际 TCC 归属需本机检查。
- [WWDC19：Advances in Speech Recognition](https://developer.apple.com/videos/play/wwdc2019/256/) 明确区分服务器限制和本地识别能力。接口文档核验不能替代本机 SDK 编译与音频实测。

## 人工审阅样本与可执行训练启动器

新 `TrainingExamples` 与自动观察记忆分开。只有用户明确保存的最终问答可成为标签；目的为 `greeting`、`activity_qa` 或 `handoff`。工作问答必须绑定当前可读的 observation ID。不会把历史助手回答自动当正确答案，不保留已标识的推理块，也不会因接入来源而开始训练。

导出重新检查来源是否仍可读取。来源失效时停止导出；遗忘、撤销及保留期删除会移除关联样本。数据以来源连通组划分 train/valid，相同文件内容的复制和跨来源样本不会跨分割泄漏。至少两个独立组只是拆分约束，不能证明样本数量或质量足够。导出包含私有文字，写入自己的 0700 目录和 0600 文件；manifest 保存源版本、分组、样本、哈希、随机种子，明确 `training=NOT_RUN` 和 `quality=NOT_EVALUATED`。已导出的独立文件不随来源停用自动销毁，界面与返回值会说明这一点。

```sh
python -m companion --config "$CONFIG" --json training-example-add --purpose greeting --question '早上好' --answer '早上好，需要时可以来找我。'
python -m companion --config "$CONFIG" --json training-example-add --purpose handoff --question '帮我修改项目代码' --answer 'NEEDS_AGENT'
python -m companion --config "$CONFIG" --json training-example-add --purpose activity_qa --question '这条记录里讨论了什么？' --answer '这里填写人工核对后的最终回答，并说明来源和未知项。' --observation-id OBSERVATION_ID
python -m companion --config "$CONFIG" --json training-examples
python -m companion --config "$CONFIG" --json training-example-delete REVIEWED_ID
python -m companion --config "$CONFIG" --json training-export --seed 17 --validation-fraction 0.2
```

上面只演示命令，不是建议用三条样本训练或宣称能力提升。Desktop 可导出已审阅样本；保存/删除样本目前通过这些 CLI/API 入口。

`companion.model.finetune` 复用仓库已有 MLX-LM，不引入训练框架。启动器固定核验 **mlx-lm 0.31.3**，本机已有训练依赖要求为 `mlx-lm[train]==0.31.3`。它不会安装依赖、下载模型或数据。仅接受已有本地模型与审阅导出，核验文件哈希、训练/验证样本、量化类型及实际 tokenizer 长度后，显式运行官方 `python -m mlx_lm lora --config ...`。离线环境变量、关闭远程日志、独立输出目录、退出码/日志/权重产物收据均由启动器设置；默认只生成计划。

```sh
python -m companion.model.finetune --model /path/to/local-model --data /path/to/reviewed-export --output /path/to/new-plan
python -m companion.model.finetune --model /path/to/local-model --data /path/to/reviewed-export --output /path/to/new-run --iterations 100 --rank 8 --layers 4 --execute
```

计划与执行使用不同的新输出目录。缺平台或依赖时准确保持 `NOT_RUN`；超出 tokenizer 预算时不悄悄截掉训练目标。成功结束也只证明产生训练产物，不证明质量改善，不自动融合或替换当前 Companion 模型。

参数依据来自 [PyPI 0.31.3 发布 provenance](https://pypi.org/project/mlx-lm/0.31.3/#files) 指向的精确 commit `ed1fca4cef15a824c5f1702c80f70b4cffc8e4dd`，已读取该版本的 [lora.py](https://github.com/ml-explore/mlx-lm/blob/ed1fca4cef15a824c5f1702c80f70b4cffc8e4dd/mlx_lm/lora.py)、CLI 和数据加载器源码。20 个生成配置字段全部属于该版本真实默认配置；源码与核验 JSON 保留在本地 validation 中。

两个具体版本限制已落实：

1. 0.31.3 的 LoRA 入口硬编码 tokenizer `trust_remote_code=True`，并不支持新版的覆盖参数。因此启动器不添加无效字段，拒绝 custom `auto_map`，且 tokenizer 预检不信任远程代码。
2. 上游 `fine_tune_type=full` 解冻的是选定 Transformer 层，默认本启动器选全部层；不包含 embedding/head，收据明确其实际范围。量化模型不走这一 dense 训练入口。不能把它称作完整模型所有参数训练。

实际 LoRA/dense 训练、显存和磁盘峰值、基线/候选 A/B、泛化质量、候选模型加载均为 **NOT_RUN**。强化学习没有在现有框架中新增实现。程序化问候仍然不需要唤醒模型，训练也不会替代既有权限和出处逻辑。

## 验证结果与保留的失败

本轮前的 Companion 基线为 **583 项：558 PASS、25 SKIP、0 FAIL、0 ERROR**。职责拆分后先通过 129 项定向回归；随后逐步验证新增来源、审阅样本与会议控制器。

- 来源首次 16 项有 2 个夹具错误：把 `sensitivity='private'` 元数据误当保留的推理文字，以及选择了现有敏感文件名规则并不匹配的测试名字。修正夹具后 16 项全部通过，原日志保留。
- 会议首轮共 61 项有 1 个真实 ERROR：已退出 helper 的 stdin 在最终 close 时仍可能抛 `BrokenPipeError`。修复按真实 Popen 对象等待和关闭后，61 项全部通过；还补充了协议失败不能被正常 stop 状态掩盖的断言。
- 全 Companion：`python -m unittest discover -s companion/tests -t . -v`，**630 项，605 PASS、25 SKIP、0 FAIL、0 ERROR，36.166 秒**。25 项是既有平台限制，未计为通过。
- 最后的来源时间依据/文字边界调整后，活动、来源、会议 47 项全部通过。
- 原生只读审查建议的用途声明补齐后，最终新增功能定向 61 项全部通过；Codex payload 类型白名单最终调整后的来源 18 项全部通过。对应 `companion-20261115-final-r3.log` 与 `companion-20261115-source-final.log`。
- `git diff --check -- companion` 与 Python 编译检查通过。原生 helper 源码由独立代理只读复核；本机没有 Swift/macOS SDK，不能把源码审查写成编译通过。

本机原始日志位于工作目录外的 `validation/`：`companion-20261115-baseline.log`、`companion-20261115-refactor-r2.log`、`companion-20261115-sources-r1.log`、`companion-20261115-sources-r2.log`、`companion-20261115-training-r1.log`、`companion-20261115-meeting-r1.log`、`companion-20261115-meeting-r2.log`、`companion-20261115-full-r1.log`、`companion-20261115-full-r2.log`、`companion-20261115-final-focus.log`、`companion-20261115-final-r3.log`。精确训练接口核验为 `companion-mlx0313-interface.json`。所有负面记录保留，不因最终通过而删除。

## 本机 Work 继续验收

在隔离配置与独立测试 APP 中检查当前 HEAD、wheel 内源码和已授予权限；保留日常 APP、已有服务和模型。先以自己准备的合成对话/字幕验证来源接入、原文件哈希不变、问答来源定位、停用/撤销/重开、保留期与训练样本导出，再按实际需要选择真实来源。

会议部分先运行 `meeting-build`，记录 Xcode/Swift/macOS/架构、构建和 codesign 输出；分别测试 microphone/system/both 的权限允许、拒绝和不支持场景。确认直接启动 bundle 内二进制时 TCC 授权究竟归属 helper 还是负责进程，不能仅凭 Info.plist 存在判定可用。检查 Desktop 全局采集状态、设置关闭后的停止入口、语言离线能力、分段边界、无语音段、停止后的 final、暂停/撤销/清空/服务退出、来源检索及无音视频落盘。至少做 110 秒的跨轮转测试、49–55 秒之间停止、静音时停止；pending 分段的结束时间必须取实际停止时间，不能取稍晚的 final 回调时间。两路各播放或说出不同合成短句，核对 mic/system 标签；不要用纯 JSON 子进程测试代替真实音轨验收。若无法通过 on-device 能力检查，保持 unavailable，不启用云回退。

晚间问候和真正睡眠/唤醒需在实际时间与 OS 事件下验证，不修改系统时间。晨间既有 PASS 引用原记录，本轮没有把软件回归扩写为新的原生 PASS。

训练先核对已有本地模型、精确依赖、可用内存/磁盘和足够的人工审阅数据，使用独立输出目录。没有可用资源或数据就如实 NOT_RUN；不为填满状态而临时下载大模型。真训练后再检查 held-out loss、出处准确率、拒答/委派、问候体验和性能，保存基线与候选结果，再决定是否集成模型。所有记录分别写 PASS/FAIL/NOT_RUN、真实环境和限制。
