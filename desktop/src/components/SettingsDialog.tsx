import { useState, type ComponentProps } from "react";
import {
  Activity,
  ArrowRight,
  Folder,
  LoaderCircle,
  Monitor,
  Power,
  ShieldCheck,
  Square,
  Terminal,
  Wifi,
} from "lucide-react";
import packageInfo from "../../package.json";
import { call, desktop } from "../bridge";
import type { Json, NativeProfile } from "../domain";
import { BrandMark as Mark } from "./BrandMark";
import { JsonView as Pretty } from "./JsonView";
import { Modal } from "./Modal";
import { PreferenceControls } from "./Preferences";
import { ProductSettings } from "./ProductSettings";
import { VersionManagement } from "./VersionManagement";

type SettingsDialogProps = {
  open: boolean;
  onClose: () => void;
  defaults: ComponentProps<typeof PreferenceControls>;
  onSaveDefaults: () => void;
  product: ComponentProps<typeof ProductSettings>;
  profile: NativeProfile;
  health: Json | null;
  compHealth: Json | null;
  diagnostic: Json | null;
  setDiagnostic: (result: Json) => void;
  connected: boolean;
  formHome: string;
  setFormHome: (home: string) => void;
  formCli: string;
  setFormCli: (cli: string) => void;
  management: boolean;
  setManagement: (busy: boolean) => void;
  busy: boolean;
  error: string;
  setError: (message: string) => void;
  showError: (error: unknown) => void;
  connect: () => void;
  refresh: () => Promise<void>;
  setModel: (model: string) => void;
  setToast: (message: string) => void;
  onOpenPanel: (panel: "initialize" | "developer" | "tools") => void;
  onPreview: () => void;
  theme: string;
  setTheme: (theme: string) => void;
  glass: boolean;
  setGlass: (enabled: boolean) => void;
  glassStatus: string;
  reduced: boolean;
  setReduced: (enabled: boolean) => void;
};

