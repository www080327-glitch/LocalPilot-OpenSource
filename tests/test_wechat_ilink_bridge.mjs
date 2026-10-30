import assert from "node:assert/strict";
import { test } from "node:test";
import http from "node:http";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { randomBytes } from "node:crypto";
import { spawnSync } from "node:child_process";
import { Bridge, BridgeError, ILink, State, channelId, login, senderId } from "../integrations/wechat-ilink-bridge/bridge.mjs";

const json = (res, data, code = 200) => { res.writeHead(code); res.end(JSON.stringify(data)); };
test("quoted credentials are rejected before Core and redacted in JSON previews", async t => {
  const f = await fixture(t);
  f.bridge.key = 'SYNTHETIC_quoted"key\\value_123456789';
  await assert.rejects(f.bridge.adapter('/messages',{text:f.bridge.key}),{code:'credential_in_input_rejected'});
  assert.equal(f.adapterCalls.length,0);
  assert.ok(!f.bridge.safe(JSON.stringify({value:f.bridge.key})).includes(JSON.stringify(f.bridge.key).slice(1,-1)));
});
const event = (id = "1", peer = "peer-a", text = "list files") => ({
  message_type: 1, message_state: 2, message_id: id, from_user_id: peer, to_user_id: "bot-1",
  context_token: "context-" + peer, item_list: [{ type: 1, text_item: { text } }],
});

test("official processing status is preserved until explicit query returns its result", async (t) => {
  const f = await fixture(t);
  f.control.result = b => ({status:"processing",task_id:b.message_id || b.task_id,reply:""});
  await f.bridge.handle(event("official-processing"));
  const record=Object.values(f.store.data.messages)[0];
  assert.equal(record.status,"processing");
  assert.match(f.sent.at(-1).item_list[0].text_item.text,/正在处理/);
  f.control.result=b=>({status:"completed",task_id:b.task_id,reply:"done"});
  await f.bridge.handle(event("official-query","peer-a","/lp status "+record.taskId));
  assert.equal(record.status,"completed");
  assert.equal(f.adapterCalls.filter(c=>c.route==="/messages").length,1);
});

test("official human and timeout states never display model text as a completed task", async (t) => {
  const f = await fixture(t);
  for (const state of ["requires_human","timed_out"]) {
    f.control.result=b=>({status:state,task_id:b.message_id,reply:"model says done"});
    await f.bridge.handle(event("official-"+state));
    assert.equal(Object.values(f.store.data.messages).at(-1).status,state);
    assert.ok(!f.sent.at(-1).item_list[0].text_item.text.includes("已完成"));
  }
});
async function fixture(t, { timeout = 500 } = {}) {
  const directory = fs.mkdtempSync(path.join(os.tmpdir(), "localpilot-ilink-测试 "));
  const store = new State(directory);
  const key = randomBytes(24).toString("hex"), token = randomBytes(24).toString("hex"), approvalKey = randomBytes(24).toString("hex");
  const received = [], adapterCalls = [], sent = [], logs = [];
  const control = { updates: [], login: [{ status: "wait" }, { status: "scaned" }],
    result: (body) => ({ status: "completed", task_id: body.message_id || body.task_id, reply: "files: one.txt" }) };
  const wx = http.createServer(async (req, res) => {
    let raw = "";
    for await (const chunk of req) raw += chunk;
    const body = raw ? JSON.parse(raw) : null;
    received.push({ route: req.url, headers: req.headers, body });
    if (req.url.includes("get_bot_qrcode")) return json(res, { qrcode: "ephemeral-qr", qrcode_img_content: "https://liteapp.weixin.qq.com/q/mock" });
    if (req.url.includes("get_qrcode_status")) return json(res, control.login.shift() || {
      status: "confirmed", bot_token: token, ilink_bot_id: "bot-1", baseurl: base,
    });
    if (req.headers.authorization !== "Bearer " + token) return json(res, {}, 401);
    if (req.url.endsWith("getupdates")) {
      const failure = control.pollFailures?.shift();
      if (failure === "disconnect") return req.socket.destroy();
      if (failure) return json(res, {}, failure);
      if (control.rawBatch) { res.writeHead(200); return res.end(control.rawBatch); }
      return json(res, control.batch || { msgs: control.updates.splice(0), get_updates_buf: "next" });
    }
    if (req.url.endsWith("sendmessage")) {
      sent.push(body.msg);
      if (control.sendLost) return; // Server may have sent it but the response never arrives.
      return json(res, control.sendError || {});
    }
    json(res, {}, 404);
  });
  const adapter = http.createServer(async (req, res) => {
    let raw = "";
    for await (const chunk of req) raw += chunk;
    const body = JSON.parse(raw);
    adapterCalls.push({ route: req.url, body, auth: req.headers.authorization });
    if (req.headers.authorization !== "Bearer " + (req.url === "/tasks/decision" ? approvalKey : key)) return json(res, { status: "error" }, 401);
    if (control.hang) return;
    if (control.redirect) { res.writeHead(302, { Location: "http://127.0.0.1:1" }); return res.end(); }
    const result = control.result(body);
    json(res, result, control.code || (result.status === "pending_approval" && req.url !== "/tasks/query" ? 409 : 200));
  });
  await Promise.all([new Promise((r) => wx.listen(0, "127.0.0.1", r)), new Promise((r) => adapter.listen(0, "127.0.0.1", r))]);
  const base = `http://127.0.0.1:${wx.address().port}`;
  const adapterUrl = `http://127.0.0.1:${adapter.address().port}`;
  store.data.account = { botId: "bot-1", token, baseUrl: base };
  store.save();
  const ilink = new ILink({ baseUrl: base, mock: true, timeout });
  const make = (state = store, allowed = [senderId("peer-a"), senderId("peer-b")], options = {}) => new Bridge(state, ilink,
    { key, allowed, adapterUrl, timeout, emit: (text) => logs.push(text), ...options });
  const bridge = make();
  t.after(() => { store.close(); wx.closeAllConnections(); adapter.closeAllConnections(); wx.close(); adapter.close(); fs.rmSync(directory, { recursive: true, force: true }); });
  return { directory, store, key, token, approvalKey, control, received, adapterCalls, sent, logs, ilink, bridge, make };
}

