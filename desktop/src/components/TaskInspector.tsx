import {
  Activity,
  AlertTriangle,
  Check,
  CheckCheck,
  ChevronRight,
  FileText,
  GitCompare,
  Layers,
  PanelRight,
  RefreshCw,
  ShieldAlert,
  ShieldCheck,
  Square,
  Terminal,
} from "lucide-react";
import {
  dimensions,
  diffsOf,
  eventDetail,
  eventName,
  isUnknown,
  label,
  terminal,
  usageOf,
  verificationLabel,
  type Json,
  type Model,
  type StreamEvent,
  type Task,
} from "../domain";
import type { ChildTrace, ModelShare } from "../collaboration";
import { JsonView as Pretty } from "./JsonView";
import { TaskStatus as Status } from "./TaskStatus";
import { Resizer } from "./Resizer";

type TaskInspectorProps = {
  currentTask?: Task;
  chosen?: Model;
  activeEvents: StreamEvent[];
  modelShare: ModelShare;
  childTraces: ChildTrace[];
  preview: boolean;
  management: boolean;
  stream: string;
  tab: string;
  width: number;
  maxWidth: number;
  onResize: (width: number) => void;
  onClose: () => void;
  onTab: (tab: string) => void;
  onRequery: () => void;
  onCancel: () => void;
  onAction: (action: string) => void;
  onInfo: (message: string) => void;
};

