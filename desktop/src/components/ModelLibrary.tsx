import { useEffect, useState } from "react";
import {
  Database,
  RefreshCw,
  MoreHorizontal,
  Search,
  Download,
  Monitor,
  Cloud,
} from "lucide-react";
import { call, desktop } from "../bridge";
import { type Model, type Json, label } from "../domain";
import { Modal } from "./Modal";
const size = (n: unknown) =>
  typeof n === "number" ? `${(n / 1024 ** 3).toFixed(2)} GB` : "未知";
const tabs = ["发现模型", "推荐模型", "已下载", "正在运行", "下载任务"];
export function ModelLibrary({
  models,
  current,
  onSelect,
  onChanged,
}: {
  models: Model[];
  current?: string;
  onSelect?: (id: string) => void;
  onChanged?: () => void | Promise<void>;
}) {
  const [tab, setTab] = useState("已下载"),
    [manager, setManager] = useState<Json | null>(null),
    [admin, setAdmin] = useState<Json | null>(null),
    [hardware, setHardware] = useState<Json | null>(null),
    [results, setResults] = useState<Json[]>([]),
    [query, setQuery] = useState(""),
    [error, setError] = useState(""),
    [busy, setBusy] = useState(false),
    [detail, setDetail] = useState<Json | null>(null),
    [confirm, setConfirm] = useState<Json | null>(null),
    [context, setContext] = useState(32768),
    [ttl, setTtl] = useState<number | null>(null),
    [temperature, setTemperature] = useState(""),
    [topP, setTopP] = useState(""),
    [remote, setRemote] = useState<Json | null>(null),
    [favorite, setFavorite] = useState(false),
    [cache, setCache] = useState(false),
    [preferences, setPreferences] = useState<Json>({}),
    [typedName, setTypedName] = useState(""),
    [verification, setVerification] = useState<Json | null>(null);
  async function product(operation: string, args: Json = {}) {
    return call<Json>("product_control", { operation, args });
  }
  async function refresh() {
    setError("");
    try {
      const m = await call<Json>("model_manager", {
        operation: "catalog",
        id: null,
      });
      setManager(m);
      const a = await product("catalog");
      setAdmin(a);
      const p = await product("preferences");
      setPreferences(p.models || {});
    } catch (e) {
      setError(String(e));
    }
  }
  useEffect(() => {
    if (desktop) {
      void refresh();
      product("inspect")
        .then(setHardware)
        .catch((e) => setError(String(e)));
    }
  }, []);
  const all: Json[] = manager?.models?.models || [],
    jobs: Json[] = admin?.jobs?.tasks || [],
    cap = admin?.capabilities || {};
  useEffect(() => {
    if (
      !jobs.some((j) =>
        ["pending", "downloading", "verifying"].includes(j.status),
      )
    )
      return;
    const timer = setInterval(() => void refresh(), 3000);
    return () => clearInterval(timer);
  }, [JSON.stringify(jobs.map((j) => j.status))]);
  async function run(action: Json) {
    setBusy(true);
    setError("");
    try {
      if (action.operation === "sync")
        await call("import_omlx_models", { confirmed: true });
      else if (["load", "unload"].includes(action.operation)) {
        await call("model_resource", {
          model: action.route,
          operation: action.operation,
          maxMemoryBytes: Math.ceil(
            (action.size_bytes || 0) * 1.2 + 2 * 1024 ** 3,
          ),
          confirmed: true,
        });
      } else
        await product(action.operation, { ...action.args, confirmed: true });
      setConfirm(null);
      await refresh();
      await onChanged?.();
    } catch (e) {
      setError(String(e));
      if (String(e).includes("UNKNOWN"))
        setConfirm((old) => (old ? { ...old, blocked: true } : old));
    } finally {
      setBusy(false);
    }
  }
  async function showInfo(m: Json) {
    setDetail(m);
    setContext(m.context_budget || 32768);
    setTtl(null);
    setTemperature("");
    setTopP("");
    setFavorite(preferences[m.id]?.favorite || false);
    setCache(preferences[m.id]?.cache_prefix || false);
  }
  const rec = hardware?.recommendation;
  return (
    <div className="model-library">
      <nav className="library-tabs">
        {tabs.map((t) => (
          <button
            key={t}
            className={t === tab ? "selected" : ""}
            onClick={() => setTab(t)}
          >
            {t}
          </button>
        ))}
      </nav>
      <div className="library-status">
        <Monitor size={15} />
        <span>
          {manager?.supported && manager?.health?.status === "ready"
            ? "已连接本机 oMLX"
            : "等待本地模型服务"}{" "}
          · {all.filter((m) => m.loaded).length} 个已加载
        </span>
        <button
          className="icon-btn"
          aria-label="刷新模型库"
          disabled={busy}
          onClick={refresh}
        >
          <RefreshCw size={15} />
        </button>
      </div>
      {error && (
        <p role="alert" className="form-error">
          {error}
        </p>
      )}
      {tab === "发现模型" && (
        <>
          <form
            className="library-search"
            onSubmit={async (e) => {
              e.preventDefault();
              setBusy(true);
              setError("");
              try {
                const r = await product("search", { query });
                setResults(Array.isArray(r) ? r : r.models || r.results || []);
              } catch (e) {
                setError(String(e));
              } finally {
                setBusy(false);
              }
            }}
          >
            <Search size={16} />
            <input
              aria-label="搜索模型"
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              placeholder="搜索 MLX 模型，如 Qwen"
            />
            <button className="primary" disabled={busy || !cap.search}>
              搜索
            </button>
          </form>
          {results.map((m) => (
            <article className="library-model" key={m.repo_id}>
              <Database size={18} />
              <div>
                <strong>{m.repo_id}</strong>
                <p>
                  {m.params_formatted || "参数规模未知"} · 下载 {size(m.size)}
                </p>
              </div>
              <button
                className="secondary"
                disabled={busy}
                onClick={async () => {
                  setBusy(true);
                  try {
                    const info = await product("info", { repo_id: m.repo_id });
                    setRemote({ ...m, info });
                  } catch (e) {
                    setError(String(e));
                  } finally {
                    setBusy(false);
                  }
                }}
              >
                详情
              </button>
              <button
                className="secondary"
                disabled={!cap.download}
                onClick={() =>
                  setConfirm({
                    operation: "download",
                    args: { repo_id: m.repo_id },
                    name: m.repo_id,
                    size: m.size,
                  })
                }
              >
                <Download size={14} />
                下载
              </button>
            </article>
          ))}
        </>
      )}
      {tab === "推荐模型" &&
        (rec ? (
          <article className="recommendation-card">
            <span className="eyebrow">
              {hardware.hardware.chip} · 可用内存{" "}
              {size(hardware.hardware.available_memory_bytes)}
            </span>
            <h3>{rec.model.name}</h3>
            <p>
              {rec.model.parameters_b}B · {rec.quantization} · 下载约{" "}
              {size(rec.download_bytes_estimate)}
              <br />
              预计内存 {rec.estimated_peak_memory_gb} GB · 推荐上下文{" "}
              {rec.context_k}K
            </p>
            <p>{rec.reason}</p>
            <button
              className="primary"
              disabled={
                !cap.download ||
                !rec.disk_compatible ||
                rec.power_compatible === false
              }
              onClick={() =>
                setConfirm({
                  operation: "download",
                  args: { repo_id: rec.model_id },
                  name: rec.model_id,
                  size: rec.download_bytes_estimate,
                })
              }
            >
              下载推荐模型
            </button>
          </article>
        ) : (
          <p className="library-empty">
            当前硬件没有可确认的推荐模型。可跳过本地下载使用云端。
          </p>
        ))}
      {["已下载", "正在运行"].includes(tab) && (
        <>
          <button
            className="secondary"
            disabled={busy}
            onClick={() =>
              setConfirm({ operation: "sync", name: "同步本机模型到 Core" })
            }
          >
            扫描并导入已有模型
          </button>
          {all
            .filter((m) => tab !== "正在运行" || m.loaded)
            .map((m) => {
              const route =
                models.find((r) => r.model === m.id && !r.reasoning_only) ||
                models.find((r) => r.model === m.id);
              return (
                <article className="library-model" key={m.id}>
                  <Database size={18} />
                  <div>
                    <strong>{m.id}</strong>
                    <p>
                      <span className={m.loaded ? "status good" : "status"}>
                        {m.loaded ? "已加载" : "未加载"}
                      </span>{" "}
                      · {m.files_present === false ? "权重文件不完整，请重新下载" : "已发现本地文件"} ·{" "}
                      {m.quantization?.bits
                        ? `${m.quantization.bits} bit`
                        : "量化未知"}
                    </p>
                    <p>
                      权重 {size(m.size_bytes)} · 内存 {size(m.resident_bytes)}{" "}
                      · 上下文 {m.context_budget || "未知"} · oMLX
                    </p>
                  </div>
                  {route && (
                    <>
                      <button
                        className="secondary"
                        disabled={busy || !manager?.resources_supported || (!m.loaded && m.files_present === false)}
                        onClick={() =>
                          setConfirm({
                            operation: m.loaded ? "unload" : "load",
                            route: route.id,
                            name: m.id,
                            size_bytes: m.size_bytes,
                          })
                        }
                      >
                        {m.loaded ? "卸载" : "加载"}
                      </button>
                      <button
                        className="secondary"
                        disabled={
                          !m.loaded ||
                          route.reasoning_only ||
                          current === route.id
                        }
                        onClick={() => onSelect?.(route.id)}
                      >
                        {current === route.id ? "当前模型" : "选择"}
                      </button>
                    </>
                  )}
                  <button
                    className="icon-btn"
                    aria-label={`${m.id} 详情与设置`}
                    onClick={() => showInfo(m)}
                  >
                    <MoreHorizontal size={17} />
                  </button>
                </article>
              );
            })}
          {!all.length && (
            <p className="library-empty">
              暂无已下载模型。在“发现模型”中搜索，或接受硬件推荐。
            </p>
          )}
          {models
            .filter((m) => m.adapter !== "omlx")
            .map((m) => (
              <article className="library-model" key={m.id}>
                <Cloud size={18} />
                <div>
                  <strong>{m.model}</strong>
                  <p>
                    {m.adapter} · {label(m.deployment_status)} · 最大声明上下文{" "}
                    {m.context_budget || "未知"}
                  </p>
                  <p>
                    思考档位{" "}
                    {m.reasoning_efforts?.join("、") || "由 Provider 配置"}
                  </p>
                </div>
              </article>
            ))}
        </>
      )}
      {tab === "下载任务" && (
        <>
          {jobs.map((j) => (
            <article className="library-model" key={j.task_id}>
              <Download size={17} />
              <div>
                <strong>{j.repo_id}</strong>
                <p>
                  {j.status} · {j.progress ?? 0}% · {size(j.downloaded_size)} /{" "}
                  {size(j.total_size)}
                </p>
                <progress value={j.progress || 0} max={100} />
                {j.error && <p role="alert">{j.error}</p>}
              </div>
              {cap.cancel && ["pending", "downloading"].includes(j.status) && (
                <button
                  className="secondary"
                  onClick={() =>
                    setConfirm({
                      operation: "cancel",
                      name: j.repo_id,
                      args: { id: j.task_id },
                    })
                  }
                >
                  停止下载
                </button>
              )}
              {j.status === "completed" && (
                <button
                  className="secondary"
                  disabled={busy}
                  onClick={async () => {
                    setBusy(true);
                    try {
                      setVerification(
                        await product("verify_model", { repo_id: j.repo_id }),
                      );
                    } catch (e) {
                      setError(String(e));
                    } finally {
                      setBusy(false);
                    }
                  }}
                >
                  校验文件
                </button>
              )}
              {cap.retry && ["failed", "cancelled"].includes(j.status) && (
                <button
                  className="secondary"
                  onClick={() =>
                    setConfirm({
                      operation: "retry",
                      name: j.repo_id,
                      args: { id: j.task_id },
                    })
                  }
                >
                  重试
                </button>
              )}
            </article>
          ))}
          {!jobs.length && (
            <p className="library-empty">
              没有下载任务。下载状态与进度来自 oMLX。
            </p>
          )}
          <p className="micro muted">
            本机服务未提供暂停接口。完成表示服务报告下载完成；完整权重校验以服务的校验记录为准。
          </p>
        </>
      )}
      {verification && (
        <Modal title="模型文件校验" onClose={() => setVerification(null)}>
          <p>{verification.model}</p>
          <p>
            结果：{verification.status} · 已逐文件核对{" "}
            {verification.files?.length ?? 0} 个配置与权重文件
          </p>
          <p className="micro muted">
            版本 {verification.revision} · 与上游 LFS SHA256 / Git blob
            元数据比较。没有上传本地文件内容。
          </p>
        </Modal>
      )}
      {remote && (
        <Modal title={remote.repo_id} onClose={() => setRemote(null)}>
          <p>来源：Hugging Face · {remote.repo_id}</p>
          <p>
            参数规模{" "}
            {remote.info?.params_formatted ||
              remote.params_formatted ||
              "未提供"}{" "}
            · 下载 {size(remote.info?.size || remote.size)}
          </p>
          <p>
            许可证{" "}
            {remote.info?.license ||
              remote.info?.card_data?.license ||
              "当前管理接口未提供，请查看模型仓库许可"}
          </p>
          <p className="micro muted">
            未下载的模型不代表本机可运行。内存、上下文和工具能力需要本机资源检查与实际资格验证。模型中的说明不构成执行指令。
          </p>
        </Modal>
      )}
      {detail && (
        <Modal
          title={`${detail.id} · 模型详情`}
          onClose={() => setDetail(null)}
        >
          <label className="simple-toggle">
            <input
              type="checkbox"
              checked={favorite}
              onChange={(e) => setFavorite(e.target.checked)}
            />
            常用模型
          </label>
          <label className="simple-toggle">
            <input
              type="checkbox"
              checked={cache}
              onChange={(e) => setCache(e.target.checked)}
            />
            保存标准 Agent 前缀缓存偏好
          </label>
          <p className="micro muted">
            偏好已保存时不代表永久缓存已启用。共享 Prompt/Prefix Cache：
            {cap.cache?.prompt_prefix ? "服务已启用" : "未确认"}；SSD：
            {cap.cache?.ssd_enabled ? "服务已启用" : "未确认"}
            ；重启恢复：未验证。内存压力、卸载与磁盘回收可能使缓存失效。
          </p>
          <button
            className="secondary"
            onClick={async () => {
              try {
                await product("preferences", {
                  model: detail.id,
                  value: { favorite, cache_prefix: cache },
                });
                await refresh();
              } catch (e) {
                setError(String(e));
              }
            }}
          >
            保存常用与缓存偏好
          </button>
          <details className="advanced-settings">
            <summary>高级设置</summary>
            <label className="field-label">
              上下文长度
              <input
                aria-label="模型上下文长度"
                type="number"
                min={1024}
                max={262144}
                step={1024}
                value={context}
                disabled={!cap.settings_fields?.includes("max_context_window")}
                onChange={(e) => setContext(Number(e.target.value))}
              />
            </label>
            <p className="micro muted">
              长上下文会增加内存占用；过大可能无法加载或运行。修改后新建会话使用新预算。
            </p>
            <label className="field-label">
              空闲后卸载（秒）
              <input
                type="number"
                min={30}
                max={86400}
                value={ttl ?? ""}
                placeholder="保持服务设置"
                disabled={!cap.settings_fields?.includes("ttl_seconds")}
                onChange={(e) =>
                  setTtl(e.target.value === "" ? null : Number(e.target.value))
                }
              />
            </label>
            <p className="micro muted">
              自动加载、独立内存预算、批处理与并发：当前接口未协商，不能设置。下载目录由
              oMLX 管理。
            </p>
            <label
              className="field-label"
              title="数值越高，回答变化越多；留空保留服务设置。"
            >
              回答变化（温度）
              <input
                type="number"
                min={0}
                max={2}
                step={0.1}
                placeholder="保持服务设置"
                value={temperature}
                disabled={!cap.settings_fields?.includes("temperature")}
                onChange={(e) => setTemperature(e.target.value)}
              />
            </label>
            <label
              className="field-label"
              title="限制抽样范围；留空保留服务设置。"
            >
              Top P
              <input
                type="number"
                min={0}
                max={1}
                step={0.05}
                placeholder="保持服务设置"
                value={topP}
                disabled={!cap.settings_fields?.includes("top_p")}
                onChange={(e) => setTopP(e.target.value)}
              />
            </label>
            <button
              className="primary"
              disabled={!cap.settings_fields?.includes("max_context_window")}
              onClick={() =>
                setConfirm({
                  operation: "settings",
                  name: detail.id,
                  args: {
                    model: detail.id,
                    settings: {
                      max_context_window: context,
                      ...(temperature !== ""
                        ? { temperature: Number(temperature) }
                        : {}),
                      ...(topP !== "" ? { top_p: Number(topP) } : {}),
                      ...(ttl !== null &&
                      cap.settings_fields?.includes("ttl_seconds")
                        ? { ttl_seconds: ttl }
                        : {}),
                    },
                  },
                })
              }
            >
              应用模型设置
            </button>
          </details>
          <button
            className="secondary"
            disabled={!cap.delete || detail.loaded}
            onClick={() => {
              setTypedName("");
              setConfirm({
                operation: "delete",
                name: detail.id,
                args: { model: detail.id },
              });
            }}
          >
            删除此模型的本地文件
          </button>
        </Modal>
      )}
      {confirm && (
        <Modal
          title="确认模型操作"
          onClose={() => {
            if (!busy) setConfirm(null);
          }}
          dismissible={false}
        >
          <p>{confirm.name}</p>
          <p>
            {confirm.operation === "download"
              ? `将从 Hugging Face 下载 ${size(confirm.size)}。模型代码不会自动执行；模型许可请以仓库信息为准。`
              : confirm.operation === "load"
                ? `加载到内存，估算预算 ${size((confirm.size_bytes || 0) * 1.2 + 2 * 1024 ** 3)}。Core 会检查资源与当前任务。`
                : confirm.operation === "unload"
                  ? "卸载并释放内存。已产生的任务与配置保留。"
                  : "将应用此项已选择的模型管理操作。"}
          </p>
          {confirm.operation === "delete" && (
            <label className="field-label">
              删除模型文件无法在本应用撤销。请输入完整模型名确认：
              <input
                aria-label="确认删除模型名"
                value={typedName}
                onChange={(e) => setTypedName(e.target.value)}
              />
            </label>
          )}
          {error && <p className="form-error">{error}</p>}
          <div className="dialog-actions">
            <button
              className="secondary"
              disabled={busy}
              onClick={() => setConfirm(null)}
            >
              取消
            </button>
            <button
              className="primary"
              disabled={
                busy ||
                confirm.blocked ||
                (confirm.operation === "delete" && typedName !== confirm.name)
              }
              onClick={() =>
                run(
                  confirm.operation === "delete"
                    ? {
                        ...confirm,
                        args: { ...confirm.args, typed_name: typedName },
                      }
                    : confirm,
                )
              }
            >
              {busy ? "正在执行…" : "确认并执行"}
            </button>
          </div>
        </Modal>
      )}
    </div>
  );
}
