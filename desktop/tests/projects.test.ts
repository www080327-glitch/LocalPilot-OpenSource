import { describe, it, expect } from "vitest";
import { groupConversations } from "../src/projects";
import type { Task } from "../src/domain";
const task = (id: string, session_id: string, created_at: number) =>
  ({ id, session_id, created_at }) as Task;
describe("project conversation navigator", () => {
  it("places pinned projects and sessions first", () => {
    const result = groupConversations(
      [task("1", "old", 1), task("2", "new", 3), task("3", "b", 4)],
      ["Alpha", "Beta"],
      { old: "Alpha", new: "Alpha", b: "Beta" },
      ["Beta"],
      ["old"],
      "默认项目",
    );
    expect(result[0].name).toBe("Beta");
    expect(result.find((p) => p.name === "Alpha")!.tasks.map((t) => t.session_id))
      .toEqual(["old", "new"]);
  });
});
