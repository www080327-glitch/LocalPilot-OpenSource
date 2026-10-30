import type { Model, Task, StreamEvent, Message } from "./domain";
export const previewModels: Model[] = [
  {
    id: "preview-local",
    model: "Qwen · 设计预览",
    adapter: "preview",
    deployment_status: "ready",
    capabilities: ["streaming", "tool_calling"],
    context_budget: 131072,
    cloud_egress: "LOCAL_ONLY",
  },
  {
    id: "preview-unavailable",
    model: "未部署模型 · 模拟",
    adapter: "preview",
    deployment_status: "not_deployed",
    capabilities: [],
    cloud_egress: "LOCAL_ONLY",
  },
];
export const previewTask: Task = {
  id: "preview_task",
  session_id: "preview_session",
  status: "completed",
  quiescent: true,
  model: "preview-local",
  last_event_id: 8,
  result: {
    text: "## 一个更清晰的开始\n\n我已阅读工作区说明，并整理了当前项目的结构。\n\n- **服务层**负责任务执行、工具权限和持久化。\n- **桌面端**呈现对话、计划与可信结果。\n- **验证记录**独立保留，便于逐项核对。\n\n下一步可以选择一个具体目标，我们一起推进。",
    runtime_status: "completed",
    deliverable_status: "complete",
    verification_status: "passed",
    engineering_status: "verified",
  },
  verification_summary: {
    runtime_status: "completed",
    deliverable_status: "complete",
    verification_status: "passed",
    engineering_status: "verified",
  },
  receipt_summary: { total: 1, unknown_effects: 0 },
  required_action: null,
  tools: [
    {
      name: "read_file",
      status: "completed",
      arguments: { path: "README.md" },
      result: "项目说明 · 设计模拟数据",
    },
  ],
  goals: [
    { title: "阅读工作区说明", status: "completed" },
    { title: "核对模块和服务边界", status: "completed" },
    { title: "整理结果与验证记录", status: "completed" },
  ],
};
export const previewMessages: Message[] = [
  {
    id: "p1",
    role: "user",
    text: "先了解一下这个工作区，整理项目结构和下一步。",
  },
  {
    id: "p2",
    role: "assistant",
    text: previewTask.result!.text,
    taskId: previewTask.id,
    source: "模拟 · 设计预览",
  },
];
export const previewEvents: StreamEvent[] = [
  "TaskStarted",
  "PlanUpdated",
  "ToolCallRequested",
  "ToolCallCompleted",
  "VerificationCompleted",
].map((type, i) => ({
  sequence: i + 1,
  type: "runtime.event",
  task_id: "preview_task",
  data: {
    type,
    data: {
      name: i === 2 ? "read_file" : "",
      status: i === 4 ? "passed" : "completed",
    },
  },
}));
