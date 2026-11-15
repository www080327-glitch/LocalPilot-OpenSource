import { useState } from "react";
import { desktop } from "../bridge";
import type { CompanionMeeting } from "../hooks/useCompanionMeeting";

export function MeetingCapture({
  controller,
}: {
  controller: CompanionMeeting;
}) {
  const [capture, setCapture] = useState("microphone");
  const [locale, setLocale] = useState("zh-CN");
  const [label, setLabel] = useState("");
  return (
    <section>
      <h4>本机会话与会议转写</h4>
      <p className="muted">
        点击开始后采集所选音轨并在本机转写。系统音轨由系统屏幕与音频捕捉权限控制，不保存视频；缺少本机语音识别能力时显示不可用。模型和音轨的真实可用性以当前状态为准。
      </p>
      <label>
        采集音轨
        <select
          aria-label="会议采集音轨"
          value={capture}
          disabled={controller.active}
          onChange={(event) => setCapture(event.target.value)}
        >
          <option value="microphone">麦克风</option>
          <option value="system">系统音频</option>
          <option value="both">麦克风与系统音频</option>
        </select>
      </label>
      <label>
        识别语言
        <select
          value={locale}
          disabled={controller.active}
          onChange={(event) => setLocale(event.target.value)}
        >
          <option value="zh-CN">中文</option>
          <option value="en-US">English</option>
        </select>
      </label>
      <label>
        会议名称
        <input
          value={label}
          disabled={controller.active}
          onChange={(event) => setLabel(event.target.value)}
          placeholder="可选，例如项目讨论"
        />
      </label>
      <div className="button-row">
        <button
          className="primary"
          disabled={
            !desktop ||
            controller.busy ||
            controller.active ||
            controller.uncertain
          }
          onClick={() =>
            void controller.control("meeting_start", {
              capture,
              locale,
              ...(label.trim() ? { label: label.trim() } : {}),
            })
          }
        >
          开始所选音轨的本机转写
        </button>
        <button
          className="secondary"
          disabled={
            !desktop ||
            controller.busy ||
            !(controller.active || controller.uncertain)
          }
          onClick={() => void controller.control("meeting_stop")}
        >
          停止采集
        </button>
      </div>
      {controller.uncertain && (
        <p className="warning" role="status">
          暂时无法确认采集状态。未自动再次启动；请停止采集或检查 Companion
          连接。
        </p>
      )}
      {controller.result && (
        <details open>
          <summary>当前采集覆盖与状态</summary>
          <pre className="json">
            {JSON.stringify(controller.result, null, 2)}
          </pre>
        </details>
      )}
    </section>
  );
}