test("QR wait/scanned/confirmed flow persists credentials without logging them", async (t) => {
  const f = await fixture(t);
  await login(f.ilink, f.store, { emit: (s) => f.logs.push(s), interval: 0 });
  assert.match(f.logs[0], /https:\/\/liteapp.weixin.qq.com/);
  assert.match(f.logs.at(-1), /channel=wechat.ilink./);
  assert.equal(JSON.parse(fs.readFileSync(f.store.file)).account.token, f.token);
  assert.ok(f.received[0].route.endsWith("get_bot_qrcode?bot_type=3"));
  assert.ok(!f.logs.join().includes(f.token));
});
test("QR expiry, unknown and incomplete confirmation never replace saved login", async (t) => {
  const f = await fixture(t);
  for (const result of [{ status: "expired" }, { status: "unexpected", bot_token: f.token }, { status: "confirmed" }]) {
    f.control.login = [result];
    await assert.rejects(login(f.ilink, f.store, { emit: () => {}, interval: 0 }), BridgeError);
    assert.equal(f.store.data.account.token, f.token);
  }
});
test("QR confirmation rejects credential redirects and account replacement", async (t) => {
  const f = await fixture(t);
  for (const patch of [{ baseurl: "https://attacker.invalid" }, { ilink_bot_id: "other-bot" }]) {
    f.control.login = [{ status: "confirmed", bot_token: f.token, ilink_bot_id: "bot-1", ...patch }];
    await assert.rejects(login(f.ilink, f.store, { emit: () => {} }), BridgeError);
  }
});
test("text task traverses mocked iLink and adapter and replies to original peer/context", async (t) => {
  const f = await fixture(t);
  f.control.updates = [event()];
  await f.bridge.poll();
  assert.equal(f.adapterCalls.length, 1);
  const call = f.adapterCalls[0];
  assert.equal(call.route, "/messages");
  assert.equal(call.auth, "Bearer " + f.key);
  assert.equal(call.body.channel, channelId("bot-1"));
  assert.equal(call.body.sender_id, senderId("peer-a"));
  assert.match(call.body.message_id, /^m_[a-f0-9]{64}$/);
  assert.equal(f.sent[0].to_user_id, "peer-a");
  assert.equal(f.sent[0].context_token, "context-peer-a");
  assert.match(f.sent[0].item_list[0].text_item.text, /官方任务结束\nfiles: one.txt/);
  assert.equal(f.store.data.cursor, "next");
});
test("64-bit numeric message IDs remain exact and distinct through HTTP, persistence and dedupe", async (t) => {
  const f = await fixture(t);
  const ids = ["9007199254740992", "9007199254740993"];
  const wire = ids.map((id) => JSON.stringify(event(id)).replace(`"message_id":"${id}"`, `"message_id":${id}`));
  f.control.rawBatch = '{"msgs":[' + wire.join(",") + '],"get_updates_buf":"large-id-cursor"}';
  await f.bridge.poll();
  assert.equal(f.adapterCalls.length, 2);
  assert.notEqual(f.adapterCalls[0].body.message_id, f.adapterCalls[1].body.message_id);
  assert.deepEqual(Object.values(f.store.data.messages).map((record) => record.messageId), ids);
  f.store.close();
  const restored = new State(f.directory);
  try {
    await f.make(restored).poll();
    assert.equal(f.adapterCalls.length, 2);
    assert.equal(f.sent.length, 2);
    assert.deepEqual(Object.values(restored.data.messages).map((record) => record.messageId), ids);
  } finally { restored.close(); }
});
test("empty independent whitelist denies everyone before adapter or reply", async (t) => {
  const f = await fixture(t);
  await f.make(f.store, []).handle(event());
  assert.equal(f.adapterCalls.length, 0);
  assert.equal(f.sent.length, 0);
  assert.deepEqual(f.store.data.peers, [senderId("peer-a")]);
  assert.ok(!f.logs.join().includes("list files"));
});
test("different peers never share identity or reply routing", async (t) => {
  const f = await fixture(t);
  await f.bridge.handle(event("same", "peer-a", "a"));
  await f.bridge.handle(event("same", "peer-b", "b"));
  assert.notEqual(f.adapterCalls[0].body.message_id, f.adapterCalls[1].body.message_id);
  assert.notEqual(f.adapterCalls[0].body.sender_id, f.adapterCalls[1].body.sender_id);
  assert.deepEqual(f.sent.map((m) => [m.to_user_id, m.context_token]), [["peer-a", "context-peer-a"], ["peer-b", "context-peer-b"]]);
});