export function TaskInspector({
  currentTask,
  chosen,
  activeEvents,
  modelShare,
  childTraces,
  preview,
  management,
  stream,
  tab,
  width,
  maxWidth,
  onResize,
  onClose,
  onTab,
  onRequery,
  onCancel,
  onAction,
  onInfo,
}: TaskInspectorProps) {
  const dims = dimensions(currentTask);
  const usage = usageOf(currentTask);
  const plans: Json[] = Array.isArray(currentTask?.goals)
    ? currentTask.goals
    : [];
  return (
    <aside className="inspector">
      <Resizer side="right" width={width} max={maxWidth} onChange={onResize} />
      <header className="inspector-header" data-tauri-drag-region>
        <span>任务详情</span>
        <button
          className="icon-btn"
          aria-label="关闭任务详情"
          onClick={() => onClose()}
        >
          <PanelRight size={16} />
        </button>
      </header>
      <div className="inspector-body">
        <div className="task-overview">
          <div className="section-eyebrow">
            {preview ? "SIMULATED TASK" : "LIVE WORKSPACE"}
          </div>
          <div className="overview-heading">
            <h2>{currentTask ? "每一步，都有依据。" : "准备好开始"}</h2>
            <button
              className="icon-btn"
              aria-label="重新查询任务"
              onClick={onRequery}
            >
              <RefreshCw size={14} />
            </button>
          </div>
          <Status task={currentTask} />
          {currentTask && !preview && !terminal.has(currentTask.status) && (
            <button className="task-cancel text-btn" onClick={onCancel}>
              <Square size={10} />
              取消任务
            </button>
          )}
          {currentTask?.error && (
            <div className="task-error">
              <AlertTriangle size={13} />
              <span>
                {typeof currentTask.error === "string"
                  ? currentTask.error
                  : currentTask.error.message ||
                    JSON.stringify(currentTask.error)}
              </span>
            </div>
          )}
          {currentTask && (
            <code className="task-id" title={currentTask.id}>
              {currentTask.id}
            </code>
          )}
        </div>
        <div className="inspector-tabs" role="tablist" aria-label="任务详情">
          <button
            role="tab"
            aria-selected={tab === "activity"}
            className={tab === "activity" ? "selected" : ""}
            onClick={() => onTab("activity")}
          >
            进度
          </button>
          <button
            role="tab"
            aria-selected={tab === "agents"}
            className={tab === "agents" ? "selected" : ""}
            onClick={() => onTab("agents")}
          >
            协同 {childTraces.length || ""}
          </button>
          <button
            role="tab"
            aria-selected={tab === "evidence"}
            className={tab === "evidence" ? "selected" : ""}
            onClick={() => onTab("evidence")}
          >
            证据
          </button>
          <button
            role="tab"
            aria-selected={tab === "diff"}
            className={tab === "diff" ? "selected" : ""}
            onClick={() => onTab("diff")}
          >
            Diff
          </button>
        </div>
        {tab === "activity" ? (
          <>
            <section className="inspector-section">
              <h3>
                <CheckCheck size={15} />
                任务计划
                <span>
                  {plans.length
                    ? `${plans.filter((p) => p.status === "completed").length}/${plans.length}`
                    : ""}
                </span>
              </h3>
              {plans.length ? (
                <ol className="plan-list">
                  {plans.map((p, i) => (
                    <li key={i}>
                      <span
                        className={`plan-number ${p.status === "completed" ? "done" : ""}`}
                      >
                        {p.status === "completed" ? <Check size={11} /> : i + 1}
                      </span>
                      <span>
                        {p.title ||
                          p.description ||
                          p.goal ||
                          p.id ||
                          JSON.stringify(p)}
                        <small>{label(p.status)}</small>
                      </span>
                    </li>
                  ))}
                </ol>
              ) : (
                <div className="quiet-empty">
                  <span className="empty-line" />
                  <span className="empty-line short" />
                  <p>
                    {currentTask
                      ? "服务未提供结构化计划"
                      : "计划会随着任务逐步展开"}
                  </p>
                </div>
              )}
            </section>
            <section className="inspector-section">
              <h3>
                <Terminal size={15} />
                工具调用<span>{currentTask?.tools?.length || ""}</span>
              </h3>
              {currentTask?.tools?.length ? (
                currentTask.tools.map((t, i) => (
                  <details className="tool-call" key={t.id || i}>
                    <summary>
                      <ChevronRight size={12} />
                      <code>{t.name || t.tool_name || "tool"}</code>
                      <span>{label(t.status || "unknown")}</span>
                    </summary>
                    <Pretty value={t} />
                  </details>
                ))
              ) : (
                <p className="muted micro">工具提案、执行与收据将在这里显示</p>
              )}
            </section>
            {currentTask?.required_action && (
              <section
                className={`approval-card ${isUnknown(currentTask) ? "unknown" : ""}`}
              >
                <ShieldAlert size={19} />
                <h3>
                  {isUnknown(currentTask)
                    ? "UNKNOWN · 副作用未知"
                    : "需要可信操作者"}
                </h3>
                <p>
                  {isUnknown(currentTask)
                    ? "保持隔离。允许查询或取消，禁止自动重放。"
                    : "先核对动作、目标与范围，再确认授权。审批身份由本机受控通道使用。"}
                </p>
                <details>
                  <summary>查看操作详情</summary>
                  <Pretty value={currentTask.required_action} />
                </details>
                {!isUnknown(currentTask) && (
                  <div className="approval-actions">
                    {currentTask.required_action.type === "approval" && (
                      <>
                        <button
                          className="primary"
                          disabled={management}
                          onClick={() => onAction("approve")}
                        >
                          允许一次
                        </button>
                        <button
                          className="secondary"
                          disabled={management}
                          onClick={() => onAction("reject")}
                        >
                          拒绝动作
                        </button>
                      </>
                    )}
                    {currentTask.required_action.type ===
                      "runtime_continuation" &&
                      currentTask.recovery?.class === "SAFE_TO_RESUME" && (
                        <button
                          className="text-btn"
                          onClick={() => onAction("resume")}
                        >
                          继续任务
                        </button>
                      )}
                  </div>
                )}
              </section>
            )}
            <section className="inspector-section timeline-section">
              <h3>
                <Activity size={15} />
                事件时间线<span>{activeEvents.length || ""}</span>
              </h3>
              {activeEvents.length ? (
                <ol className="timeline">
                  {activeEvents
                    .filter((e) => eventName(e) !== "TextDelta")
                    .slice(-35)
                    .map((e) => (
                      <li key={e.sequence}>
                        <i />
                        <div>
                          <span>{eventName(e)}</span>
                          <small>
                            {eventDetail(e) || `sequence ${e.sequence}`}
                          </small>
                        </div>
                        <code>{String(e.sequence).padStart(2, "0")}</code>
                      </li>
                    ))}
                </ol>
              ) : (
                <p className="muted micro">
                  等待服务事件。流中断后使用原任务和游标恢复。
                </p>
              )}
            </section>
          </>
        ) : tab === "agents" ? (
          <section className="inspector-section">
            <h3>
              <Layers size={15} /> 实际模型协同
            </h3>
            <p className="micro muted">
              按本会话已经记录的模型请求次数统计；不把静态路由或缺失来源当成真实模型调用。
              失败请求也计入调用次数。实际 API 费用需另行核对。
            </p>
            {modelShare.observed > 0 ? (
              <>
                <div className="collaboration-percentages">
                  <span>
                    本地 {modelShare.localPercent}% · {modelShare.local} 次
                  </span>
                  <span>
                    云端 {modelShare.cloudPercent}% · {modelShare.cloud} 次
                  </span>
                </div>
                <div
                  className="collaboration-bar"
                  aria-label="已记录模型调用占比"
                >
                  <span
                    className="collaboration-local"
                    style={{ width: `${modelShare.localPercent}%` }}
                  />
                  <span
                    className="collaboration-cloud"
                    style={{ width: `${modelShare.cloudPercent}%` }}
                  />
                </div>
              </>
            ) : (
              <p className="muted micro">暂无可核对的本地/云端调用次数。</p>
            )}
            {modelShare.unknown > 0 && (
              <p className="muted micro">
                另有 {modelShare.unknown} 次调用没有可信来源分类，未计入百分比。
              </p>
            )}
            <h3>
              <Layers size={15} /> 子代理 · {childTraces.length}
            </h3>
            {childTraces.length ? (
              childTraces.map((child) => (
                <details
                  className="tool-call"
                  key={child.id}
                  open={child.status === "running"}
                >
                  <summary>
                    <ChevronRight size={12} />
                    <span>
                      {child.source === "local"
                        ? "本地"
                        : child.source === "cloud"
                          ? "云端"
                          : "来源未知"}{" "}
                      · {child.model}
                    </span>
                    <span>{label(child.status)}</span>
                  </summary>
                  <div className="collaboration-child-details">
                    <p>子代理 ID：{child.id}</p>
                    <p>实际提供方：{child.provider}</p>
                    <p>配置模型：{child.model}</p>
                    {child.reportedModels.length > 0 && (
                      <p>
                        提供方实际返回的模型：
                        {child.reportedModels.join("、")}
                      </p>
                    )}
                    {child.task && <p>委派任务：{child.task}</p>}
                    {child.steps.length ? (
                      <ol className="collaboration-child-steps">
                        {child.steps.slice(-20).map((step) => (
                          <li key={step.sequence}>{step.label}</li>
                        ))}
                      </ol>
                    ) : (
                      <p>尚无可展示的执行步骤。</p>
                    )}
                  </div>
                </details>
              ))
            ) : (
              <p className="muted micro">
                当前任务未观察到子代理创建事件；不能据此宣称已经执行了跨模型委派。
              </p>
            )}
          </section>
        ) : tab === "evidence" ? (
          <>
            <section className="inspector-section">
              <h3>
                <ShieldCheck size={15} />
                执行与交付
              </h3>
              <div className="dimension-list">
                {[
                  ["执行", dims.runtime],
                  ["交付", dims.delivery],
                  ["验证", dims.verification],
                  ["工程状态", dims.engineering],
                  ["任务验收", dims.outcome],
                ].map(([k, v]) => (
                  <div key={k}>
                    <span>{k}</span>
                    <span
                      className={
                        v === "passed" || v === "completed" || v === "verified"
                          ? "mint"
                          : ""
                      }
                    >
                      {k === "验证"
                        ? verificationLabel(v)
                        : k === "工程状态"
                          ? v === "passed"
                            ? "通过"
                            : v === "failed"
                              ? "未通过"
                              : label(v)
                          : label(v)}
                    </span>
                  </div>
                ))}
              </div>
              <p className="micro muted">
                执行完成、交付结果和可信验证分别呈现。缺失的指标保留为未知。
              </p>
            </section>
            <section className="inspector-section">
              <h3>
                <FileText size={15} />
                验证与收据
              </h3>
              {currentTask ? (
                <>
                  <details className="evidence-details" open>
                    <summary>Verification summary</summary>
                    <Pretty
                      value={
                        currentTask.verification_summary || {
                          verification_status: "not_run",
                        }
                      }
                    />
                  </details>
                  <details className="evidence-details" open>
                    <summary>文件位置与内容校验</summary>
                    <Pretty
                      value={
                        currentTask.file_operation_verification || {
                          status: "NOT_RUN",
                        }
                      }
                    />
                    <p className="micro muted">
                      核对真实文件与操作收据；任务要求是否全部满足仍单独验证。
                    </p>
                  </details>
                  <details className="evidence-details">
                    <summary>Receipt summary</summary>
                    <Pretty
                      value={
                        currentTask.receipt_summary || { status: "unknown" }
                      }
                    />
                  </details>
                  <details className="evidence-details">
                    <summary>Route decision / recovery</summary>
                    <Pretty
                      value={{
                        service: currentTask.service,
                        recovery: currentTask.recovery,
                      }}
                    />
                  </details>
                </>
              ) : (
                <p className="muted micro">提交任务后显示服务提供的证据。</p>
              )}
            </section>
          </>
        ) : (
          <section className="inspector-section">
            {diffsOf(currentTask).length ? (
              <>
                <h3>
                  <GitCompare size={15} />
                  当前审批的变更预览
                </h3>
                {diffsOf(currentTask).map((c, i) => (
                  <div className="diff-file" key={i}>
                    <div>
                      <FileText size={13} />
                      <code>{c.path}</code>
                      <span>{c.operation}</span>
                    </div>
                    <pre>
                      {c.diff.split("\n").map((line: string, n: number) => (
                        <span
                          key={n}
                          className={
                            line.startsWith("+")
                              ? "addition"
                              : line.startsWith("-")
                                ? "deletion"
                                : ""
                          }
                        >
                          {line}
                          {"\n"}
                        </span>
                      ))}
                    </pre>
                  </div>
                ))}
                <p className="micro muted">
                  来自服务的当前审批预览。它描述拟议变更，不证明已经写入磁盘。最终状态以收据与
                  Verification 为准。
                </p>
              </>
            ) : (
              <div className="diff-empty">
                <GitCompare size={28} />
                <h3>变更，从可信来源开始。</h3>
                <p>
                  当前没有审批 Diff。服务提供 apply_patch
                  审批预览时，会在这里显示；RC2 尚无通用工作区 Diff 接口。
                </p>
                <span className="outline-badge">不读取工作区文件</span>
              </div>
            )}
          </section>
        )}
        <div className="inspector-bottom">
          <div>
            <span>上下文</span>
            <strong>
              {chosen?.context_budget
                ? `${Math.round(chosen.context_budget / 1024)}k`
                : "未知"}
            </strong>
          </div>
          <div>
            <span>Tokens</span>
            <strong>
              {usage
                ? `${usage.input?.toLocaleString() ?? "未知"} / ${usage.output?.toLocaleString() ?? "未知"}`
                : "未知"}
            </strong>
          </div>
          <div>
            <span>实际费用</span>
            <strong>未知</strong>
          </div>
          <button
            className="text-btn"
            onClick={() =>
              onInfo(
                "模型上下文来自服务注册表；Token 仅展示 provider 实际返回的 usage。RC2 没有计费 API，客户端不估算实际费用。上下文总容量不代表当前已使用量。",
              )
            }
          >
            关于这些指标
            <ChevronRight size={12} />
          </button>
        </div>
      </div>
      <footer className="inspector-status">
        <span
          className={`connection-dot ${stream === "connected" ? "online" : ""}`}
        />
        {preview
          ? "模拟事件 · 不连接服务"
          : stream === "connected"
            ? "SSE 已连接"
            : stream === "reconnecting"
              ? "SSE 正在重连"
              : stream === "disconnected"
                ? "连接中断 · 可重新查询"
                : currentTask?.quiescent
                  ? "任务已静止 · 快照保留"
                  : "事件连接待命"}
        <button className="icon-btn" aria-label="重连 SSE" onClick={onRequery}>
          <RefreshCw size={12} />
        </button>
      </footer>
    </aside>
  );
}
