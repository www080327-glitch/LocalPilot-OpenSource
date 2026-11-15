import type { Json } from "./domain";

const states: Record<string, string> = {
  idle: "会议采集未启动",
  starting: "会议转写正在启动",
  recording: "正在采集会议音频",
  stopping: "正在停止会议采集",
  stopped: "会议采集已停止",
  unavailable: "本机会议转写不可用",
  denied: "会议采集权限未允许",
  failed: "会议采集发生错误",
  interrupted: "上次采集已中断，未自动恢复",
};

export function meetingStateLabel(state?: string) {
  return states[state || ""] || state || "尚未检查采集状态";
}

export function requireMeetingSnapshot(result: Json): Json {
  if (
    !["ok", "active", "stopped", "unavailable"].includes(result.status) ||
    !Object.hasOwn(states, result.meeting?.state)
  )
    throw Error(
      result.error ||
        result.text ||
        result.reason ||
        (result.status === "busy"
          ? "Companion 正忙，会议采集状态尚未确认。"
          : result.status === "stopping"
            ? "Companion 正在停止，尚未确认会议采集已结束。"
            : "会议采集状态尚未确认。"),
    );
  return result;
}

export const meetingTrackNames: Record<string, string> = {
  mic: "麦克风",
  system: "系统音频",
};
