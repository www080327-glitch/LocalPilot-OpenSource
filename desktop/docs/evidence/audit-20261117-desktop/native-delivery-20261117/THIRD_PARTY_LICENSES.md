# Third-party license inventory for the Ubuntu arm64 Test build

This inventory is tied to PR source `b728bf1a62742ce7862bd48c49a5a5928cc19901` and the Ubuntu 24.04 arm64 RC14 Test DEB. License expressions below come from the corresponding locked package metadata; they are disclosure metadata, not a legal compatibility opinion.

| Included build area | Inventory | Count / evidence |
| --- | --- | --- |
| LocalPilot modules | Core `Apache-2.0 AND MIT`; Suite `Apache-2.0`; Companion `Apache-2.0`; Channels `Apache-2.0 AND MIT` | Component `pyproject.toml` files; their source license/notice files are carried in each built wheel |
| Isolated Python runtime | Version-pinned PyPI wheels and pip | 36 distributions in [runtime-dependencies-linux-arm64-py312.json](runtime-dependencies-linux-arm64-py312.json), with version, official file URL, SHA-256 and declared license. The packaged wheel `dist-info` license files were present in the extracted DEB. |
| Desktop frontend runtime | Non-development npm packages from the pinned `desktop/package-lock.json` | 108 entries in [npm-third-party-licenses.json](npm-third-party-licenses.json); license expressions were read from the installed package metadata corresponding to that lock. No missing license expressions were observed. |
| Rust/Tauri dependency lock | Registry crates from `desktop/src-tauri/Cargo.lock` | 514 entries in [cargo-third-party-licenses.json](cargo-third-party-licenses.json), collected through `cargo metadata --locked --offline`; all declared a license expression. The list includes target-specific lock entries that may not be linked into the Linux binary. |
| Bundled Node runtime | Official Node v22.23.4 Linux arm64 archive | SHA-256 `f7a1e486dbc8b286847815b477d4fb5e9fb963ed4489c3e1588853d685f589f9`; archive includes its `LICENSE` and Corepack/npm notice files listed in [node-license-files.txt](node-license-files.txt). |
| Desktop-specific notice | QRCode MIT notice | [desktop/licenses/qrcode-0.14.1-LICENSE-MIT.txt](../../../../licenses/qrcode-0.14.1-LICENSE-MIT.txt) is included by the existing Tauri resource configuration. |
| Repository and reused source | Apache-2.0 plus existing upstream notices | [root LICENSE](../../../../../LICENSE), [NOTICE](../../../../../NOTICE), and [DeepSeek Harness reuse/license record](../../../../../DEEPSEEK_HARNESS_REUSE_LICENSES.md) remain authoritative. |

The package build retains Python wheel license payloads and the existing Desktop license resource. The machine-readable inventories are supplied for a future release review; this Test package is not a release asset. The production macOS installers and release publication remain blocked by the missing real Mac builds and acceptance described in [RESULTS.md](RESULTS.md).
