# ITBench 参考数据入口适配：评分开始前的修复

**输入适配已验证；本目录没有评分结果。** combined 的 40 个候选已全部形成终态后，评分在读取固定参考文件的结构时失败。随后仅修复参考数据入口，没有重跑候选、改写旧回执或改变评分规则。

## 原始失败与盲测边界

[旧评分日志](grading-before.log) 记录 `ValueError: Reference JSONL/YAML does not match the expected 40-case schema`；[退出回执](grading-before-exit.json) 为 returncode 2。[旧 job](grading-before-job.json) 指向 frozen 91dd87c 的 grader。公开 job 仅将私有 key 文件路径替换为占位符，没有读取密钥文件。

combined 原汇总为 **40 planned、30 completed、32 格式有效、3 个外层错误、graded=false**。候选驱动的 returncode 1 来自“格式有效数不足 40”的既定退出规则，汇总本身已写入；case 029 已 completed。这里不把格式有效数当作准确率。

真实 `grade_run` 先执行 `completed_run`，再加载/解析参考数据，随后才创建 grading 目录、构造 judge 后台并逐题请求。因此原 schema 异常发生在 judge 初始化之前。两次 native 结构探针也先核对 40 份终态、输出目录范围内无候选 Core，再读取参考文件；它们只在内存中解析，没有调用 judge、持久化参考原文、读取候选答案文件或生成 judge 请求/输出回执。归档时 combined 仍没有 grading 目录。

## 固定输入的实际结构

参考文件 SHA-256 固定为 `6073f64edc4e011fbf4d4677ca04f5b4ff84d2041d1786c0f54b3e3e7392a745`，185,557 字节，40 行 public SRE 数据，场景集合与冻结的 40 题一致。

[第一探针结果](itbench-reference-schema-probe.json) 仅保存类型统计：278 个实体中，root_cause 有 40 个显式布尔值、238 个未提供；namespace 有 275 个字符串、2 个未提供、1 个 null；另有一个重复 ID。旧 ground_truth 对 39 个场景报结构错误，完整 parse_labels 失败。

[第二探针结果](itbench-reference-adapter-probe.json) 仅保存字段相等布尔与数量：唯一重复项在 id/name/namespace/kind/filter 上原始及规范化后的比较均相等，默认后的 root 标志也相等；**冲突重复为 0**。没有输出实体 ID、实体名称、根因或参考正文。旧 parser 仍报 ValueError；新 parser **通过全部 40 场景**，合并后为 277 个身份记录，供 judge 识别的身份字段仍没有 root 标志。

## 最小改动与验证

[精确 diff](grader-input-adapter.patch) 只修改主仓的 `scripts/grade_itbench_aa.py` 和已有 `tests/test_itbench_scoring.py`：

- 仅对未提供的 root_cause 使用 false；显式非法类型仍拒绝。
- 可选 namespace 为 null 时视为未提供；name/kind 等字段仍保持原类型要求。
- 只有允许的身份字段及默认后的 root 标志完全相同，才合并重复 ID；身份或 root 标志冲突仍报错。

[修复前四个新增用例](itbench-reference-schema-before.log) 为 **3 ERROR、1 PASS**，对应前三种结构被旧入口拒绝，冲突重复负例保持拒绝。[修复后完整 scoring 模块](itbench-reference-schema-after.log) 为 **22 项全部通过，2.145 秒**；测试调用真实解析、计分与文件恢复实现，并包含本地 TLS 运输用例；模型回复均为合成 fixture，没有付费模型调用。

[SOURCE_IDENTITY.json](SOURCE_IDENTITY.json) 记录新旧源码、测试和 diff 哈希。按源码顶层节点逐段比较，只有 `ground_truth` 变化；**normalization prompt、parse_normalization、score_entities、summarize 的 40 题分母、模型、预算、停止检查及恢复规则均未变**。新 grader SHA-256 为 `4cd3f405f7a4d1c05edb6bf5d5530657c69de6b934bf59c2cdf01df7e2f20b76`，旧版为 `26ca645748a5272409bbc74f92e366a7d2b95138a86e92fec2d94db86733f8f0`。

## 证据与恢复范围

两个探针源码分别为 [结构探针](inspect_itbench_reference_schema.py) 和 [重复项及新旧解析器探针](inspect_itbench_reference_duplicates.py)。[ARTIFACT_MANIFEST.json](ARTIFACT_MANIFEST.json) 保存每份原件和归档的大小与 SHA-256，明确 job 的单字段路径替换；不包含 raw labels、候选答案或密钥。

本修复发生在所有候选结束后、任何真实 judge 调用开始前；它是独立入口修复，不计入主审计 40 项，也不构成准确率或 AA 成绩。恢复须指向新提交并冻结的 grader，继续使用既有 combined 候选目录，保留旧失败日志并使用新的日志/退出记录名称。当前仅准备了待绑定冻结路径与提交的 job，尚未启动评分；不能直接重用仍指向旧 91dd87c grader 的 job。
