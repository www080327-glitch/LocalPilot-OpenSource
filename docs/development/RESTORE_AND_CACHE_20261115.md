# 精确 Skill 恢复与自有缓存预算

旧库必须保留。`restore_skill_catalog_migration` 是显式、一次性恢复计划，适用于 PR #1 `94e0e6f` 的旧 `load_skill` schema；不是任意配置迁移。服务配置顶层示例（摘要必须由实际旧 checkpoint 和当前已审核 bundle 读取，不能照抄占位值）：

```json
{
  "restore_skill_catalog_migration": {
    "version": 1,
    "sessions": [{
      "session_id": "指定旧 Session ID",
      "configuration_sha256": "旧 checkpoint 的 64 位十六进制 configuration",
      "bundle_sha256": {"public-notes:user": "当前已审核 bundle 的 64 位十六进制摘要"}
    }]
  }
}
```

只反向投影旧工具描述，再校验完整 configuration 摘要。已加载 Skill 的每条成功收据还必须与当前 bundle 的旧格式投影逐字节相符；只去掉旧格式没有的 description/bundle_sha256，正文、版本、输入输出和依赖均参与比较。旧 schema 未绑定未加载 Skill 的内容，因此计划中的当前摘要是宿主对目标 bundle 的明确审核，不能宣称恢复了未知的旧正文。

恢复沿用原消息、工具收据、历史任务模型、幂等键和 UNKNOWN。只追加新 checkpoint/journal revision，不改历史摘要。新指纹写入后再次启动无需该计划。模型、权限、工具集合、工作区或 async_policy 变化仍拒绝。已有 `restore_path_migration` 可以同时反向投影最多三个明确私有路径；此组合要求对应 Skill Session 也在计划中。保留 child runtime 的同 Session 换模仍拒绝。

复测使用真正旧 checkout 创建的数据库，覆盖无计划拒绝、指定计划恢复、原 journal 保留、同键不再执行、UNKNOWN 不重放，以及错误 Session/摘要/bundle、权限变化、已加载 Skill 正文变更拒绝。设置 `LOCALPILOT_LEGACY_SOURCE` 为固定 `94e0e6f` checkout 后执行 `tests.test_restore_skill_catalog_migration`；没有旧源码时明确 SKIP。

受管 `CachedModelHost` 在启动前为自己的 `prefix-cache` 预留容量。`cached_model_host.cache_bytes` 是正整数字节，默认登记 2,000,000,000 字节（十进制 2 GB）。旧 Provider CLI 的 `2GB` 实际按 2 GiB 解析；若要保留该容量，第一次登记时显式配置 `cache_bytes: 2147483648`。所有受管根的最大容量之和不得超过 50 GiB；同一根不能静默改变容量。登记册默认位于 `~/.local/share/localpilot-owned-cache-budget`，隔离服务可用 `LOCALPILOT_CACHE_BUDGET_HOME` 指定独立位置。Suite 的 product `cache_budget` 操作返回登记根、实际逻辑字节和额度。

这是受管缓存的容量预留与准入约束。条目淘汰交给实际 oMLX 的 LRU；产品不扫描陌生目录，也没有删除接口。共享 oMLX/HuggingFace、权重、活动记忆、任务/收据、凭据、APP 和发行/回滚归档不进入自动清理。50 GiB 是上限，不代表当前磁盘可分配 50 GiB。已有外部服务没有被接管。已加载数组的引用由 Provider 保留，磁盘缓存文件可被 LRU 淘汰；这不承诺缓存永不失效或任意 Provider 均有相同语义。

模型预算对照使用同一个本地传输与精确的已安装 oMLX 模板/tokenizer 规范化，禁止隐藏传输重试。Terminus2 保留官方任务循环、parser 和 tmux，替换其 LLM transport，因此报告必须称为“Terminus2 + measured product transport”，不能称为原样官方产品成绩。API 计费为本地零费用，硬件和能源成本未计量。

旧 Provider 在受管私有宿主根下创建的 `prefix-cache` 可能是 755。升级只对该固定、非链接且本用户拥有的缓存子目录收紧为 700，保留全部块内容，再做容量准入；不会因此接管任意共享目录。Suite 检查请求为 `{"version":1,"operation":"cache_budget","args":{}}`。
