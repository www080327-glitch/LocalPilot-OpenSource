# Runtime、安装态与 Suite 续验 — 2026-11-17

本目录记录 Core **5.0.0b32**、Companion **0.5.7b9**、Suite **0.2.0b32**、Channels **0.1.0a4** 的开发回归、全新 wheel 安装态及 Suite 完整回归。它不替代原生 GUI 或系统安装验收。

## 结果

| 门禁 | 结果 | 范围 |
|---|---|---|
| 修复前容量复现 | 原问题确认 | 已关闭会话和已结束任务达到上限后，重启前后均拒绝新任务；四条原始输出保留 |
| Service 定向回归 | 96 PASS，0 SKIP；5.069 秒 | 真实 SQLite、HTTP、回执、原请求重试、归属、批准及 UNKNOWN、存储失败恢复、模型切换等 |
| Document 归档补充回归 | 11 PASS，0 SKIP；0.876 秒 | 关闭未归档与已归档会话 import 均返回 409；旧附件仍能读取及撤销 |
| 四 wheel 全新安装 | PASS | 独立 venv；隔离导入、CLI 版本、pip check 一致；286 个 `.py` / `.swift` 文件与源码及安装副本逐字节相等 |
| 安装态渠道生命周期 | 12 PASS，0 SKIP；5.711 秒 | 真实 HTTP、SQLite、子进程退出、重启、卸载保留状态；模型与平台身份为测试夹具 |
| Suite 完整回归 | 123 项：122 PASS + 1 SKIP；52.728 秒 | 直接导入本次 Core b32 / schema 2 源码；唯一跳过为 macOS fixed system alias |

这些集合有重叠，不能相加作为独立测试总数。Service 定向运行仅记录结束后的源码哈希；最后冻结代码的整体覆盖以[独立 Core 门禁](../core/final-run.json)为准。安装态与 Suite 两次运行均核对 **670 个输入文件**前后 SHA-256 完全相同。

Suite 日志保留两条 `ResourceWarning`：配置失败回滚用例中的 Popen 对象析构时，对应服务进程仍运行。该用例及整套断言通过；随后扫描本次候选 venv，剩余进程为 0。不能将此记录改述为全程没有警告。

## 会话归档与迁移

现在仅在容量不足时归档终态且 quiescent 的任务和已关闭会话。历史回执、SSE、owner、路由、原请求指纹与幂等键保留在 SQLite，并可按 ID 检索。相同请求重试返回原任务；批准、UNKNOWN 等未终结记录不会被清理。仍 open 的会话不会被自动关闭。

数据库采用 schema 2。打开 schema 1 时，先使用 SQLite backup 创建唯一命名、权限 0600、验证通过的备份，再事务升级。真实旧 b31 reader 已验证拒绝打开 schema 2，拒绝前后数据库字节未变。降级旧程序须恢复升级前数据库备份；这里没有用旧 RC14 系统安装结果替代新 schema 的降级验收。

独立审查曾观察到 Document v2 向归档会话导入时因 `runtime=None` 断开 HTTP 连接。修复前没有保存原始探针与完整回溯，归档内将其明确记为审查观察；修复后的 11 项真实日志与最终 Core 回归承担验证证据，没有重构伪造“原始错误日志”。

## 全新 wheel

| 文件 | 字节数 | SHA-256 |
|---|---:|---|
| `localpilot_agent_service-5.0.0b32-py3-none-any.whl` | 584,363 | `095774e7f464e968e49ed7e45e3406166ce0244fbd79ddd11d57d040c4c826b3` |
| `localpilot_channels-0.1.0a4-py3-none-any.whl` | 45,932 | `154c473fd909aca5926543b4787506ca6adc5d0210c7bc248db1d9561ab202e6` |
| `localpilot_companion-0.5.7b9-py3-none-any.whl` | 356,058 | `753c5fcc3a5c252866d72c108e28f94cad2232401916907124e9d3db44767b91` |
| `localpilot_suite-0.2.0b32-py3-none-any.whl` | 108,572 | `e2851cbfd505251ffdae17e5f4f57525b2ce336210b7322629be521b714193d6` |

构建使用仓库既有 `build --wheel --no-isolation` 和 `scripts/build_channels_wheel.py`，构建工具为 build 1.6.1、setuptools 84.2.1、wheel 0.48.0。依赖沿用 psutil 7.2.2、pypdf 6.21.4、Pillow 12.3.0、defusedxml 0.7.1、watchdog 6.0.0。环境为 Debian 13.6 x86_64、CPython 3.12.14、glibc 2.41。

安装态生命周期于北京时间 12:06:17–12:06:23 执行；Suite 完整回归于北京时间 12:10:07–12:11:00 执行。执行时基线 HEAD 为 `e278f0677c8eed4c0d49b6b08a672e15fe56495d`，本轮候选修改尚未提交，因此 `source_dirty=true` 如实保留；新代码归属依赖逐文件哈希，不将旧 HEAD 冒称为包含本轮修复的提交。

## 证据与边界

[机器摘要](SUMMARY.json)、[原始日志与 JSON 归档](evidence.tar.gz)、[归档内逐文件 SHA-256](PAYLOAD_MANIFEST.json)和[归档校验](ARCHIVE.json)可独立核对。gzip/tar 时间、所有者等元数据已固定，原始 payload 字节未改写，重复构造得到相同压缩字节。

发布文件采用明确白名单，排除数据库、wheel 二进制、venv、环境文件、密钥与测试运行目录。本组没有调用真实模型、登录 QQ/微信、安装系统软件包或操作用户服务；Linux 原生 GUI、macOS Apple Silicon/Intel、签名及发布门禁不属于这些结果。完整 canonical history 与存活会话 journal 仍有增长成本，本次归档不构成“无限历史恒定时间或恒定存储”的证明。
