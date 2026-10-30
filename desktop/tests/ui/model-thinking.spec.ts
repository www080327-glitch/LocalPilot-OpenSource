import { test, expect } from "@playwright/test";
test("thinking stays per-model and local controls use the same two-level slider", async ({
  page,
}) => {
  await page.route(
    "**/node_modules/.vite/deps/@tauri-apps_api_event.js*",
    (route) =>
      route.fulfill({
        contentType: "text/javascript",
        body: "export async function listen(){return ()=>{}};export async function once(){return ()=>{}};export async function emit(){};export async function emitTo(){}",
      }),
  );
  await page.route("**/src/bridge.ts", (route) =>
    route.fulfill({
      contentType: "text/javascript",
      body: `
    export const desktop=true;
    export async function streamListener(){return ()=>{}};
    const caps=['durable_tasks','durable_idempotency','sse_cursor','verification_dimensions','model_registry','session_thinking_v1'];
    const models=[{id:'cloud',model:'DeepSeekFixture',adapter:'deepseek-native',deployment_status:'ready',capabilities:['tool_calling'],cloud_egress:'REQUIRES_APPROVAL',reasoning_efforts:['none','low','medium','high']},{id:'local',model:'QwenFixture',adapter:'omlx',deployment_status:'ready',capabilities:['tool_calling'],cloud_egress:'LOCAL_ONLY',reasoning_efforts:['none','high'],default_reasoning_effort:'none'}];
    export async function call(command,args={}){
      if(command==='profile')return {home:'/fixture/home',cli:'/fixture/cli',origin:'http://127.0.0.1:9',workspace:'/fixture/workspace'};
      if(command==='global_preferences')return {version:1,completed:true,defaults:{source:'local_first',objective:'balanced',effort:null}};
      if(command==='api' && args.path==='/healthz')return {status:'ready',persistence:true,version:'fixture',client_subject:'fixture',compatibility:{agent_service_api:'1.0',companion_client_contract:'1.0',capabilities:caps}};
      if(command==='api' && args.path==='/localpilot/v1/model-registry')return {models};
      if(command==='api' && args.path==='/localpilot/v1/tasks')return {tasks:[]};
      if(command==='product_control' && args.operation==='workspace_grants')return {grants:[]};
      if(command==='pending_submissions')return [];
      if(command==='submission_history')return {};
      if(command==='session_preferences')return null;
      if(command==='model_manager')return {resources_supported:true,models:{models:[{id:'QwenFixture',loaded:true,files_present:true,size_bytes:1000}]}};
      return {};
    }
  `,
    }),
  );
  await page.goto("/");
  await expect(
    page.getByRole("button", { name: "选择模型", exact: true }),
  ).toContainText("DeepSeekFixture");
  await page.getByRole("button", { name: "调整思考强度", exact: true }).click();
  await page
    .getByRole("button", { name: "思考强度 深入", exact: true })
    .click();
  await page.getByRole("button", { name: "选择模型", exact: true }).click();
  await page.getByRole("button", { name: /QwenFixture.*local/ }).click();
  await page.getByRole("button", { name: "调整思考强度", exact: true }).click();
  const slider = page.getByRole("slider", { name: "思考强度", exact: true });
  await expect(slider).toHaveAttribute("max", "1");
  await expect(slider).toHaveValue("0");
  await page
    .getByRole("button", { name: "思考强度 开启", exact: true })
    .click();
  await expect(slider).toHaveValue("1");
  await page.getByRole("button", { name: "选择模型", exact: true }).click();
  await page.getByRole("button", { name: /DeepSeekFixture.*cloud/ }).click();
  await page.getByRole("button", { name: "调整思考强度", exact: true }).click();
  await expect(slider).toHaveAttribute("max", "3");
  await expect(slider).toHaveValue("2");
});