for (const failure of [503, "disconnect"]) {
  test(`receive reconnect after ${failure} dedupes replayed batches across senders and restart`, async (t) => {
    const f = await fixture(t);
    f.control.result = (body) => ({ status: "completed", task_id: body.message_id, reply: body.text });
    const a1 = { ...event("9007199254740993", "peer-a", "a-first"), context_token: "a-first-context" };
    const b1 = { ...event("9007199254740993", "peer-b", "b-first"), context_token: "b-first-context" };
    const a2 = { ...event("9007199254740994", "peer-a", "a-second"), context_token: "a-second-context" };
    f.control.batch = { msgs: [a1], get_updates_buf: "before-disconnect" };
    await f.bridge.poll();
    f.control.pollFailures = [failure];
    f.control.batch = { msgs: [a1, b1, a2], get_updates_buf: "after-reconnect" };
    const controller = new AbortController();
    t.after(() => controller.abort());
    const send = f.ilink.send.bind(f.ilink);
    f.ilink.send = async (...args) => {
      const result = await send(...args);
      if (f.sent.length === 3) controller.abort();
      return result;
    };
    await f.bridge.run(AbortSignal.any([controller.signal, AbortSignal.timeout(5000)]));
    assert.equal(f.adapterCalls.length, 3);
    assert.deepEqual(f.sent.map((m) => [m.to_user_id, m.context_token]),
      [["peer-a", "a-first-context"], ["peer-b", "b-first-context"], ["peer-a", "a-second-context"]]);
    assert.deepEqual(f.sent.map((m) => m.item_list[0].text_item.text.split("\n")[1]), ["a-first", "b-first", "a-second"]);
    assert.deepEqual(f.received.filter((r) => r.route.endsWith("getupdates")).map((r) => r.body.get_updates_buf),
      ["", "before-disconnect", "before-disconnect"]);
    f.store.close();
    const restored = new State(f.directory);
    try {
      assert.equal(restored.data.cursor, "after-reconnect");
      await f.make(restored).poll();
      assert.equal(f.adapterCalls.length, 3);
      assert.equal(f.sent.length, 3);
      assert.deepEqual(Object.values(restored.data.messages).map((r) => r.messageId),
        ["9007199254740993", "9007199254740993", "9007199254740994"]);
    } finally { restored.close(); }
  });
}

