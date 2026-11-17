# engineering-r11

R11：最终候选 Sol medium 的原始工程结果、固定验收输入与实际 model/effort 摘录。

- [原始证据归档](engineering-r11.tar.gz)：41 个文件，132737 字节。
- [逐文件 SHA-256 清单](engineering-r11.MANIFEST.json)。
- 原始输入 SHA-256 与公开归档成员 SHA-256 一致；没有修改原始字节。
- 归档 SHA-256：`b828fff66c5e4f6e1a2710570fcecb74e3ac7e7af5bb6bddd4780d995f21abc8`。
- 归档采用固定时间、固定权限和排序，保持可复现。

## 文件

| 路径 | 字节 | SHA-256 |
|---|---:|---|
| engineering-candidate-sol-medium-r11.log | 203 | `023e7ebfccfac40a2786586ad0a778c1cddd7b8e3ed4ad61cb184a0f7e0a4ccd` |
| engineering-candidate-sol-medium-r11/INFERENCE_AUDIT.json | 9795 | `0d190b678d9b632625d7eaf0294a48ee27f43b82ec270cf2d4cb409b56660938` |
| engineering-candidate-sol-medium-r11/POSTRUN_SUMMARY.json | 8549 | `d54a7022770275a6d5290d33b3d94c8047b05ba765ae7e1c005212f574d4c1aa` |
| engineering-candidate-sol-medium-r11/PROTOCOL.json | 14987 | `70940b4e4306147be7b95b92cdb57a64cbe93b28c8ee90c0d22f2d69c597bb4f` |
| engineering-candidate-sol-medium-r11/RESULTS.json | 181935 | `315c42c913bd5955de918f10b38a8ecf43fb468259025ff6a6e81dfa5a7d8d78` |
| engineering-candidate-sol-medium-r11/RUN_EXECUTION.json | 23545 | `aa5bf4785ba72c3b2a15af821a7902e940b30b8bca88a680c92d06eccfe997ec` |
| engineering-candidate-sol-medium-r11/acceptance-manifest.json | 1139 | `b22f47e53e46966a7d115b46974c07626217c3b03950735cf4f2b26cf80136fc` |
| engineering-candidate-sol-medium-r11/acceptance-original/SPEC.md | 3304 | `3a581fcd5925e86dfcea0d87bbbcacfaf0065ed8139280c100769d8c6870c3e6` |
| engineering-candidate-sol-medium-r11/acceptance-original/fixtures/basic.csv | 168 | `6c0dcee9e8d138f61ed6da850c9bc77be3ccabe49a98fb99a693298a6b431d41` |
| engineering-candidate-sol-medium-r11/acceptance-original/fixtures/basic.expected.json | 374 | `3d8d1af6ab844d19fc24b4029044458ef877dfc129232e3f9824e6bf5d54d34a` |
| engineering-candidate-sol-medium-r11/acceptance-original/fixtures/empty.csv | 26 | `318a41c33c77ab0db8e5c651bd4b9918c26222daf02f90d8e2e01a8bb5be516a` |
| engineering-candidate-sol-medium-r11/acceptance-original/fixtures/invalid.csv | 61 | `74097f4b98ff64d3b01a6233836f5505ebe99bee92b9c8bc3537cb14a2f6dd34` |
| engineering-candidate-sol-medium-r11/acceptance-original/fixtures/precision.csv | 208 | `c70350dc5653955376297e2ccedff0e24cf1371f5f09101958d0cd9182b723d8` |
| engineering-candidate-sol-medium-r11/acceptance-original/fixtures/precision.expected.json | 528 | `ac5226181296f432e36f85e1bee5b5b6c1efb519bb1ae12755dd971e66850603` |
| engineering-candidate-sol-medium-r11/acceptance-original/logstats/__init__.py | 45 | `ae8f92d8e600d6dc9ad8d3ac5063b4ee18d5ef365e259d9323608625b76ef7de` |
| engineering-candidate-sol-medium-r11/acceptance-original/logstats/__main__.py | 137 | `f849849731b05ad7b37f1e6636741a8c7ecaf00a8d5e78712e5d132522546a5b` |
| engineering-candidate-sol-medium-r11/acceptance-original/logstats/aggregate.py | 177 | `9d2e4a7aec763e41478efb936a03fccb545b72f775218aa8e11123e241535d0b` |
| engineering-candidate-sol-medium-r11/acceptance-original/logstats/parser.py | 311 | `16b2d904fab3ccfbfe24baa15473981957458ce4996f582b8c8c5238bc69cbda` |
| engineering-candidate-sol-medium-r11/acceptance-original/tests/test_acceptance.py | 6928 | `e406b48f904550da19c4feff630962f393197f024bcc0c77683163fe26081837` |
| engineering-candidate-sol-medium-r11/engineering-task.json | 361073 | `30f15cce468f6d277ba2d10ba6e97e191e91b4f0da7c0e371bf4685e5a5b6623` |
| engineering-candidate-sol-medium-r11/external-cli.json | 4455 | `c2e8d4228e7c8e5b255c2ee44cd3b7250ceaef5e63f779cdb17f3a0859fd428f` |
| engineering-candidate-sol-medium-r11/external-unittest.json | 2032 | `40127637b3db99be9922d95c9bd54a154bb158bc7ba83c77d35b9a20d47d2444` |
| engineering-candidate-sol-medium-r11/file-manifest.json | 2650 | `38dcadc8969d104ccc2b6e0fabe3e7f9d039ccc9344cc728b4ddfaa234e8fcc2` |
| engineering-candidate-sol-medium-r11/final-project/SPEC.md | 3304 | `3a581fcd5925e86dfcea0d87bbbcacfaf0065ed8139280c100769d8c6870c3e6` |
| engineering-candidate-sol-medium-r11/final-project/fixtures/basic.csv | 168 | `6c0dcee9e8d138f61ed6da850c9bc77be3ccabe49a98fb99a693298a6b431d41` |
| engineering-candidate-sol-medium-r11/final-project/fixtures/basic.expected.json | 374 | `3d8d1af6ab844d19fc24b4029044458ef877dfc129232e3f9824e6bf5d54d34a` |
| engineering-candidate-sol-medium-r11/final-project/fixtures/empty.csv | 26 | `318a41c33c77ab0db8e5c651bd4b9918c26222daf02f90d8e2e01a8bb5be516a` |
| engineering-candidate-sol-medium-r11/final-project/fixtures/invalid.csv | 61 | `74097f4b98ff64d3b01a6233836f5505ebe99bee92b9c8bc3537cb14a2f6dd34` |
| engineering-candidate-sol-medium-r11/final-project/fixtures/precision.csv | 208 | `c70350dc5653955376297e2ccedff0e24cf1371f5f09101958d0cd9182b723d8` |
| engineering-candidate-sol-medium-r11/final-project/fixtures/precision.expected.json | 528 | `ac5226181296f432e36f85e1bee5b5b6c1efb519bb1ae12755dd971e66850603` |
| engineering-candidate-sol-medium-r11/final-project/logstats/__init__.py | 45 | `ae8f92d8e600d6dc9ad8d3ac5063b4ee18d5ef365e259d9323608625b76ef7de` |
| engineering-candidate-sol-medium-r11/final-project/logstats/__main__.py | 1415 | `61e5e5e010ded05277f62c2c68773f7bd2a06f5a7b0dceda23514aa46d17c1e3` |
| engineering-candidate-sol-medium-r11/final-project/logstats/aggregate.py | 1947 | `65620ff1c2ccac8de8ec0af2958b57b4f95cfc9b8334cad190c6c7fce470888f` |
| engineering-candidate-sol-medium-r11/final-project/logstats/parser.py | 3388 | `d1f7a93fc612cec3b7af71176338ec5d729551ca833fddda000e9de6dd1b2042` |
| engineering-candidate-sol-medium-r11/final-project/result.json | 284 | `a3211a34cf3e4419cf8c2c89c33d51009dbff3d2ee06b6597cde3912af3e5a69` |
| engineering-candidate-sol-medium-r11/final-project/tests/test_acceptance.py | 6928 | `e406b48f904550da19c4feff630962f393197f024bcc0c77683163fe26081837` |
| engineering-candidate-sol-medium-r11/project.diff | 7350 | `1aa5a87095833b1730e34d73372624a5264c0bee276e35efb4d1f2ad675c5e63` |
| engineering-candidate-sol-medium-r11/prompt.txt | 2396 | `cf4cc64fcd5eb2b0a97323d677562e3ac7c090b491b93025c92811ade7dcef0a` |
| engineering-candidate-sol-medium-r11/resolved-inference.json | 434 | `4d08b44fa5f7756faebbe7f34b4f3cb4614488032921332d103d5cfc707be29d` |
| engineering-candidate-sol-medium-r11/resolved-runtime-budgets.json | 1238 | `603b4a44b1de4ac5bf6159d496350670ecdebffe64db9e461e10bf7130580dd8` |
| engineering-candidate-sol-medium-r11/runner.py | 36204 | `1878a177ed32600e9d53490ad518a93ece8d729643f2e2681c7b10d11d4724c4` |

## 排除规则

- Only explicitly listed files are eligible; engineering snapshot members come from the final audited allowlist.
- Private runtime/state, workspace caches, credentials/environment files and all SQLite/database sidecars are excluded.
- Wheel binaries, archives, model files and unlisted file types are excluded; packaging uses hashes and import proofs.
- Required files are never silently omitted. Undeclared files and directories are not traversed.
- Inputs are not redacted or reformatted. Known API keys are read only from private files and matched exactly; any match aborts export.