export function SettingsDialog({
  open,
  onClose,
  defaults,
  onSaveDefaults,
  product,
  profile,
  health,
  compHealth,
  diagnostic,
  setDiagnostic,
  connected,
  formHome,
  setFormHome,
  formCli,
  setFormCli,
  management,
  setManagement,
  busy,
  error,
  setError,
  showError,
  connect,
  refresh,
  setModel,
  setToast,
  onOpenPanel,
  onPreview,
  theme,
  setTheme,
  glass,
  setGlass,
  glassStatus,
  reduced,
  setReduced,
}: SettingsDialogProps) {
  const [cloudPaths, setCloudPaths] = useState("");
  async function pick(kind: string) {
    try {
      const v = await call<string | null>("pick_suite", { kind });
      if (v) (kind === "home" ? setFormHome : setFormCli)(v);
    } catch (e) {
      showError(e);
    }
  }
  async function manage(action: string) {
    setError("");
    setManagement(true);
    try {
      const r = await call<Json>("lifecycle", { action });
      setDiagnostic(r);
      await refresh().catch(() => {});
      if (r.exit === 0) {
        setToast("操作已返回，状态以诊断结果为准");
      } else {
        setError(
          "管理操作未成功，请查看诊断。连接状态已按服务实际健康情况更新。",
        );
      }
    } catch (e) {
      await refresh().catch(() => {});
      showError(e);
    } finally {
      setManagement(false);
    }
  }
  if (!open) return null;
  return (
    <Modal title="连接与偏好设置" onClose={onClose} wide>
      <div className="settings-intro">
        <Mark small />
        <div>
          <strong>LocalPilot Desktop</strong>
          <p>管理模型、权限和宠物。服务连接与专业参数放在高级设置。</p>
        </div>
        <span className="outline-badge">{packageInfo.version}</span>
      </div>
      <section className="global-preferences">
        <div className="preference-panel-title">
          <h3>新会话默认值</h3>
          <span className="micro muted">保存后仅影响后续新会话</span>
        </div>
        <PreferenceControls {...defaults} />
        <button className="primary" onClick={onSaveDefaults}>
          保存全局默认值
        </button>
      </section>
      <ProductSettings {...product} onModelsChanged={refresh} />
      <details className="advanced-settings">
        <summary>高级设置 · 服务、API、路由与诊断</summary>
        <div className="settings-grid">
          <section>
            <h3>服务连接</h3>
            {desktop && (
              <section>
                <label className="field-label">
                  云端文件正文范围 · 精确工作区相对路径，一行一个
                  <textarea
                    aria-label="云端文件正文范围"
                    value={cloudPaths}
                    onChange={(e) => setCloudPaths(e.target.value)}
                    placeholder={"input.txt\nanswer.txt"}
                  />
                </label>
                <button
                  className="secondary full"
                  disabled={
                    management || busy || !connected || !cloudPaths.trim()
                  }
                  onClick={async () => {
                    setManagement(true);
                    try {
                      const result = await call<Json>("configure_cloud_scope", {
                        paths: cloudPaths
                          .split("\n")
                          .map((p) => p.trim())
                          .filter(Boolean),
                        confirmed: true,
                      });
                      await refresh();
                      setModel(
                        result.result?.route ||
                          result.route ||
                          "deepseek-agent",
                      );
                      setToast(
                        "精确文件范围已授权。新会话使用新增的云端路由；每次请求仍需出站审批。",
                      );
                    } catch (e) {
                      showError(e);
                    } finally {
                      setManagement(false);
                    }
                  }}
                >
                  授权以上文件正文出站 · 创建独立云端路由
                </button>
                <p className="micro muted">
                  仅授权列出的文件；可列出尚未创建的目标文件。已有 Session
                  保留原范围。任务或审批未结束时不修改配置。
                </p>
              </section>
            )}
            {desktop && (
              <button
                className="secondary full"
                disabled={management || busy || !connected}
                onClick={async () => {
                  setManagement(true);
                  try {
                    await call("add_cloud_provider");
                    await refresh();
                    setToast("DeepSeek 已配置；每次云端任务仍需出站授权。");
                  } catch (e) {
                    showError(e);
                  } finally {
                    setManagement(false);
                  }
                }}
              >
                配置 DeepSeek · 选择现有私有密钥文件
              </button>
            )}
            <button
              className="text-btn"
              onClick={() => {
                onOpenPanel("initialize");
              }}
            >
              首次使用：初始化空 Suite 目录
              <ArrowRight size={13} />
            </button>
            <label className="field-label">
              Suite 数据目录
              <div className="path-input">
                <input
                  aria-label="Suite 数据目录"
                  value={formHome}
                  onChange={(e) => setFormHome(e.target.value)}
                  placeholder="~/.local/share/localpilot"
                />
                <button
                  className="icon-btn"
                  onClick={() => pick("home")}
                  aria-label="选择 Suite 数据目录"
                >
                  <Folder size={16} />
                </button>
              </div>
            </label>
            <label className="field-label">
              Suite 命令
              <div className="path-input">
                <input
                  aria-label="Suite 命令"
                  value={formCli}
                  onChange={(e) => setFormCli(e.target.value)}
                  placeholder="/path/to/venv/bin/localpilot"
                />
                <button
                  className="icon-btn"
                  onClick={() => pick("cli")}
                  aria-label="选择 Suite 命令"
                >
                  <Folder size={16} />
                </button>
              </div>
            </label>
            <p className="micro muted">
              <ShieldCheck size={12} /> 仅由原生侧读取 Suite 的 600
              私有凭据。GUI 保存连接引用，不复制 Token。
            </p>
            <button
              className="primary"
              onClick={connect}
              disabled={management || !formHome}
            >
              {management ? (
                <LoaderCircle className="spin" size={14} />
              ) : (
                <Wifi size={14} />
              )}
              连接并检查
            </button>
            {profile.origin && (
              <p className="micro muted">
                {profile.origin}
                <br />
                {connected
                  ? `Core ${health?.version} · 契约 ${health?.compatibility?.agent_service_api}`
                  : "已配置连接；服务可能尚未启动"}
              </p>
            )}
          </section>
          <section>
            <h3>外观与交互</h3>
            <button
              className="secondary full"
              onClick={() => {
                onOpenPanel("developer");
              }}
            >
              <Terminal size={14} />
              开发者工具 · 完整 CLI
            </button>
            <button
              className="secondary full"
              onClick={() => {
                onOpenPanel("tools");
              }}
            >
              <Terminal size={14} />
              Suite / Companion 工具
            </button>
            <div className="setting-row">
              <span>主题</span>
              <select
                aria-label="主题"
                value={theme}
                onChange={(e) => setTheme(e.target.value)}
              >
                <option value="system">跟随系统</option>
                <option value="dark">深色 · Graphite</option>
                <option value="light">浅色 · Paper</option>
              </select>
            </div>
            <div className="setting-row">
              <span>原生 Liquid Glass</span>
              <input
                type="checkbox"
                aria-label="原生 Liquid Glass"
                checked={glass}
                onChange={(e) => setGlass(e.target.checked)}
              />
            </div>
            <p className="micro muted">{glassStatus}</p>
            <div className="setting-row">
              <span>减少动态效果</span>
              <input
                aria-label="减少动态效果"
                type="checkbox"
                checked={reduced}
                onChange={(e) => setReduced(e.target.checked)}
              />
            </div>
            <p className="micro muted">
              同时遵循系统 Reduce Motion。无持续背景动画。
            </p>
            <button className="secondary full" onClick={onPreview}>
              <Monitor size={14} />
              查看模拟工作区
            </button>
            <p className="micro muted">
              浏览器只提供设计预览；真实接入通过桌面应用的原生连接层。
            </p>
          </section>
        </div>
        <VersionManagement
          key={`${profile.cli}|${profile.home}`}
          health={health}
          cliReady={!!profile.cli}
        />
        <div className="settings-service">
          <h3>
            服务管理
            <span>{compHealth ? "Companion 已连接" : "Companion 未连接"}</span>
          </h3>
          <div className="management-actions">
            {[
              ["start", "启动 Core"],
              ["companion_start", "启动 Companion"],
              ["doctor", "诊断"],
              ["status", "服务状态"],
              ["restart", "重启 Core"],
              ["logs", "日志"],
              ["config", "配置摘要"],
              ["models", "模型注册表"],
              ["version", "版本"],
              ["companion_status", "Companion 状态"],
              ["companion_privacy", "观察权限状态"],
              ["companion_stop", "停止 Companion"],
              ["stop", "停止 Core"],
            ].map(([a, t]) => (
              <button
                className="secondary"
                disabled={management || !profile.cli}
                key={a}
                onClick={() => manage(a)}
              >
                {a === "doctor" ? (
                  <Activity size={13} />
                ) : a.includes("stop") ? (
                  <Square size={11} />
                ) : (
                  <Power size={13} />
                )}{" "}
                {t}
              </button>
            ))}
          </div>
          {diagnostic && (
            <>
              <Pretty value={diagnostic} />
            </>
          )}
        </div>
      </details>
      {error && (
        <p className="form-error" role="alert">
          {error}
        </p>
      )}
    </Modal>
  );
}
