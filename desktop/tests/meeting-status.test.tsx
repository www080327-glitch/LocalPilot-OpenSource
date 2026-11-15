import { describe, expect, it, vi } from "vitest";
import { renderToStaticMarkup } from "react-dom/server";
import { requireMeetingSnapshot } from "../src/meetingStatus";
import { MeetingCapture } from "../src/components/MeetingCapture";

// Only host availability is substituted; the actual component renders the controls.
vi.mock("../src/bridge", () => ({ desktop: true }));

describe("Companion meeting command admission and snapshots", () => {
  it.each(["busy", "stopping", "UNKNOWN", "error"])(
    "does not accept a %s command receipt as a capture snapshot",
    (status) => {
      expect(() => requireMeetingSnapshot({ status })).toThrow();
    },
  );

  it("preserves the registered status/start/stop response fields without rewriting them", () => {
    for (const [status, state] of [
      ["ok", "idle"],
      ["active", "recording"],
      ["stopped", "stopped"],
      ["unavailable", "unavailable"],
    ]) {
      const response = {
        status,
        meeting: { state, segments: 3, sources: { mic: { state } } },
      };
      expect(requireMeetingSnapshot(response)).toBe(response);
    }
  });

  it("rejects a nominal success without an authoritative meeting state", () => {
    expect(() => requireMeetingSnapshot({ status: "ok" })).toThrow();
    expect(() =>
      requireMeetingSnapshot({ status: "ok", meeting: { state: "UNKNOWN" } }),
    ).toThrow();
  });

  it("keeps the stop control available while the last active snapshot is uncertain", () => {
    const meeting = {
      state: "recording",
      segments: 3,
      sources: { mic: { state: "recording" } },
    };
    const html = renderToStaticMarkup(
      <MeetingCapture
        controller={{
          meeting,
          result: { status: "active", meeting },
          active: true,
          busy: false,
          uncertain: true,
          connected: false,
          control: async () => {},
        }}
      />,
    );
    expect(html).toContain("暂时无法确认采集状态");
    expect(html).toContain('<button class="secondary">停止采集</button>');
    expect(html).toContain(
      '<button class="primary" disabled="">开始所选音轨的本机转写</button>',
    );
  });
});
