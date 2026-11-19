import { test, expect, type Page } from "@playwright/test";

async function configuredModels(page: Page) {
  await page.route("**/src/bridge.ts", (route) =>
    route.fulfill({
      contentType: "text/javascript",
      body: `
      export const desktop=true;
      const models=[
        {id:'main',model:'Main fixture',adapter:'openai',thinking:'high',cooperation_supported:true},
        {id:'cheap',model:'Search fixture',adapter:'openai',thinking:'low',cooperation_supported:true},
        {id:'strong',model:'Review fixture',adapter:'openai',thinking:'medium',cooperation_supported:true}
      ];
      window.configurationCalls=[];
      export async function call(command,args={}){
        window.configurationCalls.push({command,args});
        if(command==='model_manager')return {supported:false,models:{models:[]}};
        if(command==='product_control'){
          if(args.operation==='model_configuration')return {models,configured:true};
          if(args.operation==='inspect')return {hardware:{arch:'arm64'},recommendation:null};
          if(args.operation==='catalog')return {jobs:{tasks:[]},capabilities:{}};
          if(args.operation==='preferences')return {models:{}};
          if(args.operation==='configure_cooperation')return {route:args.args.name,inference:'NOT_RUN',connection:'NOT_PROBED',next:'配置已保存'};
        }
        return {};
      }
    `,
    }),
  );
  await page.goto("/tests/ui/intel-fixture.html?library");
  await page.getByText("模型端点与多 Agent 配置", { exact: true }).click();
  await page.getByLabel("协作主模型").selectOption("main");
}

test("optional worker roles preserve the chosen coordinator and configured efforts", async ({
  page,
}) => {
  await configuredModels(page);
  await page.getByRole("checkbox", { name: /cheap · Search fixture/ }).check();
  await page.getByRole("checkbox", { name: /strong · Review fixture/ }).check();
  await page.getByLabel("探索模型（只读）").selectOption("cheap");
  await page.getByLabel("审阅模型（只读）").selectOption("strong");
  await expect(
    page.getByLabel("审阅模型（只读）").locator("option:checked"),
  ).toContainText("思考 medium");
  await expect(page.getByLabel("协作主模型")).toHaveValue("main");
  await page.getByLabel("协作来源策略").selectOption("cloud-only");
  await page
    .getByRole("button", { name: "保存协作 Agent 配置", exact: true })
    .click();
  await expect(page.getByRole("status")).toContainText("配置已保存");
  const saved = await page.evaluate(() =>
    (window as any).configurationCalls.filter(
      (item: any) => item.args.operation === "configure_cooperation",
    ),
  );
  expect(saved).toHaveLength(1);
  expect(saved[0].args.args).toEqual({
    name: "personal-agent",
    primary: "main",
    partners: ["cheap", "strong"],
    mode: "cloud-only",
    async_enabled: true,
    roles: { search: "cheap", review: "strong" },
  });
});

test("removing a partner or choosing it as primary clears both optional roles", async ({
  page,
}) => {
  await configuredModels(page);
  const cheap = page.getByRole("checkbox", { name: /cheap · Search fixture/ });
  await cheap.check();
  await page.getByLabel("探索模型（只读）").selectOption("cheap");
  await page.getByLabel("审阅模型（只读）").selectOption("cheap");
  await cheap.uncheck();
  await expect(page.getByLabel("探索模型（只读）")).toHaveValue("");
  await expect(page.getByLabel("审阅模型（只读）")).toBeDisabled();
  await cheap.check();
  await expect(page.getByLabel("审阅模型（只读）")).toHaveValue("");
  await page.getByLabel("探索模型（只读）").selectOption("cheap");
  await page.getByLabel("协作主模型").selectOption("cheap");
  await expect(page.getByLabel("探索模型（只读）")).toHaveValue("");
  await page.getByRole("checkbox", { name: /strong · Review fixture/ }).check();
  await page
    .getByRole("button", { name: "保存协作 Agent 配置", exact: true })
    .click();
  const saved = await page.evaluate(() =>
    (window as any).configurationCalls.find(
      (item: any) => item.args.operation === "configure_cooperation",
    ),
  );
  expect(saved.args.args.primary).toBe("cheap");
  expect(saved.args.args.partners).toEqual(["strong"]);
  expect(saved.args.args).not.toHaveProperty("roles");
});
