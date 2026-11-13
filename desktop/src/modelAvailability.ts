import type { Model } from "./domain";

// Model management can list undeployed and Companion-only routes. The normal
// Agent picker must not advertise those routes as executable.
export function availableAgentModels(models: Model[]): Model[] {
  const seen = new Set<string>();
  return models.filter((model) => {
    if (model.deployment_status !== "ready" || model.reasoning_only ||
        !model.capabilities.includes("tool_calling")) return false;
    const key = [model.adapter, model.model, model.cloud_egress || ""].join("|");
    if (seen.has(key)) return false;
    seen.add(key);
    return true;
  });
}
