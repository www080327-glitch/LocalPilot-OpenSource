import { test, expect, type Page } from "@playwright/test";

// These fixtures exercise real React controls through a synthetic native bridge.
// Actual HTTP discovery and service activation are covered by Suite tests.
async function intelBridge(page: Page, system = "Darwin", stage = 1) {
  await page.route("**/src/bridge.ts", (route) =>
    route.fulfill({
      contentType: "text/javascript",
      body: `
      export const desktop=true;
      const hardware={os:${JSON.stringify(system)},arch:'x86_64',chip:'CPU fixture',memory_bytes:16*1024**3,available_memory_bytes:8*1024**3,free_disk_bytes:30*1024**3,backends:[],models:[]};
      const configuredModels=[];
      window.intelCalls=[];
      export async function call(command,args={}){
        window.intelCalls.push({command,args});
        if(command==='setup_progress')return {stage:${stage}};
        if(command==='discover_suites')return {installations:[]};
        if(command==='bootstrap_product')return {setup:{companion_ready:true}};
        if(command==='model_manager')return {supported:false,models:{models:[]}};
        if(command==='product_control'){
          if(args.operation==='inspect')return {hardware,core_configured:true,omlx_installed:false,recommendation:null};
          if(args.operation==='model_configuration')return {
            models:configuredModels.slice(),
            restart_required:localStorage.getItem('fixture.pending')==='yes'
          };
          if(args.operation==='catalog')return {jobs:{tasks:[]},capabilities:{}};
          if(args.operation==='preferences')return {models:{}};
          if(args.operation==='workspace_grants')return {grants:[]};
          if(args.operation==='discover_local_endpoint')return {models:[{id:'fixture-gguf'}],connection:'REACHABLE',inference:'NOT_RUN'};
          if(args.operation==='configure_local_endpoint'){
            localStorage.setItem('fixture.pending','yes');
            configuredModels.push({id:args.args.name,model:args.args.model,adapter:'local-openai',cooperation_supported:true});
            return {route:args.args.name,restart_required:true,inference:'NOT_RUN',connection:'NOT_PROBED',backup:'/fixture/service.backup.json'};
          }
          if(args.operation==='activate_model_configuration'){
            if(window.fixtureActiveTask)throw Error('Active tasks must become quiescent before restart');
            localStorage.removeItem('fixture.pending');
            return {status:'activated',restart_required:false,inference:'NOT_RUN',next:'服务已恢复，请选择新模型并检查连接，然后提交真实任务。'};
          }
        }
        return {};
      }
    `,
    }),
  );
}

test("Linux setup uses the same explicit HTTP route without offering MLX", async ({
  page,
}) => {
  await intelBridge(page, "Linux", 0);
  await page.goto("/tests/ui/intel-fixture.html");
  await expect(
    page.getByText("请使用与当前 Linux 发行版和处理器匹配的安装包。", {
      exact: false,
    }),
  ).toBeVisible();
  await expect(
    page.getByText("macOS 需要 15 或更新版本。", { exact: false }),
  ).toHaveCount(0);
  await page.getByRole("button", { name: "开始准备 Agent", exact: true }).click();
  const form = page.getByRole("region", { name: "连接本机模型服务" });
  await expect(form).toBeVisible();
  await expect(
    form.getByText("可连接 llama.cpp 等推理程序的本机 OpenAI 兼容服务。", {
      exact: false,
    }),
  ).toBeVisible();
  await expect(form.getByText("Intel Mac", { exact: false })).toHaveCount(0);
  await expect(page.getByRole("button", { name: /安装 oMLX/ })).toHaveCount(0);
  await form.getByRole("button", { name: "检查连接并读取模型列表" }).click();
  await form.getByLabel("服务报告的模型").selectOption("fixture-gguf");
  await form.getByLabel("上下文 token 上限").fill("2048");
  await expect(
    form.getByRole("button", { name: "保存本机模型配置", exact: true }),
  ).toBeDisabled();
  await form.getByLabel("上下文 token 上限").fill("4096");
  await form
    .getByRole("button", { name: "保存本机模型配置", exact: true })
    .click();
  await expect(form.getByText("已保存路由：local-cpu")).toBeVisible();
  const calls = await page.evaluate(() => (window as any).intelCalls);
  expect(
    calls.filter(
      (item: any) => item.args.operation === "configure_local_endpoint",
    ),
  ).toHaveLength(1);
});

