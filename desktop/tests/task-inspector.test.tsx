import { renderToStaticMarkup } from "react-dom/server";
import { expect, it } from "vitest";
import { TaskInspector } from "../src/components/TaskInspector";
import { observedModelShare } from "../src/collaboration";
import { previewTask } from "../src/preview";

it("renders actual Core goal statuses and keeps the old completed presentation", () => {
  const task = {
    ...previewTask,
    goals: [
      { id: "core", description: "真实 Core 已完成步骤", status: "done" },
      { id: "old", description: "旧版完成步骤", status: "completed" },
      { id: "active", description: "当前步骤", status: "in_progress" },
      { id: "blocked", description: "受阻步骤", status: "blocked" },
    ],
  };
  const noop = () => {};
  const html = renderToStaticMarkup(
    <TaskInspector
      currentTask={task}
      activeEvents={[]}
      modelShare={observedModelShare([], task, [])}
      childTraces={[]}
      preview={false}
      management={false}
      stream=""
      tab="activity"
      width={320}
      maxWidth={600}
      onResize={noop}
      onClose={noop}
      onTab={noop}
      onRequery={noop}
      onCancel={noop}
      onAction={noop}
      onInfo={noop}
    />,
  );
  expect(html).toContain("2/4");
  expect(html.match(/class="plan-number done"/g)).toHaveLength(2);
  expect(html).toContain("<small>已完成</small>");
  expect(html).toContain("<small>进行中</small>");
  expect(html).toContain("<small>暂时受阻</small>");
});
