# Work 接力：仅补真实设备与受阻验证

这是 2026-11-16 Intel 优先续作的接力提示词。源码与云端可执行的回归由本轮完成；下列工作需要 Intel/macOS、真实模型、系统授权或当前云端缺少的运行条件。请完整复制代码块给本机 Work。

```text
继续 LocalPilot 的真实设备验收。仓库：https://github.com/www080327-glitch/LocalPilot-OpenSource 。

先读取最新 main、PR #11 的 47e39faf3e97fbd13a562a9ec74efa30dfcc7b42 基线和本轮合入记录，使用独立工作树。读取：
- README.md
- docs/development/PLATFORM_SUPPORT_20261116.md
- docs/evidence/intel-portability-20261116/RESULTS.md
- desktop/AGENTS.md
- desktop/docs/development/INTEL_MAC_20261116.md
- docs/development/CORE_PORTABILITY_20261116.md
- docs/development/COMPANION_INTEL_20261116.md
- docs/evidence/pa-cooperation-20261115-mac/RESULTS.md

目标是补本轮确实无法完成的验证，先检查实际环境，不重新实现已完成的架构。保留当前日常 APP、外部模型服务、旧534队列、所有失败记录、私有数据和旧工作树。没有逐路径授权，不删除或移动模型/缓存/备份来腾空间。不要发布 Release 或提交比赛/落地表单。记录全部 Git SHA、真实命令、模型身份、产物哈希和失败历史。

一、Intel Mac 是最高优先级。
1. 确认是真实 Intel macOS，记录 uname -m、macOS、Python 和内存。Apple Silicon 上的 Rosetta 只能算兼容性检查，不能写成 Intel 原生通过。桌面最低系统仍为 macOS15，不能为通过验收直接改版本声明。
2. 按 INTEL_MAC_20261116.md 获取固定35项依赖和四个组件；对 watchdog6.0.0、cryptography50.0.2 执行真实x86_64源码构建，记录源码哈希、CPython3.14.6、Rust/Clang/SDK、OpenSSL静态库及许可证。缺项则明确BLOCKED，不伪造Intel锁或复用arm64哈希。
3. 使用现有单worker构建与安装计划流程，Test配置必须是 desktop/src-tauri/tauri.test.conf.json，身份 io.localpilot.desktop.test。生成目标资源，执行Rust、Swift、完整APP、签名、Mach-O和资源搬移导入检查。安装到独立Test位置，不能覆盖日常身份。
4. 运行当前npm test、npm run build、npm run test:ui。云端已完成类型/Vite和Vitest；Playwright因Chromium下载及容器Unix socket限制没有完成，必须实际运行全部用例，不能把收集成功计为通过。
5. 使用已有可验证GGUF与CPU OpenAI兼容服务。不要把MLX权重当GGUF，不要把LM Studio作为Intel保证可用的运行时。模型选择按可用内存、磁盘和实际上下文决定，不默认加载35B。先验模型来源、revision、文件，再读取/v1/models、实际推理和真实工具任务。
6. 通过Test APP首次向导保存端点、关闭/重开恢复pending、显式应用。核对旧路由/Session/收据保留，新协作主/子模型选项可见；活动任务和待批准状态应阻止普通重启。Companion选择此端点后应有独立reasoning-only及标准Agent两路由。
7. 核验真实pmset -g batt/custom/cap；覆盖无电池桌面/接电/电池、系统低功耗策略及一次性电池确认。关闭Companion低功耗不等于永久开放电池。云端缺电源资料的合成测试不能替代此项。
8. 测真实Companion轻聊、手动强推理、Agent任务、显式自动本地策略；至少一个实际文件读回任务、一个子Agent任务、运行中取消和重启恢复。记录Core确认取消、任务quiescent、provider是否仍计算分别是什么。请求连接被关闭不等于外部模型服务已卸载；等待HTTP头阶段允许stopping，不能提前报告停完；取消后不得执行晚到工具或重放UNKNOWN收据。
9. 做独立Test APP安装、更新、四类故障回滚和反向安装回滚。PR#11仅验证旧安装回滚归档提取/哈希，不能当成已经执行反向安装回滚。核对日常APP摘要不变。

二、现有Apple Silicon机器能补的真实材料。
1. 对新源码做arm64原生回归，保持既有服务独立。若只有Apple Silicon，先做这一部分，并明确Intel物理验收仍NOT_RUN。
2. 从真正的Test APP用户界面开始系统音轨/麦克风/both会议采集，确认TCC责任进程与用途说明。上轮因责任归为ChatGPT而SIGABRT、零音轨，旧失败必须保留。不得绕过TCC或将没有音轨的结果记为成功。没有授权或本地Speech能力则阻塞。
3. 使用明确授权的真实Codex可见历史、会议与日常来源，执行没有把答案直接写入问题的问答；验证来源引用、撤销后不再检索、晨晚去重/勿扰和真正系统睡眠唤醒。没有实际观察的信息应如实说不知道。
4. 真实多模型本地/云端与五档调用保留父子身份、模型revision、请求/token/provider用量、成本和失败。未知usage及此前DeepSeek费用继续UNKNOWN。不能用合成回复或过滤think文本宣称模型通过。
5. LoRA只有在实际回答/来源已经人工确认且设备资源满足时，沿现有训练入口执行，并用独立测试集比较候选。不得从模型自答自动造真值、自动替换当前模型，也不能把未实现的RL或partial dense写成全参强化学习。
6. KV按固定Skills/提示词、模型和模板做冷/热/服务重启实验，记录实际命中指标。50GiB是受管缓存配额，不是保证空闲空间或永久不失效。

三、正式公开对照。
先确认Docker daemon可用、剩余磁盘达到既有study准入要求，再按 docs/development/EVALUATION_CONTINUATION_20261115.md 建新study并冻结当前源码/模型/任务/预算/参考实现。旧534队列固定旧SHA，继续保留1PASS/3FAIL/13ERROR/517无最终结果；不能把新候选接进去洗掉旧失败。当前没有条件则给准确阻碍，不能报排名或“主流Agent同等能力”。

输出每项PASS/FAIL/ERROR/BLOCKED/NOT_RUN、原始脱敏日志和哈希，更新新的evidence目录。若发现真实代码缺陷，按仓库现有实现修复、针对回归后正常PR同步main；不改写历史记录、不发布Release。最终只列实际尚未完成的项目和需要用户提供的准确设备/资料，不再给一份泛泛的重做架构计划。
```

仓库侧不会自动代填 AIC 表单。用户给出的全国半决赛通知列出 **2026-11-19 23:59** 的材料截止时间，与另行收到的 **11 月 20 日**成果落地意向收集不是同一项提交。官方来源：[全国半决赛通知](https://www.aicomp.cn/notice/notice-3/5856.html)。
