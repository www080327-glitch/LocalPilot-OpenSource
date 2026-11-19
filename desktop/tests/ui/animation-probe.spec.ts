import { test, expect } from "@playwright/test";
import { auditBridge } from "./audit-bridge";

test("animation sampling excludes transparent parents and offscreen sprites", async ({
  page,
}) => {
  await auditBridge(page);
  await page.goto("/?pet=character");
  await expect(page.locator(".edge-sprite")).toBeVisible();
  await expect(page.locator(".edge-sprite")).toHaveAttribute(
    "data-image-ready",
    "true",
  );
  await page.evaluate(() => {
    const host = window as any;
    const edge = structuredClone(host.fixtureEdge);
    edge.mode = "RETRACTING";
    host.emitFixture("pet-edge", edge);
    const clip = document.querySelector<HTMLElement>(".edge-art-clip")!;
    clip.style.opacity = "0";
    host.emitFixture("pet-measure-animation", {});
    let x = 0;
    const change = setInterval(() => {
      edge.render.box[0] = 100 + (x++ % 20);
      host.emitFixture("pet-edge", structuredClone(edge));
    }, 35);
    setTimeout(() => {
      clearInterval(change);
      clip.style.opacity = "1";
      edge.mode = "PEEKING";
      edge.render.box[0] = -500;
      host.emitFixture("pet-edge", structuredClone(edge));
    }, 1200);
  });
  await expect
    .poll(
      () =>
        page.evaluate(
          () =>
            (window as any).fixtureCalls.filter(
              (call: any) =>
                call.command === "pet_action" &&
                call.args.action === "animation_report",
            ).length,
        ),
      { timeout: 9000 },
    )
    .toBe(1);
  const result = await page.evaluate(
    () =>
      (window as any).fixtureCalls.find(
        (call: any) =>
          call.command === "pet_action" &&
          call.args.action === "animation_report",
      ).args.value,
  );
  expect(result.sampling_method).toBe("visible_element_styles");
  expect(result.pixel_visibility_verified).toBe(false);
  expect(result.segments).toHaveLength(2);
  for (const segment of result.segments) {
    expect(segment.status).toBe("NOT_VISIBLE");
    expect(segment.changes).toHaveLength(0);
    expect(segment.observed_fps).toBe(0);
  }
});
