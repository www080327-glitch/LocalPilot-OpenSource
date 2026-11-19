# RC19 续作验收（2026-11-19）

**NOT_RELEASE_READY。** 本轮修复了实际首次使用、模型配置、历史检索、角色导入和拖动状态问题，完成主要组件回归及 Linux 包构建与包内运行验证。Linux 窗口启动被当前环境缺少 WebKit 系统子进程挡住；浏览器页面断言、RC19 Mac 安装和真实可见动画没有通过记录。不能据此宣称全部要求完成、没有 Bug，或任何新手都能独立完成所有操作。

实现说明：[RC19 续作](../../development/RC19_FOLLOWUP_20261119.md)。完整要求状态：[需求核对](../../development/REQUIREMENTS_AUDIT_20261119.md)。剩余工作：[可执行 Work 任务](../../development/WORK_RC19_ACCEPTANCE.md)。

## 受测源码与版本

| 项目 | 标识 |
|---|---|
| 原始 RC18 基线 | `fe9765c69ce8a39e8a3682d61ceb67c86894c3b4` |
| 最终本地受测源码 | `02838a5db0b342647fc0f7904738bee87f167cf0` |
| 同一文件树的 GitHub 源码 | `26ae7a1a1ace2a6d0200121b1ef14e4ea4baf9e1` |
| 最终源码 tree | `3983bab60b25a6e60515e4baaaf221b6f27f9f7a` |
| 版本组合 | Desktop `5.0.1-rc.19` / Core `5.0.0b36` / Suite `0.2.0b35` / Companion `0.5.7b12` / Channels `0.1.0a4` |

CLI 没有 GitHub HTTPS 写凭据，代码通过已连接的 GitHub 工具发布；提交元数据不同，文件内容与 mode 相同。最终源码已从远端重新拉取，整树比较一致。前一冻结点 `05a5dd7` 对应公开 `c65ab45`，随后补入 Unicode 检索和 Linux Wayland 坐标修复。见 [PUBLIC_SOURCE_MAP.json](PUBLIC_SOURCE_MAP.json)。

本报告和 Channels 文案断言更新发生在产品冻结之后。Channels 测试文件单独执行了下面的 86 项回归，产品文件不变。完整回归和 DEB 对应上述产品树，不把后续文档提交冒充重新受测的二进制来源。用户附带的 RC18 Mac 报告与公开 `fe9765c` 报告字节相同，SHA-256 为 `6572578e9c51ec37a090e32e3d13d6cb3e8f8a920cf7651d5d6d0917baef1761`。

## 这次具体修了什么

- **纠正密钥真正生效。** 保存新密钥会更新既有后端引用，清理旧环境变量密钥的优先级；其他模型、工作区与旧会话保留。Companion 恢复失败时回滚配置，成功后刷新模型列表。
- **首次使用不再卡在已知死路。** MLX 只出现在 macOS arm64；跳过下载实际进入下一步；未连接模型的完成页明确说明并能返回。仅发现一个模型时自动选择；切换地址清空旧模型与旧上下文预算。
- **升级与任务状态准确。** 页面可停止阻挡升级的 Core/Companion；仍在停止时不显示已停止。新计划按自身 ID 读取收据，避免继承旧成功或错误。目标按真实 `done` 状态计数和显示。
- **同一角色可导入基础动作。** 选择原始 `pet.json` / `spritesheet.webp` 文件夹并启用基础动作，不再以缺失的私人扩展姿态包作为基础显示的前提。开关独立保存，RC18 偏好格式不变。没有重画或公开私人画作。
- **拖动与动画测量更准确。** Mac 按相邻位移识别反向；Linux 使用真实鼠标释放和窗口位移。实际 X11 后端才能报告全局坐标，Wayland 不把缓存零点当成位置。采样排除未加载、透明祖先及屏幕外元素，完整阶段时长包含停顿；没有阶段明确返回 `NO_ANIMATION_STAGES`。仍需真实可见像素验收。
- **主会话可检索原文。** 同一持久会话、同配置身份可搜索可见用户/助手文字并按引用、偏移分段读取；普通云端遵守既有可披露范围。中文和表情按字节预算裁剪正文，引用及偏移保留。子代理未继承绑定父会话的召回工具。
- **扩大可轮换会话范围。** Adaptive、精确云授权及满足静止条件的 Computer 会话保留预算、授权和恢复要求后轮换。显式较新 worker 模型使用既有 Responses 适配器，没有新增运行时。

## 最终执行结果

