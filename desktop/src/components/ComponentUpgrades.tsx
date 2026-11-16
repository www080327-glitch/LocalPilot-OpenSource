import { useEffect, useState } from "react";
import { call, desktop } from "../bridge";
import type { Json } from "../domain";

const names: Record<string, string> = {
  core: "Core",
  companion: "Companion",
  suite: "Suite",
  channels: "Channels",
};
const statuses: Record<string, string> = {
  plan_only: "已生成计划，尚未安装",
  installing: "安装中 / 上次执行尚未完成",
  completed: "安装与组件验证通过",
  failed_rolled_back: "升级失败，已恢复原版本",
  failed_rollback_failed: "回滚未完成，请保留收据与日志",
  rolled_back: "已恢复原版本",
  rolling_back: "正在回滚 / 上次回滚尚未完成",
  awaiting_gui_exit: "等待当前 GUI 退出",
  handoff_failed: "维护助手未完成，请核对错误记录",
};

function result(value: Json) {
  const payload = value.result?.[0];
  if (value.exit !== 0 || !payload)
    throw Error(payload?.error || "维护操作未完成，请检查 Suite 版本与收据。");
  return payload;
}

export function ComponentUpgrades({
  cliReady,
  maintenanceReturn = false,
  desktopAppUpgrade = true,
}: {
  cliReady: boolean;
  maintenanceReturn?: boolean;
  desktopAppUpgrade?: boolean;
}) {
  const [plan, setPlan] = useState<Json | null>(null);
  const [receipt, setReceipt] = useState<Json | null>(null);
  const [handoffError, setHandoffError] = useState<Json | null>(null);
  const [records, setRecords] = useState<Json[]>([]);
  const [historyOpen, setHistoryOpen] = useState(maintenanceReturn);
  const [busy, setBusy] = useState(false);
  const [reviewed, setReviewed] = useState(false);
  const [identityAllowed, setIdentityAllowed] = useState(true);
  const [error, setError] = useState("");
  async function load() {
    const rows: Json[] =
      result(await call<Json>("upgrade_plan", { module: "history" }))
        .upgrades || [];
    setRecords(rows);
    const selected = rows.find((row) => row.plan.id === plan?.id);
    if (selected) {
      setReceipt(selected.receipt || null);
      setHandoffError(selected.handoff_error || null);
    }
  }
  useEffect(() => {
    if (desktop && cliReady)
      void load().catch((error) => setError(String(error)));
  }, [cliReady]);
  async function select(module: string) {
    setBusy(true);
    setError("");
    setReviewed(false);
    setReceipt(null);
    setHandoffError(null);
    setPlan(null);
    setIdentityAllowed(true);
    try {
      setPlan(result(await call<Json>("upgrade_plan", { module })));
      await load();
    } catch (e) {
      setError(String(e));
    } finally {
      setBusy(false);
    }
  }
  async function execute(rollback = false) {
    if (!plan || !reviewed || !identityAllowed) return;
    setBusy(true);
    setError("");
    setReviewed(false);
    try {
      const response = await call<Json>("execute_upgrade", {
        planId: plan.id,
        rollback,
      });
      const value = response.result?.[0];
      if (!value?.status)
        throw Error(value?.error || "操作返回未知结果，请读取原计划收据。");
      setReceipt(value);
      await load();
    } catch (e) {
      setError(String(e));
    } finally {
      setBusy(false);
    }
  }
  return (
    <section aria-labelledby="component-upgrades-title">
      <h4 id="component-upgrades-title">统一升级与回滚</h4>
      {maintenanceReturn && (
        <p role="status">
          已从维护助手返回。请打开本次计划核对收据与错误记录，再显式恢复服务。
        </p>
      )}
      <p className="micro muted">
        选择本机发布包和对应的旧版本
        wheel，先生成完整计划。安装前核对组合依赖；安装或验证失败时按相反顺序恢复。用户数据、模型和任务收据保留。
      </p>
      <div className="management-actions">
        {(desktopAppUpgrade
          ? [
              ["bundle", "GUI 与四个组件一起升级"],
              ["all", "仅升级独立组件"],
              ["desktop", "仅升级 GUI"],
            ]
          : [["all", "升级独立组件"]]
        ).map(([module, label]) => (
          <button
            className="secondary"
            disabled={!desktop || !cliReady || busy}
            key={module}
            onClick={() => void select(module)}
          >
            {label}
          </button>
        ))}
        <button
          className="text-btn"
          disabled={!desktop || !cliReady || busy}
          onClick={() => void load().catch((e) => setError(String(e)))}
        >
          读取升级记录
        </button>
      </div>
      {!desktopAppUpgrade && (
        <p className="micro muted">
          Linux GUI 使用系统包管理器安装或降级 DEB。此处审阅和执行
          Core、Companion、Suite、Channels 的组件升级与失败回滚。
        </p>
      )}
      <details>
        <summary>单个组件</summary>
        <div className="management-actions">
          {Object.entries(names).map(([module, label]) => (
            <button
              className="text-btn"
              key={module}
              disabled={!desktop || !cliReady || busy}
              onClick={() => void select(module)}
            >
              {label} 升级计划
            </button>
          ))}
        </div>
      </details>
      {plan && (
        <div className="version-notice">
          <strong>待审阅计划 · {plan.id}</strong>
          <table>
            <thead>
              <tr>
                <th>组件</th>
                <th>当前版本</th>
                <th>目标版本</th>
              </tr>
            </thead>
            <tbody>
              {plan.desktop && (
                <tr>
                  <td>GUI</td>
                  <td>{plan.desktop.old_version || "目标位置尚未安装"}</td>
                  <td>{plan.desktop.new_version}</td>
                </tr>
              )}
              {(plan.components || []).map((row: Json) => (
                <tr key={row.module}>
                  <td>{names[row.module]}</td>
                  <td>{row.installed}</td>
                  <td>{row.target.version}</td>
                </tr>
              ))}
            </tbody>
          </table>
          <p className="micro">配置与收据目录：{plan.home}</p>
          <p className="micro">Python：{plan.python}</p>
          {plan.desktop && (
            <p className="micro">
              GUI：{plan.desktop.source} → {plan.desktop.destination}
              <br />
              身份：{plan.desktop.bundle_id}
              <br />
              归档：{plan.desktop.archive_directory}
            </p>
          )}
          {(plan.components || []).map((row: Json) => (
            <details key={row.module}>
              <summary>{names[row.module]} 的安装与回滚包</summary>
              <p className="micro">
                安装：{row.target.source}
                <br />
                SHA256：{row.target.sha256}
              </p>
              <p className="micro">
                回滚：{row.rollback.source}
                <br />
                SHA256：{row.rollback.sha256}
              </p>
            </details>
          ))}
          <p>
            {plan.desktop
              ? "执行后当前 GUI 将退出；独立 helper 完成安装或回滚后重新打开目标应用。"
              : "GUI 保持打开，独立组件安装完成后显示验证与回滚结果。"}
          </p>
          {plan.legacy_core_channel_overlap && (
            <p className="micro">
              旧 Core wheel 同时包含
              Channels。此计划强制纳入其独立组件；回滚先恢复
              Core，最后恢复确切的 Channels wheel，避免旧 Core 覆盖渠道代码。
            </p>
          )}
          {plan.channels?.runtimes?.map((row: Json) => (
            <p className="micro" key={row.root}>
              Channels {row.kind}：{row.version} · {row.root}
              （代码归档后更新，消息状态与 UNKNOWN 保留）
            </p>
          ))}
          <p>
            Core、Companion
            和已安装的消息平台服务必须先安全停止。存在活动任务时不会自动终止或重放；完成后在服务管理中显式恢复。
          </p>
          {plan.blocking_services?.length > 0 && (
            <p className="form-error">
              生成计划时仍运行：{plan.blocking_services.join("、")}
              。请先在服务管理中停止；执行时将再次检查。
            </p>
          )}
          <label className="tool-confirm">
            <input
              type="checkbox"
              checked={reviewed}
              onChange={(e) => setReviewed(e.target.checked)}
              disabled={busy || !identityAllowed}
            />
            我已核对版本、路径、回滚包及退出行为
          </label>
          <div className="management-actions">
            <button
              className="primary"
              disabled={
                !reviewed ||
                !identityAllowed ||
                busy ||
                !!receipt?.attempted?.length ||
                receipt?.desktop_attempted
              }
              onClick={() => void execute()}
            >
              {plan.desktop ? "退出并执行此升级" : "执行此升级"}
            </button>
            {(receipt?.attempted?.length > 0 || receipt?.desktop_attempted) && (
              <button
                className="secondary"
                disabled={!reviewed || busy || !identityAllowed}
                onClick={() => void execute(true)}
              >
                {plan.desktop
                  ? "退出并恢复此计划的原版本"
                  : "恢复此计划的原版本"}
              </button>
            )}
          </div>
        </div>
      )}
      {receipt && (
        <div role="status" className="version-notice">
          <strong>{statuses[receipt.status] || receipt.status}</strong>
          {receipt.finished_at && (
            <p className="micro">
              收据完成时间：
              {new Date(receipt.finished_at * 1000).toLocaleString()}
            </p>
          )}
          <p>{receipt.failure || receipt.error || receipt.next}</p>
          {(receipt.rollback_failures || []).map((item: Json) => (
            <p key={item.module} className="form-error">
              {item.module}：{item.error}
            </p>
          ))}
          <details>
            <summary>执行收据与日志路径</summary>
            <pre className="json">{JSON.stringify(receipt, null, 2)}</pre>
          </details>
        </div>
      )}
      {handoffError && (
        <div className="version-notice error" role="alert">
          <strong>维护助手错误记录</strong>
          <p className="micro">
            {new Date(handoffError.at * 1000).toLocaleString()}
          </p>
          <p>{handoffError.error}</p>
          <p className="micro">
            此记录独立保留；请结合安装与回滚收据的时间判断本次结果。
          </p>
        </div>
      )}
      {records.length > 0 && (
        <details
          open={historyOpen}
          onToggle={(event) => setHistoryOpen(event.currentTarget.open)}
        >
          <summary>已有计划与恢复入口（{records.length}）</summary>
          {records.map((row: Json) => (
            <button
              className="text-btn"
              disabled={busy}
              key={row.plan.id}
              onClick={() => {
                setPlan(row.plan);
                setReceipt(row.receipt || null);
                setHandoffError(row.handoff_error || null);
                setReviewed(false);
                setIdentityAllowed(row.execution_allowed !== false);
                setError(row.blocked_reason || "");
              }}
            >
              {new Date(row.plan.created_at * 1000).toLocaleString()} ·{" "}
              {statuses[
                row.receipt?.status || row.handoff_error?.status || "plan_only"
              ] || row.receipt?.status}
              {row.handoff_error && " · 有助手错误记录"}
            </button>
          ))}
        </details>
      )}
      {busy && <p role="status">正在执行维护操作，请保留窗口与发布包…</p>}
      {error && (
        <p className="form-error" role="alert">
          {error}
        </p>
      )}
    </section>
  );
}
