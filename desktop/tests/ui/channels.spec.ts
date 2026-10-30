import { test, expect } from "@playwright/test";
import { evidence } from "./evidence";
test.beforeEach(async ({ page }) => {
  await page.route("**/src/bridge.ts", (route) =>
    route.fulfill({
      contentType: "text/javascript",
      body: `
    export const desktop=true;
    const states={qq:{status:'not_installed',installed:false,configured:false,connected:false},wechat:{status:'not_installed',installed:false,configured:false,connected:false}};
    window.channelCalls=[];
    export async function call(command,{kind,action,args}={}){
      window.channelCalls.push({command,kind,action,args});const state=states[kind];
      if(window.fixtureConfigured)Object.assign(states.qq,{installed:true,configured:true,status:'stopped',processes:{qq:false,adapter:false},permissions:{operator:false,cloud:false}});
      if(action==='receipts')return {source:'official_core_agent_service',tasks:window.fixtureTasks||[],read_only:true};
      if(action==='install')Object.assign(state,{installed:true,status:'not_configured'});
      if(action==='login')Object.assign(state,{status:'waiting_scan',processes:{wechat:true},qr_image:'data:image/svg+xml;base64,PHN2ZyB4bWxucz0iaHR0cDovL3d3dy53My5vcmcvMjAwMC9zdmciIHdpZHRoPSIyNDAiIGhlaWdodD0iMjQwIj48cmVjdCB3aWR0aD0iMjQwIiBoZWlnaHQ9IjI0MCIgZmlsbD0id2hpdGUiLz48L3N2Zz4='});
      if(action==='cancel_login')Object.assign(state,{status:'cancelled',qr_image:null,processes:{wechat:false}});
      if(action==='skip')state.skipped=true;
      if(action==='login_status' && window.delayNextLoginStatus){window.delayNextLoginStatus=false;const snapshot={...state};await new Promise(resolve=>setTimeout(resolve,750));return snapshot;}
      return {...state};
    }`,
    }),
  );
  await page.goto("/tests/ui/channel-fixture.html");
});
test("synthetic native controls: installed is not connected, no automatic login or start", async ({
  page,
}) => {
  await expect(page.getByText("未安装", { exact: true })).toHaveCount(2);
  await page.getByRole("button", { name: "连接", exact: true }).first().click();
  await page.getByRole("button", { name: "同意下载并安装渠道组件" }).click();
  await expect(page.getByText("未配置", { exact: true })).toHaveCount(1);
  await expect(
    page.getByRole("button", { name: "安全输入 AppID 与 AppSecret…" }),
  ).toBeVisible();
  await expect(page.locator("input[type=password]")).toHaveCount(0);
  const calls = await page.evaluate(() => (window as any).channelCalls);
  expect(
    calls.some((c: any) => ["login", "start", "discover"].includes(c.action)),
  ).toBe(false);
  await page.screenshot({ path: evidence("channel-qq-synthetic.png") });
});
test("synthetic QR status can cancel and close without completing a connection", async ({
  page,
}) => {
  await page.getByRole("button", { name: "连接", exact: true }).nth(1).click();
  await page.getByRole("button", { name: "同意下载并安装渠道组件" }).click();
  await page.getByRole("button", { name: "获取微信登录二维码" }).click();
  await expect(
    page.getByRole("img", { name: "微信平台登录二维码，请用手机扫码并确认" }),
  ).toBeVisible();
  await page.screenshot({ path: evidence("channel-wechat-synthetic-qr.png") });
  await page.evaluate(() => ((window as any).delayNextLoginStatus = true));
  await page.getByRole("button", { name: "刷新消息渠道状态" }).click();
  await page.getByRole("button", { name: "取消扫码", exact: true }).click();
  await expect(
    page.getByRole("img", { name: "微信平台登录二维码，请用手机扫码并确认" }),
  ).toHaveCount(0);
  await expect(page.getByText("已连接", { exact: true })).toHaveCount(0);
  await page.getByRole("button", { name: "关闭渠道引导" }).click();
  await page.getByRole("button", { name: "稍后设置" }).nth(1).click();
  expect(await page.evaluate(() => JSON.stringify(localStorage))).not.toContain(
    "qrcode",
  );
});
test("channel cards fit a narrow light window and keep keyboard focus visible", async ({
  page,
}) => {
  await page.setViewportSize({ width: 540, height: 780 });
  await page.evaluate(() => (document.documentElement.dataset.theme = "light"));
  await page.getByRole("button", { name: "连接", exact: true }).first().focus();
  await expect(
    page.getByRole("button", { name: "连接", exact: true }).first(),
  ).toBeFocused();
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= innerWidth,
    ),
  ).toBe(true);
  await page.screenshot({
    path: evidence("channel-narrow-light-synthetic.png"),
  });
});

test("host approval requires reviewing the exact action and sends only scoped identifiers", async ({
  page,
}) => {
  await page.evaluate(() => {
    (window as any).fixtureConfigured = true;
    (window as any).fixtureTasks = [
      {
        official_task_id: "resp_" + "a".repeat(32),
        status: "requires_approval",
        local_mapping_status: "pending_approval",
        required_action: {
          id: "approval_fixture",
          requests: [{ name: "apply_patch", path: "approved.txt" }],
        },
        preview_fingerprint: "b".repeat(64),
        approval_id: "approval_fixture",
        can_approve: true,
        can_reject: true,
      },
    ];
  });
  await page.getByRole("button", { name: "刷新消息渠道状态" }).click();
  await page.getByRole("button", { name: "管理连接" }).click();
  await page.getByText("高级诊断与只读任务收据", { exact: true }).click();
  await page.getByRole("button", { name: "查询原任务与收据" }).click();
  const approve = page.getByRole("button", { name: "宿主批准此动作" });
  await expect(approve).toBeDisabled();
  await page.getByText("核对待审批动作", { exact: true }).click();
  await page
    .getByRole("checkbox", { name: "我已核对此动作的范围和副作用" })
    .check();
  await approve.click();
  const calls = await page.evaluate(() =>
    (window as any).channelCalls.filter((c: any) => c.action === "decision"),
  );
  expect(calls).toHaveLength(1);
  expect(calls[0].args.task_id).toBe("resp_" + "a".repeat(32));
  expect(calls[0].args.preview_fingerprint).toBe("b".repeat(64));
  expect(calls[0].args.decision).toBe("approve");
  expect(JSON.stringify(calls[0])).not.toContain("LOCALPILOT_OPERATOR_TOKEN");
});
