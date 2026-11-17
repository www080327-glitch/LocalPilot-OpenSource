# GPT-6 Luna：真实续接与归档幂等实测

**PASS，5 次真实 Responses 调用，42.876651 秒。** 只验证合成文件读取、请求前缀、服务重启和旧幂等键查回；不属于 AA 排名、一般任务质量、小时级稳定或动画验收。

使用实际 `OpenAIResponsesBackend`、Core V5 Session、TaskService 与 SQLite。虽然 gateway 设为 Full，测试 capabilities 明确限于只读；这不是完整高权限执行的验收。第一个任务读取两个文件得到两个随机标记；服务停止并重启后，第二个任务只读取第三个文件，同时回忆前两个标记。容量设置 `max_tasks=1` 触发首个任务归档；重试旧任务的同一幂等键返回旧结果，不增加模型调用。

| 观察 | 结果 |
| --- | --- |
| 请求 / 提供方响应 | 5 / 5；提供方实际报告 `gpt-6-luna` |
| 相邻请求输入前缀 | 4 / 4 完整延伸；在公开脱敏前比较实际请求 |
| 工具定义与 reasoning 参数 | 五次保持一致 |
| 外部文件语义断言 | 三个随机标记全部一致；实际 `read_file` 为 2 + 1 次 |
| 产品内建交付验收 | 两份任务收据均为 `task_outcome=unverified`、`verification_status=not_run`、`task_succeeded=false`；不能改写成内建验收成功 |
| 重启与旧幂等键 | 保留原结果；读取/重试不新增模型请求 |
| 提供方 `input_transformations` | 五次实际返回显式空数组；不能等同于内部推理过程的证明 |
| 提供方用量 | 14,098 输入 token；152 输出 token；9,783 缓存输入 token |
| 上下文压缩 | 0 次；本次不测试压缩后的模型质量 |
| 结束状态 | 自有服务正常停止；没有余额查询 |

外部 runner 的 `semantic_pass=true` 只表示本次合成标记匹配，与产品内建验收是不同层。运行收据的未验证状态原样保留，不能用外部断言覆盖或宣称更广的完成质量。

独立只读复核共 17 项一致，记录在归档的 `live-review.json`，状态为 `PASS_WITH_SCOPE_LIMITS`。

## 来源与隐私处理

[run.json](run.json) 的 `source_commit` 是工作树基线 `e278f06`，不是干净的被测提交。实际身份由归档中的 112 个源码 SHA 定义；运行期间全部未变。[后续源码比较](source-continuity.json)只有 `localpilot_service/documents/api.py` 在此实测后修复；这条未在文件读取测试中执行的附件导入路径由后续完整 Core 门禁覆盖，不能追认为实测已经验证。

[响应诊断和用量](responses.json)、[前缀比较](prefix-comparisons.json)、提示词、合成文件、任务收据、运行器和来源哈希完整保留在 [evidence.tar.gz](evidence.tar.gz)，[ARCHIVE.json](ARCHIVE.json)记录逐文件字节数和 SHA。

API 密钥、认证头和私有 runtime SQLite 不在归档中。请求中的不透明 `encrypted_content` 在采集时替换为原值的 SHA-256 与长度，其余公开请求内容保留。空转换数组与缓存 token 是两个独立观察；没有用缓存命中代替推理保留诊断，也没有推导未测量的费用。
