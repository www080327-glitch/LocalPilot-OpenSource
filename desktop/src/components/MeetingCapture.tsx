import { useState } from "react";
import { desktop } from "../bridge";
import type { CompanionMeeting } from "../hooks/useCompanionMeeting";
import { meetingStateLabel, meetingTrackNames } from "../meetingStatus";

export function MeetingCapture({
  controller,
}: {
  controller: CompanionMeeting;
}) {
  const [capture, setCapture] = useState("microphone");
  const [locale, setLocale] = useState("zh-CN");
  const [label, setLabel] = useState("");
  const linux =
    controller.result?.capabilities?.backend === "ffmpeg_pulse_whisper_cpp";
  const capabilities = controller.result?.capabilities;
  return (
    <section>
      <h4>本机会话与会议转写</h4>
      <p className="muted">
        点击开始后采集所选音轨并在本机转写，不保存音视频。
        {linux
          ? "Linux 使用已选择的麦克风或系统音频来源；需运行当前用户的音频服务并配置本地转写模型。"
          : "系统音轨由系统屏幕与音频捕捉权限控制；缺少本机语音识别能力时显示不可用。"}
        模型和音轨的真实可用性以当前状态为准。
      </p>
      {linux && (
        <p className="micro muted" role="status">
          音频服务：{capabilities.pulse_socket_available ? "已发现" : "未发现"}{" "}
          · 本地转写工具：
          {capabilities.ffmpeg_available && capabilities.whisper_available
            ? "已配置"
            : "待安装或配置"}{" "}
          · 模型文件与校验：
          {capabilities.model_available && capabilities.model_hash_configured
            ? "已配置，启动时核验"
            : "待配置"}{" "}
          · 麦克风来源：
          {capabilities.microphone_configured ? "已选择" : "未选择"} ·
          系统音频来源：
          {capabilities.system_source_configured ? "已选择" : "未选择"}
        </p>
      )}
      <label>
        采集音轨
        <select
          aria-label="会议采集音轨"
          value={capture}
          disabled={
            controller.active || controller.busy || controller.uncertain
          }
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
          disabled={
            controller.active || controller.busy || controller.uncertain
          }
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
          disabled={
            controller.active || controller.busy || controller.uncertain
          }
          onChange={(event) => setLabel(event.target.value)}
          placeholder="可选，例如项目讨论"
        />
      </label>
      <div className="button-row">
        <button
          className="primary"
          disabled={
            !desktop ||
            !controller.connected ||
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
      {!controller.connected && !controller.uncertain && (
        <p className="muted" role="status">
          等待 Companion 连接。Core 停止时仍可独立使用会议转写。
        </p>
      )}
      {controller.uncertain && (
        <p className="warning" role="status">
          暂时无法确认采集状态。未自动再次启动；请停止采集或检查 Companion
          连接。
        </p>
      )}
      {controller.result && (
        <>
          <div className="meeting-status" role="status">
            <strong>{meetingStateLabel(controller.meeting?.state)}</strong>
            <p>
              已记录 {controller.meeting?.segments || 0}{" "}
              段文字，转写内容仍需核对。
            </p>
            {Object.entries(controller.meeting?.sources || {}).map(
              ([track, value]) => (
                <p key={track}>
                  {meetingTrackNames[track] || track}：
                  {meetingStateLabel((value as { state?: string }).state)}
                </p>
              ),
            )}
            {controller.result.reason && <p>{controller.result.reason}</p>}
          </div>
          <details>
            <summary>当前采集覆盖与状态详情</summary>
            <pre className="json">
              {JSON.stringify(controller.result, null, 2)}
            </pre>
          </details>
        </>
      )}
    </section>
  );
}
