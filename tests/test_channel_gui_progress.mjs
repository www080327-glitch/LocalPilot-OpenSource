import test from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { State, login } from "../integrations/wechat-ilink-bridge/bridge.mjs";

test("native login progress separates scan, confirmation and login; never exposes token", async () => {
  const root=fs.mkdtempSync(path.join(os.tmpdir(),"lp-gui-login-"));
  const before=process.env.LOCALPILOT_CHANNEL_GUI;process.env.LOCALPILOT_CHANNEL_GUI="1";
  const store=new State(root), statuses=[];
  const ilink={baseUrl:"https://ilinkai.weixin.qq.com",mock:false,
    startLogin:async()=>({qrcode:"private-handle",qrcode_img_content:"https://weixin.qq.com/fixture-login"}),
    pollLogin:async()=>statuses.length<2 ? {status:["wait","scaned"][statuses.length]} : {status:"confirmed",bot_token:"PRIVATE-LOGIN-TOKEN",ilink_bot_id:"fixture-bot"}};
  try {
    await login(ilink,store,{interval:0,emit:()=>{
      const p=path.join(root,"connection.json");if(fs.existsSync(p))statuses.push(JSON.parse(fs.readFileSync(p)).status);
    }});
    const progress=fs.readFileSync(path.join(root,"connection.json"),"utf8");
    assert.equal(JSON.parse(progress).status,"logged_in");
    assert.ok(!progress.includes("PRIVATE-LOGIN-TOKEN"));
    assert.ok(!progress.includes("private-handle"));
    assert.ok(!progress.includes("login_url"));
    assert.equal(fs.statSync(path.join(root,"connection.json")).mode&0o777,0o600);
  } finally { store.close();if(before===undefined)delete process.env.LOCALPILOT_CHANNEL_GUI;else process.env.LOCALPILOT_CHANNEL_GUI=before;fs.rmSync(root,{recursive:true}); }
});
