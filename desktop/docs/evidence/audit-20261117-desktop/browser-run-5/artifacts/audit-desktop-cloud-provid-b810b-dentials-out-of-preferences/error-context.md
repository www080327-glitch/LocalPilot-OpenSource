# Instructions

- Following Playwright test failed.
- Explain why, be concise, respect Playwright best practices.
- Provide a snippet of code with the fix, if possible.

# Test info

- Name: audit-desktop.spec.ts >> cloud provider form submits OpenAI options and keeps credentials out of preferences
- Location: tests/ui/audit-desktop.spec.ts:137:1

# Error details

```
Test timeout of 30000ms exceeded.
```

```
Error: locator.selectOption: Test timeout of 30000ms exceeded.
Call log:
  - waiting for getByRole('region', { name: '连接云端模型' }).getByLabel('提供商', { exact: true })

```

# Page snapshot

```yaml
- generic [ref=e3]:
  - complementary [ref=e4]:
    - generic [ref=e6]:
      - generic [ref=e11]: LocalPilot
      - generic "5.0.1-rc.9" [ref=e12]
    - button "新会话 ⌘ N" [ref=e13] [cursor=pointer]:
      - text: 新会话
      - generic [ref=e15]: ⌘ N
    - button "模型库 模型、下载与推理服务" [ref=e16] [cursor=pointer]:
      - generic [ref=e21]:
        - text: 模型库
        - generic [ref=e22]: 模型、下载与推理服务
    - generic [ref=e25]:
      - textbox "搜索历史任务" [ref=e29]:
        - /placeholder: 搜索会话…
      - generic [ref=e30]: ⌘ K
    - generic [ref=e31]:
      - generic [ref=e32]: 工作区
      - button "工作区设置" [ref=e33] [cursor=pointer]
    - button "work 服务端绑定" [ref=e35] [cursor=pointer]:
      - generic [ref=e38]:
        - text: work
        - generic [ref=e39]: 服务端绑定
    - generic [ref=e42]:
      - generic [ref=e43]: 项目与会话
      - button "创建项目" [ref=e44] [cursor=pointer]
      - button "刷新任务列表" [ref=e47] [cursor=pointer]
    - navigation "任务历史" [ref=e53]:
      - generic [ref=e54]: 你的下一件作品从一次对话开始。
    - generic [ref=e55]:
      - button "服务已连接 Core fixture" [ref=e56] [cursor=pointer]:
        - generic [ref=e58]:
          - text: 服务已连接
          - generic [ref=e59]: Core fixture
      - generic [ref=e62]:
        - button "设置" [ref=e63] [cursor=pointer]
        - button "切换浅色或深色主题" [ref=e67] [cursor=pointer]
        - button "键盘快捷键" [ref=e70] [cursor=pointer]
    - separator "调整侧栏宽度" [ref=e73]
  - main [ref=e74]:
    - generic [ref=e75]:
      - generic [ref=e76]:
        - button "切换左侧栏" [ref=e77] [cursor=pointer]
        - generic [ref=e80]: work
        - generic [ref=e83]: 新会话
      - generic [ref=e84]:
        - generic [ref=e85]: 独立客户端
        - button "切换任务详情" [ref=e89] [cursor=pointer]
    - generic [ref=e93]:
      - heading "今天，想完成什么？" [level=1] [ref=e99]
      - paragraph [ref=e100]: 从一个问题，或一件待办开始。
    - generic [ref=e101]:
      - generic [ref=e102]:
        - button "调整本会话偏好" [ref=e103] [cursor=pointer]:
          - generic [ref=e105]: 完全本地
        - generic [ref=e108]: 仅此会话
      - generic [ref=e109]:
        - textbox "给 LocalPilot 发送消息" [ref=e111]:
          - /placeholder: 描述一个明确目标，让 Agent 帮你推进…
        - button "授权文件夹" [ref=e113] [cursor=pointer]: 选择文件夹
        - generic [ref=e114]:
          - generic [ref=e115]:
            - button "添加附件" [ref=e116] [cursor=pointer]
            - button "导入附件文件夹" [ref=e120] [cursor=pointer]: 文件夹
            - button "权限模式" [ref=e122] [cursor=pointer]: 工作区写入
            - generic "工作模式" [ref=e128]:
              - button "极简 Agent" [ref=e129] [cursor=pointer]
              - button "标准 Agent" [pressed] [ref=e133] [cursor=pointer]
            - button "选择模型" [ref=e140] [cursor=pointer]:
              - generic [ref=e142]: Fixture local model
            - combobox "下次任务时限" [ref=e145]:
              - option "普通任务 · 10 分钟" [selected]
              - option "长任务 · 4 小时"
              - option "长任务 · 24 小时"
            - button "调整思考强度" [ref=e147] [cursor=pointer]
          - button "发送消息" [disabled] [ref=e149]
      - generic [ref=e152]:
        - button "查看本地、云端调用占比及子代理" [ref=e153] [cursor=pointer]: 本地/云端占比：暂无真实调用记录
        - generic [ref=e160]: 操作按当前权限执行 · 云端使用所选模型
        - generic [ref=e164]: Enter 换行 · ⌘ Enter 发送
  - dialog "连接与偏好设置" [ref=e166]:
    - generic [ref=e167]:
      - heading "连接与偏好设置" [level=2] [ref=e168]
      - button "关闭对话框" [ref=e169] [cursor=pointer]
    - generic [ref=e173]:
      - generic [ref=e178]:
        - strong [ref=e179]: LocalPilot Desktop
        - paragraph [ref=e180]: 管理模型、权限和宠物。服务连接与专业参数放在高级设置。
      - generic [ref=e181]: 5.0.1-rc.9
    - generic [ref=e182]:
      - generic [ref=e183]:
        - heading "新会话默认值" [level=3] [ref=e184]
        - generic [ref=e185]: 保存后仅影响后续新会话
      - generic [ref=e186]:
        - generic [ref=e187]:
          - generic [ref=e188]:
            - generic [ref=e189]: 模型来源
            - strong [ref=e192]: 完全本地
          - slider "模型来源" [ref=e195] [cursor=pointer]: "0"
          - generic [ref=e196]:
            - button "模型来源 完全本地" [pressed] [ref=e197] [cursor=pointer]: 完全本地
            - button "模型来源 本地优先" [ref=e198] [cursor=pointer]: 本地优先
            - button "模型来源 平衡" [ref=e199] [cursor=pointer]: 平衡
            - button "模型来源 云端优先" [ref=e200] [cursor=pointer]: 云端优先
            - button "模型来源 完全云端" [ref=e201] [cursor=pointer]: 完全云端
          - paragraph [ref=e202]: 仅允许明确声明为本地的路由；不可用时停止。
        - paragraph [ref=e203]: 此服务暂不支持自动选择模型，请手动选择
      - button "保存全局默认值" [ref=e207] [cursor=pointer]
    - generic [ref=e208]:
      - heading "常用设置" [level=3] [ref=e209]
      - generic [ref=e210]:
        - generic [ref=e211]:
          - text: 回车键行为
          - generic [ref=e212]: 中文输入法确认候选时始终不发送；⌘ Enter 可发送。
        - combobox "回车键行为" [ref=e213]:
          - option "回车换行，⌘ Enter 发送" [selected]
          - option "回车发送，Shift Enter 换行"
      - group [ref=e214]:
        - generic "安装、服务与数据恢复" [ref=e215] [cursor=pointer]
      - region "消息渠道" [ref=e216]:
        - generic [ref=e217]:
          - generic [ref=e218]:
            - heading "连接消息平台" [level=3] [ref=e219]
            - paragraph [ref=e220]: 从手机向同一个 LocalPilot Agent 提交任务。平台连接可随时跳过，之后在设置中继续。
          - button "刷新消息渠道状态" [ref=e221] [cursor=pointer]
        - generic [ref=e227]:
          - heading "微信扫码连接（可跳过）" [level=4] [ref=e228]
          - paragraph [ref=e229]: 扫码并在手机确认。登录后发一句话，自动完成连接，无需勾选身份。
          - generic [ref=e230]:
            - text: 使用模型
            - combobox "微信使用模型" [ref=e231]:
              - option "稍后选择模型" [selected]
          - button "扫码连接微信" [ref=e232] [cursor=pointer]
          - status [ref=e233]:
            - strong [ref=e234]: 尚未连接完成
            - paragraph [ref=e235]: 点击上方按钮获取二维码
        - group [ref=e236]:
          - generic "高级 · QQ、权限与连接诊断" [ref=e237] [cursor=pointer]
        - paragraph [ref=e238]: 默认不连接、不扫码、不读取通讯录。QQ 与微信通过独立 Bridge、Adapter 连接同一个官方 Core。
      - button "检查并更新内置组件" [ref=e242] [cursor=pointer]
      - generic [ref=e243]:
        - generic [ref=e244]:
          - text: 默认模型
          - generic [ref=e245]: 仅影响以后新建的会话，不自动下载或加载
        - combobox "默认模型" [ref=e246]:
          - option "按来源偏好自动选择" [selected]
          - option "Fixture local model · local-openai"
      - generic [ref=e247]:
        - generic [ref=e248]: 软件更新
        - button "检查更新" [ref=e249] [cursor=pointer]
      - generic [ref=e250]:
        - generic [ref=e251]:
          - text: 默认权限模式
          - generic [ref=e252]: 新会话采用所选工具批准策略
        - combobox [ref=e253]:
          - option "只读"
          - option "请求批准"
          - option "工作区写入" [selected]
          - option "完全权限"
          - option "原有：逐项批准"
          - option "原有：低风险自动"
          - option "原有：较高风险自动"
      - generic [ref=e254]:
        - generic [ref=e255]:
          - text: 模型与常用模型
          - generic [ref=e256]: 下载、加载、上下文和缓存偏好
        - button "打开模型库" [ref=e257] [cursor=pointer]
      - generic [ref=e258]:
        - generic [ref=e259]:
          - text: Companion 宠物模式
          - generic [ref=e260]: 独立开启与关闭，不改变标准 Agent
        - button "开启宠物" [ref=e261] [cursor=pointer]
      - group [ref=e262]:
        - generic "Companion 独立设置" [ref=e263] [cursor=pointer]
        - option "麦克风" [selected]
        - option "系统音频"
        - option "麦克风与系统音频"
        - option "中文" [selected]
        - option "English"
        - option "Codex 对话文件" [selected]
        - option "会议文本或字幕"
      - group [ref=e264]:
        - generic "连接云端模型" [active] [ref=e265] [cursor=pointer]
        - region "连接云端模型" [ref=e266]:
          - heading "连接云端模型" [level=3] [ref=e267]
          - generic [ref=e268]:
            - text: 提供商
            - combobox "提供商" [ref=e269]:
              - option "DeepSeek" [selected]
              - option "OpenAI"
          - generic [ref=e270]:
            - text: 模型
            - textbox "模型" [ref=e271]: deepseek-flash
          - generic [ref=e272]:
            - text: DeepSeek API 密钥
            - textbox "DeepSeek API 密钥" [ref=e273]
          - button "保存并连接" [disabled] [ref=e274]
          - paragraph [ref=e275]: 密钥仅保存到本机私有目录。连接配置不会发送任务；发送任务时按当前权限处理云端上下文。
      - paragraph [ref=e276]: 数据与隐私：本地附件在授权工作区保留副本。选择云端模型后，按当前权限处理并发送上下文。关闭窗口不会删除配置、历史或任务。
    - group [ref=e277]:
      - generic "高级设置 · 服务、API、路由与诊断" [ref=e278] [cursor=pointer]
      - option "跟随系统" [selected]
      - option "深色 · Graphite"
      - option "浅色 · Paper"
```