| 范围 | 结果 | 实际边界 |
|---|---|---|
| Core 全量 | **1,636 PASS，99 SKIP，0 FAIL/ERROR** | 1,735 项，235.996 秒 |
| Companion 全量 | **730 PASS，33 SKIP，0 FAIL/ERROR** | 763 项，44.597 秒 |
| Suite 全量 | **127 PASS，1 SKIP，0 FAIL/ERROR** | 128 项，91.848 秒 |
| Channels 五份 Node 测试 | **86 PASS，0 SKIP/FAIL** | 3.081 秒，最终测试断言单独更新 |
| 桌面 Vitest | **78 PASS，0 FAIL** | 15 个测试文件 |
| 原生 Rust 默认集 | **63 PASS，3 ignored，0 FAIL** | 最终源码上的真实 Rust 测试 |
| 原生真实 Core 恢复与身份 | **1 PASS** | 单独执行默认忽略用例；真实丢失 POST 回复后同键恢复、关闭会话拒绝和身份隔离 |
| 原生离线 Release 查询 | **1 PASS** | 单独执行默认忽略用例；仅该进程使用不可达代理，结果保持 UNKNOWN |
| DEB 包内 Python | **27 PASS，0 FAIL/ERROR/SKIP** | Python 3.13，`-I` 隔离执行；8 项原文检索、19 项 Companion 存储/历史 |
| 前端生产构建 | **PASS** | 最终源码的 TypeScript + Vite |
| Playwright 收集 | **72 个用例／22 个文件** | 仅收集，不能算 72 项页面通过 |
| 五份改动页面用例严格类型检查 | **PASS** | 全部页面的额外严格检查因可选 Node 类型缺失受阻；生产构建通过 |
| Playwright 页面执行 | **BLOCKED_AT_LAUNCH，0 页面断言** | 锁定 Chromium 缺失；既有系统 Chromium 入口在单例 socket 创建时 EPERM、SIGABRT |
| 原生 GUI | **BLOCKED_BEFORE_WINDOW，0 界面断言** | 经真实桌面文件管理器启动最终提取的 Test ELF，未出现 LocalPilot 窗口 |

Core 定向的 130 项、worker 模型/传输 69 项等与全量有重叠，不累加成独立覆盖总量。Rust 第三个默认忽略用例依赖认证的 GitHub 下载与旧 Mac 制品，本轮未执行。两个显式重跑不改写原默认集的 ignored 数字。跳过不是通过。

## 保留的失败与原因

1. Core 首次环境缺 `defusedxml`，MCP/packaging 与锁定依赖不一致，并有一次本地健康检查调度失败。按既有依赖恢复后重跑；初次日志保留，不计为通过。
2. 第二次 Core 的超时测试依赖固定 80 ms 休眠等待 50 ms 定时器，在负载下偶发失败；原用例单独复测三次通过。测试改为等待实际取消状态，50 ms 任务期限、最终超时与不多产出内容的断言不变，产品超时行为没有放宽。
3. Channels 首次 76 通过、10 失败，测试仍期待旧中文提示与旧完成前缀；现有文案来自早先 `1fca748`。仅更新 11 处文本断言，任务归属、调用次数、重启去重、阻塞和禁止重放检查保留。最终 86 项通过。
4. 新检索入口的 Unicode 结果曾超过工具字节预算，引用结构被截断。这是真实产品问题。修复后经 Registry 网关完整重建含非 BMP 字符的长回答，并保留十条搜索引用；原失败日志保留。
5. 原生启动实际缺少 `/usr/lib/x86_64-linux-gnu/webkit2gtk-4.1/WebKitNetworkProcess`。官方 Debian WebKit 包含该文件，RC19 DEB 已声明依赖。当前为 uid 1000，无 sudo、受支持安装 helper 或可写系统库目录；私有依赖目录满足编译/动态链接，不能完成正常系统依赖安装。没有修改系统固定路径或关闭 sandbox。动画未采样，帧率为 `null`，不是 0 Hz。

## Luna 失败与真实模型证据

R10 的 4096 输出截断、Parser 保留桩代码是真实工程失败。现有恢复允许首次截断后在**同一个子任务、原预算内**继续一次，丢弃截断响应的提案及不完整重放材料，保留此前收据；再次截断仍停止。最终 Core 的八项相关测试包括实际读文件、同 child 继续写代码、该 child 运行 unittest，以及持久化重启、取消与预算边界。

测试由脚本提供方安排响应，证明机制可用，**不是 RC19 的真实 Luna 工程复验，也不证明原 Parser 夹具已被 Luna 修好**。本轮没有付费模型调用，没有提供方可用性或总体成功率新结论。此前 R9 Luna high 成功、R10 Luna high 失败、R11 Sol medium 成功、R12 Luna medium Full 成功分别保留。R12 及 7,219.684 秒／240 心跳长任务属于原版本，不能套给 RC19。密钥少一字符与 TLS EOF 有独立原因，不能统归模型能力。

