# Desktop / Companion 用户层审计 — 2026-11-17

本轮在 `b420b97` 之后审查 Desktop 的聊天提交、首次设置、产品设置、桌宠事件、素材、原生窗口和动画路径，以及 Companion Swift 推理卡片、通知和菜单栏展示。修改集中在用户实际会遇到的行为与这些路径的维护成本。未改个人角色图集、生成的产品美术、日常配置或旧验收证据。

独立计数为 **8 个 bug、5 个维护项、4 个一步操作改进、3 个过度防御清理，共 20 项**。每项仅归一个类别。OpenAI 一键配置与长任务预算是跨组件功能，下文记录 Desktop 接线，但不在这 20 项之外重复计数整个功能。

## Bug 修复

| 编号 | 原行为与实际后果 | 修改 | 验证 |
|---|---|---|---|
| D-B1 | 原生动画固定等待 50 ms，调度上限约 20 fps；图集帧还以 130 ms 间隔切换 | 可见窗口用 30 Hz `tokio::time::interval`，错过 tick 时跳过积压；进度按真实经过时间计算，隐藏窗口仍低频休眠 | 实际 Linux WebKit 两次点击采样，4 个动作阶段的视觉变化平均 26.79–29.46 fps；真实 `advance` 单测 |
| D-B2 | 指定当前同侧的锚点也会被替换成随机对侧，按钮含义与结果不符 | 显式锚点原样采用；只有未指定锚点的身体点击才选对侧 | 全部锚点对单测；原生从左上点“左边探头”，窗口落到 `(0, 402)` |
| D-B3 | 浏览器的系统减少动态效果只影响 CSS，Rust 的缩回、探出和位置动画继续播放 | `matchMedia` 初值与变化传给 native；系统偏好、应用动画开关、安静模式共同决定是否动画。关闭时直接完成定位 | 实际 hook 的系统偏好动态切换测试；原生关闭动画后的 6 秒采样无动作阶段，点击直接换位 |
| D-B4 | DeepSeek 身份在底部总是选可选 `comic`，没有该扩展时整个角色不可见 | 仅在扩展真实存在时使用；否则使用已加载的边缘姿态 | 可选扩展缺失单测；原生夹具故意使用 DeepSeek 前缀且无 comic，底部可见 |
| D-B5 | 用户取消导出文件对话框后，界面仍显示“已导出 undefined” | 消费明确的 `cancelled` 返回值；只有实际路径结果显示成功 | 真实 React 控件测试（仅 native transport 被替代） |
| D-B6 | 用户取消导入素材后，将 `{cancelled:true}` 当成新素材覆盖当前角色状态 | 取消时保留已有素材 | 导入取消后角色标签仍为原角色的 UI 断言 |
| D-B7 | 文本清空后输入区高度遗留；首次隐藏气泡展开和连接提示消失后也可能沿用旧尺寸 | 输入内容、视图、展开及显式聚焦时重新测量输入区；气泡高度同时响应服务连接状态 | 多行发送后输入区收缩测试；原生确认首次展开的后续收尾原因，最终整包复核该新增尺寸触发 |
| D-B8 | 主界面全局 `button:hover` 命中宠物浅色界面，产生深底深字；原生设置中的高级入口和停止按钮文字难读 | 以零特异性 `:where` 将主界面通用 hover 规则限定在非宠物页面，保留宠物已有主题 | 原生首次截图保存失败外观；最终整包复核 hover |

主要源码：[pet_native.rs](../../desktop/src-tauri/src/pet_native.rs)、[pet_edge.rs](../../desktop/src-tauri/src/pet_edge.rs)、[Pet.tsx](../../desktop/src/Pet.tsx)、[useReducedMotion.ts](../../desktop/src/pet/useReducedMotion.ts)、[style.css](../../desktop/src/style.css)。

## 维护成本