test("unknown sender state and repeated queries stay isolated across restart", async (t) => {
  const f = await fixture(t, { timeout: 30 });
  f.control.hang = true;
  await f.bridge.handle(event("1", "peer-a"));
  const id = f.adapterCalls[0].body.message_id;
  f.control.hang = false;
  await f.bridge.handle(event("1", "peer-b"));
  f.store.close();
  const restored = new State(f.directory);
  try {
    const bridge = f.make(restored);
    f.control.result = (body) => ({ status: "unknown", task_id: body.task_id });
    await bridge.handle(event("q1", "peer-a", "/lp status " + id));
    await bridge.handle(event("q1", "peer-a", "/lp status " + id));
    await bridge.handle(event("q2", "peer-a", "/lp status " + id));
    await bridge.handle(event("q-other", "peer-b", "/lp status " + id));
    await bridge.handle(event("2", "peer-a", "must not execute"));
    f.control.result = (body) => ({ status: "completed", task_id: body.message_id, reply: "b-still-works" });
    await bridge.handle(event("2", "peer-b"));
    assert.deepEqual(f.adapterCalls.map((c) => c.route),
      ["/messages", "/messages", "/tasks/query", "/tasks/query", "/messages"]);
    assert.equal(restored.data.blocked[senderId("peer-a")], true);
    assert.equal(restored.data.blocked[senderId("peer-b")], undefined);
    assert.equal(f.sent.at(-1).to_user_id, "peer-b");
    assert.match(f.sent.at(-1).item_list[0].text_item.text, /b-still-works/);
    assert.match(f.sent.at(-2).item_list[0].text_item.text, /暂停/);
  } finally { restored.close(); }
});

test("mismatched task receipts cannot replace the sender's task mapping or leak a reply", async (t) => {
  const f = await fixture(t);
  await f.bridge.handle(event("1", "peer-b"));
  const otherTask = f.adapterCalls[0].body.message_id;
  f.control.result = () => ({ status: "completed", task_id: otherTask, reply: "WRONG_TASK_RESULT" });
  await f.bridge.handle(event("1", "peer-a"));
  assert.equal(f.store.data.blocked[senderId("peer-a")], true);
  assert.equal(Object.values(f.store.data.messages).find((r) => r.sender === senderId("peer-a")).taskId,
    f.adapterCalls[1].body.message_id);
  assert.ok(!f.sent.at(-1).item_list[0].text_item.text.includes("WRONG_TASK_RESULT"));
});

test("query and decision receipts must match the exact requested task", async (t) => {
  for (const action of ["status", "approve"]) {
    const f = await pendingApproval(t);
    f.control.result = () => ({ status: "completed", task_id: "wrong-task", reply: "WRONG_TASK_RESULT" });
    const command = `/lp ${action} ${f.id}` + (action === "approve" ? " operation-1 decision-1" : "");
    await f.bridge.handle(event("bad-receipt", "peer-a", command));
    assert.equal(f.store.data.blocked[senderId("peer-a")], true);
    assert.match(f.sent.at(-1).item_list[0].text_item.text, /结果未知/);
    assert.ok(!f.sent.at(-1).item_list[0].text_item.text.includes("WRONG_TASK_RESULT"));
    await f.bridge.handle(event("new-task", "peer-a"));
    assert.equal(f.adapterCalls.length, 2);
  }
});

