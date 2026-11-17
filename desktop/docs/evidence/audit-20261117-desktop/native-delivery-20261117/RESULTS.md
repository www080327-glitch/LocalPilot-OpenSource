# Native delivery follow-up — 2026-11-17

## Result

**Ubuntu 24.04 arm64 Test DEB build and system install/upgrade/rollback: PASS. macOS Apple Silicon and Intel native delivery: NOT_RUN. Release: NOT RELEASE-READY.** This run adds evidence; it does not change production source or relabel prior failures.

At kickoff, PR #15 HEAD was `b728bf1a62742ce7862bd48c49a5a5928cc19901`, and production source remained frozen at `c5439659a579b2ee9e74fd53e6d3232fe12fb855`. The build used a clean checkout at the PR HEAD (`source_dirty=false`). The generated DEB is the isolated Test identity and stays in the Ubuntu VM; it was not copied to the Mac or uploaded to GitHub under the low-data instruction.

| Check | Result |
| --- | --- |
| Ubuntu builder | Ubuntu 24.04.4 LTS, arm64/aarch64, Linux 6.8.0-149-generic, glibc 2.39, CPython 3.12.3; account had normal `sudo` access |
| Build tools | Rust/Cargo 1.100.0; Node 22.23.4; Rust build used one worker and the repository build entry point |
| RC14 Test DEB | `LocalPilot-Test-5.0.1-rc.14-linux-arm64.deb`, 112,400,014 bytes, SHA-256 `10a0130f62bbffbdb499c46ab0553441f889a9c750920a0c6c40fcf4abd6a659` |
| Packaged versions | Desktop 5.0.1-rc.14 / Core 5.0.0b31 / Suite 0.2.0b32 / Companion 0.5.7b8 / Channels 0.1.0a4 |
| Runtime resources | 40 wheels checked; isolated imports and `pip check` passed; Node 22.23.4 archive SHA-256 `f7a1e486dbc8b286847815b477d4fb5e9fb963ed4489c3e1588853d685f589f9` |
| Package self-check | PASS: arm64 ELF, bundle ID `io.localpilot.desktop.test`, RC14 and module versions agree; `services_started=false`, `user_data_opened=false` |
| apt system transaction | PASS: built RC13 Test fixture installed first; apt upgraded to RC14; `apt-get install --allow-downgrades` restored RC13; RC14 was installed again after rollback |
| Data isolation | `test-owner.json` SHA-256 stayed `8487dfdcf54cf360951d6dd600563a58bba5a1cec4a97841b8a5fda1e7d6afb4` across install, upgrade, rollback, and restoration |

The RC13 package is an upgrade/rollback fixture rebuilt from historical source commit `1dca93c5a6a2d0c557a9507ca020c07458dd92d1` (Desktop RC13 / Core b30). It is not presented as a historical Release asset and was not uploaded. Its actual test-package SHA-256 is `b32c9570c8e2dbd04ee400880a0ca52d66642a7d1d29a3bac646609a43f3db1f` (112,398,524 bytes). Both the pre-install extracted-package checks and post-install `--bundle-self-check` ran against each version. The private apt command logs remain on the VM; the published record contains only the result and hashes.

## macOS and GUI matrix

| Target | Result | Evidence boundary |
| --- | --- | --- |
| Apple Silicon Mac | **NOT_RUN** | Current host is arm64 macOS 27.0.1, but full Xcode is absent (`xcodebuild` reports only Command Line Tools selected). The required `~/Applications/LocalPilot Test.app` slot is occupied by a running prior Test APP and its services. Neither was stopped or replaced. No candidate APP was built or installed. |
| Intel Mac | **NOT_RUN** | No Intel Mac was available. Rosetta, Linux, static tests, and previous builds are not substituted for an Intel device. |
| First setup, Full long-task selection, Super Agent, Companion bubble focus, zoom, multiple displays, reduced motion, cancel/recovery | **NOT_RUN on a new candidate** | No new Mac APP was built or interacted with. Previous RC14 Linux WebKit results and animation numbers are not transferred to Mac. |
| Animation update rate | **NOT_RUN on a new Mac candidate** | The Ubuntu VM has no GUI session. Prior 6007 ms Linux WebKit sampling belongs to its recorded artifact and is not a Mac measurement. |
| Model request | **NOT_RUN** | No model request was needed for package identity or apt transactions; no private credential was read and no balance was queried. |

## Release state

This does **not** pass the repository release gate. The Apple Silicon real build/install and required UI acceptance are missing; Intel real-device acceptance is missing; this DEB is a Test identity rather than a production package. No Tag or GitHub Release was created or changed, no historical Release or failed result was edited, and no release asset was uploaded. Existing audit evidence remains in its original locations.

The Ubuntu arm64 DEB and its build output remain in the local Multipass VM. The PR contains only the small text evidence, hashes, source-derived license inventories, and metadata files linked below.

- [RC14 package build results](build-results/RC14-TEST-package-results.json)
- [RC13 rollback-fixture build results](history-baseline/RC13-TEST-package-results.json)
- [Ubuntu 24.04 arm64 / Python 3.12 dependency lock](runtime-dependencies-linux-arm64-py312.json)
- [Full third-party license inventory](THIRD_PARTY_LICENSES.md)
- [System apt transaction matrix](system-installation.json)
- [Version matrix](VERSION_MATRIX.json)
- [Checksums for DEBs retained in the VM](VM-ARTIFACT-SHA256SUMS.txt)