| 编号 | 原问题 | 修改与边界 | 验证 |
|---|---|---|---|
| D-M1 | 每次求图集帧边界都重新扫描该行的 8 帧 Alpha；它位于动画热路径 | 素材加载时一次计算 11 行共享裁剪框，`Atlas::frame_rect` 只做坐标运算。保留逐像素 Alpha 供真正命中测试 | 从实际 PNG 解码验证空行、跨帧共同裁剪和注册位置 |
| D-M2 | Pet 与 EdgeCharacter 分别维护异步 Tauri 事件注册、取消和晚到的 unlisten | 共享 `petEvents`，两处使用同一个注册/销毁生命周期 | 实际事件桥接、严格模式组件挂载、偏好实时变化与聚焦测试 |
| D-M3 | 状态推进与 Tauri 窗口 I/O 混在一个 tick 中，难以直接检验轨迹和时序 | `advance` 承载真实状态推进，生产 tick 调用它；窗口移动与事件发送留在外层 | 测实际 `advance` 的完整经过时间轨迹、目标位置、减少动画，而非在测试复制实现 |
| D-M4 | `bubble_origin` 虽有单测，但生产 `follow` 另写一套几何算法，测试未覆盖真实位置算法 | `follow` 改用实际被测的锚点几何函数 | 工作区边缘、负坐标显示器、小工作区、2 倍物理比例坐标测试 |
| D-M5 | 首次设置与产品设置各有一套密钥输入、忙碌状态和连接反馈 | 共用 `CloudProviderForm`，保留两处不同的准备/刷新回调。提供商与模型选择属于同一个表单 | OpenAI 参数、密钥清空、不进入 localStorage、已有配置保留原密钥提示的 UI 测试 |

主要源码：[pet_assets.rs](../../desktop/src-tauri/src/pet_assets.rs)、[events.ts](../../desktop/src/pet/events.ts)、[CloudProviderForm.tsx](../../desktop/src/components/CloudProviderForm.tsx)。

## 一步操作

| 编号 | 以前的路径 | 现在的路径 | 验证 |
|---|---|---|---|
| D-U1 | 轻聊断线要进入高级设置找启动服务；聊天区的重试按钮没有可重试问题时也出现 | 聊天区直接“连接轻聊服务”；只恢复连接，不重新发送问题 | UI 断言没有 `pet_chat`；原生先停止独立服务，再从聊天区一键恢复 |
| D-U2 | 不支持 MLX 的平台只能看到需要去主窗口手动寻找模型库的说明 | 宠物高级设置直接打开主窗口模型库 | UI 验证 `pet_core(models)`；主窗口已有时发导航事件，未创建时带 `view=models` |
| D-U3 | 简单相对提醒也需填写日期和时间 | 输入内容后直接点“10 分钟后提醒”或“30 分钟后提醒” | UI 校验真实提交的时间差；原生 SQLite 记录 599.995 秒差值的提醒，没有模型调用 |
| D-U4 | 手动打开气泡后还需点输入框，原窗口已展开时 focus 请求会被早退吞掉 | 显式打开和返回聊天会聚焦输入；自动提醒仍不请求输入焦点 | UI 聚焦断言；原生打开后直接输入 `native-focus-check`，保留未发送并清空 |

## 过度防御清理

| 编号 | 原成本 | 修改 | 保留的入口约束 |
|---|---|---|---|
| D-O1 | 自己生成的 Render JSON 在命中、帧记录、窗口更新时再按字符串键解析，多处补默认值，掩盖内部形状错误 | Rust 内部使用 `RenderPart` / `Render` / `Presentation`；前端使用对应类型；只在命令和事件边界序列化 | 导入素材和外部配置仍在入口校验 |
| D-O2 | 8 列、11 行的内部帧索引由确定的状态机生成，却每次索引再 `min` 截断 | 删除热路径重复截断，使用状态机保证的行列索引 | 图集尺寸和格式仍由解码入口验证，方向与帧索引有实际实现测试 |
| D-O3 | 没有生产调用者的 `pose` RPC 维护验证、锁和写入；下一 tick 又覆盖该姿态 | 删除这条未使用动作入口及其重复验证，姿态由动画路径统一产生 | 真实 `drag`、系统动态效果、设置等入口仍保留其有效校验 |

## 跨组件接线

### 云端连接

`configure_cloud_key` 接收可选 `provider` / `model`，默认仍为 DeepSeek。入口只允许既有两种提供商；私有密钥文件按提供商命名。Suite 已负责事务式服务重启，UI 不再追加激活操作。新表单同时服务首次设置和产品设置。

独立复核指出 Suite 的 `already_configured` 会保留原密钥。表单据此明确提示“已有配置，保留原有密钥”，不声称替换成功。配置也不会切换当前 Session，因此成功信息准确写为可以在模型选择器选择该模型。具体 API 可用性仍由实际任务结果决定；本轮 UI 验证没有使用真实 API key。

Companion Swift 推理卡片原来将所有云端咨询标成 DeepSeek；改成云端通用标题，具体模型仍显示后端 `model` 字段。Linux 无 AppKit，本轮不宣称 macOS 原生编译或通知实测通过。

### 长任务

任务提交显式携带 `timeoutSeconds`，Rust 转为 `timeout_seconds`。提供 600 / 14400 / 86400 秒三档，分别映射 standard / extended / extended 执行预算；预算和工具权限分别处理。现有 Session 使用成对的 `execution_budget` / `expected_execution_budget` 做 profile 更新，新 Session 直接携带预算。旧服务缺少 `desktop_execution_budget_v1` 时不开放长任务选项。

