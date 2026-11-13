import { describe, expect, it } from "vitest";
import { classifyConversations, type ProjectOrganization } from "../src/projects";
import type { Task } from "../src/domain";

const task = (id: string): Task => ({
  id,
  session_id: id,
  status: "completed",
  quiescent: true,
  result: null,
  tools: [],
  required_action: null,
  last_event_id: 0,
});

describe("per-client project organization", () => {
  const org: ProjectOrganization = {
    projects: [
      { id: "b", name: "Research", pinned: false },
      { id: "a", name: "LocalPilot", pinned: true },
    ],
    assignments: { s1: "a", s3: "b", s4: "unknown-project" },
    pinnedSessions: ["s2"],
  };

  it("separates pinned threads and pinned projects without losing task facts", () => {
    const tasks = [task("s1"), task("s2"), task("s3"), task("s4")];
    const result = classifyConversations(tasks, org);
    expect(result.orderedProjects.map((p) => p.id)).toEqual(["a", "b"]);
    expect(result.pinnedConversations.map((t) => t.id)).toEqual(["s2"]);
    expect(result.uncategorized.map((t) => t.id)).toEqual(["s4"]);
    expect(result.otherConversations.map((t) => t.id)).toEqual(["s1", "s3", "s4"]);
    expect(tasks[1].result).toBeNull();
  });

  it("treats deleted project references as unclassified instead of losing conversations", () => {
    const result = classifyConversations([task("s1"), task("s4")], {
      ...org, projects: [], pinnedSessions: [],
    });
    expect(result.uncategorized.map((t) => t.id)).toEqual(["s1", "s4"]);
  });
});
