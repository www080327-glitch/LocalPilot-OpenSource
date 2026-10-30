import { useEffect, useState, useRef } from "react";
import { Check, RefreshCw, Download, Monitor } from "lucide-react";
import { call, desktop } from "../bridge";
import type { Json } from "../domain";
import {
  ChannelSettings,
  channelLabels,
  channelRequest,
} from "./ChannelSettings";
const gb = (n: any) =>
  typeof n === "number" ? `${(n / 1024 ** 3).toFixed(1)} GB` : "未知";
const readiness = (s?: string) =>
  (
    ({
      ready: "已就绪",
      running: "运行中",
      stopped: "已停止",
      unavailable: "尚未就绪",
      starting: "正在准备",
    }) as Record<string, string>
  )[s || ""] || "正在检测";
export function SetupAssistant({
  onReady,
  onError,
  onBusy,
  onWorkspace,
  onStage,
}: {
  onReady: () => Promise<void>;
  onError: (e: unknown) => void;
  onBusy?: (busy: boolean) => void;
  onWorkspace?: (id: string) => void;
  onStage?: (stage: number) => void;
}) {
  const [stage, setStage] = useState(() => {
    if (desktop) return 0;
    const saved = Number(
      localStorage.getItem("lp.setup.stage") || (desktop ? 0 : 3),
    );
    return Number.isInteger(saved) && saved >= 0 && saved <= 3 ? saved : 0;
  });
  const [stageLoaded, setStageLoaded] = useState(!desktop);
  useEffect(() => {
    if (desktop)
      call<Json>("setup_progress", { stage: null })
        .then((v) => {
          setStage(
            Number.isInteger(v.stage) && v.stage >= 0 && v.stage <= 3
              ? v.stage
              : 0,
          );
          setStageLoaded(true);
        })
        .catch((e) => {
          onError(e);
          setStage(0);
          setStageLoaded(true);
        });
  }, []);
  const [summary, setSummary] = useState<Json>({});
  useEffect(() => {
    if (!stageLoaded) return;
    if (desktop) void call("setup_progress", { stage }).catch(onError);
    else localStorage.setItem("lp.setup.stage", String(stage));
    onStage?.(stage);
    if (stage === 3 && desktop) {
      Promise.all([
        call<Json>("product_control", {
          operation: "installation_diagnostics",
          args: {},
        }),
        channelRequest("qq", "status").catch(() => ({ status: "UNKNOWN" })),
        channelRequest("wechat", "status").catch(() => ({ status: "UNKNOWN" })),
        call<Json>("api", {
          method: "GET",
          path: "/localpilot/v1/model-registry",
          body: null,
        }).catch(() => ({ models: null })),
      ])
        .then(([product, qq, wechat, registry]) =>
          setSummary({ product, qq, wechat, registry }),
        )
        .catch(onError);
    }
  }, [stage, stageLoaded]);
  const [state, setState] = useState<Json | null>(null),
    [busy, setBusy] = useState(""),
    [modelWork, setModelWork] = useState(false),
    [downloadProgress, setDownloadProgress] = useState<number | null>(null),
    [favorite, setFavorite] = useState(true),
    [cache, setCache] = useState(true),
    [status, setStatus] = useState(""),
    [installations, setInstallations] = useState<Json[]>([]),
    [cloudKey, setCloudKey] = useState("");
  useEffect(() => {
    onBusy?.(!!busy && !modelWork);
  }, [busy, modelWork]);
  const alive = useRef(true);
  useEffect(() => {
    alive.current = true;
    return () => {
      alive.current = false;
    };
  }, []);
  async function inspect() {
    setBusy("检测设备");
    try {
      setState(
        await call("product_control", { operation: "inspect", args: {} }),
      );
    } catch (e) {
      onError(e);
    } finally {
      setBusy("");
    }
  }
  useEffect(() => {
    if (desktop) {
      void inspect();
      call<Json>("discover_suites")
        .then((v) => setInstallations(v.installations || []))
        .catch(() => {});
    }
  }, []);
  async function prepare() {
    setBusy("安装独立组件");
    try {
      const prepared = await call<Json>("bootstrap_product", {
        confirmed: true,
      });
      await onReady();
      setStatus(
        prepared.setup?.companion_ready === false
          ? "Core 已连接；Companion 尚未就绪，可在设置中检查。标准 Agent 可以独立使用。"
          : "本机组件已连接。可接受推荐，也可跳过下载直接使用已配置的云端模型。",
      );
      await inspect();
      return true;
    } catch (e) {
      onError(e);
      return false;
    } finally {
      setBusy("");
    }
  }
  const r = state?.recommendation,
    hw = state?.hardware;
  return (
    <section className="setup-assistant">
      <ol className="setup-steps" aria-label="首次设置进度">
        {["欢迎使用", "准备 Agent", "连接消息平台", "完成设置"].map(
          (label, i) => (
            <li
              key={label}
              aria-current={stage === i ? "step" : undefined}
              className={stage === i ? "current" : stage > i ? "done" : ""}
            >
              <span>{i + 1}</span>
              {label}
            </li>
          ),
        )}
      </ol>
      {stage === 0 && (
        <div className="setup-welcome">
          <h3>让 AI 帮你完成电脑上的任务</h3>
          <p>
            选择本地模型或填写 DeepSeek 密钥，即可开始。微信连接可以稍后再做。
          </p>
          <p className="micro muted">
            macOS 15
            或更新版本。已有安装、模型和工作区会保留；需要下载时会单独确认。
          </p>
        </div>
      )}
      {stage < 2 && (
        <>
          <div className="setup-title">
            <Monitor size={18} />
            <strong>
              {(
                {
                  existing: "检测到已有安装",
                  repair_required: "配置不完整 · 需要修复",
                  upgrade_available: "检测到可升级安装",
                  installed_service_stopped: "已安装 · 服务未连接",
                  first_launch: "首次使用 · 准备 LocalPilot",
                } as Record<string, string>
              )[state?.installation] || "正在检测安装状态"}
            </strong>
            <button
              className="icon-btn"
              aria-label="重新检测设备"
              disabled={!!busy}
              onClick={inspect}
            >
              <RefreshCw size={14} />
            </button>
          </div>
          {installations.length > 0 && (
            <details>
              <summary>检测到已有安装 · 可直接连接</summary>
              {installations.map((item, i) => (
                <div className="setting-row" key={i}>
                  <span>{item.label}</span>
                  <button
                    className="secondary"
                    disabled={!!busy}
                    onClick={async () => {
                      setBusy("正在连接已有安装");
                      try {
                        await call("connect_suite", {
                          home: item.home,
                          cli: item.cli,
                        });
                        await onReady();
                        setStatus(
                          "已连接已有服务，没有重复初始化。较旧服务可在设置中更新内置组件。",
                        );
                        await inspect();
                      } catch (e) {
                        onError(e);
                      } finally {
                        setBusy("");
                      }
                    }}
                  >
                    连接此安装
                  </button>
                </div>
              ))}
            </details>
          )}
          {hw && (
            <details className="advanced-settings">
              <summary>高级 · 设备信息</summary>
              <p>
                {hw.chip} · {gb(hw.memory_bytes)} 统一内存 · 当前可用{" "}
                {gb(hw.available_memory_bytes)}
                <br />
                剩余磁盘 {gb(hw.free_disk_bytes)} ·{" "}
                {hw.backends.length ? "已发现 oMLX" : "尚未连接本地推理服务"} ·
                已发现 {hw.models.length} 个模型
              </p>
            </details>
          )}
          {stage === 1 && (
            <>
              {state && !state.omlx_installed && (
                <>
                  <p>
                    本地模型需要 oMLX。下载安装官方 0.7.2（约 0.9
                    GB），核验后安装到个人 Applications。可能需要系统确认。
                  </p>
                  <button
                    className="secondary"
                    disabled={!!busy}
                    onClick={async () => {
                      setBusy("正在下载并校验 oMLX…");
                      try {
                        const x = await call<Json>("product_control", {
                          operation: "install_backend",
                          args: { confirmed: true },
                        });
                        setStatus(x.next || "已检测到安装");
                        await call("product_control", {
                          operation: "initialize_backend",
                          args: { confirmed: true },
                        });
                        await inspect();
                      } catch (e) {
                        onError(e);
                      } finally {
                        setBusy("");
                      }
                    }}
                  >
                    同意下载并安装 oMLX
                  </button>
                </>
              )}
              {state?.omlx_installed && !hw?.backends?.length && (
                <div className="dialog-actions">
                  <button
                    className="secondary"
                    disabled={!!busy}
                    onClick={async () => {
                      setBusy("启动本地推理服务");
                      try {
                        await call("product_control", {
                          operation: "initialize_backend",
                          args: { confirmed: true },
                        });
                        await inspect();
                      } catch (e) {
                        onError(e);
                      } finally {
                        setBusy("");
                      }
                    }}
                  >
                    启动本地推理服务
                  </button>
                  <button
                    className="text-btn"
                    disabled={!!busy}
                    onClick={() => call("open_omlx_setup").catch(onError)}
                  >
                    打开 oMLX
                  </button>
                </div>
              )}
              <button className="primary" disabled={!!busy} onClick={prepare}>
                {busy ||
                  (state?.core_configured
                    ? "连接 LocalPilot"
                    : "准备 LocalPilot")}
              </button>
              <div className="setup-cloud">
                <h3>使用 DeepSeek</h3>
                <input
                  aria-label="首次设置 DeepSeek API 密钥"
                  type="password"
                  autoComplete="off"
                  placeholder="DeepSeek API 密钥"
                  value={cloudKey}
                  onChange={(e) => setCloudKey(e.target.value)}
                />
                <button
                  className="secondary"
                  disabled={!!busy || !cloudKey}
                  onClick={async () => {
                    if (!(await prepare())) return;
                    setBusy("连接云端配置");
                    try {
                      await call("configure_cloud_key", {
                        key: cloudKey,
                        confirmed: true,
                      });
                      setCloudKey("");
                      await onReady();
                      setStatus("云端配置已保存。发送任务时再确认云端授权。");
                    } catch (e) {
                      onError(e);
                    } finally {
                      setBusy("");
                    }
                  }}
                >
                  保存并连接
                </button>
                <p className="micro muted">
                  密钥仅保存到本机私有目录，添加配置不会发送任务。
                </p>
              </div>
              <details className="advanced-settings">
                <summary>高级 · 工作文件夹</summary>
                <button
                  className="secondary"
                  disabled={!!busy}
                  onClick={async () => {
                    if (!(await prepare())) return;
                    try {
                      const grant = await call("pick_workspace", {
                        scope: "modify",
                        cloudPaths: [],
                      });
                      if (grant) {
                        onWorkspace?.(grant.id);
                        setStatus("文件夹授权已保存；云端文件范围需另行批准。");
                      }
                    } catch (e) {
                      onError(e);
                    }
                  }}
                >
                  选择工作文件夹…
                </button>
              </details>
              {r && (
                <article className="recommendation-card">
                  <span className="eyebrow">使用本地模型 · 推荐</span>
                  <h3>{r.model.name}</h3>
                  <p>
                    首次下载约 {gb(r.download_bytes_estimate)}
                    ；已有完整模型会直接使用。
                  </p>
                  <details className="advanced-settings">
                    <summary>高级 · 模型与缓存</summary>
                    <p>
                      预计内存 {r.estimated_peak_memory_gb} GB · 上下文{" "}
                      {r.context_k}K
                    </p>
                    <label className="simple-toggle">
                      <input
                        type="checkbox"
                        checked={favorite}
                        onChange={(e) => setFavorite(e.target.checked)}
                      />
                      将此模型设为常用模型
                    </label>
                    <label className="simple-toggle">
                      <input
                        type="checkbox"
                        checked={cache}
                        onChange={(e) => setCache(e.target.checked)}
                      />
                      为常用模型保存标准 Agent 前缀缓存偏好
                    </label>
                    <p className="micro muted">
                      可在设置中修改。oMLX 使用共享前缀及 SSD
                      缓存；当前无法单独控制每个模型的缓存，卸载、空间回收和服务重启后的保留效果未经验证。
                    </p>
                  </details>
                  <div className="dialog-actions">
                    <button
                      className="secondary"
                      onClick={() =>
                        setStatus(
                          "已跳过模型下载。完成向导后可使用云端或已有模型。",
                        )
                      }
                    >
                      跳过，稍后自行选择
                    </button>
                    <button
                      className="primary"
                      disabled={
                        !!busy ||
                        !r.disk_compatible ||
                        r.power_compatible === false
                      }
                      onClick={async () => {
                        setModelWork(true);
                        setDownloadProgress(null);
                        setBusy("准备本地模型");
                        try {
                          if (!(await prepare())) return;
                          if (!hw.backends?.length) {
                            setBusy("启动本地推理服务");
                            await call("product_control", {
                              operation: "initialize_backend",
                              args: { confirmed: true },
                            });
                            await call("bootstrap_product", {
                              confirmed: true,
                            });
                          }
                          const known = hw.models.some(
                            (m: Json) =>
                              m.source_repo_id === r.model_id ||
                              m.id === r.model_id.replace("/", "--") ||
                              m.id === r.model_id.split("/").at(-1),
                          );
                          if (!known) {
                            const queued = await call<Json>("product_control", {
                              operation: "download",
                              args: { repo_id: r.model_id, confirmed: true },
                            });
                            const taskId = queued.task?.task_id;
                            if (!taskId)
                              throw Error(
                                "服务没有返回下载任务 ID，请在模型库核对状态。未自动重试。",
                              );
                            while (alive.current) {
                              setBusy("下载推荐模型…");
                              await new Promise((resolve) =>
                                setTimeout(resolve, 2500),
                              );
                              const observed = await call<Json>(
                                "product_control",
                                {
                                  operation: "catalog",
                                  args: {},
                                },
                              );
                              const job = observed.jobs?.tasks?.find(
                                (j: Json) => j.task_id === taskId,
                              );
                              if (!job)
                                throw Error(
                                  "下载状态未确认，请在模型库核对。未自动重试。",
                                );
                              setDownloadProgress(
                                typeof job.progress === "number"
                                  ? job.progress
                                  : null,
                              );
                              setStatus(
                                `模型下载 ${job.progress ?? "待确认"}% · ${job.status}`,
                              );
                              if (job.status === "completed") break;
                              if (["failed", "cancelled"].includes(job.status))
                                throw Error(
                                  job.error ||
                                    "下载已停止，请在模型库查看并重试。",
                                );
                            }
                            if (!alive.current) return;
                          }
                          setBusy("应用推荐配置并加载模型…");
                          await call("import_omlx_models", { confirmed: true });
                          const catalog = await call<Json>("api", {
                            method: "GET",
                            path: "/localpilot/v1/model-registry",
                            body: null,
                          });
                          const route = catalog.models?.find(
                            (m: Json) =>
                              !m.reasoning_only &&
                              (m.model === r.model_id.replace("/", "--") ||
                                m.model === r.model_id.split("/").at(-1)),
                          );
                          if (!route)
                            throw Error(
                              "下载已完成，但未找到可用的 Agent 路由。请在模型库扫描导入。",
                            );
                          // Full upstream hashing is available in Model Library; do not
                          // block first setup on a network lookup and multi-GB hash pass.
                          // Core load still checks that required local weights exist.
                          setDownloadProgress(null);
                          setBusy("正在加载本地模型（首次可能需要一些时间）…");
                          const capabilities = await call<Json>(
                            "product_control",
                            {
                              operation: "capabilities",
                              args: {},
                            },
                          );
                          if (
                            capabilities.settings_fields?.includes(
                              "max_context_window",
                            )
                          )
                            await call("product_control", {
                              operation: "settings",
                              args: {
                                model: route.model,
                                settings: {
                                  max_context_window: r.context_length,
                                },
                                confirmed: true,
                              },
                            });
                          await call("product_control", {
                            operation: "preferences",
                            args: {
                              model: route.model,
                              value: { favorite, cache_prefix: cache },
                            },
                          });
                          await call("model_resource", {
                            model: route.id,
                            operation: "load",
                            maxMemoryBytes: Math.ceil(
                              r.estimated_peak_memory_gb * 1024 ** 3,
                            ),
                            confirmed: true,
                          });
                          await onReady();
                          setStatus("本地模型已加载，可以开始使用。");
                        } catch (e) {
                          onError(e);
                        } finally {
                          setBusy("");
                          setModelWork(false);
                          setDownloadProgress(null);
                        }
                      }}
                    >
                      <Download size={14} />
                      使用推荐模型
                    </button>
                  </div>
                </article>
              )}
              {!r && state && (
                <p className="micro muted">
                  当前没有同时满足可用内存与 Core 主 Agent
                  上下文要求的本地建议。你可以跳过下载，稍后在模型库选择，或连接云端模型。
                </p>
              )}
              {!r && (
                <button
                  className="secondary"
                  onClick={() => setStatus("已跳过模型下载。可继续完成设置。")}
                >
                  跳过，稍后自行选择
                </button>
              )}
            </>
          )}
        </>
      )}
      {stage === 2 && <ChannelSettings onError={onError} onboarding />}
      {stage === 3 && (
        <div className="setup-completion">
          <h3>准备好了，开始使用</h3>
          <p>模型和微信都可以稍后在设置中调整。</p>
          <details>
            <summary>高级 · 查看组件状态</summary>
            <div className="setup-summary">
              <p>
                Core{" "}
                <strong>
                  {readiness(summary.product?.services?.core?.status)}
                </strong>
              </p>
              <p>
                Companion{" "}
                <strong>
                  {readiness(summary.product?.services?.companion?.status)}
                </strong>
              </p>
              <p>
                模型{" "}
                <strong>
                  {summary.registry?.models === null
                    ? "模型状态尚未确认，请在模型库检查"
                    : summary.registry?.models?.some(
                          (m: Json) =>
                            m.model &&
                            m.model !== "not-selected" &&
                            m.adapter !== "unavailable" &&
                            m.deployment_status !== "not_deployed",
                        )
                      ? "已配置模型路由，推理可用性仍需测试"
                      : "未配置模型，可稍后设置"}
                </strong>
              </p>
              <p>
                QQ{" "}
                <strong>
                  {channelLabels[summary.qq?.status] || "尚未确认"}
                </strong>
              </p>
              <p>
                微信{" "}
                <strong>
                  {channelLabels[summary.wechat?.status] || "尚未确认"}
                </strong>
              </p>
            </div>
          </details>
          <p>
            渠道可选。模型缺失时任务会明确提示配置，平台授权未完成时不会显示已连接。
          </p>
        </div>
      )}
      <div className="dialog-actions setup-navigation">
        {stage > 0 && (
          <button
            className="secondary"
            disabled={!!busy && !modelWork}
            onClick={() => setStage(stage - 1)}
          >
            上一步
          </button>
        )}
        {stage < 3 && (
          <button
            className="primary"
            disabled={
              (!!busy && !modelWork) ||
              (desktop && stage === 1 && !state?.core_configured)
            }
            onClick={() => setStage(stage + 1)}
          >
            {
              ["开始准备 Agent", "继续 · 连接消息平台", "继续 · 核对完成状态"][
                stage
              ]
            }
          </button>
        )}
      </div>
      {busy && (
        <aside className="setup-transfer" role="status" aria-live="polite">
          <strong>{busy}</strong>
          {downloadProgress !== null ? (
            <>
              <progress max={100} value={downloadProgress} />
              <span>{downloadProgress.toFixed(1)}%</span>
            </>
          ) : (
            <progress aria-label={busy} />
          )}
          <p>
            {modelWork
              ? "可以继续下一步。进度会保留在这里，请保持此窗口打开。"
              : "正在准备，请稍候。"}
          </p>
        </aside>
      )}
      {status && (
        <p className="setup-status">
          <Check size={14} />
          {status}
        </p>
      )}
    </section>
  );
}
