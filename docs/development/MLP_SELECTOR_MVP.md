# 可选 MLP 本地模型排序原型

基于官方 `main` `df04ca709b699b170a29c2aaa337aeebe8a38ef4`。本原型默认关闭，
现有规则仍是默认选择；实验结果尚未经过独立设备或任务质量验证，不能宣称优于规则。
本轮没有在 macOS 实机验证新原型；下述 macOS 测速为已有历史记录。

## 入口与约束

本地 MLX 模型推荐入口为 `recommender.recommend()`，由 `main.py` 调用。
`localpilot_service/routing.py` 选择已配置的服务路由，`agent/routing.py` 控制运行时
本地／云端切换；它们不是此处的模型目录排序器，本轮未修改。

原有 Apple Silicon 平台范围、目录、估算内存预算、输出预留、最低上下文
`minimum_context_k` 和 `excluded_size_classes` 在排序前照常生效。原模型能力评分是
主观排序，并非独立实测能力标签或通用硬性能力门槛；MLP 实验限于 `speed` 和 `balanced`
偏好，不声称保留规则的能力排序。估算内存准入不能保证实际不会 OOM。

仅当调用方明确提供实验模式和模型文件时启用：

```python
from recommender import recommend

result = recommend(
    64, "speed", 128, "balanced", os_name="macOS", arch="arm64",
    chip="Apple M1 Max", selector="mlp",
    mlp_path="benchmarks/data/selector_mlp_prototype.json",
)
```

这是重放历史硬件信息的离线示例，不会检测本机、加载模型或启动推理。默认调用保持旧规则；
文件损坏／缺失、特征不全、超出训练硬件／模型／上下文范围或不支持的偏好均返回旧规则结果，
以 `selector_used`、`selector_fallback` 表明回退。选择文件由宿主明确提供；Python 打包包含
`selector_mlp` 模块，但不自动把实验权重安装为服务默认配置。

## 模型和数据

`selector_mlp.py` 沿用原功能分支的标准库实现，网络为输入 → 8 个 `tanh` 单元 → 单输出，
两层全连接，模型档案 `schema_version=1`。输入为配置内存减 3 GiB 系统预留、目录模型大小、
总参数、活跃参数和上下文 K。配置内存不是系统实时可用内存。特征的均值与标准差、
目标归一化及网络参数均只由训练数据计算；训练目标是历史实测 `log(decode TPS)`。
待评估样本的实测吞吐和延迟不会作为预测输入，避免答案泄漏；现有记录缺少足够的协议身份，
不足以提供可靠的跨条件测速输入特征。权重为 JSON，无 PyTorch 等新增重型依赖。

官方 `benchmarks/mlx_profiles.json` 与旧原型摘要内容一致：33 条有效测速、4 个模型，
全部来自 M1 Max／64GB，每条 1 次；另保留 17 条失败／停止记录。全部缺失缓存、输出预算、
提示协议等字段，13 条缺电源信息；成功样本训练有幸存者偏差。训练 25 条、留出 8 条，
按同设备同上下文分组，不拆开该组记录。由于只有一台设备，这是**同设备内部上下文留出**，
不是独立硬件评估。未来有多设备时脚本按整台设备分组留出；未知设备会安全回退规则。

## 实际离线对照

报告 [selector-mlp-official.json](../evidence/selector-mlp-official.json) 对两种方法使用相同的
可行候选和训练侧准入数据，按各自选择查找留出侧的实际记录。没有任务质量标签，未测指标保留未知。

| 请求 | 规则选择及历史观察 | MLP 选择及历史观察 |
|---|---|---|
| 128K | 35B-A3B：17.09 TPS、首 token 878.879 秒、MLX 峰值 30.409 GiB；估算准入 41.95 GiB | 4B：28.40／28.75 TPS、首 token 572.573／565.484 秒、MLX 峰值 17.273 GiB；估算准入 29.75 GiB |
| 256K | 35B-A3B 降至 192K，估算准入 57.31 GiB；精确留出测速缺失 | 4B 降至 192K，估算准入 29.75 GiB；精确留出测速缺失 |

两个 128K 的 4B 旧记录未合并，因为运行协议身份不完整；任务能力及质量没有可靠标签。
吞吐速度差异不能证明整体效果更好。可行性是估算内存风险而非 OOM 实测。

从仓库根目录复现评估，输出必须是两个**不存在的新文件**：

```text
python -m benchmarks.selector_eval --profiles benchmarks/mlx_profiles.json --output-model selector-new-model.json --output-report selector-new-report.json
```

采集接口沿用 `benchmarks.mlx_context`；新增 `--max-new-tokens` 用于固定输出预算，
必须在具备 MLX 的 Apple Silicon Mac 上由操作者确认模型、磁盘和内存后执行真实采集。
使用新输出文件，保留失败记录及软硬件、缓存、提示和生成参数，不能用合成测试标签冒充实测。
下一步是跨设备、跨任务进行重复采集，冻结训练／评估划分，并与规则比较任务质量、延迟、
吞吐量和 OOM／内存风险；数据不足前保持规则为默认。
