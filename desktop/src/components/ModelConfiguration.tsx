import { useEffect, useState } from "react";
import { call, desktop } from "../bridge";
import type { Json } from "../domain";
import { LocalEndpointForm } from "./LocalEndpointForm";

export function ModelConfiguration({
  onChanged,
  preferEndpoint = false,
}: {
  onChanged?: () => void | Promise<void>;
  preferEndpoint?: boolean;
}) {
  const [models, setModels] = useState<Json[]>([]);
  const [primary, setPrimary] = useState("");
  const [partners, setPartners] = useState<string[]>([]);
  const [workerRoles, setWorkerRoles] = useState<Record<string, string>>({});
  const [mode, setMode] = useState("local-first");
  const [asyncEnabled, setAsyncEnabled] = useState(true);
  const [name, setName] = useState("personal-agent");
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
  function removePartner(id: string) {
    setPartners((old) => old.filter((value) => value !== id));
    setWorkerRoles((old) =>
      Object.fromEntries(
        Object.entries(old).filter(([, value]) => value !== id),
      ),
    );
  }
  const eligible = models.filter((model) => model.cooperation_supported);
  const roleModels = eligible.filter((model) => partners.includes(model.id));
  return (
    <section className="model-configuration">
      <h3>添加本机模型与协作 Agent</h3>
      <p className="muted">
        配置将保存为新路由。等待活动任务结束后，显式重启服务以应用配置。 已有
        Session 与收据保留；连接检查与实际推理分别验证。
      </p>
      <details open={!preferEndpoint} className="advanced-settings">
        <summary>由多个已注册模型协作</summary>
        <label>
          协作路由名称
          <input
            value={name}
            onChange={(event) => setName(event.target.value)}
            placeholder="personal-agent"
          />
        </label>
        <label>
          主模型
          <select
            aria-label="协作主模型"
            value={primary}
            onChange={(event) => {
              setPrimary(event.target.value);
              removePartner(event.target.value);
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
                onChange={(event) => {
                  if (event.target.checked) {
                    setPartners((old) => [...old, model.id]);
                  } else {
                    removePartner(model.id);
                  }
                }}
              />
              {model.id} · {model.model} · {model.adapter}
            </label>
          ))}
        {[
          { role: "search", label: "探索模型（只读）" },
          { role: "review", label: "审阅模型（只读）" },
        ].map(({ role, label }) => (
          <label key={role}>
            {label}
            <select
              aria-label={label}
              value={workerRoles[role] || ""}
              disabled={!roleModels.length}
              onChange={(event) => {
                const model = event.target.value;
                setWorkerRoles((old) => {
                  const roles = { ...old };
                  if (model) roles[role] = model;
                  else delete roles[role];
                  return roles;
                });
              }}
            >
              <option value="">不指定</option>
              {roleModels.map((model) => (
                <option key={model.id} value={model.id}>
                  {model.id} · {model.model}
                  {model.thinking ? ` · 思考 ${model.thinking}` : ""}
                </option>
              ))}
            </select>
          </label>
        ))}
        <p className="muted">
          Super Agent 负责统筹，按需派发探索与审阅，收集结果后继续完成任务。
          两种职责均只读，可使用同一伙伴模型；测试由执行 Agent 负责。
          来源策略仍决定允许使用的本地或云端模型。
        </p>
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
              ...(Object.keys(workerRoles).length
                ? { roles: workerRoles }
                : {}),
            })
          }
        >
          保存协作 Agent 配置
        </button>
      </details>
      <details open={preferEndpoint} className="advanced-settings">
        <summary>Intel / CPU 或其他本机 OpenAI 兼容服务</summary>
        <LocalEndpointForm
          onChanged={async () => {
            await refresh();
            await onChanged?.();
          }}
        />
      </details>
      {error && (
        <p role="alert" className="warning">
          {error}
        </p>
      )}
      {result && (
        <div role="status">
          <p>{result.next}</p>
          {result.route && (
            <p>
              已保存：{result.route} · 推理 {result.inference} · 连接{" "}
              {result.connection}
            </p>
          )}
          {result.backup && (
            <p className="muted">
              原配置备份：<code>{result.backup}</code>
            </p>
          )}
          {result.restart_required && (
            <button
              className="secondary"
              disabled={busy}
              onClick={() =>
                void save("activate_model_configuration", { confirmed: true })
              }
            >
              确认重启服务并应用配置
            </button>
          )}
        </div>
      )}
    </section>
  );
}
