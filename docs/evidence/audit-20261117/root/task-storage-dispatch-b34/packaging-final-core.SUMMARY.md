# packaging-final-core

3764fc0 最终 Core 与原同批其余三个 wheel 的组合安装验证，独立保留构建来源。

- [原始证据归档](packaging-final-core.tar.gz)：17 个文件，95570 字节。
- [逐文件 SHA-256 清单](packaging-final-core.MANIFEST.json)。
- 原始输入 SHA-256 与公开归档成员 SHA-256 一致；没有修改原始字节。
- 归档 SHA-256：`7fe2f882ce3642d0ec48aa54e840b00e9c597f04da251e4d156cd6f422cd1c98`。
- 归档采用固定时间、固定权限和排序，保持可复现。

## 文件

| 路径 | 字节 | SHA-256 |
|---|---:|---|
| packaging-final-core/ARTIFACTS.json | 1946 | `e56cb83501874f0228a4d0c148653fd67a7a2452cd37ea4512ad6a39a1ca6d63` |
| packaging-final-core/RESULTS.json | 5759 | `8f46ed52bc2756669bfda2be7e8ca873d87939343bfa765a758b23d9a48fed47` |
| packaging-final-core/SHA256SUMS | 541 | `0d3d1eeb654f032ad9bc5a41296c714b4066acfb263a938fae9130da4b076c26` |
| packaging-final-core/installed_final_core.py | 14278 | `3b6bcf9e6476be8b9aa47a45c55c55b7ec5ffec1eb6fdce4aa1a65c2b6e865c7` |
| packaging-final-core/r1/build.log | 39682 | `d325c48d428598ec775669a94cb466c71ca469fa4bf3df62e2a79e513259911c` |
| packaging-final-core/r1/cli-version.log | 289 | `2fc878b680561ddeb3127b017f7f8c843ac0b18c1c8a28a4d842ac73ce4c8f87` |
| packaging-final-core/r1/dependencies.log | 1407 | `a4d36eb4076d352747e8e179fd5068397632d38a3ec1318855382c2fca142e74` |
| packaging-final-core/r1/import-proof.json | 4799 | `e49ff9de1b68b24a3409808855267281e1a29a43394b2add53380e052903f522` |
| packaging-final-core/r1/install.log | 1546 | `6ffea079187375de0296d35ebe0defabba8f38023e2df03915a93bcd5042b24e` |
| packaging-final-core/r1/pip-check.log | 166 | `d6ed46b182b1635221c33772db7005b760ad847acd8a1690e8fcc7e888584128` |
| packaging-final-core/r1/run.json | 39760 | `cfa310e9c72c99ed80231ad4d1986fb03e96544af45cf1ce61565090269040f2` |
| packaging-final-core/r1/runner.py | 14278 | `3b6bcf9e6476be8b9aa47a45c55c55b7ec5ffec1eb6fdce4aa1a65c2b6e865c7` |
| packaging-final-core/r1/source-after.json | 71950 | `3f54c01947f932d9c0e0f1a9a5fc473a80cea21d19582f559646aa0e2e9e4e3c` |
| packaging-final-core/r1/source-before.json | 71950 | `3f54c01947f932d9c0e0f1a9a5fc473a80cea21d19582f559646aa0e2e9e4e3c` |
| packaging-final-core/r1/stage.log | 24257 | `ee950356d77ba4da078a7f58a7d7ea24b21d5bf152994bba7d0461d5f6ffe680` |
| packaging-final-core/r1/tests.log | 6522 | `214d36ac1238fff415992d80e88110711601573e8d2999175dffc8ca1fe3fb6b` |
| packaging-final-core/r1/venv.log | 214 | `896515d1bc707967f30565629bb63a1cf7b707ca835547f506fb1d9dc4d090aa` |

## 排除规则

- Only explicitly listed files are eligible; engineering snapshot members come from the final audited allowlist.
- Private runtime/state, workspace caches, credentials/environment files and all SQLite/database sidecars are excluded.
- Wheel binaries, archives, model files and unlisted file types are excluded; packaging uses hashes and import proofs.
- Required files are never silently omitted. Undeclared files and directories are not traversed.
- Inputs are not redacted or reformatted. Known API keys are read only from private files and matched exactly; any match aborts export.
