import type { Task } from "./domain";
export function latestConversations(tasks: Task[]): Task[] {
  const sessions = new Map<string, Task>();
  for (const task of [...tasks].sort(
    (a, b) => (b.created_at || 0) - (a.created_at || 0),
  )) {
    const key = task.session_id || task.id;
    if (!sessions.has(key)) sessions.set(key, task);
  }
  return [...sessions.values()];
}
export function conversationTitle(
  task: Task,
  tasks: Task[],
  titles: Record<string, string>,
  inputs: Record<string, { input?: string }>,
): string {
  const turns = tasks
    .filter((t) => t.session_id === task.session_id)
    .sort((a, b) => (a.created_at || 0) - (b.created_at || 0));
  const custom =
    titles[task.session_id] || turns.map((t) => titles[t.id]).find(Boolean);
  if (custom) return custom;
  const first = turns.find((t) => t.user_input || inputs[t.id]?.input) || task;
  return String(first.user_input || inputs[first.id]?.input || "未命名会话")
    .trim()
    .split("\n")[0]
    .slice(0, 40);
}
