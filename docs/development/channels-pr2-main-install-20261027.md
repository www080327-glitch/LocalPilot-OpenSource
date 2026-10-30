# 渠道合并与本机安装（2026-10-27）

维护者在已知 Intel、真实平台和完整 GUI 未测试的边界下，明确指示合入 main 并安装到本机。
这项决定不把 NOT_RUN 改成实测通过，不创建正式 Release，不替换日常 LocalPilot.app。

候选源码为 a07177d91a4b9df270b52735ac3cd36a407491d3，包含原 PR #2 作者提交。
合并前重新核对 main 为 df04ca709b699b170a29c2aaa337aeebe8a38ef4，PR #2 为
1d7303d94dc9743d6d1ec97abad07160850a1adf，无新增产品代码差异或冲突。
集成分支通过普通 merge 合入，禁止 force push、覆盖其它 Work 或提交私密数据。

## 本机安装入口

独立安装位置：`/Users/localpilot-user/Desktop/aic竞赛/LocalPilot-Channels`。
`bin/localpilot` 固定使用该目录内 Python 3.14 Suite 和独立 data；与日常 APP 的运行时和数据分开。
Suite 主机安装 Core 5.0.0b20+channels.1、Suite 0.2.0b21+channels.1 和 Companion 0.5.7b2 的 wheel。
安装这些代码不启动 Core/Companion，不加载模型。渠道 facade 由 Suite 另建 venv 安装，调用外部既有 Core。
Node 24.20.0 已存在；桥接资源内置，无 npm 安装。

```sh
LP='/Users/localpilot-user/Desktop/aic竞赛/LocalPilot-Channels/bin/localpilot'
"$LP" --version
"$LP" channels list
"$LP" channels status
"$LP" channels --help
```

也可双击 `LocalPilot-Channels.command` 查看状态和命令帮助。
安装后所有渠道保持停止、尚未配置。没有扫码、登录、发送消息或迁移旧桥接。
`message-channels.example.json` 只有占位身份与环境变量名，不含 Token。

配置时必须使用现有 Core 中已授权的普通发送者身份及微信独立 Operator；QQ 普通身份没有审批资格。
命令需要显式提供该 Core 的私有配置，Suite 只核对，不写入或提升权限。
替换模板中的占位值，将配置存为 0600 的文件，在本机私下设置引用的环境变量。
使用全新状态目录；不得将现有 QQ/微信登录状态复制进来。

```sh
"$LP" channels configure --config /private/path/message-channels.json --core-config /private/path/service.json --state-dir /private/path/new-channel-state --port 8003
"$LP" channels doctor
"$LP" channels start adapter
"$LP" channels login wechat
"$LP" channels start wechat
"$LP" channels start qq
"$LP" channels status
"$LP" channels stop qq
"$LP" channels stop wechat
"$LP" channels stop adapter
"$LP" channels uninstall --execute
```

登录或启动仅在确认发送者、身份和新状态后执行。凭据不应贴入聊天、README 或 shell 命令参数。
卸载只删除可选组件代码，保留配置/凭据/数据库；Suite 主机和日常 APP 不受影响。

## 保留的验收边界

原生 Intel、真实 QQ/微信连接、完整 GUI/APP 升级、物理断电及长时间运行仍 NOT_RUN。
线上独立 Verification 仍 NOT_RUN；本轮文件结果证明来自测试侧的独立断言。
详细审查、历史失败和 UNKNOWN 见 [arm64 验收](channels-pr2-acceptance-20261027.md)。

## 合并前重跑与本机检查

直接从远端 a07177d 候选 worktree 重新构建所有三个渠道相关 wheel，并使用固定官方 b20 wheel 做对照。
两套全新环境各 123 Python / 77 Node，零失败、错误、跳过；所有构建、安装、隔离导入和无 Node list 阶段 PASS。
结果保存在仓库外 arm64-main-premerge；[脱敏摘要](../evidence/channels-pr2-arm64-20261027/premerge-install-summary.json) 绑定源码与 wheel 摘要。

本机持久安装使用本次重建 wheel，并另构建未改动的 Companion 0.5.7b2 wheel。
`pip check` 无缺失依赖；在 `/tmp` 通过固定 launcher 验证版本、list、status、help。
状态为 installed / configured=false；adapter、qq、wechat 全部 stopped，无最近错误。
安装根、data、组件根及 facade venv 均为当前属主 0700；安装记录/配置模板为 0600。
Suite 主机的 Core/Companion 包只安装代码，没有启动服务或模型。没有注册自启动项。
