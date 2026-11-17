# superagent

Super Agent 定向与跨版本验证、独立审阅、原 4k 窗口 rotation 失败诊断及修复复验。

- [原始证据归档](superagent.tar.gz)：46 个文件，50463 字节。
- [逐文件 SHA-256 清单](superagent.MANIFEST.json)。
- 原始输入 SHA-256 与公开归档成员 SHA-256 一致；没有修改原始字节。
- 归档 SHA-256：`6bdf9045e3d893a5258f0cd7c2ffdb4c6c7ee49d2ebe1f1ec7c93d04275736da`。
- 归档采用固定时间、固定权限和排序，保持可复现。

## 文件

| 路径 | 字节 | SHA-256 |
|---|---:|---|
| ENGINEERING_COMPARISON.json | 10628 | `88bead09600a07ff3e909e8f54a1e1aaa00232f06aeed40a6d1bd2d72040eea0` |
| ENGINEERING_PUBLIC_EVIDENCE_ALLOWLIST.json | 23937 | `72d24c92c43f1ebf63799f8387d2b132d9fede5cfffef3bce5a7e16a4f435bfc` |
| diagnose_rotation_budget.py | 3271 | `53b07033a93eba98477b03d40b636f1dc92be8e9bfc9f09ce30a68b774532509` |
| extract_engineering_inference.py | 3652 | `8fd71ae43c1e94031a7803441bbff7ecac13d358304399a8b3dc1ad5861aeca1` |
| review-core-final-delta.json | 2789 | `f8991faccd9e5dc1ba71988a83683a4adb02d825f8506dbb3a10fc3d33f59de0` |
| review-core-fixed.json | 4484 | `1d54b36ea620f7abdd632033d37c231a4f1faae4fd4f3588868a4fb71791e25d` |
| review-core-fixed.log | 717 | `1723b35d3b30752ed34eda830f4847f615e11f153488498843f01c026608454b` |
| review-core-reproductions.json | 3816 | `af5d9c51c0de1b164e86dac2cc5c1d68ba42d38ed49ea9bb4884b6d8512c2b20` |
| review-core.json | 8603 | `b269fa3b2da27482598da8c941208b614a7a66881d79a5773aa7f3f968d25498` |
| rotation-budget/baseline.json | 1812 | `d24ed764f37bc0f0c7f5d7cb8f28fd2b7e32ad7c30f42a678e986087006ce356` |
| rotation-budget/baseline.log | 330 | `890136a73ea9efb35acc207e09367520d32f0a42db840a0e31734e06f1fbd979` |
| rotation-budget/candidate-without-contract.json | 1802 | `eadff0a74102603c260d85339400b0442275d385a56124372f76397bef5a5ab6` |
| rotation-budget/candidate-without-contract.log | 330 | `720dcf7c40250cc00986dc522dfecfe22560c497160dac3cc4d3fb407304ba84` |
| rotation-budget/candidate.json | 2114 | `d71fa666908b092bcf8d3ce44eb7dfc462907833dda69c7ff783ca72fc87f514` |
| rotation-budget/candidate.log | 1470 | `99774f5bffed38eb637cd772e74f40897e52bef93f0498df18b67a56f63a5736` |
| summarize_engineering_run.py | 10163 | `a46313471952afdd3577588dd9f8cdc9a0a17b03cc5a8766cd909e157adb1554` |
| superagent/REPAIR_ANALYSIS.json | 3505 | `ed7ec9184be89a305e5a6e6a367ab32fb9a26be67736a2364484155ee4eae819` |
| superagent/cross-version-r2/expected.json | 6600 | `c8be2a7d8a7ce1598fb84529ddbbb7d4201230ea3cbfba0e4f883c6e78038ab0` |
| superagent/cross-version-r2/original-system.txt | 2733 | `882fc7bc3a3c877a308366b55eb9d82bb2714c4ef6a805e11c58fdfa65d88458` |
| superagent/cross-version-r2/restore.json | 249 | `308e2e7bb9556e30a58bf3c9cc53a9af34ca0e051ebcf64da1ea947e4656ad04` |
| superagent/cross-version-r2/write.json | 162 | `5c554cee2b931e2503ffaa00160f53a3c59b2508910db81e561118acad50d34f` |
| superagent/cross-version/expected.json | 6603 | `cb104148910e07725d8d3b32d3e97e7959f96c51dbf8d50b849f791769eef1bd` |
| superagent/cross-version/original-system.txt | 2733 | `882fc7bc3a3c877a308366b55eb9d82bb2714c4ef6a805e11c58fdfa65d88458` |
| superagent/cross-version/restore.json | 249 | `308e2e7bb9556e30a58bf3c9cc53a9af34ca0e051ebcf64da1ea947e4656ad04` |
| superagent/cross-version/write.json | 162 | `5c554cee2b931e2503ffaa00160f53a3c59b2508910db81e561118acad50d34f` |
| superagent/cross_version_session.py | 3762 | `57f13513bf80954c93b1e52b967760bb5808a60d1fdc262bbe76c1c79341a588` |
| superagent/review-negative-control-r2.log | 2263 | `11421d19a86d8d74626d0bd6342ec799888618a65715e28371ddd6d58f44efb1` |
| superagent/review-negative-control.log | 4585 | `c529ebbffbcbeff106678b847b661179608c8dd7f369c16f0f95107a38bb3ddf` |
| superagent/review-positive-control-r2.log | 717 | `494c49fb246a8fe6686ab15ae6035d02bb308400f7c61294d46bce9daa22a3a2` |
| superagent/review-positive-control.log | 2910 | `331df1e2150e72fbe3e020e350e15ed68bf81357cc960d590bb7832b46f8eb03` |
| superagent/rotation-fix-r1/RESULTS.json | 525 | `3e431a46cd21d49be97d05812381646a2882a6fc486ecc369a00c656e9049a9d` |
| superagent/rotation-fix-r1/source-after.json | 11391 | `193db384d7ae1ed8311d65a929c9a0b4f851f694d266204447d4a89b2b365887` |
| superagent/rotation-fix-r1/source-before.json | 11391 | `193db384d7ae1ed8311d65a929c9a0b4f851f694d266204447d4a89b2b365887` |
| superagent/rotation-fix-r1/unittest.log | 5656 | `e1ce559382759371b51e3daf955516091d228ede2d1865db8f596c99f2ea621c` |
| superagent/run_rotation_fix.py | 2321 | `a29de2fdcc47cd03c301e25da5d4d58b0bae340fb651da6d1485395f32b18462` |
| superagent/run_targeted.py | 2487 | `8ae76e36332d8208649997dca1520cb2db9f669fee158d38185398f81e4e846e` |
| superagent/run_targeted_r2.py | 2562 | `14c80fae0bbd46c13faa6b6f353767ac5dcf2fc7a1351c3ecd0d40b2b34cd164` |
| superagent/targeted-r1/RESULTS.json | 694 | `c932ff893d8f83ae7c675b49d5ad0a8e0b18f289b2e99dfa53b3a3ab2c2693e8` |
| superagent/targeted-r1/source-after.json | 11904 | `47b588d8724a735e5a46fe053b64ae86cbf48e5bbe27de5b81dd4a60da752071` |
| superagent/targeted-r1/source-before.json | 11904 | `47b588d8724a735e5a46fe053b64ae86cbf48e5bbe27de5b81dd4a60da752071` |
| superagent/targeted-r1/unittest.log | 20401 | `ab037c6cc85662265d99846fc8232b4a8f18a8e08a2aa9b378dac723123038c2` |
| superagent/targeted-r2/RESULTS.json | 767 | `f411a76386b415820de3b3f46e81a10be0f96ddf826d9d393c71ada48faf5c9e` |
| superagent/targeted-r2/source-after.json | 12114 | `8b53dfc363b0a876cd5273de1dc497511acc9491fb9e649bc3eecdd8a66efb25` |
| superagent/targeted-r2/source-before.json | 12114 | `8b53dfc363b0a876cd5273de1dc497511acc9491fb9e649bc3eecdd8a66efb25` |
| superagent/targeted-r2/unittest.log | 26506 | `18562233e96f68d50da52b7b1d07bfd601131c1640e7edc7fc8b15fa09453528` |
| work-contract-tools-only.patch | 717 | `b7b9c0f4438f580fe1db24f3797aac3afef19eef756eb018f108b1e9ab4cec98` |

## 排除规则

- Only explicitly listed files are eligible; engineering snapshot members come from the final audited allowlist.
- Private runtime/state, workspace caches, credentials/environment files and all SQLite/database sidecars are excluded.
- Wheel binaries, archives, model files and unlisted file types are excluded; packaging uses hashes and import proofs.
- Required files are never silently omitted. Undeclared files and directories are not traversed.
- Inputs are not redacted or reformatted. Known API keys are read only from private files and matched exactly; any match aborts export.
