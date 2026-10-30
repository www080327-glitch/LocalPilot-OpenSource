# Attachment API v2

所有操作使用已认证的 `POST /localpilot/v2/attachments`，返回 `version: "2.0"`。v1 导入接口不改变；v1 工作区副本不获得 v2 撤销机制。OpenAPI 入口在 `localpilot_service/openapi.json`。

## 会话授权

请求共同字段：`operation`、`session_id`；操作者代客户端操作时提供 `client_subject`，必须位于其 `approval_for`。所有读取都核对会话所有者。`import/revoke/gc/vision_approve/vision_infer` 要求独立 host operator + control scope。普通客户端不能通过文档文字或路径参数授予自己权限。

| operation | 附加字段 | 行为 |
|---|---|---|
| import | paths；可选 origin、origins、ttl_seconds | 本地导入文件/文件夹并记录 queued；必须为空闲、本地且 LOCAL_ONLY 的会话 |
| list | 可选 cursor、limit | 当前有效授权元数据，默认每页 100；返回 count/next_cursor/has_more；不返回绝对来源路径 |
| status | attachment_id | 实际格式、状态、检查点、错误和测量值 |
| process / reindex | attachment_id | 有预算的同步本地解析；busy 返回 429；reindex 重建可验证索引 |
| cancel | attachment_id | 请求中断；已提交片段保留 |
| read | attachment_id；可选 cursor、limit | 按结构节点翻页；返回 next_cursor/has_more、锚点和 citation |
| search | query；可选 ids、limit、mode | 仅搜索当前有效授权；mode 为 fts 或 hybrid |
| verify | citation、quote | 精确引文、节点和原件哈希验证 |
| revoke | attachment_id | 立即禁止新读取、检索、验证、解析和图像出站；幂等 |
| gc | 无 | 显式回收无有效授权的原件/索引、孤立任务输出 |
| vision_plan | model、attachment_ids、question | 验证实际能力开关、准备派生图像并返回精确披露摘要；不发送 |
| vision_approve | request_sha256 | 120 秒、一次性精确文件出站批准 |
| vision_infer | 与计划完全一致的 model、attachment_ids、question | 再次授权检查后发送；返回派生信息、回答及实际可获得的 usage |

同步 process 可能超过 SDK 默认 30 秒；调用者应选择高于宿主解析预算的 HTTP timeout，并通过另一请求 cancel。服务每实例只允许一个解析进程，应用可在独立工作线程发起调用。

状态 `queued/processing/complete/partial/failed/unsupported` 与授权 `active/revoked/expired` 独立。`complete` 表示受支持的提取流程结束，不表示所有版式、图片或公式都已理解；应检查 unparsed/limitations 和覆盖范围。

## 示例

```json
{"operation":"import","session_id":"sess_...","client_subject":"local","paths":["/absolute/operator-selected/report.pdf"],"origin":"native_selection"}
```

```json
{"operation":"read","session_id":"sess_...","attachment_id":"att_...","cursor":0,"limit":8}
```

```json
{"operation":"verify","session_id":"sess_...","citation":"lpdoc:att_<32hex>:3:<64hex>","quote":"actual exact excerpt"}
```

绝对路径只用于 host-local 操作者选择，不发送 Provider。原生 WebView 的通用 product_control 禁止路径式 import；必须通过原生选择产生的 ID 调用 import_attachments。Suite CLI 的 `product-control` 增加 `documents` operation，继续使用既有操作者凭据路径。

## Agent 扩展

首个 v2 导入后才在相同 Registry 注册 `document_list/read/process/search/verify/image`。所有文档工具仍走 Gateway；列表和节点按输出预算翻页，模型不能以参数改变授权主体、工作区、缓存根目录或出站批准。复用原 TaskService，不创建第二套 Agent Runtime。

客户端应先 list，再 process/read；跨文档 search 前应确保所需文件已解析。partial 文件必须检查原因并显式 process 恢复。引用应使用实际返回的 citation，验证引文后以 `[文件与位置](lpdoc:...)` 表示。GUI 点击引用会重新读取并核对节点；伪造、撤销和跨会话引用不会被当作已读证据。
