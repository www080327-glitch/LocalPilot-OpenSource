# GitHub 公开源码与历史版本留存约定

> 2026-11-14 起执行。约束的是后续研发/发布流程，不代表已有 RC 或未验收候选通过发布检查。

## 唯一正式源码入口

- 后续产品源码、修复、Issue、PR 与版本索引统一写入公开仓库 [LocalPilot-OpenSource](https://github.com/www080327-glitch/LocalPilot-OpenSource)。每次开工核对 PR 最新 HEAD；并行提交不覆盖，不在历史私有仓库继续开发同一条产品主线。
- 旧 `LocalPilot` 私有仓库及 AIC 冻结仓库仅供追溯。**旧私有 Git 历史可能包含凭据、评测隐藏答案和未授权素材；不直接整体导入公开仓库或公开私有仓库访问权限。**若需迁出历史源码，先逐项审查敏感文件、第三方许可与需要保留的不可公开证据。
- 本仓库当前为 Public，仓库自有代码遵守 `LICENSE`（Apache-2.0）；第三方代码和素材遵循原许可证。开源不代表云端 API 密钥、安装证明、系统日志、模型权重或隐藏评测集也应公开。

## 可追溯版本在 GitHub，日常本地不存历史副本

1. 开发进行中：代码只通过公开仓库独立分支、PR、提交 SHA 保存。PR 可以是 Draft，不能把它宣传成正式发行。
2. 完成全部发布门禁后：批准合并的源码和每个模块的机器可读版本进入正式分支，以不可复用的版本 Tag（如 `desktop-v5.0.1-rc.7-chat-20261030`）对应一个**确切提交**，并在 GitHub Release 中归档该版本说明和构建产物。
3. GitHub Release 包含与 Tag/源提交核对一致的 macOS 安装包、SHA256SUMS、组件版本矩阵、第三方许可证说明、安装/回滚说明和实际测试证据。未经验证的资源不得冒充可发布应用；缺安装产物时只能明确写“源码候选 / NOT RELEASE-READY”。
4. 历史版本保持 GitHub Tags/Releases 可查，不覆盖旧 Tag、旧 Release Asset、不直接把“最新版”指向未经验收的候选。过去已有的公开 Release 保持原样；未搬迁的历史版本须由经审计的原始构建产物补录，不能凭版本名重新生成或猜测 SHA。
5. 新版本可追溯信息记录在 GitHub 代码/Tag/Release，**不以 Mac 上多个旧 APP、wheel、源码目录作为版本数据库**。实际安装的 APP 仍有自己的运行生命周期，不能因为 GitHub 已归档就自动删除。

## 本机仅作为真实运行与测试工作区

- 需要执行 Python、Vitest、Playwright、Rust、macOS GUI 或真实模型时，按仓库现有流程使用独立测试工作树、虚拟环境与临时构建槽。测试完成后由操作者**核实目录归属、活跃进程、备份关系、输出证据和是否可重建**，才决定是否清理；没有获得许可不删除已有 Mac 上的文件。
- `node_modules`、`.venv`、`target`、`__pycache__`、缓存、下载模型、原始日志和机器本地绝对路径只在本地使用，不作为 GitHub 历史发布物。
- 可公开的短验收结论、命令、测试数、精确源码 SHA 和局限放到 `docs/evidence`；**原始日志可能包含路径、账户、IP、敏感文件内容，默认不提交**。准备分享日志时先人工检查与脱敏。
- 发布前按现有 `desktop/scripts/`、`scripts/check-candidate-versions.py`、各 `MODULE_RELEASE.json`、`desktop/recommended-release.json` 的仓库流程，核对独立应用标识、真实 `bundled-backends` 资源、运行版本和回滚。不要从正在使用的日常 APP 偷换未校验的资源。
- 正式 APP 和持久用户数据不是“测试临时目录”；保留它们，直到用户明确授权的安装/迁移/卸载步骤完成。

## Desktop 更新来源与历史清单边界

- 新候选 Desktop 的只读“检查 GUI 更新”现在查询公开 `LocalPilot-OpenSource` 的 Release API、验证公开仓库下载路径；原私有仓库不能继续作为日常 GUI 更新来源。无需登录即可检查，登录 GitHub CLI 仍只是可选的查询方式。
- 公开仓库目前核实到一项 `desktop-v5.0.1-rc.7-chat-20261030` **预发布**，而更新器只自动推荐经过正式发布确认的稳定版本。因此现在没有可自动推荐的公共正式 GUI Release，并不意味着可以把 RC 伪装成稳定更新；首次可发布版本需通过实际原生打包与安装验收。
- `desktop/recommended-release.json` 是历史 5.0.0 来源快照，仍引用旧私有发行页。**不要在没有资产及 SHA256 对应证据时仅将历史网址替换成公共仓库网址**。公开历史版本回填由 [GitHub Issue #4](https://github.com/www080327-glitch/LocalPilot-OpenSource/issues/4) 跟踪。
- 历史 benchmark 包仍在旧研发仓库，公开版只提供可复现的非 benchmark 产品测试；缺包的模块通过明确的 unittest SKIP 标识 NOT_RUN，而不是把导入 ERROR 或未运行说成成功。其可审计开源迁移由 [GitHub Issue #3](https://github.com/www080327-glitch/LocalPilot-OpenSource/issues/3) 跟踪。

## 当前 PR #1 的限制

`fix/nationals-runtime-ux-20261113` 尚是 Draft。最近一次完整 macOS Python 结果仍有 5 failures、13 个缺少公开 benchmark 模块的 import errors；真实 APP 打包/安装、双向真实模型协同、SSE 409 与统一升级回滚均未通过验收。**该分支只保留为 GitHub 候选历史；不得新建发布 Tag 或覆盖 Release/Latest。**

[公开历史发行](https://github.com/www080327-glitch/LocalPilot-OpenSource/releases) · [当前整改 PR #1](https://github.com/www080327-glitch/LocalPilot-OpenSource/pull/1)
