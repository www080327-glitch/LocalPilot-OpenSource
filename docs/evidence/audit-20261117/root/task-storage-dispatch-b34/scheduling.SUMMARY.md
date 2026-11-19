# scheduling

分工配置、真实 loopback 角色/effort/恢复验证、完整前端及浏览器启动失败证据。

- [原始证据归档](scheduling.tar.gz)：20 个文件，24903 字节。
- [逐文件 SHA-256 清单](scheduling.MANIFEST.json)。
- 原始输入 SHA-256 与公开归档成员 SHA-256 一致；没有修改原始字节。
- 归档 SHA-256：`dea6ba278ebde2f3000ec9cb9bdbc2502c0836d5c16cf7d316d5e1efa93f1909`。
- 归档采用固定时间、固定权限和排序，保持可复现。

## 文件

| 路径 | 字节 | SHA-256 |
|---|---:|---|
| scheduling/SCHEDULING_REPORT.json | 3726 | `e9ae4135c4397c3ad2ab4935f3b1a837125fee3d3e00ea6a7294ad4e61f4cab5` |
| scheduling/frontend-r1/RESULTS.json | 1021 | `8c5a636d63f57753c66e6a289c028636fc60ac9b28b7dac77026784ce2926a8f` |
| scheduling/frontend-r1/SOURCE_AFTER.json | 16469 | `cd6f6dfd33de4eee947f3bc46034871e3d746c0aa030e89a0b1e54a807910ce2` |
| scheduling/frontend-r1/SOURCE_BEFORE.json | 16469 | `cd6f6dfd33de4eee947f3bc46034871e3d746c0aa030e89a0b1e54a807910ce2` |
| scheduling/frontend-r1/build.log | 889 | `af849d90e7053737da93f70ea402d14ab7b78621bdf3d6cb609b89e6bd3b96ff` |
| scheduling/frontend-r1/ui.log | 11870 | `19787bcb7977e98d702f428cd0fcd7ef4026a4395c383d02bee92395f0163568` |
| scheduling/frontend-r1/ui/browser-tests.json | 36561 | `bcb47d6c6f27a28bebc4b33ed723ba58e8a39c201b8b6e90a687f4ed1ba54e1a` |
| scheduling/frontend-r1/ui/test-results/.last-run.json | 145 | `edd64482c7e0a1e83e33b004914db45cd80b60943eae1124e916b12582e7bac7` |
| scheduling/frontend-r1/ui/test-results/model-configuration-option-11377-ator-and-configured-efforts/error-context.md | 5092 | `6c4e32559cf4d6be629a08687c5718e00d02da3c87f7a22a7b900d419aab1570` |
| scheduling/frontend-r1/ui/test-results/model-configuration-removi-2e8dc--clears-both-optional-roles/error-context.md | 5087 | `72e2f4ba3ced9a5afa0955b15eae9d7ab22a769cbf3b27b9b9fbc4fcebc9c907` |
| scheduling/frontend-r1/unit.log | 408 | `46ae575c9881a757d46e4ba229229ab58db85ea865a4f158f734b5f399ffe58d` |
| scheduling/initial-frontend-tools.json | 777 | `9afba9f642800b0cb3045bd0391ef0b21cb4804097e2de48b1ea0b47e3fcff9e` |
| scheduling/npm-ci.json | 285 | `4f646c6e5cb00edd357fceb42e4cb5ebf37518532ffcda2f05fd1d2e5dbb416f` |
| scheduling/r1/RESULTS.json | 1086 | `14de2f5eb08f704cc6cb05c294347107a1477b4ee820d36eaedfa082e41a426d` |
| scheduling/r1/SOURCE_AFTER.json | 18970 | `8482ecb5de208b0ba219562151171140fcc0124907d2344cbe612c03d5ac5742` |
| scheduling/r1/SOURCE_BEFORE.json | 18970 | `8482ecb5de208b0ba219562151171140fcc0124907d2344cbe612c03d5ac5742` |
| scheduling/r1/core.log | 1056 | `cb5b6530ac711500c1475d213d5bae6ab13d6251e03ce96a851c9b402ff7e579` |
| scheduling/r1/suite.log | 2865 | `2f3bc7b134c37d8d43ebae0a43dd8870cd5eaeb6e15e432d0b7a26abf56ead5a` |
| scheduling/run_checks.py | 2796 | `c21a95edd707d099357a36304f6551e32e082f913ccfa502d8a573f1836cb7ca` |
| scheduling/run_frontend.py | 2931 | `20ce3562ecba37325e08041af670d6308510af069de15eb98b891cd2e5a0d18b` |

## 排除规则

- Only explicitly listed files are eligible; engineering snapshot members come from the final audited allowlist.
- Private runtime/state, workspace caches, credentials/environment files and all SQLite/database sidecars are excluded.
- Wheel binaries, archives, model files and unlisted file types are excluded; packaging uses hashes and import proofs.
- Required files are never silently omitted. Undeclared files and directories are not traversed.
- Inputs are not redacted or reformatted. Known API keys are read only from private files and matched exactly; any match aborts export.
