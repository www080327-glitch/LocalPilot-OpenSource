# engineering-r10

R10：候选 Luna high 的原始失败证据与固定验收输入，未替换或删减。

- [原始证据归档](engineering-r10.tar.gz)：40 个文件，95627 字节。
- [逐文件 SHA-256 清单](engineering-r10.MANIFEST.json)。
- 原始输入 SHA-256 与公开归档成员 SHA-256 一致；没有修改原始字节。
- 归档 SHA-256：`3ac31f0291e54bb7f51171be9ea4b030966fb6594c4264ad25e1fa6d4e8c3807`。
- 归档采用固定时间、固定权限和排序，保持可复现。

## 文件

| 路径 | 字节 | SHA-256 |
|---|---:|---|
| engineering-candidate-luna-high-r10.log | 204 | `7ee1dbdb48998e1e7491305368b600c58c901c8e18ec2921c51228d2352e4749` |
| engineering-candidate-luna-high-r10/FAILURE_ANALYSIS.json | 8904 | `eaeba2d0b93a308336d71dee1d485c0efc3d1611657a0e98dcb1224128bfc9e8` |
| engineering-candidate-luna-high-r10/POSTRUN_SUMMARY.json | 9996 | `f976ff5ca505f452a918ebd07b4ba0a05fc945939a8255397d85dc8600e707a9` |
| engineering-candidate-luna-high-r10/PROTOCOL.json | 14987 | `9f5757ec5e25b3040a470894ac54a0f71f0faf95a924690c2e1460592ca59533` |
| engineering-candidate-luna-high-r10/RESULTS.json | 120011 | `f61df664f7bfc237d7535da7f76d147ff7c143e988aa31da59f6ea1600903bab` |
| engineering-candidate-luna-high-r10/RUN_EXECUTION.json | 23542 | `de55a69b75b48713a3d7dc6443712a0a1e1967dc8c23d89828062da50eca3450` |
| engineering-candidate-luna-high-r10/acceptance-manifest.json | 1139 | `b22f47e53e46966a7d115b46974c07626217c3b03950735cf4f2b26cf80136fc` |
| engineering-candidate-luna-high-r10/acceptance-original/SPEC.md | 3304 | `3a581fcd5925e86dfcea0d87bbbcacfaf0065ed8139280c100769d8c6870c3e6` |
| engineering-candidate-luna-high-r10/acceptance-original/fixtures/basic.csv | 168 | `6c0dcee9e8d138f61ed6da850c9bc77be3ccabe49a98fb99a693298a6b431d41` |
| engineering-candidate-luna-high-r10/acceptance-original/fixtures/basic.expected.json | 374 | `3d8d1af6ab844d19fc24b4029044458ef877dfc129232e3f9824e6bf5d54d34a` |
| engineering-candidate-luna-high-r10/acceptance-original/fixtures/empty.csv | 26 | `318a41c33c77ab0db8e5c651bd4b9918c26222daf02f90d8e2e01a8bb5be516a` |
| engineering-candidate-luna-high-r10/acceptance-original/fixtures/invalid.csv | 61 | `74097f4b98ff64d3b01a6233836f5505ebe99bee92b9c8bc3537cb14a2f6dd34` |
| engineering-candidate-luna-high-r10/acceptance-original/fixtures/precision.csv | 208 | `c70350dc5653955376297e2ccedff0e24cf1371f5f09101958d0cd9182b723d8` |
| engineering-candidate-luna-high-r10/acceptance-original/fixtures/precision.expected.json | 528 | `ac5226181296f432e36f85e1bee5b5b6c1efb519bb1ae12755dd971e66850603` |
| engineering-candidate-luna-high-r10/acceptance-original/logstats/__init__.py | 45 | `ae8f92d8e600d6dc9ad8d3ac5063b4ee18d5ef365e259d9323608625b76ef7de` |
| engineering-candidate-luna-high-r10/acceptance-original/logstats/__main__.py | 137 | `f849849731b05ad7b37f1e6636741a8c7ecaf00a8d5e78712e5d132522546a5b` |
| engineering-candidate-luna-high-r10/acceptance-original/logstats/aggregate.py | 177 | `9d2e4a7aec763e41478efb936a03fccb545b72f775218aa8e11123e241535d0b` |
| engineering-candidate-luna-high-r10/acceptance-original/logstats/parser.py | 311 | `16b2d904fab3ccfbfe24baa15473981957458ce4996f582b8c8c5238bc69cbda` |
| engineering-candidate-luna-high-r10/acceptance-original/tests/test_acceptance.py | 6928 | `e406b48f904550da19c4feff630962f393197f024bcc0c77683163fe26081837` |
| engineering-candidate-luna-high-r10/engineering-task.json | 257405 | `3a9702ec354aa54d8f73c4b5c6fee6332f31c50447fb1271c9ad73979bcb4618` |
| engineering-candidate-luna-high-r10/external-cli.json | 6178 | `54c51ed4dbf6af5a6246a34c311afc7167b0f9929a776d34fe25091009c089c6` |
| engineering-candidate-luna-high-r10/external-unittest.json | 30230 | `4a8a1fbe629dd430e6772d167ae1b76f288af8e589025e06726dc881487cfca8` |
| engineering-candidate-luna-high-r10/file-manifest.json | 2562 | `6c3f9cad41e8c1c40d9443fc73f233a248584ab97e40305c610ab4a38577219c` |
| engineering-candidate-luna-high-r10/final-project/SPEC.md | 3304 | `3a581fcd5925e86dfcea0d87bbbcacfaf0065ed8139280c100769d8c6870c3e6` |
| engineering-candidate-luna-high-r10/final-project/fixtures/basic.csv | 168 | `6c0dcee9e8d138f61ed6da850c9bc77be3ccabe49a98fb99a693298a6b431d41` |
| engineering-candidate-luna-high-r10/final-project/fixtures/basic.expected.json | 374 | `3d8d1af6ab844d19fc24b4029044458ef877dfc129232e3f9824e6bf5d54d34a` |
| engineering-candidate-luna-high-r10/final-project/fixtures/empty.csv | 26 | `318a41c33c77ab0db8e5c651bd4b9918c26222daf02f90d8e2e01a8bb5be516a` |
| engineering-candidate-luna-high-r10/final-project/fixtures/invalid.csv | 61 | `74097f4b98ff64d3b01a6233836f5505ebe99bee92b9c8bc3537cb14a2f6dd34` |
| engineering-candidate-luna-high-r10/final-project/fixtures/precision.csv | 208 | `c70350dc5653955376297e2ccedff0e24cf1371f5f09101958d0cd9182b723d8` |
| engineering-candidate-luna-high-r10/final-project/fixtures/precision.expected.json | 528 | `ac5226181296f432e36f85e1bee5b5b6c1efb519bb1ae12755dd971e66850603` |
| engineering-candidate-luna-high-r10/final-project/logstats/__init__.py | 45 | `ae8f92d8e600d6dc9ad8d3ac5063b4ee18d5ef365e259d9323608625b76ef7de` |
| engineering-candidate-luna-high-r10/final-project/logstats/__main__.py | 921 | `d8e720747b4a9bc74ccf691e2626ecafd177912f23615a325f71535dcf685fa4` |
| engineering-candidate-luna-high-r10/final-project/logstats/aggregate.py | 2141 | `c96e94ca68d1e9ea800472559bbdc882dc4d38ca265057b718d11cf9b6234e3f` |
| engineering-candidate-luna-high-r10/final-project/logstats/parser.py | 311 | `16b2d904fab3ccfbfe24baa15473981957458ce4996f582b8c8c5238bc69cbda` |
| engineering-candidate-luna-high-r10/final-project/tests/test_acceptance.py | 6928 | `e406b48f904550da19c4feff630962f393197f024bcc0c77683163fe26081837` |
| engineering-candidate-luna-high-r10/project.diff | 3433 | `6de1dc8ed188df996e4ebcd46d7f5ccb1c499caf8cb8995eb1b644394892d8b1` |
| engineering-candidate-luna-high-r10/prompt.txt | 2396 | `cf4cc64fcd5eb2b0a97323d677562e3ac7c090b491b93025c92811ade7dcef0a` |
| engineering-candidate-luna-high-r10/resolved-inference.json | 422 | `4d03609ea2cd0dd9db86366015ddf08b10e16eab2a45df20f7a3d3bab37ee214` |
| engineering-candidate-luna-high-r10/resolved-runtime-budgets.json | 1238 | `603b4a44b1de4ac5bf6159d496350670ecdebffe64db9e461e10bf7130580dd8` |
| engineering-candidate-luna-high-r10/runner.py | 36204 | `1878a177ed32600e9d53490ad518a93ece8d729643f2e2681c7b10d11d4724c4` |

## 排除规则

- Only explicitly listed files are eligible; engineering snapshot members come from the final audited allowlist.
- Private runtime/state, workspace caches, credentials/environment files and all SQLite/database sidecars are excluded.
- Wheel binaries, archives, model files and unlisted file types are excluded; packaging uses hashes and import proofs.
- Required files are never silently omitted. Undeclared files and directories are not traversed.
- Inputs are not redacted or reformatted. Known API keys are read only from private files and matched exactly; any match aborts export.
