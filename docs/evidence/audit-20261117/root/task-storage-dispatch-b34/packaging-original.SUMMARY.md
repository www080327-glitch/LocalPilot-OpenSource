# packaging-original

37570b9 原四 wheel 的安装来源、哈希及验证；环境导致的首轮失败与五项复验均保留。

- [原始证据归档](packaging-original.tar.gz)：23 个文件，175812 字节。
- [逐文件 SHA-256 清单](packaging-original.MANIFEST.json)。
- 原始输入 SHA-256 与公开归档成员 SHA-256 一致；没有修改原始字节。
- 归档 SHA-256：`a7bc6eb9c02084d02c1d25f7cd9bda35c656f4114f389b951e781971b9c00934`。
- 归档采用固定时间、固定权限和排序，保持可复现。

## 文件

| 路径 | 字节 | SHA-256 |
|---|---:|---|
| packaging/ARTIFACTS.json | 932 | `5246378b2ef3c52ea07c7825e57cd935ef3094125c4c02811b2b36184a68372f` |
| packaging/RESULTS.json | 4579 | `9485878a72a53de7c59055a89610446b1bb644c83d6fd0c9cc5b526307a97388` |
| packaging/SHA256SUMS | 490 | `0f8b701d8040cbe584308a74ab3eaa6838ad61f0d1f366131008175346295667` |
| packaging/build-environment.json | 727 | `af31509465630116cb4ffcbc6d394e9ea2069fa30e834f33f925a88900b02b52` |
| packaging/build-environment.log | 1370 | `327b73f27299e21d33cf5c62473d94952d45b5d7093897e5c100b5b010fdb46b` |
| packaging/installed_gate.py | 14068 | `6e0089487fbee414498c22b0a227ea83a7a48904b8c473b2acdb3554c2d11f88` |
| packaging/r1/PROGRESS.json | 39981 | `4f799bcb8587c6a2e24ec826a96d038de4aa93e7b775475ecd4ea577d9c76a76` |
| packaging/r1/build.log | 84063 | `2f2719814ac1f09f7c040d9b36add7dec24ec14697f2ab89d70709ef75ea735d` |
| packaging/r1/cli-version.log | 278 | `60b3a354a756c6738008356efad62891e2028db0a64d59f180f1bf2005552456` |
| packaging/r1/dependencies.log | 1396 | `10d90085245231f3e01f6e0d2e3b5fbb409bed399ce94d254ab2b4fd6ea531a1` |
| packaging/r1/import-proof.json | 4689 | `da7a8cace28d5b3a423becdfcd119d43c621019e89b30e92f51341b54dc798a1` |
| packaging/r1/install.log | 1513 | `7af397b63d02df09b2e8f734014cf068d62b895bc210a2d10acd09626de72ad9` |
| packaging/r1/pip-check.log | 155 | `d7a4f7925d1e4c519b77971f3a453c6bb3c83b8900a73b5aaeb6315ee1940059` |
| packaging/r1/run.json | 40718 | `4d88f09ed02033ccd38e87e684d103e68a169572277462aeeb0400afc39c332a` |
| packaging/r1/runner.py | 14068 | `6e0089487fbee414498c22b0a227ea83a7a48904b8c473b2acdb3554c2d11f88` |
| packaging/r1/source-after.json | 71950 | `8aeff0cc2b2c13a482ec7cc90fd5310f001ae48d32d01a424f2f97621701bacd` |
| packaging/r1/source-before.json | 71950 | `8aeff0cc2b2c13a482ec7cc90fd5310f001ae48d32d01a424f2f97621701bacd` |
| packaging/r1/stage.log | 24246 | `46ffb44e7c4a5ceebd7734c89b5daa58f8e2e6c15e8704b1786ffa5644cf18ab` |
| packaging/r1/tests.log | 12222 | `2c5a5fe2272a4dc8cd1170381a51e132d222d6856c606d3995417e6591cd8ff9` |
| packaging/r1/venv.log | 203 | `8e556fac08b8b537ba8825da5c2ddad2963d1eb7bd66fdc9e94bc67e9a9cf472` |
| packaging/recheck_installed.py | 3873 | `a913e815506dfe39dc9ff9132a27a4768803b777a7bdf0293544a808d249b021` |
| packaging/verification-r2/run.json | 148261 | `85457fad2d77945ca2f1c8914665b43fed87069942fe9f9da26d974078b246af` |
| packaging/verification-r2/tests.log | 1145 | `3eb8fd4e2fd7870ae336133c86d9daf3358d65d347121d3443677fb506c4196b` |

## 排除规则

- Only explicitly listed files are eligible; engineering snapshot members come from the final audited allowlist.
- Private runtime/state, workspace caches, credentials/environment files and all SQLite/database sidecars are excluded.
- Wheel binaries, archives, model files and unlisted file types are excluded; packaging uses hashes and import proofs.
- Required files are never silently omitted. Undeclared files and directories are not traversed.
- Inputs are not redacted or reformatted. Known API keys are read only from private files and matched exactly; any match aborts export.