test("only a known same-sender pending task may redirect a new message", async (t) => {
  const f = await pendingApproval(t);
  f.control.result = () => ({ status: "pending_approval", task_id: f.id,
    approval_id: "operation-1", approval: { tool: "apply_patch", target: "test.txt" } });
  await f.bridge.handle(event("second-message", "peer-a"));
  assert.match(f.sent.at(-1).item_list[0].text_item.text, /等待人工审批/);
  assert.equal(f.store.data.blocked[senderId("peer-a")], undefined);
  await f.bridge.handle(event("second-message", "peer-b"));
  assert.match(f.sent.at(-1).item_list[0].text_item.text, /结果未知/);
  assert.equal(f.store.data.blocked[senderId("peer-b")], true);
  f.control.result = () => ({ status: "completed", reply: "MISSING_TASK_RESULT" });
  await f.bridge.handle(event("missing-task", "peer-a"));
  assert.match(f.sent.at(-1).item_list[0].text_item.text, /结果未知/);
  assert.ok(!f.sent.at(-1).item_list[0].text_item.text.includes("MISSING_TASK_RESULT"));
});
test("pending approval is not completed and later explicit query returns final result", async (t) => {
  const f = await fixture(t);
  f.control.result = (body) => ({ status: "pending_approval", task_id: body.message_id });
  await f.bridge.handle(event());
  const id = f.adapterCalls[0].body.message_id;
  assert.match(f.sent[0].item_list[0].text_item.text, /等待人工审批，尚未完成/);
  f.control.result = (body) => ({ status: "completed", task_id: body.task_id, reply: "human approved result" });
  await f.bridge.handle(event("query", "peer-a", "/lp status " + id));
  assert.deepEqual(f.adapterCalls.map((c) => c.route), ["/messages", "/tasks/query"]);
  assert.match(f.sent[1].item_list[0].text_item.text, /human approved result/);
  await f.bridge.handle(event("approve", "peer-a", "/lp approve " + id));
  assert.equal(f.adapterCalls.length, 2);
});
test("querying another sender's task never forwards the query", async (t) => {
  const f = await fixture(t);
  await f.bridge.handle(event());
  await f.bridge.handle(event("query", "peer-b", "/lp status " + f.adapterCalls[0].body.message_id));
  assert.equal(f.adapterCalls.length, 1);
  assert.equal(f.sent[1].to_user_id, "peer-b");
  assert.match(f.sent[1].item_list[0].text_item.text, /失败/);
});
test("adapter restart losing a pending receipt blocks new work instead of rebuilding task", async (t) => {
  const f = await fixture(t);
  f.control.result = (body) => ({ status: "pending_approval", task_id: body.message_id });
  await f.bridge.handle(event());
  const id = f.adapterCalls[0].body.message_id;
  f.control.code = 404;
  f.control.result = () => ({ status: "error" });
  await f.bridge.handle(event("query", "peer-a", "/lp status " + id));
  await f.bridge.handle(event("new"));
  assert.deepEqual(f.adapterCalls.map((c) => c.route), ["/messages", "/tasks/query"]);
  assert.equal(f.store.data.blocked[senderId("peer-a")], true);
});
test("dedupe and reply suppression survive restart and updated context token", async (t) => {
  const f = await fixture(t);
  await f.bridge.handle(event());
  f.store.close();
  const next = new State(f.directory);
  try { await f.make(next).handle({ ...event(), context_token: "new-context" }); }
  finally { next.close(); }
  assert.equal(f.adapterCalls.length, 1);
  assert.equal(f.sent.length, 1);
});
test("changed duplicate blocks sender without another execution", async (t) => {
  const f = await fixture(t);
  await f.bridge.handle(event());
  await f.bridge.handle(event("1", "peer-a", "changed"));
  await f.bridge.handle(event("2"));
  assert.equal(f.adapterCalls.length, 1);
  assert.equal(f.store.data.blocked[senderId("peer-a")], true);
});
test("adapter timeout persists unknown, blocks new submissions but permits safe queries", async (t) => {
  const f = await fixture(t, { timeout: 30 });
  f.control.hang = true;
  await f.bridge.handle(event());
  const id = f.adapterCalls[0].body.message_id;
  assert.match(f.sent[0].item_list[0].text_item.text, /结果未知/);
  f.store.close();
  const next = new State(f.directory);
  try {
    const bridge = f.make(next);
    await bridge.handle(event("2"));
    assert.equal(f.adapterCalls.length, 1);
    f.control.hang = false;
    f.control.code = 404;
    f.control.result = () => ({ status: "error" });
    await bridge.handle(event("q", "peer-a", "/lp status " + id));
    assert.equal(f.adapterCalls[1].route, "/tasks/query");
    assert.equal(next.data.blocked[senderId("peer-a")], true);
  } finally { next.close(); }
});
test("interrupted persisted submission recovers as unknown, never replays", async (t) => {
  const f = await fixture(t);
  const sender = senderId("peer-a");
  const id = "m_" + "a".repeat(64);
  f.store.data.messages[id] = { sender, peer: "peer-a", messageId: "1", taskId: id,
    fingerprint: "b".repeat(64), context: "context", reply: "", status: "submitting", delivery: "sending" };
  f.store.save(); f.store.close();
  const next = new State(f.directory);
  try {
    assert.equal(next.data.messages[id].status, "unknown");
    assert.equal(next.data.messages[id].delivery, "unknown");
    await f.make(next).handle(event());
    assert.equal(f.adapterCalls.length, 0);
  } finally { next.close(); }
});
test("lost send response never resends even on event redelivery", async (t) => {
  const f = await fixture(t, { timeout: 30 });
  f.control.sendLost = true;
  await f.bridge.handle(event());
  await f.bridge.handle(event());
  assert.equal(f.sent.length, 1);
  assert.equal(Object.values(f.store.data.messages)[0].delivery, "unknown");
});
test("iLink HTTP 200 business rejection is not delivery success", async (t) => {
  const f = await fixture(t);
  f.control.sendError = { ret: -2, errmsg: f.token };
  await f.bridge.handle(event());
  assert.equal(Object.values(f.store.data.messages)[0].delivery, "unknown");
  f.control.batch = { errcode: -14, errmsg: f.token };
  await assert.rejects(f.bridge.poll(), { code: "ilink_login_expired" });
  assert.ok(!f.logs.join().includes(f.token));
});
test("rejects groups, media, partial events, missing context and unsafe IDs", async (t) => {
  const f = await fixture(t);
  for (const patch of [{ group_id: "group" }, { message_type: 2 }, { message_state: 1 },
    { item_list: [{ type: 2 }] }, { context_token: undefined }, { message_id: undefined },
    { message_id: Number.MAX_SAFE_INTEGER + 1 }, { to_user_id: "another-bot" }]) {
    await f.bridge.handle({ ...event(), ...patch });
  }
  assert.equal(f.adapterCalls.length, 0);
});
test("state lock, corrupt state, capacity and failed persistence fail closed", async (t) => {
  const f = await fixture(t);
  assert.throws(() => new State(f.directory), { code: "state_locked_operator_required" });
  f.bridge.capacity = 0;
  await assert.rejects(f.bridge.handle(event()), { code: "message_capacity_operator_required" });
  f.bridge.capacity = 4096;
  const save = f.store.save;
  f.store.save = () => { throw new BridgeError("state_save_failed_stop_required"); };
  await assert.rejects(f.bridge.handle(event()));
  assert.equal(f.adapterCalls.length, 0);
  f.store.save = save;
  f.store.close();
  for (const raw of ["broken", JSON.stringify({ ...f.store.data, messages: [] }),
    JSON.stringify({ ...f.store.data, messages: { invalid: { status: "submitting" } } })]) {
    fs.writeFileSync(f.store.file, raw);
    assert.throws(() => new State(f.directory), { code: "state_invalid_operator_required" });
  }
});
test("known credentials never appear in logs, result text, or CLI info", async (t) => {
  const f = await fixture(t);
  f.control.result = (body) => ({ status: "completed", task_id: body.message_id, reply: f.key + " " + f.token });
  await f.bridge.handle(event());
  const text = JSON.stringify(f.sent) + f.logs.join();
  assert.ok(!text.includes(f.key));
  assert.ok(!text.includes(f.token));
  f.store.close();
  const result = spawnSync(process.execPath, ["integrations/wechat-ilink-bridge/cli.mjs", "info"], {
    cwd: new URL("..", import.meta.url), env: { ...process.env, LOCALPILOT_WECHAT_STATE_DIR: f.directory }, encoding: "utf8",
  });
  assert.equal(result.status, 0);
  assert.ok(!result.stdout.includes(f.token));
  assert.ok(!result.stderr.includes(f.token));
  if (process.platform !== "win32") assert.equal(fs.statSync(f.store.file).mode & 0o777, 0o600);
});
test("adapter redirects fail closed and local URL cannot leak key externally", async (t) => {
  const f = await fixture(t);
  for (const adapterUrl of ["https://127.0.0.1", "http://example.com", "http://u:p@127.0.0.1", "http://127.0.0.1/path"]) {
    assert.throws(() => new Bridge(f.store, f.ilink, { key: f.key, adapterUrl }));
  }
  f.control.redirect = true;
  await f.bridge.handle(event());
  assert.equal(f.adapterCalls.length, 1);
  assert.equal(f.store.data.blocked[senderId("peer-a")], true);
});

