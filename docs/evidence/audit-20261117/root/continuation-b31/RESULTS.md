# RC14 / b31 续作：恢复、完整回归与已安装组件补验

日期：2026-11-17（Asia/Shanghai）。本轮从 GitHub PR #15 的 `89c46468995c46f90a73d9c41ea0044d564cd175` 恢复独立工作树，Git tree 为 `af45086818468de3c4dd12e93f5e216ac9aa9b60`。生产源码继续绑定 `c5439659a579b2ee9e74fd53e6d3232fe12fb855`，Desktop RC14 / Core b31 / Suite b32 / Companion b8 / Channels a4。**本轮修改当前操作文档并增加证据，没有修改生产代码、测试、版本或历史验收结果。**

## 本轮结果

| 检查 | 实际结果 | 证据 |
| --- | --- | --- |
| b31 Core 完整回归 | **1,644 执行 = 1,545 PASS + 99 SKIP；0 failure / error；177.165 秒** | [完整输出](core-core-full.log.gz)、[运行身份及源码清单](core-run.json.gz)、[可读摘要](SUMMARY.json) |
| 当前四组件 wheel | 按既有 setuptools / build 流程重新构建并安装到独立用户虚拟环境；Core b31、Suite b32、Companion b8、Channels a4 | [构建输出](installed/build.log.gz)、[安装输出](installed/install.log.gz)、[新 wheel 的大小与 SHA](installed/run.json) |
| 已安装组件导入及依赖 | `python -I` 确认五个产品模块均从该虚拟环境导入；实际服务版本 b31；`pip check` PASS | [导入证明](installed/import-proof.json)、[依赖检查](installed/pip-check.log) |
| 渠道诊断与生命周期补验 | **12/12 PASS，0 SKIP，5.640 秒**；真实 HTTP、子进程、SQLite、停止与重启，模型及平台端点为合成夹具 | [测试原始输出](installed/tests.log)、[命令与运行身份](installed/run.json) |
| 生产源一致性 | 635 个选定源码、测试与构建输入文件的测试前后 SHA 相同；相对冻结源码的非文档差异为空 | [SUMMARY.json](SUMMARY.json)、[完整文件清单](core-run.json.gz) |
| 组件版本门禁 | PASS，版本维持 RC14 / b31 / b32 / b8 | [实际 checker 输出](version-check.json) |
| 已发布证据恢复完整性 | 七组归档 **743 个 payload** 的大小与 SHA256 全部匹配，没有未列入清单的文件 | [逐组清单身份与结果](archive-integrity.json) |

Core 完整回归于上海时间 **09:01:43–09:04:41** 执行，解释器为 Python 3.12.14，系统为 Debian 13 x86_64。177.165 秒是 unittest 报告的测试时长；177.990 秒是外层启动、运行和收尾总时长。安装态补验使用同一 Python minor 的全新独立虚拟环境，依赖版本及解释器信息单独记录。它不代表最终 DEB 的 Python 3.13 环境或系统包安装验收。

安装态测试的 harness 只复制现有测试与 wheel 中的渠道资产，不复制产品源码；`-I` 导入检查确认产品模块来自实际安装目录。测试观察了失败诊断不泄漏任意异常文本、真实子进程回收、HTTP 就绪后的身份确认、最终身份保存失败的清理、SIGINT / SIGTERM、显式重启与测试安装卸载。没有连接真实微信/QQ 账户，也没有调用付费模型。

补验结束后的[自有进程检查](owned-process-check.json)记录该测试 runtime 的产品服务剩余数为 0；没有清理或停止其他用户进程。

四个新 wheel 是本轮隔离补验的构建输入，**不是原 RC14 DEB 的替代身份**。原 RC14 DEB 的历史哈希及提取运行结果继续保留在[原始 RC14 报告](../../../../../desktop/docs/evidence/audit-20261117-desktop/final-package-rc14/RESULTS.md)。重新构建的任何交付包都须记录其自己的真实哈希。

## 跳过项没有改判

本轮 Core 完整回归的 99 项 SKIP 比旧 R2 多 8 项：7 项缺少可导入的已安装 Suite，1 项缺少原固定旧版本工作树。安装态补验通过了前述 7 项，并额外执行了需要显式 Channels wheel 的 5 项现有测试；完整回归的原日志仍保留 99 SKIP，两个运行的数字不相加充当另一轮全量结果。

