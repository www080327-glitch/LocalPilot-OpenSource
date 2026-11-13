# LocalPilot 国赛前减法式整改记录（2026-11-13）

> **状态：PR 草稿，代码已提交；本次追加修改没有完成完整构建、macOS 实机、真实模型或端到端回归。不得据此合并、替换日常 APP 或发布安装包。**

## 基线与所有权

- 当前正式发布源码：`www080327-glitch/LocalPilot-OpenSource` 的 `main`，本轮核对初始提交 `34e95eb1`；`PUBLIC_SOURCE.json` 指向私有 `LocalPilot` 的后期产品提交 `c3568e65`。
- 本次继续上轮未完成的 `fix/nationals-runtime-ux-20261113` 分支及 PR #1；不覆盖 `main`。
- 私有 `LocalPilot` 与 `LocalPilot-AIC-20261030-Frozen` 仅供追溯，冻结历史未修改。
- 主要沿 Runtime → Hybrid/Cooperative → Service → Tauri → React → Suite 的关键真实调用链审阅。**不声称逐字读取全部仓库文件，也不覆盖未推送代码或用户 Mac 当前环境。**

## 已提交的代码修复

1. **上下文计量统一**：`agent/context_budget.py` 保留 tokenizer chat template 优先、启发式 token 估算明确标注；`context.py`、`context_v5.py`、`harness_context.py`、`session.py`、`hybrid.py`、`vllm.py` 统一模型上下文请求和跨模型交接的 token 窗口判断，不再叠加 `max_output_tokens * 16` 到上下文限制。保留旧的 *字节* 回合预算账本；模型配置、工具 Schema、预留余量仍须核对。新增 32K 短中文与真实超窗适配器测试。绝不把启发式估算冒充准确 token 数。
2. **本地试用更积极**：前序 PR 修改了默认小模型资格、本地有界尝试及实际失败后升级。正式效果尚无独立配对数据支持；没有宣称节费百分比。
3. **偏好失败可恢复**：`App.tsx` 保存队列不因一次 rejected Promise 永远损坏，UI 展示尚未保存；新会话不冒充服务端已保存。
4. **UNKNOWN 作用域**：`main.rs`、`App.tsx` 按同一 Session 而非同一个客户端身份隔离未决提交。原请求/幂等记录不删除；新的独立 Session 可以继续。
5. **切换模型历史边界**：当前 Backend Session 不支持直接迁移任意另一模型的完整历史。因此显式切模型创建**独立会话**并清空新会话可见历史，保留旧会话列表并提示“历史未交接”；没有谎称实现同会话无损切换。
6. **四档权限与长命令**：前序 PR 在 `scope_permissions.py` 的 full/revision3 改为真实目录目标解析，并保留叶节点/范围的合法授权判断；`host_tools.py` Shell 支持可配置至 3600 秒、默认 120 秒，修正工具 Schema 与网络说明。原生 macOS Seatbelt/取消流程未验收。
7. **协同显示与子代理**：`collaboration.ts` 根据实际 Hybrid 调用和持久任务快照给出本地/云端请求次数与占比，来源未知单列，既不把注册路由当实际请求，也不推算 API 真实费用。`App.tsx` 底部可点击协同占比；运行中子代理 banner 可打开右侧“协同”页，显示实际后端类型、配置模型、提供方返回模型（若记录）、委派任务、状态、步骤、持久工具收据。跨 GUI 重启以 TaskService 子代理快照为兜底。
8. **双向可配置协同**：现有 `HybridController` 已支持 child delegation；`deployment.py` 增加云端主路由指向经注册的同工作区本地伙伴（`cooperation.local_route` + optimizer），不添加另一套 Runtime/Router。局部子代理不支持主模型 thinking 档位时改用它自身默认能力并记事件。**新能力需明确配置，不会静默修改已有安装配置；没有完成真实模型协同验收。**
9. **模型列表**：正常选择器仅显示已注册且声明 ready、tool_calling 可用且来源匹配的路由；不可用/仅推理项留在模型库。状态来自服务端声明，不承诺所有远端 API 已作实时探测；`remote-vllm` 与 Service 的云端分类一致。
10. **项目分类/置顶**：新增 `projects.ts`，持久化只保存当前用户/服务作用域下的项目、归属、置顶 UI 元数据；任务事实仍由服务端负责。项目重命名、会话归类、项目与会话置顶已接入侧栏。
11. **SSE 恢复**：显式从 `after=0` 重放不再被 Tauri 上次持久游标跳过；前端对累计正文按事件 sequence 去重，快照子代理可在缺失早期 SSE 时恢复。事件服务端保留窗口和原生 GUI 重启仍需实机测量。
12. **减法式前端提取**：新增可独立测试的协同数据投影、项目组织 hook/分组函数、模型可选路由筛选；不引入新状态管理框架。

## 待执行的真实回归（**本次追加工作未运行**）

可从仓库根目录按既有流程执行：

```bash
python3 -m unittest tests.test_nationals_runtime tests.test_context_v5 tests.test_harness_context tests.test_v49_context_cache tests.test_vllm_cooperative tests.test_cloud_local_partners
cd desktop
npm test
npm run build
cargo test --manifest-path src-tauri/Cargo.toml
npm run test:ui
```

需要在独立 macOS 测试 APP 槽做：保存失败/连续发送、不同 Session 的 UNKNOWN、合法软链接与系统临时目录、Shell 长命令和取消、32K 本地/云端跨模型真实交接、GUI 关闭重开、子代理活动页、模型加载状态、全流程安装与升级。不能把函数级证明、模拟协议、原生 GUI 或真实模型测试数量相加来称为 Agent 成功率。

## 仍未完成 / 不可声称已解决

- **同一会话无损跨模型切换**：当前明确分新会话，仅修正误导性的 UI 连续性。要真正实现需复用服务端 canonical history/context 迁移并证明工具收据不重复执行。
- **正式本地↔云端持续协同**：协议和展示已提供，但对历史用户的安装配置仍需单独显式授权/迁移，之后才有真实模型调用与经济性实验。
- **完整拆分 App.tsx 与多代 Runtime 策略**：本轮只对新增职责完成提取，没有进行高风险全 Runtime 替换。
- **统一一次升级 GUI/Core/Channels**：未完成真实组件事务式升级与回滚，不能只靠发布说明推断一致。
- **50 GiB 受管缓存总限额**：审查到 `CachedOmlxHost` 的启动参数将该实例 prefix SSD 缓存约束到 2GB；不能从源码证明第三方 oMLX 或用户机器其它缓存受管。没有本机目录归属清单，**不盲删或扩张清理范围**，全局预算留待本机证据确认。
- **真实模型在线健康、完整取消、权限/低功耗解耦、长期稳定性和独立成本成功率评估**仍待验收；静态检查不能替代运行证明。

## 合并准则

优先完成编译、既有回归、原生测试槽再审查。保留原任务持久化、工具收据、真正 UNKNOWN 的防重放，以及冻结仓库不变。仅对本轮 PR 评审后决定何时合并，未经用户进一步批准不替换日常 APP、main 或 Latest。
