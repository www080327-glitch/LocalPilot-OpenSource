import { useEffect, useState } from "react";
import { call, desktop } from "../bridge";
import { compatible, type Json } from "../domain";

const date = (v?: number) =>
  v ? new Date(v * 1000).toLocaleString() : "本次启动尚未检查";
const bytes = (v?: number) => `${((v || 0) / 1024 / 1024).toFixed(1)} MB`;
const labels: Record<string, string> = {
  UNKNOWN: "UNKNOWN · 无法确认",
  CURRENT: "与正式 GUI Release 相同",
  LOCAL_AHEAD: "本地维护版本领先于正式 Release",
  UPDATE_AVAILABLE: "有可用 GUI 更新",
};

export function VersionManagement({
  health,
  cliReady,
}: {
  health: Json | null;
  cliReady: boolean;
}) {
  const [installation, setInstallation] = useState<Json | null>(null);
  const [release, setRelease] = useState<Json | null>(null);
  const [modules, setModules] = useState<Json | null>(null);
  const [scan, setScan] = useState<Json | null>(null);
  const [verified, setVerified] = useState<Json | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [notes, setNotes] = useState(false);
  const [guide, setGuide] = useState(false);
  useEffect(() => {
    if (desktop)
      call<Json>("desktop_installation")
        .then((v) => {
          setInstallation(v);
          if (v.last_check?.checked_at) setRelease(v.last_check);
        })
        .catch((e) => setError(String(e)));
  }, []);
  useEffect(() => {
    setModules(null);
  }, [cliReady]);
  async function action(fn: () => Promise<void>) {
    setBusy(true);
    setError("");
    try {
      await fn();
    } catch (e) {
      setError(String(e));
    } finally {
      setBusy(false);
    }
  }
  async function check(authenticated: boolean) {
    await action(async () => {
      setVerified(null);
      setRelease(await call("desktop_update_check", { authenticated }));
    });
  }
  return (
    <section
      className="version-management"
      aria-labelledby="version-management-title"
    >
      <h3 id="version-management-title">版本更新与存储管理</h3>
      <p className="micro muted">
        GUI 独立更新。Core、Companion、Suite
        使用下方各自的升级计划。点击检查才连接 GitHub；没有后台更新或清理。
      </p>
      <dl className="version-facts">
        <div>
          <dt>当前 GUI</dt>
          <dd>
            {installation?.version ||
              (desktop ? "读取中" : "浏览器预览 · 原生版本不可用")}
          </dd>
        </div>
        <div>
          <dt>最新正式 GUI Release</dt>
          <dd>
            {release?.status === "UNKNOWN"
              ? "UNKNOWN"
              : release?.version || "UNKNOWN · 尚未检查"}
          </dd>
        </div>
        <div>
          <dt>当前 Core 服务</dt>
          <dd>{health?.version || "UNKNOWN · 未连接"}</dd>
        </div>
        <div>
          <dt>已安装 Core</dt>
          <dd>
            {modules?.["localpilot-agent-service"] ||
              "UNKNOWN · 请读取模块版本"}
          </dd>
        </div>
        <div>
          <dt>已安装 Companion</dt>
          <dd>
            {modules?.["localpilot-companion"] || "UNKNOWN · 请读取模块版本"}
          </dd>
        </div>
        <div>
          <dt>已安装 Suite</dt>
          <dd>{modules?.suite || "UNKNOWN · 请读取模块版本"}</dd>
        </div>
        <div>
          <dt>API 兼容状态</dt>
          <dd>
            {health
              ? compatible(health)
                ? `兼容 · Agent Service ${health.compatibility?.agent_service_api || "UNKNOWN"}`
                : "不兼容 · 请检查服务契约"
              : "UNKNOWN · 未连接"}
          </dd>
        </div>
        <div>
          <dt>最后检查时间</dt>
          <dd>{date(release?.checked_at)}</dd>
        </div>
        <div>
          <dt>当前安装位置</dt>
          <dd className="installation-path">
            {installation?.executable || "UNKNOWN"}
          </dd>
        </div>
      </dl>
      {installation?.build && (
        <p className="micro muted">{installation.build}</p>
      )}
      <div className="management-actions">
        <button
          className="secondary"
          disabled={!desktop || busy}
          onClick={() => check(false)}
        >
          检查 GUI 更新
        </button>
        <button
          className="secondary"
          disabled={!desktop || busy}
          onClick={() => check(true)}
        >
          使用本机 GitHub 登录检查
        </button>
        <button
          className="secondary"
          disabled={!desktop || busy || !cliReady}
          onClick={() =>
            action(async () => {
              setModules(null);
              const v = await call<Json>("lifecycle", { action: "version" });
              if (v.exit !== 0 || !v.result?.[0]?.suite)
                throw new Error("模块版本读取失败 · UNKNOWN");
              setModules(v.result[0]);
            })
          }
        >
          读取已安装模块版本
        </button>
        <button
          className="text-btn"
          disabled={!desktop || busy}
          onClick={() =>
            action(async () => {
              await call("desktop_open_release", { asset: null });
            })
          }
        >
          打开 GitHub Release
        </button>
        <button
          className="text-btn"
          disabled={!release?.notes}
          onClick={() => setNotes(!notes)}
        >
          查看更新日志
        </button>
        <button className="text-btn" onClick={() => setGuide(!guide)}>
          手动更新指引
        </button>
      </div>
      <p className="micro muted">
        私有仓库需要本机已安装并登录 GitHub
        CLI。只有点击登录检查才调用现有登录；Token 不传给页面。
      </p>
      {busy && <p role="status">正在读取，请稍候…</p>}
      {release && (
        <div
          className={
            release.status === "UNKNOWN"
              ? "version-notice error"
              : "version-notice"
          }
          role="status"
        >
          <strong>{labels[release.status] || release.status}</strong>
          <p>{release.error || `已读取 ${release.tag} · ${release.source}`}</p>
        </div>
      )}
      {error && (
        <p className="version-notice error" role="alert">
          {error}
        </p>
      )}
      {notes && release?.notes && (
        <pre className="release-notes">{release.notes}</pre>
      )}
      {release && release.assets?.length > 0 && (
        <div className="release-assets">
          <p className="micro">
            从本次 Release
            下载；下载由系统浏览器处理。安装前选择文件进行原生只读校验。
          </p>
          {release.assets.map((a: Json) => (
            <div key={a.name}>
              <button
                className="text-btn"
                disabled={busy}
                onClick={() =>
                  action(async () => {
                    await call("desktop_open_release", { asset: a.name });
                  })
                }
              >
                {a.name} · {bytes(a.bytes)}
              </button>
              <code className="asset-hash">
                SHA256: {a.sha256 || "UNKNOWN · 无法验证"}
              </code>
            </div>
          ))}
          <button
            className="secondary"
            disabled={busy}
            onClick={() =>
              action(async () => {
                setVerified(null);
                setVerified(await call("desktop_verify_archive"));
              })
            }
          >
            校验已下载的 GUI 安装包
          </button>
        </div>
      )}
      {verified && (
        <div className="version-notice" role="status">
          <strong>安装包 SHA256 验证通过</strong>
          <p>{verified.path}</p>
          <p>{verified.guidance}</p>
        </div>
      )}
      {guide && (
        <div className="manual-update-guide">
          <ol>
            <li>
              成功检查 GUI Release，打开官方页面下载适合当前 Mac
              的安装包。当前构建只验证 macOS arm64。
            </li>
            <li>
              在本页选择安装包，核对 GitHub 提供的 SHA256 与大小。缺少 digest
              或校验失败时停止安装。
            </li>
            <li>
              解包后在可信终端运行{" "}
              <code>
                codesign --verify --deep --strict /path/to/LocalPilot.app
              </code>
              。当前正式版为 ad-hoc
              签名、未公证；这不证明开发者身份，勿绕过系统安全设置。
            </li>
            <li>
              退出要替换的 GUI，保存当前 APP 作为回滚副本，再用 Finder
              将新版复制到 Applications。服务、任务和用户数据保持独立。
            </li>
            <li>
              重新打开并检查版本、连接与会话。失败时退出新版并恢复旧
              APP。不要替换 Core/Companion/Suite，不要清除 Application
              Support、配置或数据库。
            </li>
          </ol>
        </div>
      )}
      <h4>存储与历史版本</h4>
      <div className="management-actions">
        <button
          className="secondary"
          disabled={!desktop || busy}
          onClick={() =>
            action(async () => {
              setScan(await call("desktop_storage_scan"));
            })
          }
        >
          扫描历史版本与重复 APP（只读）
        </button>
      </div>
      <p className="micro muted">
        扫描 Applications、Downloads 与明确的 Desktop 发行/Bundle 目录。只核对
        LocalPilot Desktop 身份；范围和遗漏会显示。此页面没有删除权限。
      </p>
      {scan && (
        <div className="storage-results">
          <p>
            最后扫描：{date(scan.scanned_at)} · 待人工审核空间{" "}
            {bytes(scan.review_candidate_bytes)} · 已授权清理空间 0 MB
          </p>
          <p className="micro">
            {scan.scope}。可执行文件相同不代表整个 APP 完全相同，候选仍需核对
            bundle 与流程引用。最新安装包、符号链接、运行中的
            APP、源码和未知文件受保护。
          </p>
          {scan.warnings.map((s: string) => (
            <p className="version-notice error" key={s}>
              {s}
            </p>
          ))}
          <details>
            <summary>扫描路径白名单</summary>
            <ul>
              {scan.roots.map((p: string) => (
                <li key={p}>
                  <code>{p}</code>
                </li>
              ))}
            </ul>
          </details>
          <details open>
            <summary>历史版本与受保护文件（{scan.items.length}）</summary>
            <ul className="storage-items">
              {scan.items.map((i: Json) => (
                <li key={i.path}>
                  <strong>
                    {i.version || "版本 UNKNOWN"} · {i.kind} ·{" "}
                    {i.running ? "运行中 · " : ""}
                    {i.review_candidate ? "待确认候选" : "受保护"} ·{" "}
                    {bytes(i.allocated_bytes)}
                  </strong>
                  <code>{i.path}</code>
                  <p>
                    {i.bundle_id || "非 APP：仅按文件名发现，需哈希确认"} ·{" "}
                    {i.reason}
                  </p>
                  {i.signature && (
                    <p>
                      Code Signature:{" "}
                      {i.signature.verified ? "有效" : "UNKNOWN / 无效"}
                    </p>
                  )}
                  {i.sha256 && <code>SHA256 {i.sha256}</code>}
                  {i.executable_sha256 && (
                    <code>可执行文件 SHA256 {i.executable_sha256}</code>
                  )}
                  {i.release_asset && <p>已匹配本次正式 Release 制品哈希</p>}
                </li>
              ))}
            </ul>
          </details>
          <details>
            <summary>待清理文件清单（dry-run，不执行删除）</summary>
            <ul>
              {scan.items
                .filter((i: Json) => i.review_candidate)
                .map((i: Json) => (
                  <li key={i.path}>
                    <code>{i.path}</code> · {bytes(i.allocated_bytes)} ·
                    需单独确认
                  </li>
                ))}
            </ul>
            <p>
              没有明确授权时全部保留。GUI 无删除入口；审核后通过 Finder
              移至废纸篓。
            </p>
          </details>
        </div>
      )}
    </section>
  );
}
