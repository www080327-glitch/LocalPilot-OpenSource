import type { Model } from "./domain";
export const thinkingKey = (model: Model) => `${model.adapter}:${model.model}`;
export function compatibleEffort(
  model: Model | undefined,
  requested: string | null | undefined,
): string | null {
  const options = model?.reasoning_efforts || [];
  if (requested && options.includes(requested)) return requested;
  const fallback = model?.default_reasoning_effort;
  if (fallback && options.includes(fallback)) return fallback;
  return options.includes("none") ? "none" : null;
}