# Test source

```ts
  45  | }) => {
  46  |   await auditBridge(page);
  47  |   await page.goto("/?pet=bubble");
  48  |   await page.getByTitle("宠物设置", { exact: true }).click();
  49  |   await page.getByRole("button", { name: "导入个人角色素材" }).click();
  50  |   await page.getByRole("textbox", { name: "提醒内容" }).fill("喝水测试");
  51  |   const started = Date.now() / 1000;
  52  |   await page.getByRole("button", { name: "10 分钟后提醒" }).click();
  53  |   await expect(page.getByText("提醒已保存。", { exact: true })).toBeVisible();
  54  |   const writes = await page.evaluate(() =>
  55  |     (window as any).fixtureCalls.filter(
  56  |       (call: any) =>
  57  |         call.command === "pet_service" &&
  58  |         call.args.payload.command === "set_reminder",
  59  |     ),
  60  |   );
  61  |   expect(writes).toHaveLength(1);
  62  |   expect(writes[0].args.payload).toMatchObject({
  63  |     text: "喝水测试",
  64  |     confirmed: true,
  65  |   });
  66  |   expect(writes[0].args.payload.due_at).toBeGreaterThanOrEqual(started + 600);
  67  |   expect(writes[0].args.payload.due_at).toBeLessThan(started + 605);
  68  |   await page.getByRole("button", { name: /查看、导出或清理记忆/ }).click();
  69  |   await page.getByRole("button", { name: "导出数据" }).click();
  70  |   await expect(page.getByText(/已导出/)).toHaveCount(0);
  71  |   await page.getByTitle("返回聊天", { exact: true }).click();
  72  |   await expect(page.locator(".pet-header strong")).toHaveText("测试角色");
  73  | });
  74  | 
  75  | test("pet model setup opens the main model library directly", async ({
  76  |   page,
  77  | }) => {
  78  |   await auditBridge(page);
  79  |   await page.goto("/?pet=bubble");
  80  |   await page.getByTitle("宠物设置", { exact: true }).click();
  81  |   await page.getByRole("button", { name: /高级设置/ }).click();
  82  |   await page.getByRole("button", { name: "打开模型库配置轻聊模型" }).click();
  83  |   const calls = await page.evaluate(() =>
  84  |     (window as any).fixtureCalls.filter(
  85  |       (call: any) =>
  86  |         call.command === "pet_core" && call.args.action === "models",
  87  |     ),
  88  |   );
  89  |   expect(calls).toHaveLength(1);
  90  | });
  91  | 
  92  | test("system reduced motion changes propagate to the native animator live", async ({
  93  |   page,
  94  | }) => {
  95  |   await auditBridge(page);
  96  |   await page.emulateMedia({ reducedMotion: "reduce" });
  97  |   await page.goto("/?pet=character");
  98  |   await expect(page.locator(".edge-viewport")).toHaveAttribute(
  99  |     "data-reduce",
  100 |     "true",
  101 |   );
  102 |   await expect
  103 |     .poll(() =>
  104 |       page.evaluate(
  105 |         () =>
  106 |           (window as any).fixtureCalls
  107 |             .filter(
  108 |               (call: any) =>
  109 |                 call.command === "pet_action" &&
  110 |                 call.args.action === "motion_preference",
  111 |             )
  112 |             .at(-1)?.args.value,
  113 |       ),
  114 |     )
  115 |     .toBe(true);
  116 |   await page.emulateMedia({ reducedMotion: "no-preference" });
  117 |   await expect(page.locator(".edge-viewport")).toHaveAttribute(
  118 |     "data-reduce",
  119 |     "false",
  120 |   );
  121 |   await expect
  122 |     .poll(() =>
  123 |       page.evaluate(
  124 |         () =>
  125 |           (window as any).fixtureCalls
  126 |             .filter(
  127 |               (call: any) =>
  128 |                 call.command === "pet_action" &&
  129 |                 call.args.action === "motion_preference",
  130 |             )
  131 |             .at(-1)?.args.value,
  132 |       ),
  133 |     )
  134 |     .toBe(false);
  135 | });
  136 | 
  137 | test("cloud provider form submits OpenAI options and keeps credentials out of preferences", async ({
  138 |   page,
  139 | }) => {
  140 |   await auditBridge(page);
  141 |   await page.goto("/");
  142 |   await page.getByRole("button", { name: "设置", exact: true }).click();
  143 |   await page.getByText("连接云端模型", { exact: true }).first().click();
  144 |   const form = page.getByRole("region", { name: "连接云端模型" });
> 145 |   await form.getByLabel("提供商", { exact: true }).selectOption("openai");
      |                                                 ^ Error: locator.selectOption: Test timeout of 30000ms exceeded.
  146 |   await expect(form.getByLabel("模型", { exact: true })).toHaveValue(
  147 |     "gpt-6-luna",
  148 |   );
  149 |   const key = form.getByLabel("OpenAI API 密钥", { exact: true });
  150 |   await key.fill("fixture-only-not-a-secret-key");
  151 |   await form.getByRole("button", { name: "保存并连接" }).click();
  152 |   await expect(key).toHaveValue("");
  153 |   const calls = await page.evaluate(() =>
  154 |     (window as any).fixtureCalls.filter(
  155 |       (call: any) => call.command === "configure_cloud_key",
  156 |     ),
  157 |   );
  158 |   expect(calls).toEqual([
  159 |     {
  160 |       command: "configure_cloud_key",
  161 |       args: {
  162 |         key: "fixture-only-not-a-secret-key",
  163 |         provider: "openai",
  164 |         model: "gpt-6-luna",
  165 |         confirmed: true,
  166 |       },
  167 |     },
  168 |   ]);
  169 |   expect(await page.evaluate(() => JSON.stringify(localStorage))).not.toContain(
  170 |     "fixture-only-not-a-secret-key",
  171 |   );
  172 |   await expect(form.getByRole("status")).toContainText("OpenAI 配置已保存");
  173 | });
  174 | 
  175 | test("long task selection sends an explicit deadline and a separate extended budget", async ({
  176 |   page,
  177 | }) => {
  178 |   await auditBridge(page);
  179 |   await page.goto("/");
  180 |   await page
  181 |     .getByRole("combobox", { name: "下次任务时限" })
  182 |     .selectOption("86400");
  183 |   await page
  184 |     .getByRole("textbox", { name: "给 LocalPilot 发送消息" })
  185 |     .fill("长任务预算测试");
  186 |   await page.getByRole("button", { name: "发送消息", exact: true }).click();
  187 |   await expect(page.getByText("任务测试完成", { exact: true })).toBeVisible();
  188 |   const calls = await page.evaluate(() => (window as any).fixtureCalls);
  189 |   const session = calls.find(
  190 |     (call: any) =>
  191 |       call.command === "product_control" &&
  192 |       call.args.operation === "desktop_session",
  193 |   );
  194 |   const submit = calls.find((call: any) => call.command === "submit_task");
  195 |   expect(session.args.args).toMatchObject({
  196 |     execution_budget: "extended",
  197 |     permission_mode: "workspace",
  198 |   });
  199 |   expect(submit.args.timeoutSeconds).toBe(86400);
  200 |   await page
  201 |     .getByRole("combobox", { name: "下次任务时限" })
  202 |     .selectOption("600");
  203 |   await page
  204 |     .getByRole("textbox", { name: "给 LocalPilot 发送消息" })
  205 |     .fill("恢复普通预算");
  206 |   await page.getByRole("button", { name: "发送消息", exact: true }).click();
  207 |   await expect
  208 |     .poll(() =>
  209 |       page.evaluate(
  210 |         () =>
  211 |           (window as any).fixtureCalls.filter(
  212 |             (call: any) => call.command === "submit_task",
  213 |           ).length,
  214 |       ),
  215 |     )
  216 |     .toBe(2);
  217 |   const profile = await page.evaluate(() =>
  218 |     (window as any).fixtureCalls
  219 |       .filter(
  220 |         (call: any) =>
  221 |           call.command === "product_control" &&
  222 |           call.args.operation === "desktop_profile",
  223 |       )
  224 |       .at(-1),
  225 |   );
  226 |   expect(profile.args.args).toMatchObject({
  227 |     execution_budget: "standard",
  228 |     expected_execution_budget: "extended",
  229 |   });
  230 | });
  231 | 
```