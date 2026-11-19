# regressions

Core 首轮与复验、Companion/Suite 原始回归记录；首轮失败照原样保留。

- [原始证据归档](regressions.tar.gz)：34 个文件，483306 字节。
- [逐文件 SHA-256 清单](regressions.MANIFEST.json)。
- 原始输入 SHA-256 与公开归档成员 SHA-256 一致；没有修改原始字节。
- 归档 SHA-256：`7a623b9a99f21ae573d99a1fe0b572626ac055615c0cebe287a6a3b7ce7a7515`。
- 归档采用固定时间、固定权限和排序，保持可复现。

## 文件

| 路径 | 字节 | SHA-256 |
|---|---:|---|
| environment/final-pip-freeze.txt | 1394 | `98b7ed9a203c8a6b6f7cc5cac7282a4473b744278dbe932f76dcdd5dc611e96c` |
| environment/install-test-extras.log | 10445 | `07aab9a2d2efce71b06a73144fb599e49128f803c6bd402156467602601541f2` |
| environment/validation-dependencies.json | 552 | `1da1f13e638eaf8f71603a477cf03894a81f2ebf9b48164f0f19312c1d453060` |
| full-companion-r1/run.json | 615 | `50b8e0f50bad4746f100c857aac8f309fa945ad74e5130057fd78964735a1fb3` |
| full-companion-r1/runner.py | 5025 | `d85c470e95bebbb57d5d43939fc858d11c821453abf6aeba9e198961f0734fa2` |
| full-companion-r1/source-after.json | 63813 | `7697717def213fe33e29730d11a2f03396a59b11088c1f3d68ba3d17b6a03078` |
| full-companion-r1/source-before.json | 63813 | `7697717def213fe33e29730d11a2f03396a59b11088c1f3d68ba3d17b6a03078` |
| full-companion-r1/tests.json | 115177 | `0d4e9805c1222e6a3bb880c71c098776255a7d863772f7bd5407e346b071b4b7` |
| full-companion-r1/unittest.log | 130366 | `a8d0262ab86d52031a9271aa3d1e00ac6e9a06d7e94c60d22dc8051ffde94959` |
| full-core-r1/console-final-chunk.json | 5213 | `835de5a042104f07025f38cefba7a9fbebc26b6bac81565b2c81baa97628add4` |
| full-core-r1/run.json | 604 | `3970b7146bbdf943ebd70483e462528ddbcadabccecd4fe68f4e09b160823e74` |
| full-core-r1/runner.py | 5025 | `d85c470e95bebbb57d5d43939fc858d11c821453abf6aeba9e198961f0734fa2` |
| full-core-r1/source-after.json | 63813 | `7697717def213fe33e29730d11a2f03396a59b11088c1f3d68ba3d17b6a03078` |
| full-core-r1/source-before.json | 63813 | `7697717def213fe33e29730d11a2f03396a59b11088c1f3d68ba3d17b6a03078` |
| full-core-r1/tests.json | 267232 | `28219d42adfbe32f36f6c71ee9e0500cf36773795b8335f38145321b49c12d08` |
| full-core-r1/unittest.log | 310638 | `49fce1b616ca0c8a43e788f43e1ca36b19b5f79f7888a0182f4439ec2175e34b` |
| full-core-r2-summary.json | 35259 | `43ce4af45a8f7c4f71c61a45a7e2b2a84748b1838e636938ed545134f6586366` |
| full-core-r2/run.json | 612 | `a73552285b8fd6d5f2cf3af8293af4cbe1720c2d82921e491dae9ea142f60586` |
| full-core-r2/runner.py | 5440 | `5882fcc3f4965fa44f899aa0b7629e9473d0e4af7973ed7b3d8ac4f35896ec7a` |
| full-core-r2/source-after.json | 63813 | `422379425da52893c1b4a81cd77881f3826b176e11f21a935d06b8e80adb2725` |
| full-core-r2/source-before.json | 63813 | `422379425da52893c1b4a81cd77881f3826b176e11f21a935d06b8e80adb2725` |
| full-core-r2/tests.json | 255974 | `246c6c6f3e603e6a2e04947b6d733c04b653bc29003b76806474236461dfa6f4` |
| full-core-r2/unittest.log | 294452 | `3b467e5aa882c0ca86117011228954e1751e725121f71fa5564904c66b5be0c8` |
| full-regression-r1-summary.json | 31484 | `3d047628d0e5f10b6fef2d5a9fddce9841470ffc174bb4f0c8a233e9696dfe71` |
| full-suite-r1/run.json | 610 | `d1714fe73060c43fdfce81d51c182a7f2f2a04c5f7b37a1b25511b52cd2a5e85` |
| full-suite-r1/runner.py | 5025 | `d85c470e95bebbb57d5d43939fc858d11c821453abf6aeba9e198961f0734fa2` |
| full-suite-r1/source-after.json | 63813 | `7697717def213fe33e29730d11a2f03396a59b11088c1f3d68ba3d17b6a03078` |
| full-suite-r1/source-before.json | 63813 | `7697717def213fe33e29730d11a2f03396a59b11088c1f3d68ba3d17b6a03078` |
| full-suite-r1/tests.json | 19114 | `f010f6b3d28a600b0c09616787e55db092164d1e8bc7ecb1966efea99b5f4000` |
| full-suite-r1/unittest.log | 22616 | `ec909ee3f24185207a14672d365ee2d2f2e4278d19cbc05f242db0d95bb35d8d` |
| publish_evidence.config.json | 35587 | `255deabc173db886563bbf440459a2bf1cbd5ef33b4ac68f8db75ebff7d65192` |
| publish_evidence.py | 11498 | `cd2acaf1eaf9539dd51414d93240d0d061ac32dab8fa9b741f503d7211fd1b61` |
| run_tests.py | 5440 | `5882fcc3f4965fa44f899aa0b7629e9473d0e4af7973ed7b3d8ac4f35896ec7a` |
| runner-main-guard.json | 546 | `4430deb1c1e24f6febe655ab7b9546def9d8d66a7487a5467dc6fc6cba1ecc88` |

## 排除规则

- Only explicitly listed files are eligible; engineering snapshot members come from the final audited allowlist.
- Private runtime/state, workspace caches, credentials/environment files and all SQLite/database sidecars are excluded.
- Wheel binaries, archives, model files and unlisted file types are excluded; packaging uses hashes and import proofs.
- Required files are never silently omitted. Undeclared files and directories are not traversed.
- Inputs are not redacted or reformatted. Known API keys are read only from private files and matched exactly; any match aborts export.
