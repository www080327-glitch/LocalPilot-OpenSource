import { test, expect, type Page } from "@playwright/test";

// Synthetic native bridge tests the product flow. Real HTTP/SQLite migration
// is covered by tests/test_pa_model_switch.py; this is not native/model E2E.
async function sessionBridge(page: Page, rejectSwitch = false) {
  await page.addInitScript(() => {
    localStorage.setItem("lp.currentTask", JSON.stringify("resp_existing"));
  });
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
      const caps=['durable_tasks','durable_idempotency','sse_cursor','verification_dimensions','model_registry','desktop_session_v1','desktop_session_idempotency_v1','desktop_profile_switch_v1','desktop_permissions_v3','desktop_model_switch_v1'];
      const options={permission_mode:'full',agent_profile:'standard',scope_revision:3,prompt_revision:2};
      const models=['a','b'].map(id=>({id,model:'Fixture '+id.toUpperCase(),adapter:'remote-openai',deployment_status:'ready',capabilities:['tool_calling'],cloud_egress:'CLOUD_ALLOWED'}));
      const first={id:'resp_existing',session_id:'sess_existing',status:'completed',quiescent:true,model:'a',session_model:localStorage.getItem('fixture.session-model')||'a',user_input:'Remember ORBIT.',result:{text:'Saved ORBIT.'},tools:[],required_action:null,last_event_id:4,created_at:1,desktop_options:options};
      const tasks=[first];
      window.fixtureCalls=[];
      export async function call(command,args={}){
        window.fixtureCalls.push({command,args});
        if(command==='profile')return {home:'/fixture/home',cli:'/fixture/cli',origin:'http://127.0.0.1:9',workspace:'/fixture/work'};
        if(command==='global_preferences')return {version:1,completed:true,defaults:{source:'balanced',objective:'balanced',effort:null}};
        if(command==='api' && args.path==='/healthz')return {status:'ready',persistence:true,version:'fixture',client_subject:'fixture',compatibility:{agent_service_api:'1.0',companion_client_contract:'1.0',capabilities:caps}};
        if(command==='api' && args.path==='/localpilot/v1/model-registry')return {models};
        if(command==='api' && args.path==='/localpilot/v1/tasks')return {tasks};
        if(command==='api' && args.path.startsWith('/localpilot/v1/tasks/'))return tasks.find(t=>args.path.endsWith('/'+t.id))||first;
        if(command==='product_control'){
          if(args.operation==='workspace_grants')return {grants:[]};
          if(args.operation==='desktop_model'){
            if(${rejectSwitch})throw Error('Target route has an incompatible host contract: workspace');
            first.session_model=args.args.model;
            localStorage.setItem('fixture.session-model',first.session_model);
            return {id:first.session_id,model:first.session_model,desktop_options:options};
          }
          if(args.operation==='desktop_profile')return {id:first.session_id,model:first.session_model,desktop_options:options};
          if(args.operation==='desktop_session')throw Error('Unexpected replacement Session');
        }
        if(command==='submit_task'){
          const task={...first,id:'resp_next',model:args.model,session_model:first.session_model,user_input:args.input,created_at:2,result:{text:'Continued ORBIT.'}};
          tasks.push(task);return task;
        }
        if(command==='pending_submissions')return [];
        if(command==='submission_history')return {};
        if(command==='session_preferences')return null;
        return {};
      }
    `,
    }),
  );
}

test("explicit model switch keeps the conversation, draft and next task Session", async ({
  page,
}) => {
  await sessionBridge(page);
  await page.goto("/");
  const picker = page.getByRole("button", { name: "选择模型", exact: true });
  const composer = page.getByRole("textbox", {
    name: "给 LocalPilot 发送消息",
  });
  await expect(page.locator(".conversation")).toContainText("Saved ORBIT.");
  await composer.fill("Keep this draft.");
  await picker.click();
  await page.getByRole("button", { name: /Fixture B.*b/ }).click();
  await expect(picker).toContainText("Fixture B");
  await expect(page.locator(".conversation")).toContainText("Saved ORBIT.");
  await expect(composer).toHaveValue("Keep this draft.");
  expect(
    await page.evaluate(() => localStorage.getItem("lp.currentTask")),
  ).toBe(JSON.stringify("resp_existing"));
  await page.reload();
  await expect(picker).toContainText("Fixture B");
  await expect(page.locator(".conversation")).toContainText("Saved ORBIT.");
  await composer.fill("Recall ORBIT.");
  await composer.press("Enter");
  await expect(page.locator(".conversation")).toContainText("Continued ORBIT.");
  const submits = await page.evaluate(() =>
    (window as any).fixtureCalls.filter(
      (v: any) => v.command === "submit_task",
    ),
  );
  expect(submits).toHaveLength(1);
  expect(submits[0].args).toMatchObject({
    sessionId: "sess_existing",
    model: "b",
  });
});

test("rejected model migration leaves the original model, history and composer intact", async ({
  page,
}) => {
  await sessionBridge(page, true);
  await page.goto("/");
  const picker = page.getByRole("button", { name: "选择模型", exact: true });
  const composer = page.getByRole("textbox", {
    name: "给 LocalPilot 发送消息",
  });
  await expect(page.locator(".conversation")).toContainText("Saved ORBIT.");
  await composer.fill("Do not lose this draft.");
  await picker.click();
  await page.getByRole("button", { name: /Fixture B.*b/ }).click();
  await expect(
    page.getByText(/Target route has an incompatible host contract/),
  ).toBeVisible();
  await expect(picker).toContainText("Fixture A");
  await expect(composer).toHaveValue("Do not lose this draft.");
  await expect(page.locator(".conversation")).toContainText("Saved ORBIT.");
  expect(
    await page.evaluate(() => localStorage.getItem("lp.currentTask")),
  ).toBe(JSON.stringify("resp_existing"));
});
