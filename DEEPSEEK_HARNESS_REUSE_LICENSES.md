# 源码复用与许可证清单

固定上游：DeepSeek Harness 0.2.1-rc.2，commit `687f282e8625c6b8d11ff58211a90524be2e4317`。

| 使用位置 | 上游依据 | 复用类型 | 分发与许可证 |
|---|---|---|---|
| `agent/deepseek_optimized.py` | `packages/llm/llm-deepseek/src/serialize.ts` | 工具历史配对校验的 Python 适配；不是 Messages serializer 的整体移植 | 保留 DeepSeek 版权；MIT 全文随源码与 wheel 附带 |
| 同上 | `packages/llm/llm-deepseek/src/sse.ts` | 完整帧才接受、尾部截断不完成的策略；未复制 eventsource-parser 的实现 | 同上；没有引入该第三方库 |
| 同上 | `packages/core/system-prompt/src/index.ts` | 默认工具名排序的确定性策略 | 同上，NOTICE 记录来源 |
| `agent/deepseek_context.py` | `core/session` 派生 request projection、工具快照理念 | 独立实现的 receipt 去重引用和当前工具快照 | 不声称实现 DSH Session；保留来源说明 |
| `agent/hybrid.py` reasoning 出站处理 | `llm-deepseek/src/replay.ts` 的源模型约束；当前 Chat API reasoning 指南 | 独立的完整消息哈希 + 模型 + 出站策略来源校验；由原 SQLite 持久化 | 未复制原生 signature 格式；不与 DSH 原生 replay 混称 |
| 原生三路参考运行 | `apps/cli` 与 headless/base bundles、core/agent-loop、llm-deepseek-api-key、session、fs tools | 直接运行固定 checkout 构建结果 | 只作独立参考；不装进 LocalPilot wheel，不发布这些 npm 依赖 |

`third_party/deepseek-harness/LICENSE` 为完整上游 MIT 文本；`NOTICE.md` 说明适配范围；`UPSTREAM_THIRD_PARTY_NOTICES.md` 是上游未修改的第三方清单参考。

参考安装使用 `pnpm install --frozen-lockfile --ignore-scripts`；构建与检查通过。锁定的完整上游依赖闭包不是全 MIT：本轮 `pnpm licenses list --json` 审计包含 MPL、LGPL、SEE LICENSE 和 Unknown 条目。许可证种类/数量写入证据 `reference-license-summary.json`，原始审计归档在证据包。未来若把完整 Node 引擎打入产品，必须逐项重新审核相应发行包、vendor LICENSE、NOTICE、传递依赖和特殊平台 payload；本轮不依赖“顶层 MIT”作整体许可推断。

LocalPilot 新增生产依赖：无。原有 `psutil` 依赖未变。wheel 增加 `share/doc/localpilot/third_party/deepseek-harness/{LICENSE,NOTICE.md}`，以防源码中有归属而二进制分发遗漏归属。
