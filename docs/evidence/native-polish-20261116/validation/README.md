# 本轮 Core、Suite 与 Desktop 验证日志归档

本目录首批归档 2026-11-16 的 **66 份**已完成材料：Core/Suite 5 次回归、此前 Desktop 清单中的 57 份日志/失败/运行身份、Linux 原生启动错误和环境报告，以及 2 份原 Desktop 日志/源码清单。最终源码另追加 **14 份**回归、构建及 schema 诊断材料，见下节。原始文件保留在验证目录；没有收录数据库、token 文件、模型、基准 gold、音频或用户 Mac 原始资料。

## 最终 b25/b30 集成与重新打包

[FINAL_LOG_MANIFEST.json](FINAL_LOG_MANIFEST.json) 单独记录最终冻结源码上的运行，原 66 份清单保持原样：

| 运行 | 总数 | PASS | SKIP | FAIL | ERROR | 时间 |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| Core final-r3 | 1563 | 1473 | 90 | 0 | 0 | 156.109 秒 |
| Suite final-r4 | 115 | 114 | 1 | 0 | 0 | 25.044 秒 |

这两次均未出现 ResourceWarning。新增 Core 测试包含实际旧源码生成的 SQLite、预算默认值变化、UNKNOWN 不重放及已声明路径迁移组合。两个 schema 检查保留旧版相对路径提示缺失的预期失败和修复后的结果。

最终 DEB 已重新构建，40 个 wheel、独立资源、模块导入及 Node 自检通过；对应 [整包报告](../package/RESULTS.json)。该包包括 Core b25、Suite b30、Companion b6，不能与下文首个 rc9 候选混用。构建不等于系统安装或原生 WebKit 验收。

## 完整回归结果

| 运行 | 总数 | PASS | SKIP | FAIL | ERROR | 时间 |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| Core full-r1 | 1552 | 1462 | 90 | 0 | 0 | 157.656 秒 |
| **Core final-r2** | **1556** | **1466** | **90** | **0** | **0** | **159.639 秒** |
| Suite full-r1 | 115 | 112 | 1 | 0 | 2 | 29.954 秒 |
| Suite full-r2 | 115 | 114 | 1 | 0 | 0 | 24.370 秒 |
| **Suite final-r3** | **115** | **114** | **1** | **0** | **0** | **29.862 秒** |

Suite 首次两个 ERROR 均发生在旧 Channels 恢复后的真实 Python import 探针，完整 traceback 保留。后续通过不覆盖第一次结果。上述是重复/逐步完成的运行，不能相加为互不重复的测试数量。Core 的 90 项跳过按原测试理由保存在 [RUN_SUMMARY.json](RUN_SUMMARY.json)，包括缺失的历史实现/fixtures、可选 SDK、固定 Harbor/旧版本环境、opt-in 真实模型以及 macOS Shell/Seatbelt；Suite 的 1 项需要 macOS 系统路径别名。

## Desktop 结果与失败历史

最终自动化结果为 **Vitest 74 PASS、TypeScript/Vite PASS、Rust 默认 50 PASS/3 ignored、Rust→真实 Core HTTP 1 PASS、Chromium Playwright 47/47 PASS**。真实 Core HTTP 的模型是脚本夹具；Playwright 使用合成 IPC，不能替代原生 WebKit、真实模型或完整安装验收。Rust 默认测试编译使用空后端资源目录。

首次缺少生成图标的 Rust 编译失败、浏览器连接失败、桥接等待问题、Vite 端口指向错误、Linux 表单旧测试值不满足当前约束，以及 r4 的容器定位器失败全部保留。浏览器各次原始统计见 RUN_SUMMARY；其中基线 r3 的 1 PASS 存在服务指向错误，不是 rc.8 缺陷已通过。确认 rc.8 运行身份后的基线 r4 为 0 PASS/1 FAIL，最终 rc.9 r5 为 47 PASS/0 FAIL。解释依据见 [Desktop 恢复记录](../../../../desktop/docs/evidence/polish-20261116/RECOVERY.md)。

已逐一核对原 [RECOVERY_LOG_SHA256.json](../../../../desktop/docs/evidence/polish-20261116/RECOVERY_LOG_SHA256.json) 列出的 **57 份日志，原始字节全部匹配**。对原源码清单的 **15 个 Desktop 生产/测试文件**与 final 集成树重新计算哈希，也全部匹配；结果见 [DESKTOP_SOURCE_CHECK.json](DESKTOP_SOURCE_CHECK.json)。这项核对不涵盖后端资源、wheel 或最终安装包。

## 原生启动与整包边界

`native-r1.log` 保留真实 Linux 图形环境下启动失败：系统路径 `/usr/lib/x86_64-linux-gnu/webkit2gtk-4.1/WebKitNetworkProcess` 不存在。环境为 X11，Wayland 不可用，Pulse 服务/socket 不可用，systemd user offline。原生 WebKit A/B profile 哨兵仍 **NOT_RUN**。

`build-linux-test-r1.log` 属于较早 RC.9 候选，包含旧 Companion b5；不能把它当成最终 Companion b6 整包。**本归档捕获时最终 RC.9 整包尚未构建，不在这里标记通过。**之后的构建、资源哈希和安装结果必须由新的独立运行证明。

真实 GTK/AT-SPI 独立窗口读取已另行完成，详见 [Linux AT-SPI 修复与最终回归](../linux-atspi/RESULTS.md)。它与失败的完整 WebKit GUI 启动是不同链路。

## 公开导出与完整性

[LOG_MANIFEST.json](LOG_MANIFEST.json) 逐文件记录原始路径、原始 SHA-256、公开文本 SHA-256、gzip SHA-256 和字节数。公开转换只有：去除 ANSI 控制序列、把 workspace 根前缀替换为 `<WORKSPACE>`、以固定 mtime=0 压缩。没有删除失败、改写状态或替换响应内容。原始 Desktop 清单一并封存；其中原始哈希应与 manifest 的 `original_sha256` 比较，不能与经过路径替换的公开文本哈希混用。

归档严格按文件允许列表选择，没有扫描或复制运行数据库、凭据目录、模型目录、题目答案集或用户 Mac 文件。凭据样式检查也没有发现 API key、Authorization/Bearer 值或用户 Mac 路径。
