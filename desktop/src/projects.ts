import type { Task } from "./domain";

export interface ProjectGroup {
  name: string;
  tasks: Task[];
  pinned: boolean;
}

export function groupConversations(
  conversations: Task[],
  known: string[],
  assigned: Record<string, string>,
  pinnedProjects: string[],
  pinnedSessions: string[],
  defaultProject: string,
): ProjectGroup[] {
  const groups = new Map<string, ProjectGroup>();
  const ensure = (name: string) => {
    if (!groups.has(name)) groups.set(name, { name, tasks: [], pinned: pinnedProjects.includes(name) });
    return groups.get(name)!;
  };
  for (const name of [defaultProject, ...known]) ensure(name);
  for (const task of conversations) {
    ensure(assigned[task.session_id] || defaultProject).tasks.push(task);
  }
  for (const group of groups.values()) {
    group.tasks.sort((a, b) =>
      Number(pinnedSessions.includes(b.session_id)) - Number(pinnedSessions.includes(a.session_id)) ||
      (b.created_at || 0) - (a.created_at || 0)
    );
  }
  return [...groups.values()].sort((a, b) =>
    Number(b.pinned) - Number(a.pinned) || a.name.localeCompare(b.name, "zh-CN")
  );
}
