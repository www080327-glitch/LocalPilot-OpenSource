import { useEffect, useState } from "react";
import { call, desktop } from "../bridge";
import type { Json } from "../domain";

export function useCompanionMeeting(
  connected: boolean,
  onError: (error: unknown) => void,
) {
  const [result, setResult] = useState<Json | null>(null);
  const [busy, setBusy] = useState(false);
  const [uncertain, setUncertain] = useState(false);
  const meeting = result?.meeting;
  const active =
    result?.status === "active" ||
    ["starting", "recording", "stopping"].includes(meeting?.state);
  useEffect(() => {
    if (!desktop || !connected) {
      if (active) setUncertain(true);
      return;
    }
    let disposed = false;
    const refresh = async () => {
      try {
        const value = await call<Json>("companion", {
          command: "meeting_status",
        });
        if (!disposed && value.status !== "error") {
          setResult(value);
          setUncertain(false);
        }
      } catch {
        if (!disposed && active) setUncertain(true);
      }
    };
    void refresh();
    const timer = window.setInterval(
      () => void refresh(),
      active ? 3000 : 15000,
    );
    return () => {
      disposed = true;
      window.clearInterval(timer);
    };
  }, [connected, active]);
  async function control(
    command: "meeting_start" | "meeting_stop",
    args: Json = {},
  ) {
    setBusy(true);
    try {
      const value = await call<Json>("companion", { command, args });
      setResult(value);
      setUncertain(false);
      if (value.status === "error")
        throw Error(value.error || value.message || "会议采集操作失败");
    } catch (error) {
      setUncertain(true);
      onError(error);
    } finally {
      setBusy(false);
    }
  }
  return { result, meeting, active, busy, uncertain, control };
}
export type CompanionMeeting = ReturnType<typeof useCompanionMeeting>;
