# Companion 持续对话与历史恢复验收 — 2026-11-17

本目录对应 **Desktop 5.0.1-rc.15 / Core 5.0.0b32 / Companion 0.5.7b9**。Python 回归与前端构建通过；**浏览器交互验收未运行，不能记为 UI PASS**。

源码身份是基线 `e278f0677c8eed4c0d49b6b08a672e15fe56495d` 加工作区修改，并由 SHA-256 清单绑定。本目录没有虚构新的提交号，也不把 RC14 的原生安装或动画证据改记为 RC15。

## 已验证的行为与改动

- 保留的旧聊天通过 SQLite FTS 搜索；相关匹配不再被最近 100 条或最近 9 条截断丢失。
- 回答依赖按记录 ID 检查，仍有效的旧来源不会因为落到最近 10,000 条之外而被误判不存在。
- 命中发生在消息后半段时，使用带原文位置的查询节选；SQLite 原文不改写。
- 有明确关联的最近一组问答才能为完整短语“继续”等提供衔接；没有有效问答组时不猜测话题。升级到 Agent 的路径保留同一份选中历史。
- 新增只读 `pet_history`，走已有认证通道，以时间戳与 ID 分页。关闭记忆时不读取历史，失效来源对应的回答不会重新进入返回结果。
- 桌宠恢复已保存消息的代码使用稳定 ID 合并，不按文本去重；恢复、翻页、未发送草稿和实时消息的浏览器用例已编写，当前不能作交互通过结论。

默认仍保留最多 10,000 条聊天；模型历史最多 9 条、序列化内容不超过 3,000 字符，每条节选最多 500 字符。界面初次读取 30 条、接口单页上限 50。没有引入无限保留、额外会话文件轮换或按固定 55 分钟调用付费模型压缩。

## 最终门禁

| 范围 | 结果 | 时长与身份 |
|---|---|---|
| 针对性 Python 回归 | **101 PASS，0 SKIP / FAIL / ERROR** | 4.039 秒；[结果](TARGETED_RESULTS.json)与[当时 12 个 owned 文件快照](TARGETED_SOURCE_FILES.json) |
| 完整 Companion 套件 | **744 = 711 PASS + 33 SKIP；0 FAIL / ERROR** | unittest 34.718 秒，总运行 35.242705 秒；[结果](FULL_RESULTS.json)与[503 文件源码清单](FULL_SOURCE_FILES.json) |
| 现有 Vitest 单元测试 | **13 文件、74 测试全部通过** | `npm test`；不是挂载后的历史界面验收 |
| 前端生产构建 | **PASS** | `npm run build`，TypeScript + Vite；[结果](FRONTEND_RESULTS.json)与[118 文件清单](FRONTEND_SOURCE_FILES.json) |
| 历史界面 Playwright | **NOT_RUN** | 原 7 例均在浏览器创建页面前被环境阻断；复审新增第 8 例未执行 |

完整 Python 测试使用 Python 3.12.14：

```sh
python -B -m unittest discover -s companion/tests -t . -v
```

完整运行期间 503 个所选文件前后完全一致，两个源码清单的 SHA-256 均为 `ff1ba29dd382727dff40a4e3b77190d9623633157fc89430ec5f5e2be76d46cd`。运行时间为北京时间 2026-11-17 12:03:44–12:04:20。

前端门禁使用 Node v24.22.1、npm 11.9.0。118 文件运行前后清单 SHA-256 均为 `67453fece514c2008dbc671498c88ce24e0908e747609930b07593d477bf1484`。这次构建只证明前端能编译，不证明原生平台验收完成。

33 个跳过项分别为：25 个 macOS Swift 夹具、5 个未安装的固定 Linux 训练环境、2 个尚未提供的 whisper.cpp / 模型 / 公开样本，以及 1 个不可用的隔离 Xvfb / D-Bus 工具环境。完整名称与原因在归档的 `raw/companion-full-r2/skipped.json`。

针对性 101 项运行只有当时的 owned 文件快照，没有另行自动捕获其运行前后全量源码；随后完整门禁提供了这项核验。完整 Python 门禁后有 README 文档修改，后来复审修复只改桌宠 UI 与其 UI 用例，没有修改 Python 实现或测试。详见 [源码连续性](SOURCE_CONTINUITY.json)，不要将后续整个工作区误写成完全相同的冻结树。

## 保留失败与复审

初次完整开发运行：736 项，663 PASS、33 SKIP、9 FAIL、31 ERROR；错误集中于真实本地服务提交返回 HTTP 500。当时共享源码仍在修改。原日志保留为 `raw/companion/full-suite.log`，不能拿后来成功的结果覆盖这次失败，也不能把这次运行当成冻结后的最终门禁。随后单独诊断原失败的恢复用例通过，最终完整 744 项运行也通过。

同一套 10 个新增归档与续聊测试在未修复的生产实现上出现 **6 FAIL、4 PASS**；这些生产文件的字节已与 e278 基线核对。修复后这些测试包含在最终 101 / 744 项中。不能把重叠运行累加为更多独立测试。

复审还发现一个确定的界面排序缺陷：加载旧页后，关闭再开启记忆会重取最新页并放到旧页前。最小修复保留已加载历史及旧游标，只有尚未载入历史时才请求首屏；记忆关闭期间的当前消息保持原位。原实现的纯合并逻辑复现保留在归档，修复后的具体界面场景是新增第 8 个 Playwright 用例。**该用例没有运行**；修复后的实际验证是现有 74 项单元测试与前端构建通过。见 [复审记录](UI_ORDER_FIX_REVIEW.json)。

## 界面环境阻断

本地 Chromium 在创建页面前报告 `socket() failed: Operation not permitted` 并退出，原 7 个用例都没有执行应用断言。另有已观察到的后备路径限制：Browser 扩展没有 originating context；云 CUA 打开 `http://127.0.0.1:1420` 返回 `ERR_CONNECTION_REFUSED`。正常 `npm run dev` 虽然打印 ready，另一 exec 中的 curl 仍无法连接；root 已停止该自有 Vite 进程。

[后备路径记录](CUA_FALLBACK.json) 区分了保存的启动日志与本会话 root 观察记录。手工 fixture HTML 只是尝试，没有作为通过证据，也没有打包进本归档。

## 归档与完整性

[完整公开日志归档](companion-test-evidence.tar.gz) 仅包含审查过的测试日志与 JSON；[payload SHA 清单](PAYLOAD_SHA256.json) 逐文件列出字节数和 SHA-256。它保留开发失败、未修复基线、最终门禁与界面启动阻断。没有数据库、环境变量转储、密钥、node_modules、模型数据或手工 fixture。

压缩包采用按路径排序的 tar 条目，固定 uid/gid/mode/mtime 与 gzip mtime=0，重复生成的字节一致；并逐文件解包核对。公开文本只替换运行环境路径前缀，[转换清单](PUBLICATION_TRANSFORMS.json) 同时保留原始与公开字节的哈希。原始 run JSON 中的日志 SHA 指向原文件，公开 payload SHA 以清单为准。

本目录的权威汇总是 [SUMMARY.json](SUMMARY.json)。归档内早期 TEST_RESULTS JSON 按原样保留为历史记录，不能覆盖上述最终状态。
