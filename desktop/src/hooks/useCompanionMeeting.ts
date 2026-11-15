import { useEffect, useState } from "react";
import { call, desktop } from "../bridge";
import type { Json } from "../domain";
import { requireMeetingSnapshot } from "../meetingStatus";

export function useCompanionMeeting(
  home: string,
  onError: (error: unknown) => void,
) {
  const [result, setResult] = useState<Json | null>(null);
  const [busy, setBusy] = useState(false);
  const [uncertain, setUncertain] = useState(false);
  const [connected, setConnected] = useState(false);
  const meeting = result?.meeting;
  const active =
    result?.status === "active" ||
    ["starting", "recording", "stopping"].includes(meeting?.state);
  useEffect(() => {
    setResult(null);
    setConnected(false);
    setUncertain(false);
  }, [home]);
  useEffect(() => {
    if (!desktop || !home) {
      setConnected(false);
      if (active) setUncertain(true);
      return;
    }
    let disposed = false;
    const refresh = async () => {
      try {
        const value = requireMeetingSnapshot(
          await call<Json>("companion", {
            command: "meeting_status",
          }),
        );
        if (disposed) return;
        setResult(value);
        setConnected(true);
        setUncertain(false);
      } catch {
        if (!disposed) {
          setConnected(false);
          if (active) setUncertain(true);
        }
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
  }, [home, active]);
  async function control(
    command: "meeting_start" | "meeting_stop",
    args: Json = {},
  ) {
    setBusy(true);
    try {
      const value = requireMeetingSnapshot(
        await call<Json>("companion", { command, args }),
      );
      setResult(value);
      setUncertain(false);
      setConnected(true);
    } catch (error) {
      setConnected(false);
      setUncertain(true);
      onError(error);
    } finally {
      setBusy(false);
    }
  }
  return { result, meeting, active, busy, uncertain, connected, control };
}
export type CompanionMeeting = ReturnType<typeof useCompanionMeeting>;
