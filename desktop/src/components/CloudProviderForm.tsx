import { useState } from "react";
import { call, desktop } from "../bridge";
import type { Json } from "../domain";

const providers = {
  deepseek: { label: "DeepSeek", model: "deepseek-flash" },
  openai: { label: "OpenAI", model: "gpt-6-luna" },
} as const;

export function CloudProviderForm({
  disabled = false,
  onBeforeConnect,
  onConnected,
  onBusy,
}: {
  disabled?: boolean;
  onBeforeConnect?: () => Promise<boolean>;
  onConnected?: () => void | Promise<void>;
  onBusy?: (busy: boolean) => void;
}) {
  const [provider, setProvider] = useState<keyof typeof providers>("deepseek");
  const [model, setModel] = useState<string>(providers.deepseek.model);
  const [key, setKey] = useState("");
  const [busy, setBusy] = useState(false);
  const [notice, setNotice] = useState("");
  const [error, setError] = useState("");
  const name = providers[provider].label;
  async function connect() {
    setBusy(true);
    onBusy?.(true);
    setError("");
    setNotice("正在保存配置并连接服务…");
    try {
      if (onBeforeConnect && !(await onBeforeConnect())) {
        setNotice("");
        return;
      }
      const result = await call<Json>("configure_cloud_key", {
        key,
        provider,
        model: model.trim(),
        confirmed: true,
      });
      setKey("");
      setNotice(
        result.status === "already_configured"
          ? `${name} / ${model.trim()} 已有配置，保留原有密钥。可在模型选择器选择此模型。`
          : `${name} 配置已保存，服务已连接。可在模型选择器选择 ${model.trim()}；API 是否可用以实际任务结果为准。`,
      );
      await onConnected?.();
    } catch (error) {
      setNotice("");
      setError(String(error));
    } finally {
      setBusy(false);
      onBusy?.(false);
    }
  }
  return (
    <section className="cloud-provider-form" aria-label="连接云端模型">
      <h3>连接云端模型</h3>
      <label>
        提供商
        <select
          value={provider}
          disabled={busy || disabled}
          onChange={(event) => {
            const value = event.target.value as keyof typeof providers;
            setProvider(value);
            setModel(providers[value].model);
            setKey("");
            setNotice("");
            setError("");
          }}
        >
          {Object.entries(providers).map(([id, item]) => (
            <option key={id} value={id}>
              {item.label}
            </option>
          ))}
        </select>
      </label>
      <label>
        模型
        <input
          value={model}
          disabled={busy || disabled}
          onChange={(event) => setModel(event.target.value)}
        />
      </label>
      <label>
        {name} API 密钥
        <input
          type="password"
          autoComplete="off"
          value={key}
          disabled={busy || disabled}
          onChange={(event) => setKey(event.target.value)}
          placeholder={`${name} API 密钥`}
        />
      </label>
      <button
        className="secondary"
        disabled={!desktop || disabled || busy || !key || !model.trim()}
        onClick={() => void connect()}
      >
        {busy ? "正在连接…" : "保存并连接"}
      </button>
      <p className="micro muted">
        密钥仅保存到本机私有目录。连接配置不会发送任务；发送任务时按当前权限处理云端上下文。
      </p>
      {notice && (
        <p role="status" aria-live="polite">
          {notice}
        </p>
      )}
      {error && <p role="alert">{error}</p>}
    </section>
  );
}
