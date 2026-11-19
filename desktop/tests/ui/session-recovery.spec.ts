import { test, expect, type Page } from "@playwright/test";

// Real App/recovery hooks through the same synthetic IPC boundary as the other
// UI tests. This does not establish native WebKit profile isolation.
async function recoveryBridge(
  page: Page,
  mode: "missing" | "existing" | "transient" | "empty" | "onboarding",
) {
  await page.addInitScript(
    ({ mode }) => {
      localStorage.setItem("lp.currentChat", JSON.stringify("sess_cached"));
      localStorage.setItem("lp.currentTask", JSON.stringify("resp_cached"));
      localStorage.setItem(
        "lp.chats.v1",
        JSON.stringify({
          sess_cached: {
            scope:
              mode === "missing"
                ? "/old/home|http://127.0.0.1:8|old-client"
                : "/fixture/home|http://127.0.0.1:9|fixture",
            title: "Preserved draft",
            input: "Unsent original text",
            preferences: {
              source: "balanced",
              objective: "balanced",
              effort: null,
            },
            model: "fixture",
          },
        }),
      );
    },
    { mode },
  );
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
      const mode=${JSON.stringify(mode)};
      const caps=['durable_tasks','durable_idempotency','sse_cursor','verification_dimensions','model_registry','desktop_session_v1','desktop_session_idempotency_v1','attachments_v2'];
      const task={id:'resp_cached',session_id:'sess_cached',status:'completed',quiescent:true,model:'fixture',session_model:'fixture',user_input:'Original question',result:{text:'Original answer'},created_at:1,tools:[{receipt_id:'receipt_unknown',side_effect_status:'unknown'}],required_action:null,last_event_id:1};
      window.recoveryCalls=[];
      window.fixtureService=0;
      window.fixtureLookupStatus=mode==='transient'?503:mode==='empty'?200:404;
      export async function call(command,args={}){
        window.recoveryCalls.push({command,args:structuredClone(args),service:window.fixtureService});
        if(command==='profile')return {home:window.fixtureService?'/fixture/new-home':'/fixture/home',cli:'/fixture/cli',origin:'http://127.0.0.1:9',workspace:'/fixture/work'};
        if(command==='global_preferences')return {version:1,completed:mode!=='onboarding',defaults:{source:'balanced',objective:'balanced',effort:null}};
        if(command==='api' && args.path==='/healthz')return {status:'ready',persistence:true,version:'fixture',client_subject:'fixture',client_generation:1,compatibility:{agent_service_api:'1.0',companion_client_contract:'1.0',capabilities:caps}};
        if(command==='api' && args.path==='/localpilot/v1/model-registry')return {models:[{id:'fixture',model:'Recovery fixture',adapter:'local-openai',deployment_status:'ready',capabilities:['tool_calling'],cloud_egress:'LOCAL_ONLY'}]};
        if(command==='api' && args.path==='/localpilot/v1/tasks')return {tasks:mode==='existing' && !window.fixtureService?[structuredClone(task)]:[]};
        if(command==='api' && args.path==='/localpilot/v1/tasks/resp_cached')return structuredClone(task);
        if(command==='api' && args.path==='/localpilot/v1/sessions/sess_cached'){
          if(window.fixtureLookupStatus===200)return {id:'sess_cached',model:'fixture',active_task_id:null,last_task_id:null};
          const code=window.fixtureLookupStatus===404?'session_not_found':'service_unavailable';
          throw 'HTTP '+window.fixtureLookupStatus+' · '+JSON.stringify({error:{code,message:'Fixture service response'}});
        }
        if(command==='product_control' && args.operation==='documents'){
          if(window.fixtureService || !['existing','empty','transient'].includes(mode))throw Error('Unconfirmed Session reached document list');
          return {files:[],count:0};
        }
        if(command==='product_control' && args.operation==='workspace_grants')return {grants:[]};
        if(command==='pending_submissions')return [{key:'unknown_original',status:'unknown',body:{session_id:'sess_cached',input:'Unknown original request',model:'fixture'}}];
        if(command==='submission_history')return {};
        if(command==='session_preferences')return null;
        if(command==='setup_progress')return {stage:0};
        if(command==='discover_suites')return {installations:[]};
        return {};
      }
    `,
    }),
  );
}

async function calls(page: Page) {
  return page.evaluate(
    () =>
      ((window as any).recoveryCalls || []) as {
        command: string;
        args: any;
        service: number;
      }[],
  );
}

test("first setup never sends cached Session ids to the new service", async ({
  page,
}) => {
  await recoveryBridge(page, "onboarding");
  await page.goto("/");
  await expect
    .poll(async () =>
      (await calls(page)).some((c) => c.command === "submission_history"),
    )
    .toBe(true);
  expect(
    (await calls(page)).filter(
      (c) =>
        c.args.operation === "documents" || c.args.path?.includes("/sessions/"),
    ),
  ).toEqual([]);
  expect(
    await page.evaluate(
      () => JSON.parse(localStorage.getItem("lp.chats.v1")!).sess_cached.input,
    ),
  ).toBe("Unsent original text");
});

test("confirmed missing Session opens a draft without clearing foreign history or replaying UNKNOWN", async ({
  page,
}) => {
  await recoveryBridge(page, "missing");
  await page.goto("/");
  await expect
    .poll(() =>
      page.evaluate(() => JSON.parse(localStorage.getItem("lp.currentChat")!)),
    )
    .toMatch(/^draft-/);
  const observed = await calls(page);
  expect(
    observed.filter(
      (c) => c.args.path === "/localpilot/v1/sessions/sess_cached",
    ),
  ).toHaveLength(1);
  expect(observed.filter((c) => c.args.operation === "documents")).toEqual([]);
  expect(
    observed.filter((c) =>
      ["submit_task", "recover_submission"].includes(c.command),
    ),
  ).toEqual([]);
  expect(
    await page.evaluate(
      () => JSON.parse(localStorage.getItem("lp.chats.v1")!).sess_cached.input,
    ),
  ).toBe("Unsent original text");
});

test("service task history confirms the document Session and retains unknown receipts", async ({
  page,
}) => {
  await recoveryBridge(page, "existing");
  await page.goto("/");
  await expect(page.locator(".conversation")).toContainText("Original answer");
  await expect(
    page.getByRole("textbox", { name: "给 LocalPilot 发送消息" }),
  ).toHaveValue("Unsent original text");
  await expect
    .poll(
      async () =>
        (await calls(page)).filter((c) => c.args.operation === "documents")
          .length,
    )
    .toBe(1);
  const observed = await calls(page);
  expect(
    observed.find((c) => c.args.operation === "documents")!.args.args
      .session_id,
  ).toBe("sess_cached");
  expect(
    observed.filter(
      (c) =>
        c.args.path?.includes("/sessions/") ||
        ["submit_task", "recover_submission"].includes(c.command),
    ),
  ).toEqual([]);
});

test("503 leaves the selected Session intact and a later refresh can confirm it", async ({
  page,
}) => {
  await recoveryBridge(page, "transient");
  await page.goto("/");
  await expect(page.getByText(/HTTP 503 ·/)).toBeVisible();
  expect(
    await page.evaluate(() =>
      JSON.parse(localStorage.getItem("lp.currentChat")!),
    ),
  ).toBe("sess_cached");
  expect(
    (await calls(page)).filter((c) => c.args.operation === "documents"),
  ).toEqual([]);
  await page.evaluate(() => {
    (window as any).fixtureLookupStatus = 200;
  });
  await page.getByRole("button", { name: "刷新任务列表", exact: true }).click();
  await expect
    .poll(
      async () =>
        (await calls(page)).filter((c) => c.args.operation === "documents")
          .length,
    )
    .toBe(1);
  await expect(
    page.getByRole("textbox", { name: "给 LocalPilot 发送消息" }),
  ).toHaveValue("Unsent original text");
  await expect(page.getByText(/HTTP 503 ·/)).toHaveCount(0);
  expect(
    (await calls(page)).filter((c) => c.command === "submit_task"),
  ).toEqual([]);
});

test("a confirmed Session without tasks keeps staged documents available", async ({
  page,
}) => {
  await recoveryBridge(page, "empty");
  await page.goto("/");
  await expect
    .poll(
      async () =>
        (await calls(page)).filter((c) => c.args.operation === "documents")
          .length,
    )
    .toBe(1);
  expect(
    await page.evaluate(() =>
      JSON.parse(localStorage.getItem("lp.currentChat")!),
    ),
  ).toBe("sess_cached");
  await expect(
    page.getByRole("textbox", { name: "给 LocalPilot 发送消息" }),
  ).toHaveValue("Unsent original text");
  expect(
    (await calls(page)).filter((c) => c.command === "submit_task"),
  ).toEqual([]);
});

test("a different Suite root invalidates the old selection even at the same origin and client", async ({
  page,
}) => {
  await recoveryBridge(page, "existing");
  await page.goto("/");
  await expect(page.locator(".conversation")).toContainText("Original answer");
  await page.evaluate(() => {
    (window as any).fixtureService = 1;
  });
  await page.getByRole("button", { name: "刷新任务列表", exact: true }).click();
  await expect
    .poll(() =>
      page.evaluate(() => JSON.parse(localStorage.getItem("lp.currentChat")!)),
    )
    .toMatch(/^draft-/);
  await expect(page.getByText("Original answer", { exact: true })).toHaveCount(
    0,
  );
  await expect(
    page.getByRole("textbox", { name: "给 LocalPilot 发送消息" }),
  ).toHaveValue("");
  expect(
    (await calls(page)).filter(
      (c) => c.service === 1 && c.args.operation === "documents",
    ),
  ).toEqual([]);
  expect(
    await page.evaluate(
      () => JSON.parse(localStorage.getItem("lp.chats.v1")!).sess_cached.input,
    ),
  ).toBe("Unsent original text");
});
