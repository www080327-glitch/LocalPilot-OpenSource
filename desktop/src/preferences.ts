import type { Json, Model } from "./domain";
export const sources = [
  {
    id: "local_only",
    label: "完全本地",
    detail: "仅允许明确声明为本地的路由；不可用时停止。",
  },
  {
    id: "local_first",
    label: "本地优先",
    detail: "偏好本地；云端仍需单次授权与后端支持。",
  },
  {
    id: "balanced",
    label: "平衡",
    detail: "由支持此契约的 Core 在安全约束内权衡来源。",
  },
  {
    id: "cloud_first",
    label: "云端优先",
    detail: "偏好云端；不会跳过 Cloud Egress 授权。",
  },
  {
    id: "cloud_only",
    label: "完全云端",
    detail: "仅允许云端路由；仍需明确授权。",
  },
] as const;
export const objectives = [
  {
    id: "speed",
    label: "速度优先",
    detail: "偏好较低延迟；不代表已测得速度保证。",
  },
  {
    id: "quality",
    label: "质量优先",
    detail: "偏好结果质量；不等同于思考强度。",
  },
  {
    id: "efficiency",
    label: "能效优先",
    detail: "偏好资源效率；不代表已测得耗电。",
  },
  {
    id: "balanced",
    label: "综合平衡",
    detail: "在延迟、质量和资源之间综合权衡。",
  },
] as const;
export interface Preferences {
  source: (typeof sources)[number]["id"];
  objective: (typeof objectives)[number]["id"];
  effort: string | null;
}
export interface GlobalPreferences {
  version: 1;
  completed: boolean;
  defaults: Preferences;
}
export const initialPreferences: Preferences = {
  source: "local_first",
  objective: "balanced",
  effort: null,
};
export const initialGlobal: GlobalPreferences = {
  version: 1,
  completed: false,
  defaults: initialPreferences,
};
export function taskPreferences(t: Json, fallback: Preferences): Preferences {
  const p = t.service?.route_decision?.routing_preferences;
  if (
    !sources.some((s) => s.id === p?.source) ||
    !objectives.some((o) => o.id === p?.objective)
  )
    return { ...fallback };
  return {
    source: p.source,
    objective: p.objective,
    effort: t.thinking?.requested ?? fallback.effort,
  };
}
export const preferenceLabel = (p: Preferences) =>
  `${sources.find((s) => s.id === p.source)?.label}`;
export const isCloud = (m: Model) =>
  ["deepseek", "deepseek-native", "remote-openai"].includes(m.adapter) ||
  m.cloud_egress !== "LOCAL_ONLY";
export function sourceAllows(p: Preferences, m: Model) {
  return p.source === "local_only"
    ? !isCloud(m)
    : p.source === "cloud_only"
      ? ["deepseek", "deepseek-native", "remote-openai"].includes(m.adapter)
      : true;
}
export function routingSupported(h: Json | null, c: Json | null) {
  return (
    !!h?.compatibility?.capabilities?.includes("routing_preferences_v1") &&
    c?.version === "1.0" &&
    c?.task_create_field === "routing_preferences" &&
    sources.every((s) => c?.sources?.includes(s.id)) &&
    objectives.every((o) => c?.objectives?.includes(o.id)) &&
    c?.evidence_field === "service.route_decision.routing_preferences"
  );
}
export function routeEvidence(t?: Json | null) {
  const d = t?.service?.route_decision;
  return d?.selected
    ? {
        selected: d.selected,
        selection: d.selection,
        backend_fallback: d.backend_fallback,
        preferences: d.routing_preferences || null,
        reason: d.reason || null,
      }
    : null;
}

// Normalize future defaults only. Saved per-session snapshots keep legacy values.
export function productDefaults(value: GlobalPreferences): GlobalPreferences {
  return { ...value, defaults: { ...value.defaults, objective: "balanced" } };
}
