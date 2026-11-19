export const taskDurations = [
  { seconds: 600, budget: "standard", label: "普通任务 · 10 分钟" },
  { seconds: 14400, budget: "extended", label: "长任务 · 4 小时" },
  { seconds: 86400, budget: "extended", label: "长任务 · 24 小时" },
] as const;

export function taskDuration(seconds?: number, budget?: string) {
  return (
    taskDurations.find((option) => option.seconds === seconds) ??
    taskDurations[budget === "extended" ? 1 : 0]
  );
}
