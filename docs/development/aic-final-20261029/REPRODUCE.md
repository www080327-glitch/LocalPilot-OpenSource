# 评审复现入口

作品名 localpilot；大肥鱼队。自有代码 MIT，比赛期间仅受限评审，不公开发布。源码包内的 AIC_SOURCE_MANIFEST.json 固定 Git 提交及每个文件的 SHA-256；实验记录包的 REDACTION_MANIFEST.json 连接私有原件与评审副本。主目录路径和凭据值的遮蔽不改变任务、用量、判分或费用。自训选择器MLP的JSON参数随代码提供；大模型权重、密钥、用户数据库和日常配置不随包分发。

## 先区分证据范围

RESULTS.json 与 STATUS.json 为指定队列快照。旧四例是修复前诊断，含原生 DSH 云端模型目录宣告1M而非预定64K的配置偏差。工具契约修复后冻结的协议为 bfcl-protocol-qualified.json，开发集37/38，独立评估25/12/16，七组每组均使用相同实例；不合并为n=7。完整多轮实例是统计单位。小样本不能证明统计非劣效，也不能外推稳定节费。

## 构建与控制测试

受限源码解包后，使用独立 Python 环境，不向日常 APP 安装。Core 要求Python>=3.10，Suite/Companion要求>=3.11；本轮候选测试环境为Python3.14，固定模型服务另用Python3.12。构建工具由隔离构建环境按pyproject.toml提供。

```sh
python -m pip wheel --no-deps --wheel-dir candidate-wheels . ./suite ./companion
python scripts/build_channels_wheel.py --out candidate-wheels
```

候选wheel另附源码逐文件校验记录。Core、Suite和Companion均在解包后的源码树重新构建；构建成功不等于消费者APP、签名、公证、干净Mac、Intel或跨平台资格。

控制测试入口和细分结果以原始回归日志为准。严格完成与终止后不再继续花费的独立控制可运行：

```sh
python -m unittest tests.test_aic_score_audit tests.test_aic_terminal_budget
```

1395项Core控制、84项Suite和565项Companion回归不是模型能力成功率。真实云端E2E只证明报告中明确列出的合成文件读取、字段验证、幂等、重启查询和目录越界拒绝；MP4为实时SDK事件视图。

## 公开基准与运行前提

BFCL V4源码和评分器取自 https://github.com/ShishirPatil/gorilla ，固定提交6ea57973c7a6097fd7c5915698c54c17c5b1b6c8。驱动只提供已审查的GorillaFileSystem内存模拟器，标记adapted benchmark，不是官方榜单总分。Terminal-Bench 2.0与SWE-bench Verified在本机缺少容器运行环境，未运行。

本轮研究驱动的默认路径、Mac原生DSH、安全配置及已下载模型服务运行时与实验机器绑定。复现者需显式配置自己的隔离运行时和凭据；修改驱动后必须生成新的冻结协议，不能沿用原哈希。不得把自己的日常模型服务或账号自动纳入测试。

固定原生DSH为0.2.1-rc.2，二进制及app.asar哈希见协议，源码标签提交687f282e8625c6b8d11ff58211a90524be2e4317；不声称已从源码重建相同二进制。本地模型为mlx-community/Qwen3.6-35B-A3B-4bit，固定权重revision 38740b847e4cb78f352aba30aa41c76e08e6eb46。原生DSH本地组与LocalPilot读取同一服务和权重。

每实例最多32次provider请求、64次工作工具、每次1024输出Token、180秒墙钟。云端thinking关闭，temperature/top_p/seed均不发送，两种Harness使用provider默认值；本地temperature=0、seed=25、enable_thinking=False。最终本地实验要求接电且省电关闭，09:30前禁止加载本地大模型；本轮服务采用独立端口/状态目录，不接触日常服务。所有失败、重试、复核和升级调用计入账本。

## 汇总和材料

```sh
python scripts/aic_summarize.py --run bfcl-evaluation-adapted2 --protocol bfcl-protocol-qualified.json --output output/aic-20261029/summary.json
python scripts/aic_report.py --summary output/aic-20261029/summary.json --output output/aic-20261029/materials
```

报告制作依赖ReportLab/Matplotlib及中文字体，PPT制作使用独立Artifact Tool环境；它们不属于推理或评分器。所有图表来自摘要，旧结果和失败原件保留。云端成本按共同峰值费率归一化，实际扣款账单UNKNOWN；时段折扣、免费额度及未测电费均不算架构节省。

本地64K缓存包含48个真实响应与输出检查，OFF/ON固定先后顺序，非ABBA资格；完整重复分布、Prefill阶段指标、实际缓存Token、资源和无收益项均在记录中。内部KV数值等价与永久保留未证明。MLP只获得有限速度场景接入，全面任务质量替换仍为NO_GO。
