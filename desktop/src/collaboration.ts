import type { Task, StreamEvent, Json } from "./domain";

export interface ModelShare {
  local: number;
  cloud: number;
  unknown: number;
  observed: number;
  localPercent: number | null;
  cloudPercent: number | null;
}

export interface ChildTrace {
  id: string;
  source: "local" | "cloud" | "unknown";
  model: string;
  provider: string;
  status: string;
  task: string | null;
  reportedModels: string[];
  steps: { sequence: number; label: string }[];
}

function payload(event: StreamEvent): { type: string; data: Json } {
  return event.type === "runtime.event"
    ? { type: event.data?.type, data: event.data?.data || {} }
    : { type: event.type, data: event.data || {} };
}

export function observedModelShare(
  tasks: Task[],
  currentTask: Task | null | undefined,
  currentEvents: StreamEvent[],
): ModelShare {
  let local = 0;
  let cloud = 0;
  let unknown = 0;
  const sessionTasks = currentTask
    ? tasks.filter((task) => task.session_id === currentTask.session_id)
    : [];
  for (const task of sessionTasks) {
    const summary = task.result?.runtime_metrics?.hybrid;
    if (summary?.by_backend) {
      for (const row of Object.values(summary.by_backend) as Json[]) {
        const calls = typeof row.calls === "number" && row.calls >= 0 ? row.calls : 0;
        if (row.kind === "local") local += calls;
        else if (row.kind === "cloud") cloud += calls;
        else unknown += calls;
      }
    } else if (task.id === currentTask?.id && !task.quiescent) {
      // Live events are temporary evidence until the task's durable summary arrives.
      for (const event of currentEvents) {
        const item = payload(event);
        if (item.type !== "HybridModelUsage") continue;
        if (item.data.usage?.kind === "local") local += 1;
        else if (item.data.usage?.kind === "cloud") cloud += 1;
        else unknown += 1;
      }
    } else if (Array.isArray(task.result?.model_calls)) {
      // A plain non-hybrid model call carries no authenticated provider location.
      unknown += task.result.model_calls.length;
    }
  }
  const observed = local + cloud;
  return {
    local,
    cloud,
    unknown,
    observed,
    localPercent: observed ? Math.round((local / observed) * 100) : null,
    cloudPercent: observed ? Math.round((cloud / observed) * 100) : null,
  };
}

export function subagentTraces(events: StreamEvent[], task?: Task | null): ChildTrace[] {
  const children = new Map<string, ChildTrace>();
  for (const event of [...events].sort((a, b) => a.sequence - b.sequence)) {
    const { type, data } = payload(event);
    if (!["SubagentStarted", "SubagentEvent", "SubagentCompleted", "SubagentFailed"].includes(type)) continue;
    if (typeof data.id !== "string") continue;
    let child = children.get(data.id);
    if (!child) {
      child = {
        id: data.id,
        source: data.backend === "local" || data.backend === "cloud" ? data.backend : "unknown",
        model: typeof data.model === "string" ? data.model : (data.configured_model || "未记录"),
        provider: data.provider || "未知",
        status: type === "SubagentStarted" ? "running" : "unknown",
        task: typeof data.task === "string" ? data.task : null,
        reportedModels: Array.isArray(data.reported_models) ? data.reported_models : [],
        steps: [],
      };
      children.set(data.id, child);
    }
    if (type === "SubagentStarted") {
      child.status = "running";
      child.source = data.backend === "local" || data.backend === "cloud" ? data.backend : "unknown";
      child.model = data.model || child.model;
      child.provider = data.provider || child.provider;
      child.task = data.task || child.task;
    } else if (type === "SubagentCompleted" || type === "SubagentFailed") {
      child.status = data.status || (type === "SubagentCompleted" ? "completed" : "failed");
      child.model = data.configured_model || child.model;
      child.reportedModels = Array.isArray(data.reported_models)
        ? data.reported_models : child.reportedModels;
    } else {
      const nested = data.event;
      if (!nested || typeof nested.type !== "string") continue;
      const d = nested.data || {};
      if (nested.type === "ModelRequestStarted") {
        child.model = d.model || child.model;
        child.steps.push({ sequence: event.sequence, label: "请求模型 · " + child.model });
      } else if (nested.type === "ToolCallStarted") {
        child.steps.push({ sequence: event.sequence, label: "调用工具 · " + (d.name || "未知") });
      } else if (nested.type === "ModelHandoffCommitted") {
        child.steps.push({ sequence: event.sequence, label: "模型交接 · " + (d.to_backend_id || "未知") });
      } else if (nested.type === "ErrorEvent") {
        child.steps.push({ sequence: event.sequence, label: "异常 · " + (d.error_type || "未知") });
      }
    }
  }
  // The persisted task snapshot is authoritative when earlier SSE events are
  // no longer retained, or when a completed child is opened after GUI restart.
  for (const row of task?.subagents || []) {
    if (typeof row.id !== "string") continue;
    const existing = children.get(row.id);
    const source = row.backend === "local" || row.backend === "cloud"
      ? row.backend : existing?.source || "unknown";
    children.set(row.id, {
      id: row.id,
      source,
      model: row.configured_model || existing?.model || "未记录",
      provider: row.provider || existing?.provider || "未知",
      status: row.status || existing?.status || "unknown",
      task: row.task || existing?.task || null,
      reportedModels: Array.isArray(row.reported_models)
        ? row.reported_models : existing?.reportedModels || [],
      steps: existing?.steps?.length
        ? existing.steps
        : (row.receipts || []).map((receipt: Json, index: number) => ({
            sequence: index + 1,
            label: "工具收据 · " + (receipt.name || "未知")
              + (receipt.payload?.ok === true ? "（完成）" : "（未成功）"),
          })),
    });
  }
  return [...children.values()];
}
