import { test, expect } from "@playwright/test";
import { evidence } from "./evidence";
test("attachment preview, structural source anchors, escaped injection and revocation", async ({
  page,
}) => {
  await page.route("**/src/bridge.ts", (route) =>
    route.fulfill({
      contentType: "text/javascript",
      body: `
    export const desktop=false;
    let revoked=false;
    export async function call(command,args={}){
      if(command==='attachment_preview') return {text:'<img src=x onerror=alert(1)>\\nOriginal local preview',representation:'local_text_preview'};
      if(command==='product_control'){
        const op=args.args.operation;
        if(op==='revoke'){revoked=true;return {status:'revoked'};}
        if(op==='list')return {files:revoked?[]:[{id:'att_fixture',name:'report.pdf',status:'complete',detected_format:'pdf',parsed_nodes:3}]};
        if(op==='read')return {document:{id:'att_fixture',name:'report.pdf',status:'complete'},nodes:[{kind:'paragraph',text:'Budget 240 <script>bad()</script>',anchor:{page:2},properties:{},citation:'lpdoc:att_'+"0".repeat(32)+':3:'+"1".repeat(64)}],has_more:false};
      }
      return {};
    }
  `,
    }),
  );
  await page.goto("/tests/ui/document-fixture.html");
  await page
    .getByRole("button", { name: "预览 note.txt", exact: true })
    .click();
  await expect(page.getByRole("dialog")).toContainText(
    "Original local preview",
  );
  await expect(page.getByRole("dialog").locator("img")).toHaveCount(0);
  await page.keyboard.press("Escape");
  await page.getByLabel("移除 note.txt", { exact: true }).click();
  await expect(
    page.getByRole("button", { name: "预览 note.txt", exact: true }),
  ).toHaveCount(0);
  await page.locator("summary").click();
  await page
    .getByRole("button", { name: "读取文档 report.pdf", exact: true })
    .click();
  await expect(page.getByRole("dialog")).toContainText("第 2 页");
  await expect(page.getByRole("dialog").locator("script")).toHaveCount(0);
  await page.screenshot({
    path: evidence("document-source-preview.png"),
    animations: "disabled",
  });
  await page.keyboard.press("Escape");
  await page.getByRole("button", { name: "查看引用来源", exact: true }).click();
  await expect(page.getByRole("dialog")).toContainText("第 2 页");
  await page.keyboard.press("Escape");
  await page
    .getByRole("button", { name: "撤销附件 report.pdf", exact: true })
    .click();
  await expect(page.getByLabel("会话附件", { exact: true })).toHaveCount(0);
});