async function pendingApproval(t, timeout) {
  const f = await fixture(t, { timeout });
  f.bridge = f.make(f.store, undefined, { approvalKey: f.approvalKey, approvers: [senderId("peer-a")] });
  f.control.result = (body) => ({ status: "pending_approval", task_id: body.message_id || body.task_id,
    approval_id: "operation-1", approval: { tool: "apply_patch", target: "test.txt", content: "test" } });
  await f.bridge.handle(event());
  f.id = f.adapterCalls[0].body.message_id;
  return f;
}
test("approval uses independent key, exact operation and decision, duplicate survives restart", async (t) => {
  const f = await pendingApproval(t);
  assert.match(f.sent[0].item_list[0].text_item.text, /operation-1/);
  assert.match(f.sent[0].item_list[0].text_item.text, /test.txt/);
  f.control.result = (body) => ({ status: "completed", task_id: body.task_id, reply: "created" });
  const command = `/lp approve ${f.id} operation-1 approve-1`;
  await f.bridge.handle(event("decision", "peer-a", command));
  assert.equal(f.adapterCalls[1].route, "/tasks/decision");
  assert.equal(f.adapterCalls[1].auth, "Bearer " + f.approvalKey);
  assert.equal(f.adapterCalls[1].body.approval_id, "operation-1");
  assert.equal(f.adapterCalls[1].body.decision_id, "approve-1");
  f.store.close();
  const restored = new State(f.directory);
  try {
    await f.make(restored, undefined, { approvalKey: f.approvalKey, approvers: [senderId("peer-a")] })
      .handle(event("duplicate-new-platform-message", "peer-a", command));
  } finally { restored.close(); }
  assert.equal(f.adapterCalls.length, 2);
  assert.match(f.sent.at(-1).item_list[0].text_item.text, /重复决定/);
});
test("rejection requires reason and returns rejected status and reason without model command", async (t) => {
  const f = await pendingApproval(t);
  await f.bridge.handle(event("missing-reason", "peer-a", `/lp reject ${f.id} operation-1 reject-1`));
  assert.equal(f.adapterCalls.length, 1);
  f.control.result = (body) => ({ status: "rejected", task_id: body.task_id,
    decisions: [{ decision: "reject", outcome: "applied", reason: "不要写入" }] });
  await f.bridge.handle(event("reject", "peer-a", `/lp reject ${f.id} operation-1 reject-2 不要写入`));
  assert.equal(f.adapterCalls[1].body.decision, "reject");
  assert.match(f.sent.at(-1).item_list[0].text_item.text, /操作被拒绝/);
  assert.match(f.sent.at(-1).item_list[0].text_item.text, /不要写入/);
  await f.bridge.handle(event("duplicate-reject", "peer-a", `/lp reject ${f.id} operation-1 reject-2 不要写入`));
  assert.equal(f.adapterCalls.length, 2);
});
test("approval role, ownership, wrong ID and disabled credentials reject before request", async (t) => {
  const f = await pendingApproval(t);
  for (const [id, peer, command] of [["wrong-id", "peer-a", `/lp approve ${f.id} wrong decision-1`],
    ["wrong-role", "peer-b", `/lp approve ${f.id} operation-1 decision-2`]]) {
    await f.bridge.handle(event(id, peer, command));
  }
  f.bridge.approvers.add(senderId("peer-b"));
  await f.bridge.handle(event("wrong-owner", "peer-b", `/lp reject ${f.id} operation-1 decision-3 no`));
  f.bridge.approvers.delete(senderId("peer-a"));
  await f.bridge.handle(event("revoked-role", "peer-a", `/lp approve ${f.id} operation-1 decision-4`));
  await f.make().handle(event("disabled", "peer-a", `/lp approve ${f.id} operation-1 decision-5`));
  assert.equal(f.adapterCalls.length, 1);
});
test("each subsequent operation needs fresh ID and decision ID cannot change action", async (t) => {
  const f = await pendingApproval(t);
  f.control.result = (body) => ({ status: "pending_approval", task_id: body.task_id,
    approval_id: "operation-2", approval: { tool: "apply_patch", target: "second.txt" } });
  await f.bridge.handle(event("first", "peer-a", `/lp approve ${f.id} operation-1 decision-1`));
  await f.bridge.handle(event("stale", "peer-a", `/lp approve ${f.id} operation-1 decision-2`));
  await f.bridge.handle(event("conflict", "peer-a", `/lp reject ${f.id} operation-2 decision-1 no`));
  assert.equal(f.adapterCalls.length, 2);
  f.control.result = (body) => ({ status: "completed", task_id: body.task_id, reply: "done" });
  await f.bridge.handle(event("second", "peer-a", `/lp approve ${f.id} operation-2 decision-3`));
  assert.equal(f.adapterCalls.length, 3);
});
test("decision timeout blocks new IDs, never replays exact decision after restart", async (t) => {
  const f = await pendingApproval(t, 30);
  f.control.hang = true;
  const command = `/lp approve ${f.id} operation-1 timed-1`;
  await f.bridge.handle(event("timeout", "peer-a", command));
  f.store.close();
  const restored = new State(f.directory);
  try {
    const bridge = f.make(restored, undefined, { approvalKey: f.approvalKey, approvers: [senderId("peer-a")] });
    await bridge.handle(event("duplicate", "peer-a", command));
    await bridge.handle(event("new-id", "peer-a", `/lp approve ${f.id} operation-1 timed-2`));
  } finally { restored.close(); }
  assert.equal(f.adapterCalls.length, 2);
  assert.match(f.sent.at(-1).item_list[0].text_item.text, /结果未知/);
});
test("approval auth refusal keeps original task pending, no automatic retries", async (t) => {
  const f = await pendingApproval(t);
  f.control.code = 503;
  f.control.result = () => ({ status: "error" });
  await f.bridge.handle(event("busy", "peer-a", `/lp approve ${f.id} operation-1 busy-1`));
  await f.bridge.handle(event("busy-duplicate", "peer-a", `/lp approve ${f.id} operation-1 busy-1`));
  assert.equal(f.adapterCalls.length, 2);
  assert.equal(f.bridge.task(senderId("peer-a"), f.id).status, "pending_approval");
});
test("approval configuration fails closed and keys are redacted from previews/reasons", async (t) => {
  const f = await pendingApproval(t);
  assert.throws(() => f.make(f.store, undefined, { approvalKey: f.key }));
  assert.throws(() => f.make(f.store, undefined, { approvers: [senderId("peer-a")] }));
  assert.throws(() => f.make(f.store, undefined, { approvalKey: f.approvalKey, approvers: [senderId("outsider")] }));
  f.control.result = (body) => ({ status: "rejected", task_id: body.task_id,
    decisions: [{ decision: "reject", outcome: "applied", reason: f.approvalKey }] });
  await f.bridge.handle(event("secret-reason", "peer-a", `/lp reject ${f.id} operation-1 secret-1 ${f.approvalKey}`));
  assert.ok(!JSON.stringify(f.sent).includes(f.approvalKey));
  assert.ok(!f.logs.join().includes(f.approvalKey));
  assert.ok(!fs.readFileSync(f.store.file, "utf8").includes(f.approvalKey));
});
test("missing or truncated approval details cannot be approved from WeChat", async (t) => {
  const f = await pendingApproval(t);
  for (const [index, approval] of [null, { content: "x".repeat(2000) }].entries()) {
    f.control.result = (body) => ({ status: "pending_approval", task_id: body.task_id, approval_id: "operation-1", approval });
    await f.bridge.handle(event("query-" + index, "peer-a", "/lp status " + f.id));
    const before = f.adapterCalls.length;
    await f.bridge.handle(event("decision-" + index, "peer-a", `/lp approve ${f.id} operation-1 invalid-${index}`));
    assert.equal(f.adapterCalls.length, before);
  }
});