## 安装包与不丢记录的降级检查

`LocalPilot-Test-5.0.1-rc.19-linux-x86_64.deb`，114,653,166 字节：

```text
SHA256 f9dc2361e767533d31ad1f80acec14423a402ad34e4c0ec16bc550ab71c2b8fc
```

提取 ELF 的 SHA-256 为 `6696d9ada3ee619c76334c6adbf416dca7f0ca79f632642d65253d25af368290`。构建前后 3,906 个受跟踪源码项不变。四组件包中 289 份 Python/Swift 文件逐字匹配最终源码，40 份 wheel 散列通过；测试加载的 127 个产品模块均来自提取 runtime 的 `site-packages`，没有源码路径覆盖。

这些是构建、包内容与包内执行结果，**本轮没有系统 apt/dpkg 安装完成记录**，不能替代 Debian 桌面首装、升级、回滚和物理操作。

Core 新索引保持 schema 3：候选创建 4 个任务，未修改 RC18 打开同一数据库并新增 3 个任务，候选再次打开，召回升级前及降级期间原文并写入第 8 个任务。三个独立进程的任务快照和归档散列核对通过；没有恢复旧备份、删除历史或修改旧版源码。数据库兼容性不替代 Mac APP 安装循环。

## 桌宠素材及尚未关闭的范围

RC18 最新 Mac 采样没有动画阶段，应记 `NO_ANIMATION_STAGES`；旧报告的 0 Hz 不代表本轮有效测量。上传报告的三条页面结果均为 `expected`，聚合统计却为零；派生审阅指出该问题，历史证据原样保留。

另行提供的 `LocalPilot-RC19-Personal-Pet-Atlases.zip` 含 fywdy 上游提交 `d5bbb27c79e5c08e8b8ab44d4023cd35a67418e2` 的八套原始基础图集，图像与元数据字节未改。图像按 CC BY-NC 4.0、JSON 按 MIT，附署名、许可和中文导入说明，仅供个人非商业导入，未打入产品发行包或提交本仓库。它不能补出原私人高级姿态。ZIP SHA-256 为 `3d7e2dec830bb44f1cdc5e35e39fa1b2f7de88ce4d014c729b75b0aa73b6e6ac`。

仍未关闭：

- RC19 Apple Silicon APP 安装循环、真实 Intel Mac、具备正常系统依赖的独立 Debian 桌面。
- 本轮完整页面实际执行；角色可见性、至少 24 Hz 的可见变化、实际拖动反向与释放、六锚点、不同缩放与多显示器。
- 无终端常用任务的新手观察；真实模型、音轨、睡眠/唤醒和具体 provider 的缓存表现。
- **单个超长活动任务的增量持久化未在 RC19 实现。** 96 次真实文件读取后，边界检查点为 2,684,179 字节／约 84.0 ms，最终 TaskRecord 后为 4,914,062 字节／约 153.5 ms。这与已解决的一万条 Companion 历史按条查询不同，是正在另外推进的源码工作，不能归为硬件阻塞。见 [Runtime 说明](../../development/RC19_RUNTIME_FOLLOWUP.md)。
- 跨任意配置身份的原文召回、通用 Linux GUI 操作型 Computer Use、所有 HTTP 服务的持久 KV 等仍有实现边界；需求表逐项记录。

## 证据组织与发布状态

五组确定性归档为 `runtime.tar.gz`、`desktop-ui.tar.gz`、`desktop-native.tar.gz`、`reviews.tar.gz`、`provenance.tar.gz`。逐成员大小和 SHA-256 见 [EVIDENCE_MANIFEST.json](EVIDENCE_MANIFEST.json)，快照散列见 [SHA256SUMS](SHA256SUMS)。[UI_RESULTS.json](UI_RESULTS.json) 区分页面执行与仅收集；[RUNTIME_REVIEW.json](RUNTIME_REVIEW.json)、[包内验证](NATIVE_PACKAGE_RESULTS.json) 与[真实窗口启动结果](NATIVE_GUI_RESULTS.json) 记录受测范围；[LOG_SUMMARY.json](LOG_SUMMARY.json) 只提取实际日志尾部，不合并重复测试。

材料不含凭据、用户数据库、私人素材、模型、环境或二进制包。PR #15 保持 open，未合并，未创建 Tag/Release。最终产品 head 的 GitHub 查询未返回关联 PR workflow 或 commit status，空列表不能算 CI 通过。
