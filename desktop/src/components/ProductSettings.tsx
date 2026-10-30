import type { EnterBehavior } from "../inputBehavior";
import { permissionModes, legacyPermissions } from "../permissions";
import { useState, useEffect } from "react";
import { call, desktop } from "../bridge";
import { InstallationSettings } from "./InstallationSettings";
import { ChannelSettings } from "./ChannelSettings";
export function ProductSettings({
  enterBehavior,
  onEnterBehavior,
  permissionMode,
  onPermission,
  onModels,
  onError,
  defaultModel,
  models,
  onDefaultModel,
  onUpdates,
}: {
  enterBehavior: EnterBehavior;
  onEnterBehavior: (value: EnterBehavior) => void;
  defaultModel: string;
  models: any[];
  onDefaultModel: (s: string) => void;
  onUpdates: () => void;
  permissionMode: string;
  onPermission: (s: string) => void;
  onModels: () => void;
  onError: (e: unknown) => void;
}) {
  const [pet, setPet] = useState(
      localStorage.getItem("lp.petEnabled") === "true",
    ),
    [key, setKey] = useState(""),
    [cloudBusy, setCloudBusy] = useState(false);
  const [cloudNotice, setCloudNotice] = useState("");
  const [companion, setCompanion] = useState<any>(null),
    [notice, setNotice] = useState("");
  useEffect(() => {
    if (desktop)
      call("companion_settings", { enabled: null, confirmed: false })
        .then(setCompanion)
        .catch(() => {});
  }, []);
  return (
    <section className="product-settings">
      <h3>常用设置</h3>
      <div className="setting-row">
        <span>
          回车键行为
          <small>中文输入法确认候选时始终不发送；⌘ Enter 可发送。</small>
        </span>
        <select
          aria-label="回车键行为"
          value={enterBehavior}
          onChange={(e) => onEnterBehavior(e.target.value as EnterBehavior)}
        >
          <option value="newline">回车换行，⌘ Enter 发送</option>
          <option value="send">回车发送，Shift Enter 换行</option>
        </select>
      </div>
      <InstallationSettings onError={onError} />
      <ChannelSettings onError={onError} />
      {notice && <p role="status">{notice}</p>}
      <button
        className="secondary"
        onClick={async () => {
          try {
            await call("bootstrap_product", { confirmed: true });
            location.reload();
          } catch (e) {
            onError(e);
          }
        }}
      >
        检查并更新内置组件
      </button>
      <div className="setting-row">
        <span>
          默认模型<small>仅影响以后新建的会话，不自动下载或加载</small>
        </span>
        <select
          aria-label="默认模型"
          value={defaultModel}
          onChange={(e) => onDefaultModel(e.target.value)}
        >
          <option value="">按来源偏好自动选择</option>
          {models.map((m) => (
            <option value={m.id} key={m.id}>
              {m.model} · {m.adapter}
            </option>
          ))}
        </select>
      </div>
      <div className="setting-row">
        <span>软件更新</span>
        <button className="secondary" onClick={onUpdates}>
          检查更新
        </button>
      </div>
      <div className="setting-row">
        <span>
          默认权限模式<small>新会话采用所选工具批准策略</small>
        </span>
        <select
          value={permissionMode}
          onChange={(e) => onPermission(e.target.value)}
        >
          {[...permissionModes, ...legacyPermissions].map(({ id, name }) => (
            <option value={id} key={id}>
              {name}
            </option>
          ))}
        </select>
      </div>
      <div className="setting-row">
        <span>
          模型与常用模型<small>下载、加载、上下文和缓存偏好</small>
        </span>
        <button className="secondary" onClick={onModels}>
          打开模型库
        </button>
      </div>
      <div className="setting-row">
        <span>
          Companion 宠物模式<small>独立开启与关闭，不改变标准 Agent</small>
        </span>
        <button
          className="secondary"
          aria-pressed={pet}
          onClick={async () => {
            try {
              await call("pet_window", { enabled: !pet });
              localStorage.setItem("lp.petEnabled", String(!pet));
              setPet(!pet);
            } catch (e) {
              onError(e);
            }
          }}
        >
          {pet ? "关闭宠物" : "开启宠物"}
        </button>
      </div>
      <details className="advanced-settings">
        <summary>Companion 独立设置</summary>
        <button
          className="secondary"
          disabled={!companion}
          onClick={async () => {
            try {
              const result = await call<any>("product_control", {
                operation: "configure_pet_model",
                args: { confirmed: true },
              });
              setCompanion(
                await call("companion_settings", {
                  enabled: null,
                  confirmed: false,
                }),
              );
              setNotice(
                result.loaded
                  ? "已连接已下载的轻量模型。"
                  : "已连接轻量模型，请在模型库确认加载后聊天。",
              );
            } catch (e) {
              onError(e);
            }
          }}
        >
          连接已下载的小模型
        </button>
        <label className="simple-toggle">
          <input
            type="checkbox"
            checked={
              companion?.proactive?.delivery === "enabled" &&
              companion?.proactive?.level !== "off"
            }
            disabled={!companion}
            onChange={async (e) => {
              try {
                setCompanion(
                  await call("companion_settings", {
                    enabled: e.target.checked,
                    confirmed: true,
                  }),
                );
              } catch (error) {
                onError(error);
              }
            }}
          />
          允许宠物主动提示
        </label>
        <p className="micro muted">
          仅使用 Companion
          已获准的观察和记忆。此开关不授予屏幕、文件或云端权限。
        </p>
        {companion?.feedback_health?.blockers?.map((b: string) => (
          <p className="micro muted" key={b}>
            {b}
          </p>
        ))}
      </details>
      <details className="advanced-settings">
        <summary>连接 DeepSeek</summary>
        <p className="micro muted">
          密钥仅保存到本机私有目录。添加 Provider
          不会自动调用云端；选择云端模型发送任务时，任务内容与允许读取的结果会交给该模型。
        </p>
        <input
          aria-label="DeepSeek API 密钥"
          type="password"
          autoComplete="off"
          value={key}
          onChange={(e) => setKey(e.target.value)}
          placeholder="API 密钥"
        />
        <button
          className="secondary"
          disabled={cloudBusy || !key}
          onClick={async () => {
            setCloudBusy(true);
            setCloudNotice(
              "正在保存配置并重新连接 Core，首次启动最多约两分钟，请勿重复点击。",
            );
            try {
              const result = await call<any>("configure_cloud_key", {
                key,
                confirmed: true,
              });
              setCloudNotice(
                result.status === "already_configured"
                  ? "DeepSeek 已配置，保留现有密钥。可以关闭设置并选择 DeepSeek 发送任务。"
                  : "DeepSeek 配置已保存，Core 已连接。可以关闭设置并选择 DeepSeek 发送任务。API 是否可用以首次任务结果为准。",
              );
              setKey("");
            } catch (e) {
              setCloudNotice("配置未完成：" + String(e));
              onError(e);
            } finally {
              setCloudBusy(false);
            }
          }}
        >
          {cloudBusy ? "正在配置…" : "保存并连接"}
        </button>
        {cloudNotice && (
          <p role="status" aria-live="polite">
            {cloudNotice}
          </p>
        )}
      </details>
      <p className="micro muted">
        数据与隐私：本地附件在授权工作区保留副本。选择云端模型后，按当前权限处理并发送上下文。关闭窗口不会删除配置、历史或任务。
      </p>
    </section>
  );
}