草稿和任务快照恢复时保留真实时限。UI 测试验证 24 小时 + extended + workspace 的组合，以及同一 Session 恢复普通任务时发送 standard / expected extended。后端的有限步骤、工具、子任务和累计预算由 runtime 审计记录，此处不重复计数。

## 验证与实测

- `cargo test --manifest-path desktop/src-tauri/Cargo.toml --offline`：**56 passed / 3 ignored / 0 failed**。3 个 ignored 是两个显式外网维护验收和一个需真实 Core 夹具的测试，不是平台测试全部通过的证明。
- 新增 pet 针对组：**14 passed**，覆盖真实图集解码、状态推进、渲染、命中与气泡位置。
- TypeScript：`tsc --noEmit` 通过。
- 新增 UI 用例：**7 passed**，业务 React 实现照常运行，仅 native transport 使用测试返回。最终状态分支的完整结果见 [browser-run-7](../../desktop/docs/evidence/audit-20261117-desktop/browser-run-7/output.log)。
- 原生：Linux WebKit + 独立 profile D；首次素材显示、身体点击换边、同侧锚点按钮、手动打开焦点、应用动画开关、十分钟快捷提醒、断线恢复及只停止自有进程全部有截图/记录。

| 原生 6 秒采样 | 动作阶段 | rAF 观测机会 / 秒 | 已布局视觉变化 / 秒 |
|---|---|---:|---:|
| 身体点击 1 | RETRACTING | 56.52 | **29.10** |
| 身体点击 1 | PEEKING | 59.75 | **29.46** |
| 同侧锚点 2 | RETRACTING | 61.62 | **26.79** |
| 同侧锚点 2 | PEEKING | 60.88 | **29.25** |

这里测的是实际 WebKit `requestAnimationFrame` 中读取到的 sprite 布局、透明度、transform 和裁剪坐标变化，统计每个完整动作阶段的平均值。rAF 观测机会与视觉变化分别报告；它不是显示器光学测量，也不声称每个相邻帧间隔都恒定。原生窗口只在角色完全缩回后迁移到目标边，连续动作在小窗口内部绘制。图集每方向只有 8 张源帧，重复播放与连续变换达到 30 Hz 目标；没有将其描述为 24 张独立手绘帧。

测试主机实际 DPR 为 1。2 倍 DPI 的物理几何有 Rust 测试，但没有把它记成真实 Retina / 多显示器 macOS 验收。Mac 专属 Alpha 命中与玻璃材质也不冒充 Linux 可验证项目。

## 候选来源和证据边界

原生 D 是用于桌面 UI 的混合候选：后端源码/资源来自已核验的 `59fad12`（Core b26、Suite b31、Companion b7、Channels a3），覆盖当前 Desktop 的 75 个源文件。它不是本轮全部新源码的最终发行包。DEB 未系统安装。

- 混合 DEB SHA-256：`675d45c81ddd41c5bf7aee4b7595d3aac3e44b303c6e6c19e4d8cdeee89ad45f`，114,619,022 bytes。
- 提取 ELF SHA-256：`c79066b761da62eb9944ab7f0c42f097035b0a669153ecc3e6a7da41703a24d8`。
- D 运行结束：`STOPPED`，`owned_remaining=[]`。
- D 使用 `backend=disabled`，观察和云端自动调用关闭；任务 journal / checkpoint、训练样本、观察记录均为 0。仅创建一条私有测试提醒。
- 两个原生可见尺寸/hover 收尾及最终云文案发生在该混合候选之后，源码和原候选 SHA 已分别保留；它们须由最终全源包的短原生验收覆盖。

证据入口：[原生结果](../../desktop/docs/evidence/audit-20261117-desktop/native/RESULTS.md)、[动画原始摘要](../../desktop/docs/evidence/audit-20261117-desktop/native/animation-summary.json)、[无模型调用与私有数据库计数](../../desktop/docs/evidence/audit-20261117-desktop/native/native-no-model-requests.json)、[Rust 完整输出](../../desktop/docs/evidence/audit-20261117-desktop/rust-tests.log)。旧 A/B / alias 以及上一轮 final-package-smoke 证据没有修改。

首次失败全部保留：命令环境 Chromium socket 限制、桌面终端缺 Node PATH、旧开发服务被复用、代理导致本机端口探测误判、一个测试选择器不匹配，以及归档构建目录缺 Git 元数据导致打包报告失败。它们都没有被删成“首次全通过”；修正后使用新 evidence 子目录继续。最后一项仅补齐隔离 stage 的提交身份并重新输出包报告，未改编译好的桌面 ELF。
