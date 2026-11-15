import { describe, expect, it } from "vitest";
import { renderToStaticMarkup } from "react-dom/server";
import { TaskInspector } from "../src/components/TaskInspector";
import { ModelPicker } from "../src/components/ModelPicker";
import { MeetingCapture } from "../src/components/MeetingCapture";
import { VersionManagement } from "../src/components/VersionManagement";
import { observedModelShare } from "../src/collaboration";
import type { Task } from "../src/domain";

const idle = () => {};
const task: Task = {
  id: "resp_observed",
  session_id: "sess_observed",
  status: "completed",
  quiescent: true,
  result: null,
  tools: [],
  required_action: null,
  last_event_id: 4,
};

function inspector(currentTask: Task, tab = "activity") {
  return renderToStaticMarkup(
    <TaskInspector
      currentTask={currentTask}
      activeEvents={[]}
      modelShare={observedModelShare([currentTask], currentTask, [])}
      childTraces={[]}
      preview={false}
      management={false}
      stream="idle"
      tab={tab}
      width={326}
      maxWidth={480}
      onResize={idle}
      onClose={idle}
      onTab={idle}
      onRequery={idle}
      onCancel={idle}
      onAction={idle}
      onInfo={idle}
    />,
  );
}

describe("extracted task and product panels", () => {
  it("keeps UNKNOWN isolated even when the snapshot also carries an approval", () => {
    const html = inspector({
      ...task,
      status: "requires_human",
      required_action: { id: "approval_1", type: "approval" },
      recovery: { class: "UNKNOWN_BLOCKED" },
    });
    expect(html).toContain("UNKNOWN · 副作用未知");
    expect(html).toContain("禁止自动重放");
    expect(html).toContain("取消任务");
    expect(html).not.toContain("允许一次");
    expect(html).not.toContain("继续任务");
  });

  it("still presents the approval controls for a genuine current approval", () => {
    const html = inspector({
      ...task,
      status: "requires_approval",
      required_action: { id: "approval_current", type: "approval" },
    });
    expect(html).toContain("允许一次");
    expect(html).toContain("拒绝动作");
    expect(html).toContain("approval_current");
  });

  it("does not turn a completed task without evidence into a verified result", () => {
    const html = inspector(task, "evidence");
    expect(html).toContain("未验证");
    expect(html).toContain("not_run");
    expect(html).not.toContain("验证通过");
    expect(html).toContain("NOT_RUN");
  });

  it("keeps missing model source evidence out of percentages", () => {
    const html = inspector(
      { ...task, result: { model_calls: [{}] } },
      "agents",
    );
    expect(html).toContain("暂无可核对的本地/云端调用次数");
    expect(html).toContain("次调用没有可信来源分类，未计入百分比");
    expect(html).not.toContain("collaboration-bar");
  });

  it("retains a disabled reasoning-only entry and the explicit new-session route choice", () => {
    const html = renderToStaticMarkup(
      <ModelPicker
        model=""
        models={[
          {
            id: "light",
            model: "Light only",
            adapter: "omlx",
            deployment_status: "ready",
            capabilities: [],
            reasoning_only: true,
          },
        ]}
        loadingModel=""
        busy={false}
        routeCloud={false}
        supportedRouting
        open
        onOpen={idle}
        onSelect={idle}
        onAutoRoute={idle}
        onLibrary={idle}
      />,
    );
    expect(html).toContain('disabled="" title="此路由用于 Companion 轻量对话');
    expect(html).toContain("Core 自动选择 · 新会话选路");
    expect(html).toContain("在线状态未验证");
  });

  it("does not describe a starting meeting as already recording audio", () => {
    const meeting = {
      state: "starting",
      segments: 0,
      sources: { mic: { state: "starting" } },
    };
    const html = renderToStaticMarkup(
      <MeetingCapture
        controller={{
          meeting,
          result: { status: "active", meeting },
          active: true,
          busy: false,
          uncertain: false,
          connected: true,
          control: async () => {},
        }}
      />,
    );
    expect(html).toContain("会议转写正在启动");
    expect(html).not.toContain("正在采集会议音频");
    expect(html).toContain("停止采集");
  });

  it("includes all four independently installed components in version review", () => {
    const html = renderToStaticMarkup(
      <VersionManagement health={null} cliReady={false} maintenanceReturn />,
    );
    for (const name of ["Core", "Companion", "Suite", "Channels"])
      expect(html).toContain("已安装 " + name);
    expect(html).toContain("已从维护助手返回");
    expect(html).toContain("UNKNOWN · 请读取模块版本");
  });
});
