# 安装、启动、模型与回滚

当前 Beta 2 安装与回滚说明以 [发行说明](../delivery/v5-completion-20261023/INSTALL.md) 为准。下文保留早期 alpha 安装记录；其版本和限制不能替代当前 Beta 2 验收。

本地候选仅供 macOS arm64，最低 macOS 15。APP 为 ad-hoc 签名，未公证、未发布。稳定版本和原配置保持独立。

1. 打开 DMG，把 LocalPilot.app 拖至用户选择的目录。候选使用独立 bundle ID，不覆盖原版用户数据。
2. 首次向导点“安装内置模块并启动本机服务”。APP 已包含 Python 与独立 Core、Companion、Suite wheels，无需先配置 Python。模块复制到候选专属 Application Support 下；配置与任务库和模型目录分离。
3. 本机已有 oMLX 时读取它的实际端口及私有认证引用。若没有 oMLX，先从 https://github.com/jundot/omlx/releases 安装正式 APP，打开并完成其配置，再重试。本候选没有伪装成已实现全新 Mac 的 oMLX 自动安装。
4. 模型库显示实际发现与加载状态。下载和加载需由用户在 oMLX 管理入口单独确认。低电量下禁止未经批准的大模型；本候选 Core 直接阻止尺寸大于 1.5 GB 或未知的 oMLX 推理，不自动加载任何模型。
5. 导入已有模型：在 oMLX 模型管理中将模型目录指向已有 MLX 权重所在目录/其父目录，按 oMLX 正式功能重新扫描；回到 LocalPilot 模型库刷新。保持模型原有 config、tokenizer 和 safetensors 文件，不改动量化或复制现有权重。初始化注册表是快照；新增模型需要新的独立 Suite 初始化目录或由可信 Host 添加路由，然后开启新 Session。
6. DeepSeek：连接设置选择现有的 600 私有原始密钥文件。只保存文件引用。若任务要向云端发送文件正文，另行填写精确工作区相对路径并点击授权；只为新路由生效。云端调用仍有本次请求审批。
7. 标准 Agent 须确认“需要帮助”；工具写入及 Cloud Egress 在 GUI 展示绑定票据，再明确确认。UNKNOWN 只允许查询/取消，不重放。

## 独立 CLI

候选 Application Support/modules/5.0.0a2/localpilot 为便携 Suite 入口。使用 --home 指定候选 product-v5 目录后执行 init、doctor、start、status、chat、agent、stop。Companion 通过同一入口的 companion start/status/stop 独立控制。GUI 退出只关闭界面；服务生命周期独立，可在设置中停止。

## 独立安装包与升级

交付目录 wheels/ 分别提供 Core 5.0.0a2、Companion 0.5.6a1、Suite 0.2.0a1。通过现有 suite upgrade MODULE --wheel FILE --previous-wheel PREVIOUS --execute 升级；先处理所有任务/审批并停止对应模块。普通启动和提交前检查 API 1.0 兼容性。不要直接把新 Engine/Provider 替换进旧 checkpoint。

## 回滚

保留原 Core RC2、Companion RC2、Suite RC2 制品和 GUI 稳定安装。停止给候选新 Session 派工作，处理收据/UNKNOWN/审批，再停止候选 Core 与 Companion。打开原 APP、指回原有配置/数据库即可。已完成候选数据保留在独立目录；不将其导入旧 Runtime，不修改稳定 tag。若回滚模块 wheel，使用记录的 previous-wheel，并重新 doctor。

27B 取消预载的原配置备份路径见 evidence/prevent-27b-auto-preload.json；只有用户明确允许大模型运行后，才在 oMLX 正式管理界面重新固定/加载。不要为回滚应用而自动恢复模型预载。