test("retired reconnect message never submits or sends an old reply", async t => {
  const f=await fixture(t), message=event('reconnect-retired');await f.bridge.handle(message);
  const id=Object.keys(f.store.data.messages)[0];assert.ok(id);
  f.store.data.retired={[id]:true};f.store.data.messages={};f.store.save();f.store.close();
  const next=new State(f.directory);f.bridge.store=next;const before=[f.adapterCalls.length,f.sent.length];
  try {await f.bridge.handle(message);assert.deepEqual([f.adapterCalls.length,f.sent.length],before);assert.deepEqual(next.data.messages,{});}
  finally {next.close();}
});
test("retired messages do not appear as newly discovered phone identities", async t => {
  const f=await fixture(t), message=event('reconnect-discovery');await f.bridge.handle(message);
  const id=Object.keys(f.store.data.messages)[0];f.store.data.retired={[id]:true};f.store.data.messages={};f.store.data.peers=[];f.store.save();f.bridge.allowed.clear();
  await f.bridge.handle(message);assert.deepEqual(f.store.data.peers,[]);assert.deepEqual(f.store.data.messages,{});
});

test("a transient QR poll failure preserves the QR and only repeats the read", async (t) => {
  const f = await fixture(t);
  const original = f.ilink.pollLogin.bind(f.ilink);
  let polls = 0;
  f.ilink.pollLogin = (...args) => {
    if (++polls === 1) throw new BridgeError("network_unknown");
    return original(...args);
  };
  await login(f.ilink, f.store, { emit: () => {}, interval: 0 });
  assert.equal(f.received.filter(r => r.route.includes("get_bot_qrcode?")).length, 1);
  assert.equal(f.adapterCalls.length, 0);
  assert.equal(f.store.data.account.token, f.token);
});
