import { useEffect, useState } from "react";
import { call, desktop } from "../bridge";
import type { Json } from "../domain";

export function LocalEndpointForm({
  onChanged,
  onBeforeSave,
}: {
  onChanged?: () => void | Promise<void>;
  onBeforeSave?: () => Promise<boolean>;
}) {
  const [name, setName] = useState("local-cpu");
  const [endpoint, setEndpoint] = useState("http://127.0.0.1:1234/v1");
  const [model, setModel] = useState("");
  const [models, setModels] = useState<string[]>([]);
  const [context, setContext] = useState("");
  const [companion, setCompanion] = useState(true);
  const [disableThinking, setDisableThinking] = useState(false);
  const [powerPolicy, setPowerPolicy] = useState("system");
  const [result, setResult] = useState<Json | null>(null);
  const [restartRequired, setRestartRequired] = useState(false);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState("");
  useEffect(() => {
    if (desktop)
      call<Json>("product_control", {
        operation: "model_configuration",
        args: {},
      })
        .then((saved) => {
          setRestartRequired(saved.restart_required);
        })
        .catch((error) => setError(String(error)));
  }, []);
  async function discover() {
    setBusy("正在检查模型列表");
    setError("");
    setResult(null);
    setModels([]);
    try {
      const observed = await call<Json>("product_control", {
        operation: "discover_local_endpoint",
        args: { base_url: endpoint },
      });
      setModels(observed.models.map((item: { id: string }) => item.id));
      setResult(observed);
    } catch (error) {
      setError(String(error));
    } finally {
      setBusy("");
    }
  }
  async function save() {
    setBusy("保存本机模型配置");
    setError("");
    setResult(null);
    try {
      if (onBeforeSave && !(await onBeforeSave())) return;
      const saved = await call<Json>("product_control", {
        operation: "configure_local_endpoint",
        args: {
          name,
          base_url: endpoint,
          model,
          context_budget: Number(context),
          companion,
          companion_power_policy: companion ? powerPolicy : "preserve",
          disable_thinking: disableThinking,
        },
      });
      setResult(saved);
      setRestartRequired(saved.restart_required);
      await onChanged?.();
    } catch (error) {
      setError(String(error));
    } finally {
      setBusy("");
    }
  }
  async function activate() {
    setBusy("正在应用已保存的配置");
    setError("");
    try {
      const activated = await call<Json>("product_control", {
        operation: "activate_model_configuration",
        args: { confirmed: true },
      });
      setResult(activated);
      setRestartRequired(activated.restart_required);
      await onChanged?.();
    } catch (error) {
      setError(String(error));
    } finally {
      setBusy("");
    }
  }
  return (
    <section className="local-endpoint-form" aria-label="连接本机模型服务">
      <h3>连接本机模型服务</h3>
      <p className="muted">
        Intel Mac 可使用 llama.cpp 等推理程序的本机 OpenAI 兼容服务。
        先启动服务并加载支持工具调用的模型，再填写地址。CPU 或 GPU
        加速由推理服务选择；模型权重不包含在 LocalPilot 中。
      </p>
      <label>
        本机路由名称
        <input value={name} onChange={(event) => setName(event.target.value)} />
      </label>
      <label>
        本机端点
        <input
          value={endpoint}
          onChange={(event) => {
            setEndpoint(event.target.value);
            setModels([]);
            setResult(null);
          }}
          placeholder="http://127.0.0.1:1234/v1"
        />
      </label>
      <button
        className="secondary"
        disabled={!desktop || !!busy}
        onClick={discover}
      >
        检查连接并读取模型列表
      </button>
      <p className="micro muted">此检查只读取模型列表，不发送推理请求。</p>
      {models.length > 0 && (
        <label>
          服务报告的模型
          <select
            value={model}
            onChange={(event) => setModel(event.target.value)}
          >
            <option value="">选择模型</option>
            {models.map((id) => (
              <option key={id} value={id}>
                {id}
              </option>
            ))}
          </select>
        </label>
      )}
      <label>
        模型 ID
        <input
          value={model}
          onChange={(event) => setModel(event.target.value)}
        />
      </label>
      <label>
        上下文 token 上限
        <input
          type="number"
          min={4096}
          max={1048576}
          value={context}
          onChange={(event) => setContext(event.target.value)}
          placeholder="填写推理服务实际配置的上限"
        />
      </label>
      <p className="micro muted">
        模型列表不能证明上下文容量；请使用服务实际加载时的配置。
      </p>
      <label className="simple-toggle">
        <input
          type="checkbox"
          checked={disableThinking}
          onChange={(event) => setDisableThinking(event.target.checked)}
        />
        请求后端关闭模型思考输出
      </label>
      <p className="micro muted">
        仅向支持该选项的后端发送关闭请求；是否生效仍需实际回答验证。
      </p>
      <label className="simple-toggle">
        <input
          type="checkbox"
          checked={companion}
          onChange={(event) => setCompanion(event.target.checked)}
        />
        同时让 Companion 使用这个本机端点
      </label>
      {companion && (
        <label>
          Companion 推理电源策略
          <select
            value={powerPolicy}
            onChange={(event) => setPowerPolicy(event.target.value)}
          >
            <option value="system">跟随系统电源策略</option>
            <option value="preserve">保留现有策略</option>
            <option value="off">关闭 Companion 低功耗限制</option>
          </select>
          <span className="micro muted">
            跟随系统时，低功耗或未知电源状态可能阻止未受管端点推理。
            关闭低功耗限制只改变 Companion 的策略，不改变系统电源设置。
            电池推理授权仍单独检查。
          </span>
        </label>
      )}
      <button
        className="primary"
        disabled={
          !desktop ||
          !!busy ||
          !name.trim() ||
          !model.trim() ||
          !context ||
          Number(context) < 4096 ||
          Number(context) > 1048576
        }
        onClick={save}
      >
        {busy || "保存本机模型配置"}
      </button>
      {result && (
        <div role="status">
          <p>
            {result.next ||
              (result.connection === "REACHABLE"
                ? "已连接服务；真实推理尚未验证。"
                : "已更新配置。")}
          </p>
          {result.route && <p>已保存路由：{result.route}</p>}
          {result.backup && (
            <p className="micro muted">
              原配置备份：<code>{result.backup}</code>
            </p>
          )}
        </div>
      )}
      {restartRequired && (
        <div>
          <p>
            应用配置会重启本次安装的 Core 与需要更新的
            Companion。正在执行或等待批准的任务会阻止重启。
          </p>
          <button className="secondary" disabled={!!busy} onClick={activate}>
            确认重启服务并应用配置
          </button>
        </div>
      )}
      {error && (
        <p role="alert" className="warning">
          {error}
        </p>
      )}
    </section>
  );
}
