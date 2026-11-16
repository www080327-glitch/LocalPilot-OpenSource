# 人工审阅数据、独立测试集与显式后训练

本轮补充 Linux CPU/CUDA 训练与独立测试集评估。已有 Apple Silicon MLX 入口保留。运行代码的验证不等同于个人助理能力提高；当前没有真实用户数据上的 LoRA 增益结论。

## 数据准备

观察、对话和模型回答不会自动成为训练标签。先在 Companion 的训练样本界面检查问题、最终答案及原始来源，再显式保存。可编辑框、密码、隐藏推理、未经证明的模型叙述不能被当成已验证事实。来源被停用、撤销、遗忘或改变后，未来导出会重新检查，失去依据的样本不会导出。

导出界面新增“保留独立测试集”，也可以使用已有 CLI：

```sh
companion --config /absolute/path/companion.json training-export \
  --seed 17 --validation-fraction 0.2 --test-fraction 0.2
```

训练/验证/测试按关联来源组划分，共享来源、相同内容和传递关联不会跨集合。三集合至少需要三个独立来源/场景组；这只是可分割的最低条件，不能视为足够评估样本量。`test_fraction=0` 保持此前两个集合的行为，但不能做最终独立测试评估。

导出包含 `train.jsonl`、`valid.jsonl`、可选 `test.jsonl` 和 `manifest.json`，记录哈希、来源分组、数量与人工审阅身份。导出的文件包含私人文字，独立于在线记忆；撤销在线来源后，已导出副本需要用户单独处置。

## Linux CPU/CUDA 训练

这是可选离线训练环境，不是桌面包默认依赖。CPU 不需要 MPS；CUDA 路径需要用户自己的匹配 GPU 和驱动，本轮未做 GPU 验收。

在仓库根目录建立独立环境，CPU 安装示例：

```sh
python3 -m venv .venv-training
. .venv-training/bin/activate
python -m pip install --upgrade pip
python -m pip install torch==2.9.1 --index-url https://download.pytorch.org/whl/cpu
python -m pip install './companion[training]'
```

入口锁定 `torch==2.9.1`、`transformers==4.57.3`、`peft==0.18.1`、`safetensors==0.7.0`。本轮实际环境为 Python 3.12、Torch `2.9.1+cpu`。完整环境解析记录与测试日志保存在本轮 evidence 中；这些顶层版本不表示所有未来传递依赖都已验证。

准备一个**已取得并核对来源的、本地未量化 Transformers safetensors 模型**和刚才导出的数据目录。不能把 GGUF、MLX 量化权重或未知自定义 tokenizer 当成可互换的训练输入。训练入口不下载模型，不执行 `auto_map` 自定义代码，不加载在线私人历史。

先生成计划：

```sh
python -m companion.model.portable_training \
  --model /absolute/path/base-model --data /absolute/path/reviewed-export \
  --output /absolute/path/new-lora-plan --method lora --layers 4 \
  --rank 8 --iterations 100 --max-seq-length 2048 --device cpu
```

执行时选择另一个新的目录，并加上 `--execute`：

```sh
python -m companion.model.portable_training \
  --model /absolute/path/base-model --data /absolute/path/reviewed-export \
  --output /absolute/path/new-lora-run --method lora --layers 4 \
  --rank 8 --iterations 100 --max-seq-length 2048 --device cpu --execute
```

`--layers 4` 选择最后四个 Transformer 层；模型不足四层时需填实际层数，`--layers -1` 选择全部。显式全参数训练使用 `--method full --layers -1`，包含 embedding 和输出 head；它与现有 MLX-LM 的“选定 Transformer 层 dense 更新”不是同一范围。全参数 float32+AdamW 的内存开销明显高于推理，入口不承诺大模型能放进当前设备。