剩余旧版本迁移用例为 `WorkerBudgetUpgradeTests.test_old_build_unknown_restore_new_default_and_strict_host_changes`。它要求 `LOCALPILOT_WORKER_BUDGET_LEGACY_SOURCE` 指向当时真实运行的旧源码。原[迁移 fixture 记录](../../../native-polish-20261116/child-budget/LEGACY_FIXTURES.json)绑定 Core b24 的 Qwen 冻结脏树；[原冻结清单](../../../qwen35-linux-20261116/SOURCE_FREEZE.json)记录基线 `d846fef0`、`working_tree_modified=true` 和 448 文件身份。当前环境没有该目录，公开历史也未能补齐精确内容，不能用任意旧提交或只匹配预算文件代替。该项本轮保持 SKIP，既有历史 PASS 保留。

其他 SKIP 的原始原因保存在 [SUMMARY.json](SUMMARY.json)，包括可选 SDK、未公开历史 benchmark、指定 Harbor / 历史 checkout、真实本地模型预算测试和 macOS 原生 Shell。没有修改 skip 条件、放宽断言或为减少 SKIP 重写夹具。

## 当前文档修正

- [根 README](../../../../../README.md)、[Desktop README](../../../../../desktop/README.md)与[Linux 指南](../../../../../desktop/docs/development/LINUX_20261116.md)：当前 DEB 文件名、构建输出槽和 Test 根目录同步 RC14，证据入口指向实际 RC14；明确尚无公开 RC14 二进制下载，历史 SHA 不能用于新构建。
- 上述 README 描述实际共享“连接云端模型”表单：选择 DeepSeek / OpenAI、模型和密钥，保存后在模型选择器选用；OpenAI 默认 Luna，生成 Responses 路由，配置保存不发送模型任务。
- [2026-11-16 OpenAI 说明](../../../../development/OPENAI_AND_PUBLIC_EVALUATION_20261116.md)增加当前入口和证据导航，明确后文是旧阶段快照；旧 Chat 配置、未运行记录和当时交接文字保留，不再作为当前要求。本轮没有查询账户余额。

这些修正不计入上一轮四类各十项的生产审计数量。

## 请求前缀限制复核

[无网络探针](prefix-review/probe.py)继续复现 V5 临时 Host state 不进入下一轮 canonical history：首次请求为三个 input item，下一轮 reasoning 前仅剩两个；reasoning、function call 和 function result 仍在下一次 payload 中。[工具输出转录](prefix-review/probe-tool-output.transcript.txt)明确标为执行后保存的 tool-output transcript，没有伪装成独立捕获的原始进程日志。

该结构不满足 [OpenAI 的推理前缀保留条件](https://developers.openai.com/api/docs/guides/preserved-reasoning)。现有真实模型归档没有 provider `input_transformations`，因此本轮不能证明实际移除了多少 reasoning，也未测量成本、延迟或质量影响。另行运行的 32 项现有测试与完整 Core 回归重叠，不另计覆盖；其原始日志没有落盘，只保留[命令及转录来源说明](prefix-review/README.md)。

本轮没有把临时快照直接塞入历史：这会改变 V5 已有的上下文预算、压缩与恢复语义，而单改快照也不覆盖最终交付阶段工具集合、换模或压缩导致的前缀变化。该限制继续保持**未修复**，不计为新修复项。

## 仍未完成的原生交付

当前执行器与可操作桌面均为 Linux。当前 OS 用户没有 `sudo`、`pkexec` 或可用的系统包安装 helper；未暴露可执行的 macOS 主机。GitHub 连接器可写源码和 PR，但当前工具没有 Release 资产上传操作；CLI 未登录，本地浏览器连接不可用，云端 Release 上传入口显示 GitHub 登录页。

因此 Linux 系统 DEB 首装 / 升级 / 回滚、macOS Apple Silicon / Intel 实机验收，以及新二进制 Release 上传仍未完成。用户此前的授权继续有效；这些缺项来自当前实际环境与登录能力，没有再次请求普通代码修改或测试授权。本轮没有合并 PR、创建 Tag、发布 Release 或覆盖旧资产。

**SOURCE CANDIDATE — NOT_RELEASE_READY。** 本轮没有新付费模型调用、余额查询或公开基准重跑；R6、两小时任务、动画采样与两份 ITBench-AA 成绩均保持自己的原始来源和范围。

## 归档方式

[PUBLICATION_TRANSFORMS.json](PUBLICATION_TRANSFORMS.json)记录源文件和发布字节的 SHA256、固定路径替换及确定性 gzip。只收录检查输出、可公开的合成测试记录和现有源码探针；虚拟环境、wheel、数据库、运行时配置、凭据及模型数据不进入本归档。最终 [ARTIFACT_MANIFEST.json](ARTIFACT_MANIFEST.json)不包含自身。
