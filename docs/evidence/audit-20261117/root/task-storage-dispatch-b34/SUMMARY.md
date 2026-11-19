# LocalPilot 本轮公开证据

原始输入字节直接归档；失败、阻断和未运行状态以各组原始结果为准。

| 证据组 | 说明 | 原始文件数 | 归档 | 清单 |
|---|---|---:|---|---|
| [engineering-r10](engineering-r10.SUMMARY.md) | R10：候选 Luna high 的原始失败证据与固定验收输入，未替换或删减。 | 40 | [engineering-r10.tar.gz](engineering-r10.tar.gz) | [engineering-r10.MANIFEST.json](engineering-r10.MANIFEST.json) |
| [engineering-r11](engineering-r11.SUMMARY.md) | R11：最终候选 Sol medium 的原始工程结果、固定验收输入与实际 model/effort 摘录。 | 41 | [engineering-r11.tar.gz](engineering-r11.tar.gz) | [engineering-r11.MANIFEST.json](engineering-r11.MANIFEST.json) |
| [engineering-r9](engineering-r9.SUMMARY.md) | R9：RC16 基线、Luna high 的原始工程结果与固定验收输入。 | 40 | [engineering-r9.tar.gz](engineering-r9.tar.gz) | [engineering-r9.MANIFEST.json](engineering-r9.MANIFEST.json) |
| [packaging-final-core](packaging-final-core.SUMMARY.md) | 3764fc0 最终 Core 与原同批其余三个 wheel 的组合安装验证，独立保留构建来源。 | 17 | [packaging-final-core.tar.gz](packaging-final-core.tar.gz) | [packaging-final-core.MANIFEST.json](packaging-final-core.MANIFEST.json) |
| [packaging-original](packaging-original.SUMMARY.md) | 37570b9 原四 wheel 的安装来源、哈希及验证；环境导致的首轮失败与五项复验均保留。 | 23 | [packaging-original.tar.gz](packaging-original.tar.gz) | [packaging-original.MANIFEST.json](packaging-original.MANIFEST.json) |
| [regressions](regressions.SUMMARY.md) | Core 首轮与复验、Companion/Suite 原始回归记录；首轮失败照原样保留。 | 34 | [regressions.tar.gz](regressions.tar.gz) | [regressions.MANIFEST.json](regressions.MANIFEST.json) |
| [scheduling](scheduling.SUMMARY.md) | 分工配置、真实 loopback 角色/effort/恢复验证、完整前端及浏览器启动失败证据。 | 20 | [scheduling.tar.gz](scheduling.tar.gz) | [scheduling.MANIFEST.json](scheduling.MANIFEST.json) |
| [storage](storage.SUMMARY.md) | 任务逐条存储迁移和原始性能记录；不含数据库、恢复副本或运行状态。 | 20 | [storage.tar.gz](storage.tar.gz) | [storage.MANIFEST.json](storage.MANIFEST.json) |
| [superagent](superagent.SUMMARY.md) | Super Agent 定向与跨版本验证、独立审阅、原 4k 窗口 rotation 失败诊断及修复复验。 | 46 | [superagent.tar.gz](superagent.tar.gz) | [superagent.MANIFEST.json](superagent.MANIFEST.json) |

## 排除规则

- Only explicitly listed files are eligible; engineering snapshot members come from the final audited allowlist.
- Private runtime/state, workspace caches, credentials/environment files and all SQLite/database sidecars are excluded.
- Wheel binaries, archives, model files and unlisted file types are excluded; packaging uses hashes and import proofs.
- Required files are never silently omitted. Undeclared files and directories are not traversed.
- Inputs are not redacted or reformatted. Known API keys are read only from private files and matched exactly; any match aborts export.
