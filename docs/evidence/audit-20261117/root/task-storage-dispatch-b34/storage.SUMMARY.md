# storage

任务逐条存储迁移和原始性能记录；不含数据库、恢复副本或运行状态。

- [原始证据归档](storage.tar.gz)：20 个文件，210228 字节。
- [逐文件 SHA-256 清单](storage.MANIFEST.json)。
- 原始输入 SHA-256 与公开归档成员 SHA-256 一致；没有修改原始字节。
- 归档 SHA-256：`852c82d127b5429c15159fa2c3b80a5461e66d16efd563defe0f4f86ea835e97`。
- 归档采用固定时间、固定权限和排序，保持可复现。

## 文件

| 路径 | 字节 | SHA-256 |
|---|---:|---|
| companion/PERF_COMPARISON.json | 27431 | `dc4de156cd48cba0c7b3f985d73b55bc534c79fb5d1ed1c298f2e06e97f63234` |
| companion/PERF_FINAL_SOURCE_EQUIVALENCE.json | 981 | `969ea3ad7284f333a3fd72b109a4d4b93a58e9962c4e08d646697397d033ac09` |
| companion/measure_history.py | 9669 | `176c67804fcfa2445f926a644e6e060354f4cef6af9469ce4fea784b3b43f84f` |
| companion/migration-r1/RESULTS.json | 1415 | `547f737fbd852320b6e9ee4bc037bf613fb20943f239e3b5792ccf9cc5c4e4bc` |
| companion/migration-r2/RESULTS.json | 1415 | `ad9e72eeae8d579e620a1334b428cfe8e9ea50c9457affed247f129486515faa` |
| companion/migration-r2/execution.json | 730 | `e940162b8762fba6a1b6040f528abdf5f29403d7a99db3a5a585c758a9ae88c6` |
| companion/migration-r2/probe.log | 1377 | `615841cf808d9bf3c3b4e782a3c9d09bf4153b8390149666f89ff4e3e5fc0875` |
| companion/migration-r2/source-after.json | 63813 | `7697717def213fe33e29730d11a2f03396a59b11088c1f3d68ba3d17b6a03078` |
| companion/migration-r2/source-before.json | 63813 | `7697717def213fe33e29730d11a2f03396a59b11088c1f3d68ba3d17b6a03078` |
| companion/migration_probe.py | 5212 | `f95f8799661ffe0b9115e0a3d515fd02aa4b516c80bedd5d9920ba3ec6a12ffa` |
| companion/perf-baseline-r1.console.log | 598 | `5bdab125c94b82ce1708f9b24d81b639b366ed79c6b7e1f0d92c06be5bb66cd4` |
| companion/perf-baseline-r1/PROGRESS.json | 58456 | `6f497ea9b82d8d8f603de3eb070ac0057f7203374ed65adcbafc0bb43d5af0e5` |
| companion/perf-baseline-r1/RESULTS.json | 104360 | `a260ab11afd1172cbb1d9ec77dd89f2e5da7f0b062fc4b16e27b8600cb6cd053` |
| companion/perf-baseline-r1/execution.json | 1035 | `10497cabe5b78a0470041b8d1fb794a084a3ed0d109c58f0f75fdcb917e6dc15` |
| companion/perf-candidate-r1.console.log | 588 | `5144e96b2506ae3e8d27372711ed009efbe3fc36dc06fc3195b4abfb244ea43b` |
| companion/perf-candidate-r1/PROGRESS.json | 59701 | `0e2163df324e39229e1886cb04e113fe8ba674e284ba4119ee99be22fc384fb0` |
| companion/perf-candidate-r1/RESULTS.json | 106264 | `636df3552b05d3058199875093b1e3a560394a4c725a6b92e0f71691ca79fd9d` |
| companion/perf-candidate-r1/execution.json | 1001 | `51db2ce619aae8c18508f488cab2cebf71b04c1d59fefa12acb5671ec80dd4d0` |
| review-companion-source-read.json | 1986 | `e2eb4bd07b05f138cc829e6fe1703940f9f9f77c2e2bb9748bf34f7700d6ce6c` |
| review-companion.json | 10733 | `0cd575f3751915cb812e85606e6b771b753975a415f45f624c384695570e0891` |

## 排除规则

- Only explicitly listed files are eligible; engineering snapshot members come from the final audited allowlist.
- Private runtime/state, workspace caches, credentials/environment files and all SQLite/database sidecars are excluded.
- Wheel binaries, archives, model files and unlisted file types are excluded; packaging uses hashes and import proofs.
- Required files are never silently omitted. Undeclared files and directories are not traversed.
- Inputs are not redacted or reformatted. Known API keys are read only from private files and matched exactly; any match aborts export.