训练使用本地文件、离线环境、仅最终答案的 loss mask、固定随机种子和单进程数据加载。超过上下文的样本明确失败，不默默截断。`train` 用于更新，`valid` 记录前后 loss，`test` 不参与训练或调参。LoRA 产物为 PEFT adapter；full 产物为 Transformers 完整候选。计划、日志、基座/候选哈希和指标均保存在新目录，基座权重不覆盖，产品模型不自动切换。

不可用 CUDA 会明确失败，不暗转 CPU。训练中断/失败保留原日志和状态。训练成功只能标记为 `COMPLETED / quality=NOT_EVALUATED`，不能由 validation loss 下降直接推定用户任务能力提高。

## Apple Silicon

已有入口 `python -m companion.model.finetune` 继续使用固定 `mlx-lm[train]==0.31.3`。其 `full` 范围按既有报告如实标注为选定 Transformer 层，不含 embedding/head。Linux PEFT adapter 不能直接填进 MLX adapter 字段。两个入口共用同一个审阅数据读取/摘要校验实现，但模型格式、训练依赖与加载器分别处理。

## 独立测试评估

先由用户显式启动候选模型的本地兼容服务；服务应正确加载目标 base/adapter，并保留实际权重、模板和启动命令记录。评估入口只允许数字环回 HTTP，不自动启动或替换服务器，也不识别其实际权重。因此报告保留 `weights_identity=NOT_VERIFIED`，须附外部身份材料。

使用**相同冻结导出、相同问题、上下文、输出预算、温度、超时**分别测原模型与候选。评估请求只含 system/user，参考答案不发送给被测服务：

```sh
python -m companion.model.evaluation run \
  --data /absolute/path/reviewed-export --endpoint http://127.0.0.1:8080/v1 \
  --model actual-baseline-id --label baseline --max-tokens 256 \
  --output /absolute/path/new-baseline-evaluation

python -m companion.model.evaluation run \
  --data /absolute/path/reviewed-export --endpoint http://127.0.0.1:8081/v1 \
  --model actual-candidate-id --label candidate --max-tokens 256 \
  --output /absolute/path/new-candidate-evaluation

python -m companion.model.evaluation compare \
  --baseline /absolute/path/new-baseline-evaluation/evaluation.json \
  --candidate /absolute/path/new-candidate-evaluation/evaluation.json
```

评估记录每项答案、精确匹配、延迟、提供方 usage 或 UNKNOWN，以及全部错误。没有自动重试、挑选最好结果或自动晋级。比较拒绝不一致的数据摘要、条件和题目；当前指标是严格答案匹配，**不是语义评审、统计非劣证明或公开排行榜**。开放问答中正确的不同表述也可能不精确匹配，应结合预先定义的人工盲审标准看原始回答。

## 已实际验证

- 审阅数据/独立测试流程：24 项，包含真实本地 HTTP 请求，确认参考答案不外发、失败保留及比较条件约束。模型响应在这一组是明确的协议夹具。
- 固定 Torch/PEFT 环境：5 项真实 CPU 测试。随机初始化微型 Qwen 模型的全层 LoRA、最后一层 LoRA、adapter 重载、full 的 embedding/head 更新、答案 mask、上下文拒绝和不可用 CUDA 均被实际执行。
- 独立复查发现 PEFT 不允许 `target_modules='all-linear'` 与正数 `layers_to_transform` 同用；已经使用实际模型的线性模块后缀修复，并通过最后一层的真实梯度/参数归属测试。初次错误记录保留。

没有真实个人训练数据的效果报告，没有 CUDA、Intel Mac 或新版 MLX 训练结果，也没有强化学习实现。当前流程不进行模型自我改进。

接口依据：[PyTorch 2.9.1 官方安装](https://pytorch.org/get-started/previous-versions/)、[PEFT 0.18 文档](https://huggingface.co/docs/peft/v0.18.0/en/quicktour)、[固定 PEFT 0.18.1](https://pypi.org/project/peft/0.18.1/)。实际训练实现已用锁定安装版本运行，不能只凭文档存在判通过。
