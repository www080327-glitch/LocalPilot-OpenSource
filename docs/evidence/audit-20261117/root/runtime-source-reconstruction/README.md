# 受测 Runtime 源码子集重建

这里保存从最终源码 `91dd87c6fd4678c103d6383dec1c1385deb38f9a` 回到两份较早受测源码的自动生成补丁。**范围严格限于各轮原 `source.json` 记录的 110 个文件**，不是完整历史产品、桌面安装包或外部依赖重建。补丁方向是最终源码 → 较早受测字节，用于复核证据，不用于升级产品。

| 快照 | 补丁 | 原清单的精确副本 | 改动 / 相同文件 | 重建后的 manifest SHA-256 |
| --- | --- | --- | --- | --- |
| qualification-source-r1 / ITBench R1 | [R1 patch](qualification-source-r1.patch) | [R1 source](qualification-source-r1.source.json) | 5 / 105 | `7fb18d68f0bf0ee8bbaa4fc3bab5b7712b906f1644110105697fa1444a6fb70f` |
| qualification-source-r2 / ITBench R2 | [R2 patch](qualification-source-r2.patch) | [R2 source](qualification-source-r2.source.json) | 4 / 106 | `c8f42a51536163e7f7ddee04823cc103d03a0e26913201cad8108e959b6d84c2` |

补丁由冻结快照的精确文件字节经 `git diff --binary --full-index` 自动生成。两份 `source.json` 是输入元数据的逐字节副本，没有添加文件或改写摘要。[VALIDATION.json](VALIDATION.json) 保存输入、快照、补丁和基准文件哈希，以及实际 Git 命令与结果。

验证分别创建全新的临时 Git 目录，只复制最终源码对应的 110 个文件，再执行 `git apply --check --index` 和 `git apply --index`。两轮均 exit 0；应用后每个文件的 SHA-256 都与原清单一致，重新计算的清单摘要也完全一致。没有运行模型或业务测试，原始证据、快照和最终 checkout 均未修改。

## 复核方法

在包含基准提交的**独立新 checkout / worktree** 中操作。R1、R2 必须分别从 `91dd87c` 开始，不能叠加两个补丁。将下面 `LP_RECON_EVIDENCE` 指向本证据目录的绝对路径；选择 `r1` 或 `r2`。

```sh
LP_RECON_EVIDENCE=/absolute/path/to/runtime-source-reconstruction
LP_RECON_REV=r1
git checkout --detach 91dd87c6fd4678c103d6383dec1c1385deb38f9a
git apply --check "$LP_RECON_EVIDENCE/qualification-source-$LP_RECON_REV.patch"
git apply "$LP_RECON_EVIDENCE/qualification-source-$LP_RECON_REV.patch"
python - "$LP_RECON_EVIDENCE/qualification-source-$LP_RECON_REV.source.json" <<'PY'
from pathlib import Path
import hashlib, json, sys
manifest = json.loads(Path(sys.argv[1]).read_text())
actual = {name: hashlib.sha256(Path(name).read_bytes()).hexdigest()
          for name in sorted(manifest['files'])}
assert len(actual) == 110
assert actual == manifest['files']
digest = hashlib.sha256(json.dumps(actual, sort_keys=True).encode()).hexdigest()
assert digest == manifest['manifest_sha256']
print('110/110 exact file hashes; manifest:', digest)
PY
```

清单范围为 `agent` 65 个文件、`localpilot_api` 7 个、`localpilot_service` 37 个，以及 `scripts/qualify_openai_agent.py`。未列入的 Desktop、Companion、Suite、Computer / plugin 模块、其他专用 runner 和依赖不由这些补丁恢复。完整 checkout 中的这些未列文件仍保持最终版本；不能据此声称已经原样重跑完整历史环境。

`cloud-smoke-r1` 的 manifest 为 `1feb0270…`，其 `desktop_sessions.py` 中间版哈希为 `b28fffe5…`，两份冻结快照都没有对应的精确字节，因此明确排除。这里的 R1 不表示该 smoke R1。文件权限、mtime 和外部环境也不属于 SHA-256 字节清单的证明范围。