test("Intel setup discovers a local model and saves explicit CPU endpoint choices", async ({
  page,
}) => {
  await intelBridge(page);
  await page.goto("/tests/ui/intel-fixture.html");
  const form = page.getByRole("region", { name: "连接本机模型服务" });
  await expect(form).toBeVisible();
  await expect(page.getByRole("button", { name: /安装 oMLX/ })).toHaveCount(0);
  await expect(form.getByLabel("上下文 token 上限")).toBeEmpty();
  await form.getByRole("button", { name: "检查连接并读取模型列表" }).click();
  await expect(form.getByRole("status")).toContainText("真实推理尚未验证");
  await form.getByLabel("服务报告的模型").selectOption("fixture-gguf");
  await form.getByLabel("上下文 token 上限").fill("4096");
  await form.getByLabel("Companion 推理电源策略").selectOption("off");
  await form.getByLabel("请求后端关闭模型思考输出").check();
  await form
    .getByRole("button", { name: "保存本机模型配置", exact: true })
    .click();
  await expect(form.getByText("已保存路由：local-cpu")).toBeVisible();
  const calls = await page.evaluate(() => (window as any).intelCalls);
  const saved = calls.filter(
    (item: any) => item.args.operation === "configure_local_endpoint",
  );
  expect(saved).toHaveLength(1);
  expect(saved[0].args.args).toEqual({
    name: "local-cpu",
    base_url: "http://127.0.0.1:1234/v1",
    model: "fixture-gguf",
    context_budget: 4096,
    companion: true,
    companion_power_policy: "off",
    disable_thinking: true,
  });
  expect(
    calls.filter((item: any) => item.command === "bootstrap_product"),
  ).toHaveLength(1);
  expect(
    calls.some(
      (item: any) => item.args.operation === "activate_model_configuration",
    ),
  ).toBe(false);
  expect(
    calls.some((item: any) =>
      ["download", "install_omlx", "initialize_omlx"].includes(
        item.args.operation,
      ),
    ),
  ).toBe(false);
});

test("saved configuration survives reopening and blocked activation requires an explicit retry", async ({
  page,
}) => {
  await intelBridge(page);
  await page.addInitScript(() =>
    localStorage.setItem("fixture.pending", "yes"),
  );
  await page.goto("/tests/ui/intel-fixture.html");
  const button = page.getByRole("button", { name: "确认重启服务并应用配置" });
  await expect(button).toBeVisible();
  await page.getByRole("button", { name: "检查连接并读取模型列表" }).click();
  await expect(button).toBeVisible();
  await page.evaluate(() => {
    (window as any).fixtureActiveTask = true;
  });
  await button.click();
  await expect(page.getByRole("alert")).toContainText("Active tasks");
  await expect(button).toBeEnabled();
  expect(
    await page.evaluate(
      () =>
        (window as any).intelCalls.filter(
          (item: any) => item.args.operation === "activate_model_configuration",
        ).length,
    ),
  ).toBe(1);
  await page.evaluate(() => {
    (window as any).fixtureActiveTask = false;
  });
  await button.click();
  await expect(button).toHaveCount(0);
  await expect(
    page.getByText("服务已恢复，请选择新模型并检查连接，然后提交真实任务。"),
  ).toBeVisible();
});

test("Intel library shows configured endpoint routes without oMLX download controls", async ({
  page,
}) => {
  await intelBridge(page);
  await page.goto("/tests/ui/intel-fixture.html?library");
  await expect(
    page.getByRole("button", { name: "已配置模型", exact: true }),
  ).toBeVisible();
  await expect(
    page.getByText("已配置 1 个本机模型路由", { exact: false }),
  ).toBeVisible();
  await expect(
    page.getByRole("region", { name: "连接本机模型服务" }),
  ).toBeVisible();
  await expect(
    page.getByRole("button", { name: "发现模型", exact: true }),
  ).toHaveCount(0);
  await expect(page.getByRole("button", { name: /扫描.*oMLX/ })).toHaveCount(0);
  await expect(page.getByText("Fixture GGUF", { exact: true })).toBeVisible();
});

test("saving a local route refreshes the cooperation model choices", async ({
  page,
}) => {
  await intelBridge(page);
  await page.goto("/tests/ui/intel-fixture.html?library");
  const form = page.getByRole("region", { name: "连接本机模型服务" });
  await expect(form).toBeVisible();
  await form.getByLabel("模型 ID", { exact: true }).fill("fixture-gguf");
  await form.getByLabel("上下文 token 上限").fill("4096");
  await form
    .getByRole("button", { name: "保存本机模型配置", exact: true })
    .click();
  await expect(form.getByText("已保存路由：local-cpu")).toBeVisible();
  await page.getByText("由多个已注册模型协作", { exact: true }).click();
  await expect(
    page.getByLabel("协作主模型").locator("option[value='local-cpu']"),
  ).toHaveText("local-cpu · fixture-gguf · local-openai");
});
