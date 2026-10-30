export type Json = Record<string, any>;
export function errorAfterHealthyConnection(
  message: string,
  connectionError: string,
) {
  if (message === connectionError) return "";
  let value = message.replace(/^Error:\s*/, "");
  if (value.startsWith("管理操作未完成：")) {
    try {
      value = JSON.parse(value.slice("管理操作未完成：".length)).error || value;
    } catch {
      return message;
    }
  }
  return value === "Core failed to start" ||
    value ===
      "Service is still starting after 30 seconds; inspect status and logs before retrying"
    ? ""
    : message;
}
export interface Model {
  id: string;
  model: string;
  adapter: string;
  deployment_status: string;
  capabilities: string[];
  context_budget?: number;
  reasoning_only?: boolean;
  cloud_egress?: string;
  provenance?: string;
  reasoning_efforts?: string[];
}
export interface Task extends Json {
  id: string;
  session_id: string;
  status: string;
  quiescent: boolean;
  model?: string;
  result: Json | null;
  tools: Json[];
  required_action: Json | null;
  last_event_id: number;
  created_at?: number;
  verification_summary?: Json;
  receipt_summary?: Json;
  recovery?: Json;
  output?: Json[];
}
export interface NativeProfile {
  home: string;
  cli: string;
  origin: string;
  workspace: string;
}
export interface Message {
  id: string;
  role: "user" | "assistant";
  text: string;
  taskId?: string;
  source?: string;
  helpInput?: string;
}
export function replyText(
  m: Message,
  task: Task | undefined,
  delta: string | undefined,
) {
  if (task?.status === "running" && !task.quiescent && delta !== undefined)
    return delta;
  return m.text || delta || "";
}
export interface StreamEvent {
  sequence: number;
  type: string;
  task_id: string;
  data: Json;
}
export const terminal = new Set([
  "completed",
  "incomplete",
  "failed",
  "cancelled",
  "timed_out",
]);
export const settled = new Set([
  "completed",
  "incomplete",
  "failed",
  "cancelled",
  "timed_out",
  "requires_approval",
  "requires_human",
]);
export const statusText: Record<string, string> = {
  queued: "排队中",
  running: "正在执行",
  cancelling: "正在取消",
  completed: "执行完成",
  incomplete: "尚未完成",
  failed: "执行失败",
  requires_approval: "等待审批",
  requires_human: "需要人工处理",
  cancelled: "已取消",
  timed_out: "已超时",
  UNKNOWN_BLOCKED: "UNKNOWN · 已隔离",
  not_run: "未验证",
  passed: "验证通过",
  unverified: "未认证",
  verified: "已验证",
  delivered: "已交付",
  present: "已生成",
  complete: "已完成",
  ready: "已配置",
  not_deployed: "未部署",
  available: "可用",
  not_called: "未调用模型",
  unknown: "未知",
};
export const label = (s?: string | null) => (s ? statusText[s] || s : "未知");
export function isUnknown(t?: Task | null) {
  return (
    t?.recovery?.class === "UNKNOWN_BLOCKED" ||
    t?.recovery?.effect_state === "UNKNOWN_BLOCKED" ||
    Number(t?.receipt_summary?.unknown_effects) > 0
  );
}
export function dimensions(t?: Task | null) {
  const r = t?.verification_summary || t?.result || {};
  return {
    runtime: r.runtime_status || t?.status || "unknown",
    delivery: r.deliverable_status || "unknown",
    verification: r.verification_status || "not_run",
    engineering: r.engineering_status || "unverified",
    outcome: r.task_outcome || t?.result?.task_outcome || "unverified",
  };
}
export function textOf(t: Task) {
  if (t.status === "requires_approval")
    return "任务正在等待你的批准。请核对下方的操作与目标。";
  if (t.status === "requires_human")
    return isUnknown(t)
      ? "服务报告了未知副作用。任务已隔离，请保留证据并核对当前状态。"
      : "任务需要人工处理。请核对右侧的当前动作与恢复条件。";
  return (
    t.result?.text ||
    t.output
      ?.filter((o) => o.type === "message")
      .flatMap((o) => (o.content || []).map((c: Json) => c.text || ""))
      .join("") ||
    ""
  );
}
export function usageOf(t?: Task | null) {
  const calls = t?.result?.model_calls;
  if (!Array.isArray(calls) || !calls.length) return null;
  const metric = (field: string, alias: string) => {
    const values = calls.map(
      (c) => (c.usage || c)[field] ?? (c.usage || c)[alias],
    );
    return values.every((v) => typeof v === "number" && Number.isFinite(v))
      ? (values.reduce((a, b) => a + b, 0) as number)
      : null;
  };
  const input = metric("input_tokens", "prompt_tokens"),
    output = metric("output_tokens", "completion_tokens");
  return input === null && output === null ? null : { input, output };
}
export function liveEfforts(model?: Model, sessionSupported = false) {
  return sessionSupported ? model?.reasoning_efforts || [] : [];
}
export function eventName(e: StreamEvent) {
  return e.type === "runtime.event" ? e.data.type : e.type;
}
export function eventDetail(e: StreamEvent) {
  const d = e.type === "runtime.event" ? e.data.data : e.data;
  return d?.tool_name || d?.name || d?.status || d?.message || "";
}
export function compatible(h: Json) {
  const c = h.compatibility;
  return (
    h.status === "ready" &&
    h.persistence === true &&
    /^1\.\d+$/.test(c?.agent_service_api || "") &&
    /^1\.\d+$/.test(c?.companion_client_contract || "") &&
    [
      "durable_tasks",
      "durable_idempotency",
      "sse_cursor",
      "verification_dimensions",
      "model_registry",
    ].every((k) => c?.capabilities?.includes(k))
  );
}

export const verificationLabel = (s?: string) =>
  s === "passed"
    ? "验证通过"
    : s === "failed"
      ? "验证失败"
      : s === "not_run"
        ? "未验证"
        : label(s);

export function diffsOf(t?: Task | null): Json[] {
  return (t?.required_action?.requests || []).flatMap((r: Json) =>
    (r.preview?.changes || []).filter((c: Json) => typeof c.diff === "string"),
  );
}

// SSE history can arrive after a newer server snapshot during reconnect.
export function latestTask(current: Task | undefined, incoming: Task): Task {
  if (
    current &&
    current.id === incoming.id &&
    current.last_event_id > incoming.last_event_id
  )
    return current;
  return incoming;
}
