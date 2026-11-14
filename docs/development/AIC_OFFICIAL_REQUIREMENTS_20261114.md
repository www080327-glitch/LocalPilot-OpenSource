# AIC 官方要求及 SuperAgent 来源核验（2026-11-14）

## 当前材料截止与录制要求

依据 [2026-11-14 全国半决赛通知](https://www.aicomp.cn/notice/notice-3/5856.html) 及其附件，AI+开源属于此次通知覆盖的赛题。**材料提交截止为 2026 年 11 月 19 日 23:59（按赛事中国本地时间执行）**；11 月 20—22 日评审。前 40% 晋级决赛，线下决赛拟于 12 月 4—6 日在南京举办，后续群通知可能细化。

附件要求腾讯会议连续录制，全体报名队员全程开摄像头并清晰可识别，开场报团队名，按评分项顺序讲解；汇报和演示合计不超过 6 分钟，不能快进或剪辑。PPT 不得出现学校、导师及暗示性标识，客观不可避免的信息需预先报备。录制视频提交至平台“视频类文件”，另交 PPT 和规定作品文件。不能用早期规则中的 3—5 分钟剪辑演示替代本次答辩录像。

用户转发的“11 月 20 日前成果落地意向收集表”是独立事项。当前仅有转发文本，未能独立读取微信表单内容；不能把该日期作为半决赛材料截止日期。本轮没有替用户提交表单或联系组委会。

## 正式评分

依据 [AI+开源赛题发布通知](https://www.aicomp.cn/notice/notice-3/4890.html) 附件 1《AIC·AI+开源竞赛规则及作品提交要求0812》。已核对 PDF 评分表：

| 评分项 | 分值 | LocalPilot 材料应呈现的证据 |
|---|---:|---|
| 问题与场景价值 | 15 | 明确用户和具体 PA 场景，避免“万能 AI”泛泛描述 |
| 创新性与方案设计 | 20 | 已实现的活动记忆、主/子代理协作、本云分工及实际差异 |
| AI 与开源融合 | 20 | 固定上游版本、许可证、自研边界与具体融合方式 |
| 实现完成度与可验证效果 | 25 | 真实原生闭环、正确故障状态、独立基准和可核验原始证据 |
| 开放成果与复用价值 | 15 | 可运行源码、安装说明、可复现实验、清晰维护计划 |
| 材料规范与表达 | 5 | 正确格式、匿名要求、主张和证据一致 |

同分时依次比较实现与可验证效果、AI 与开源融合、创新性。模型规模、算力投入、代码行数和材料数量不作为单一评分依据。当前优先完成真实闭环与证据，比增加尚未验证的模型训练更贴近该评分结构；这是工程优先级判断，不是对获奖结果的预测。

原创 Apache-2.0 代码与第三方组件许可证应明确区分。完整代码开源不要求将无权再分发的数据、模型、私人活动日志、凭据一起公开；生成式 AI 辅助开发的使用环节、团队审查和验证也需在报告中说明。

## DeepSeek SuperAgent 的具体来源

已核实 [deepseek-ai/dsh-superagent-prototype](https://github.com/deepseek-ai/dsh-superagent-prototype)，固定 commit `8c32a9dc5d72c033816c6a8110b37f40cf94fba4`。许可证为 MIT；README 明确它是研究原型，不是正式 DeepSeek 产品，公开实现与内部版本/设计文章不同，部分构想尚未实现。

它作为 bundle 使用 DeepSeek Harness，与本项目 `DEEPSEEK_HARNESS_REUSE_LICENSES.md` 中已有的 Harness `0.2.1-rc.2` / `687f282e8625c6b8d11ff58211a90524be2e4317` 复用记录不是同一项集成。不能把已适配 Harness 序列化等细节描述为已经完整接入 SuperAgent。

已阅读官方 [领域模型](https://github.com/deepseek-ai/dsh-superagent-prototype/blob/8c32a9dc5d72c033816c6a8110b37f40cf94fba4/docs/001-domain.md)、[执行与恢复](https://github.com/deepseek-ai/dsh-superagent-prototype/blob/8c32a9dc5d72c033816c6a8110b37f40cf94fba4/docs/003-execution.md)、[提示词](https://github.com/deepseek-ai/dsh-superagent-prototype/blob/8c32a9dc5d72c033816c6a8110b37f40cf94fba4/docs/004-prompts.md) 和 [架构](https://github.com/deepseek-ai/dsh-superagent-prototype/blob/8c32a9dc5d72c033816c6a8110b37f40cf94fba4/docs/007-architecture.md)。值得借鉴的是事件来源、主 Session 分派、Worker 独立执行、异步报告和持久恢复。可映射到已有 Companion 事件、TaskService、Runtime/Session、Hybrid 子代理及 SSE，而不是另建一套并行 Runtime。

其 team skills 支持按需加载；稳定提示前置、动态策略靠后。文档中的 `TextCache` 为有界内存文本缓存、重启丢失，不能用它证明模型 KV 可以永久保存。LocalPilot 的持久前缀缓存必须单独验证后端实际命中、重启恢复、模型/权重/量化/模板变更失效和容量预算。

本记录只描述来源和设计参考；具体产品实现及实测状态以本次代码和对应验收记录为准。未复制该原型源码进本仓库。
