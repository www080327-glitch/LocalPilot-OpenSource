import { useEffect, useState } from "react";
import { call, desktop } from "../bridge";
import type { Json } from "../domain";

export function ModelConfiguration({
  onChanged,
}: {
  onChanged?: () => void | Promise<void>;
}) {
  const [models, setModels] = useState<Json[]>([]);
  const [primary, setPrimary] = useState("");
  const [partners, setPartners] = useState<string[]>([]);
  const [mode, setMode] = useState("local-first");
  const [asyncEnabled, setAsyncEnabled] = useState(true);
  const [name, setName] = useState("personal-agent");
  const [endpoint, setEndpoint] = useState("http://127.0.0.1:1234/v1");
  const [localModel, setLocalModel] = useState("");
  const [context, setContext] = useState(32768);
  const [companion, setCompanion] = useState(false);
  const [result, setResult] = useState<Json | null>(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  async function refresh() {
    const result = await call<Json>("product_control", {
      operation: "model_configuration",
      args: {},
    });
    setModels(result.models || []);
  }
  useEffect(() => {
    if (desktop) void refresh().catch((error) => setError(String(error)));
  }, []);
  async function save(operation: string, args: Json) {
    setBusy(true);
    setError("");
    setResult(null);
    try {
      const result = await call<Json>("product_control", { operation, args });
      setResult(result);
      await refresh();
      await onChanged?.();
    } catch (error) {
      setError(String(error));
    } finally {
      setBusy(false);
    }
  }
  const eligible = models.filter((model) => model.cooperation_supported);
  return (
    <section className="model-configuration">
      <h3>添加本机模型与协作 Agent</h3>
      <p className="muted">
        配置将保存为新路由。等待活动任务结束后，在设置中显式停止并恢复
        Core；涉及 Companion 时也需重启其服务。连接检查与实际推理分别验证。
      </p>
      <label>
        新路由名称
        <input
          value={name}
          onChange={(event) => setName(event.target.value)}
          placeholder="personal-agent"
        />
      </label>
      <details open className="advanced-settings">
        <summary>由多个已注册模型协作</summary>
        <label>
          主模型
          <select
            aria-label="协作主模型"
            value={primary}
            onChange={(event) => {
              setPrimary(event.target.value);
              setPartners((old) =>
                old.filter((id) => id !== event.target.value),
              );
            }}
          >
            <option value="">选择主模型</option>
            {eligible.map((model) => (
              <option key={model.id} value={model.id}>
                {model.id} · {model.model} · {model.adapter}
              </option>
            ))}
          </select>
        </label>
        <p>子 Agent 可用模型</p>
        {eligible
          .filter((model) => model.id !== primary)
          .map((model) => (
            <label className="simple-toggle" key={model.id}>
              <input
                type="checkbox"
                checked={partners.includes(model.id)}
                onChange={(event) =>
                  setPartners((old) =>
                    event.target.checked
                      ? [...old, model.id]
                      : old.filter((id) => id !== model.id),
                  )
                }
              />
              {model.id} · {model.model} · {model.adapter}
            </label>
          ))}
        <label>
          五档来源策略
          <select
            aria-label="协作来源策略"
            value={mode}
            onChange={(event) => setMode(event.target.value)}
          >
            <option value="local-only">完全本地</option>
            <option value="local-first">本地优先</option>
            <option value="balanced">均衡</option>
            <option value="cloud-first">云端优先</option>
            <option value="cloud-only">完全云端</option>
          </select>
        </label>
        <label className="simple-toggle">
          <input
            type="checkbox"
            checked={asyncEnabled}
            onChange={(event) => setAsyncEnabled(event.target.checked)}
          />
          异步子 Agent · 共享模型与并发预算
        </label>
        <p className="muted">
          新主 Agent：最多 48 步、64 次工具调用；每个子 Agent：12 步、16
          次工具调用。每轮最多创建 4 个子
          Agent。首次启用异步配置时，本机模型并发为 1、云模型并发为
          2；已有服务限额继续沿用。云端调用仍遵循会话来源与出站策略。
        </p>
        <button
          className="primary"
          disabled={!desktop || busy || !primary || !partners.length}
          onClick={() =>
            void save("configure_cooperation", {
              name,
              primary,
              partners,
              mode,
              async_enabled: asyncEnabled,
            })
          }
        >
          保存协作 Agent 配置
        </button>
      </details>
      <details className="advanced-settings">
        <summary>Intel / CPU 或其他本机 OpenAI 兼容服务</summary>
        <p className="muted">
          先用自己的推理程序启动本机服务，再填写模型 ID
          与实际上下文上限。硬件加速由该服务检测，CPU
          回退由该服务执行。LocalPilot 不为此启动
          MLX、下载权重或更改其他推理服务。
        </p>
        <label>
          本机端点
          <input
            value={endpoint}
            onChange={(event) => setEndpoint(event.target.value)}
          />
        </label>
        <label>
          模型 ID
          <input
            value={localModel}
            onChange={(event) => setLocalModel(event.target.value)}
          />
        </label>
        <label>
          上下文 token 上限
          <input
            type="number"
            min={4096}
            max={1048576}
            value={context}
            onChange={(event) => setContext(Number(event.target.value))}
          />
        </label>
        <label className="simple-toggle">
          <input
            type="checkbox"
            checked={companion}
            onChange={(event) => setCompanion(event.target.checked)}
          />
          同时让 Companion 使用这个本机端点
        </label>
        <button
          className="primary"
          disabled={!desktop || busy || !localModel.trim()}
          onClick={() =>
            void save("configure_local_endpoint", {
              name,
              base_url: endpoint,
              model: localModel,
              context_budget: context,
              companion,
            })
          }
        >
          保存本机模型配置
        </button>
      </details>
      {error && (
        <p role="alert" className="warning">
          {error}
        </p>
      )}
      {result && (
        <div role="status">
          <p>{result.next}</p>
          <p>
            已保存：{result.route} · 推理 {result.inference} · 连接{" "}
            {result.connection}
          </p>
          <p className="muted">
            原配置备份：<code>{result.backup}</code>
          </p>
        </div>
      )}
    </section>
  );
}
