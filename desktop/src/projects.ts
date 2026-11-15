import { useEffect, useState } from "react";
import type { Task } from "./domain";

export interface ProjectOrganization {
  projects: { id: string; name: string; pinned: boolean }[];
  assignments: Record<string, string>;
  pinnedSessions: string[];
}

const storageKey = "lp.projectOrganization.v1";
const empty: ProjectOrganization = {
  projects: [], assignments: {}, pinnedSessions: [],
};

export function useConversationProjects(scope: string) {
  const [organizations, setOrganizations] = useState<Record<string, ProjectOrganization>>(() => {
    try {
      return JSON.parse(localStorage.getItem(storageKey) || "{}");
    } catch {
      return {};
    }
  });
  const organization = organizations[scope] || empty;
  useEffect(() => {
    localStorage.setItem(storageKey, JSON.stringify(organizations));
  }, [organizations]);

  function update(change: (old: ProjectOrganization) => ProjectOrganization) {
    setOrganizations((all) => ({ ...all, [scope]: change(all[scope] || empty) }));
  }
  function createProject() {
    const name = window.prompt("新项目名称（可将会话归入该项目）")?.trim();
    if (!name) return;
    update((old) => ({
      ...old,
      projects: [...old.projects, { id: crypto.randomUUID(), name: name.slice(0, 60), pinned: false }],
    }));
  }
  function renameProject(id: string, currentName: string) {
    const name = window.prompt("重命名项目", currentName)?.trim();
    if (!name) return;
    update((old) => ({
      ...old,
      projects: old.projects.map((project) => project.id === id
        ? { ...project, name: name.slice(0, 60) } : project),
    }));
  }
  function toggleProjectPinned(id: string) {
    update((old) => ({
      ...old,
      projects: old.projects.map((project) => project.id === id
        ? { ...project, pinned: !project.pinned } : project),
    }));
  }
  function toggleConversationPinned(id: string) {
    update((old) => ({
      ...old,
      pinnedSessions: old.pinnedSessions.includes(id)
        ? old.pinnedSessions.filter((session) => session !== id)
        : [...old.pinnedSessions, id],
    }));
  }
  function assignConversation(id: string, projectId: string) {
    update((old) => ({
      ...old, assignments: { ...old.assignments, [id]: projectId },
    }));
  }
  return { organization, createProject, renameProject, toggleProjectPinned,
    toggleConversationPinned, assignConversation };
}

export function classifyConversations(conversations: Task[], organization: ProjectOrganization) {
  const pinned = new Set(organization.pinnedSessions);
  const orderedProjects = [...organization.projects].sort(
    (a, b) => Number(b.pinned) - Number(a.pinned) || a.name.localeCompare(b.name),
  );
  const assignedProjects = new Set(orderedProjects.map((project) => project.id));
  const others = conversations.filter((task) => !pinned.has(task.session_id));
  return {
    pinnedIds: pinned,
    pinnedConversations: conversations.filter((task) => pinned.has(task.session_id)),
    otherConversations: others,
    orderedProjects,
    assignedProjects,
    uncategorized: others.filter(
      (task) => !assignedProjects.has(organization.assignments[task.session_id]),
    ),
  };
}
