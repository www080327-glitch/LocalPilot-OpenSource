import type { StreamEvent } from "./domain";

export type ModelSource = "local" | "cloud";

export interface SubagentCall {
  id: string;
  model: string;
  provider: string;
  backend: string;
  tier: string;
  status: string;
  requests: number;
}

export interface CollaborationUsage {
  localRequests: number;
  cloudRequests: number;
  unknownRequests: number;
  subagents: SubagentCall[];
}

function source(value: unknown): ModelSource | null {
  return value === "local" || value === "cloud" ? value : null;
}

export function summarizeCollaboration(events: StreamEvent[]): CollaborationUsage {
  const agents = new Map<string, SubagentCall>();
  const seen = new Set<number>();
  const summary: CollaborationUsage = {
    localRequests: 0,
    cloudRequests: 0,
    unknownRequests: 0,
    subagents: [],
  };
  const count = (data: Record<string, unknown>, agentId?: string) => {
    const kind = source(data.primary);
    if (kind === "local") summary.localRequests++;
    else if (kind === "cloud") summary.cloudRequests++;
    else summary.unknownRequests++;
    if (agentId && agents.has(agentId)) agents.get(agentId)!.requests++;
  };
  for (const item of events) {
    if (seen.has(item.sequence)) continue;
    seen.add(item.sequence);
    if (item.type !== "runtime.event") continue;
    const outer = item.data;
    const data = (outer.data || {}) as Record<string, unknown>;
    if (outer.type === "ModelRequestStarted") count(data);
    else if (outer.type === "SubagentStarted") {
      const id = String(data.id || "");
      if (!id) continue;
      agents.set(id, {
        id,
        model: String(data.model || "未报告"),
        provider: String(data.provider || "未报告"),
        backend: String(data.backend || "未知"),
        tier: String(data.tier || "未指定"),
        status: "运行中",
        requests: 0,
      });
    } else if (outer.type === "SubagentEvent") {
      const event = data.event as { type?: string; data?: Record<string, unknown> } | undefined;
      if (event?.type === "ModelRequestStarted") count(event.data || {}, String(data.id || ""));
    } else if (outer.type === "SubagentCompleted" || outer.type === "SubagentFailed") {
      const agent = agents.get(String(data.id || ""));
      if (agent) agent.status = String(data.status || outer.type);
    }
  }
  summary.subagents = [...agents.values()];
  return summary;
}
