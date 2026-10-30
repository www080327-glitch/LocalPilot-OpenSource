import assert from "node:assert/strict";
import { test } from "node:test";
import http from "node:http";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { randomBytes } from "node:crypto";
import { spawnSync } from "node:child_process";
import { Bridge, QQClient, State, channelId, senderId, parseMessage } from "../integrations/qq-bridge/bridge.mjs";
import { runGateway } from "../integrations/qq-bridge/gateway.mjs";

const appId = "123456789";
test("quoted credentials are rejected before any Core request and redacted in JSON previews", async t => {
  const f = await fixture(t);
  f.bridge.key = 'SYNTHETIC_quoted"key\\value_123456789';
  await assert.rejects(f.bridge.adapter('/messages',{text:f.bridge.key}),{code:'credential_in_input_rejected'});
  assert.equal(f.adapterCalls.length,0);
  assert.ok(!f.bridge.safe(JSON.stringify({value:f.bridge.key})).includes(JSON.stringify(f.bridge.key).slice(1,-1)));
});
const json = (res, data, code = 200) => { res.writeHead(code); res.end(JSON.stringify(data)); };
const event = (id = "message-1", peer = "peer-a", text = "list files", extra = {}) => ({
  op: 0, s: 2, t: "C2C_MESSAGE_CREATE", d: { id, author: { user_openid: peer, bot: false },
    content: text, message_type: 0, timestamp: new Date().toISOString(), ...extra },
});

test("official queued/running facade status can later be queried without another submission", async (t) => {
  const f = await fixture(t);
  f.control.result = b => ({status:"processing",task_id:b.message_id || b.task_id,reply:""});
  await f.bridge.handle(event("official-processing"));
  const record = Object.values(f.store.data.messages)[0];
  assert.equal(record.status,"processing");
  assert.match(f.qqCalls.at(-1).body.content,/正在处理/);
  f.control.result = b => ({status:"completed",task_id:b.task_id,reply:"done"});
  await f.bridge.handle(event("official-query","peer-a","/lp status "+record.taskId));
  assert.equal(record.status,"completed");
  assert.equal(f.adapterCalls.filter(c=>c.route==="/messages").length,1);
});

test("official human and timeout states stay explicit and are not treated as completed", async (t) => {
  const f = await fixture(t);
  for (const state of ["requires_human","timed_out"]) {
    f.control.result = b => ({status:state,task_id:b.message_id,reply:"model says done"});
    await f.bridge.handle(event("official-"+state));
    assert.equal(Object.values(f.store.data.messages).at(-1).status,state);
    assert.ok(!f.qqCalls.at(-1).body.content.includes("已完成"));
  }
});
async function fixture(t, timeout = 500) {
  const directory = fs.mkdtempSync(path.join(os.tmpdir(), "localpilot-qq-测试 "));
  const secret = randomBytes(24).toString("hex"), token = randomBytes(24).toString("hex"), key = randomBytes(24).toString("hex");
  const qqCalls = [], adapterCalls = [], logs = [];
  const control = { now: Date.now(), result: (body) => ({ status: "completed", task_id: body.message_id || body.task_id, reply: "files: one.txt" }) };
  const qq = http.createServer(async (req, res) => {
    let raw = ""; for await (const chunk of req) raw += chunk;
    const body = raw ? JSON.parse(raw) : null;
    qqCalls.push({ route: req.url, body, auth: req.headers.authorization });
    if (control.redirect) { res.writeHead(302, { Location: "http://127.0.0.1:1" }); return res.end(); }
    if (req.url === "/app/getAppAccessToken") {
      if (body.appId !== appId || body.clientSecret !== secret) return json(res, { code: 100016 });
      return json(res, control.tokenError || { access_token: token, expires_in: "7200" });
    }
    if (req.headers.authorization !== "QQBot " + token) return json(res, { err_code: 11243 }, 401);
    if (req.url === "/gateway/bot") return json(res, control.gateway || {
      url: "wss://api.bot.qq.com/websocket/", shards: 1, session_start_limit: { remaining: 100 },
    }, control.gatewayHttpStatus || 200);
    if (/^\/v2\/users\/[^/]+\/messages$/.test(req.url)) {
      if (control.sendLost) return;
      return json(res, control.sendError || { id: "reply-receipt", timestamp: new Date().toISOString() }, control.sendHttpStatus || 200);
    }
    json(res, {}, 404);
  });
  const adapter = http.createServer(async (req, res) => {
    let raw = ""; for await (const chunk of req) raw += chunk;
    const body = JSON.parse(raw);
    adapterCalls.push({ route: req.url, body, auth: req.headers.authorization });
    control.arrived?.();
    if (req.headers.authorization !== "Bearer " + key) return json(res, { status: "error" }, 401);
    if (control.hang) return;
    if (control.wait) await control.wait(body);
    if (control.adapterRedirect) { res.writeHead(302, { Location: "http://127.0.0.1:1" }); return res.end(); }
    const result = control.result(body);
    json(res, result, control.code || (req.url === "/messages" && result.status === "pending_approval" ? 409 : 200));
  });
  await Promise.all([new Promise((r) => qq.listen(0, "127.0.0.1", r)), new Promise((r) => adapter.listen(0, "127.0.0.1", r))]);
  const client = new QQClient(appId, secret, { base: `http://127.0.0.1:${qq.address().port}`, mock: true, timeout, now: () => control.now });
  const store = new State(directory, appId);
  const make = (state = store, allowed = [senderId(appId, "peer-a"), senderId(appId, "peer-b")]) => new Bridge(state, client,
    { key, allowed, adapterUrl: `http://127.0.0.1:${adapter.address().port}`, timeout, emit: (s) => logs.push(s), now: () => control.now });
  t.after(() => { store.close(); qq.closeAllConnections(); adapter.closeAllConnections(); qq.close(); adapter.close(); fs.rmSync(directory, { recursive: true, force: true }); });
  return { directory, store, make, bridge: make(), client, control, qqCalls, adapterCalls, logs, secret, token, key };
}

test("authenticated QQ API caches and refreshes tokens; business failures and redirects fail closed", async (t) => {
  const f = await fixture(t);
  await f.client.gateway(); await f.client.gateway();
  assert.equal(f.qqCalls.filter((c) => c.route === "/app/getAppAccessToken").length, 1);
  f.control.now += 7200000;
  await f.client.gateway();
  assert.equal(f.qqCalls.filter((c) => c.route === "/app/getAppAccessToken").length, 2);
  f.client.expires = 0; f.control.tokenError = { code: 100016, message: f.secret };
  await assert.rejects(f.client.accessToken(), { code: "qq_token_refused" });
  f.control.redirect = true;
  await assert.rejects(f.client.accessToken());
  assert.ok(!f.logs.join().includes(f.secret));
});

test("rejects unsafe QQ origins, gateway URLs, sharding and message-adapter credential routing", async (t) => {
  const f = await fixture(t);
  assert.throws(() => new QQClient(123456789, f.secret));
  for (const base of ["https://evil.invalid", "http://api.bot.qq.com", "https://u:p@api.bot.qq.com", "https://api.bot.qq.com/path"]) {
    assert.throws(() => new QQClient(appId, f.secret, { base }));
  }
  for (const gateway of [{ url: "wss://evil.invalid", shards: 1, session_start_limit: { remaining: 1 } },
    { url: "wss://api.bot.qq.com/websocket/", shards: 2, session_start_limit: { remaining: 1 } }]) {
    f.control.gateway = gateway; await assert.rejects(f.client.gateway());
  }
  assert.throws(() => new Bridge(f.store, f.client, { key: f.secret }));
  assert.throws(() => new Bridge(f.store, f.client, { key: f.key, adapterUrl: "http://example.com" }));
});

test("gateway accepts exact official hosts with a single shard and available sessions", async (t) => {
  const f = await fixture(t);
  for (const host of ["api.bot.qq.com", "api.sgroup.qq.com"]) {
    for (const suffix of ["/websocket", ":443/websocket/"]) {
      const url = "wss://" + host + suffix;
      f.control.gateway = { url, shards: 1, session_start_limit: { remaining: 1500 } };
      assert.equal(await f.client.gateway(), new URL(url).href);
    }
  }
  assert.equal(f.adapterCalls.length, 0);
});

test("gateway URL restrictions and session limits remain enforced for both official hosts", async (t) => {
  const f = await fixture(t);
  for (const host of ["api.bot.qq.com", "api.sgroup.qq.com"]) {
    const valid = { url: "wss://" + host + "/websocket", shards: 1, session_start_limit: { remaining: 1500 } };
    for (const url of ["ws://" + host + "/websocket", "wss://user:password@" + host + "/websocket",
      "wss://" + host + ":444/websocket", "wss://" + host + "/other", "wss://" + host + "/websocket?token=mock",
      "wss://" + host + "/websocket#fragment", "wss://" + host + ".evil.invalid/websocket",
      "wss://evil." + host + "/websocket"]) {
      f.control.gateway = { ...valid, url };
      await assert.rejects(f.client.gateway(), { code: "qq_gateway_unavailable_or_sharded" });
    }
    for (const shards of [undefined, "1", 0, 2]) {
      f.control.gateway = { ...valid, shards };
      await assert.rejects(f.client.gateway(), { code: "qq_gateway_unavailable_or_sharded" });
    }
    for (const remaining of [undefined, "1500", 0, -1, 1.5]) {
      f.control.gateway = { ...valid, session_start_limit: { remaining } };
      await assert.rejects(f.client.gateway(), { code: "qq_gateway_unavailable_or_sharded" });
    }
  }
  assert.equal(f.adapterCalls.length, 0);
});

test("private text traverses mocked QQ REST and LocalPilot services with original reply ID", async (t) => {
  const f = await fixture(t);
  await f.bridge.handle(event("9007199254740993", "peer-a", "list files", {
    message_scene: { ext: ["msg_idx=index-1", "auth_token=never-forward-scene-secret"] },
  }));
  assert.equal(f.adapterCalls.length, 1);
  assert.equal(f.adapterCalls[0].route, "/messages");
  assert.equal(f.adapterCalls[0].auth, "Bearer " + f.key);
  assert.deepEqual(Object.keys(f.adapterCalls[0].body).sort(), ["channel", "message_id", "sender_id", "text"]);
  assert.equal(f.adapterCalls[0].body.channel, channelId(appId));
  assert.equal(f.adapterCalls[0].body.sender_id, senderId(appId, "peer-a"));
  const sent = f.qqCalls.at(-1);
  assert.equal(sent.route, "/v2/users/peer-a/messages");
  assert.equal(sent.body.msg_id, "9007199254740993");
  assert.equal(sent.body.msg_seq, 1);
  assert.match(sent.body.content, /官方任务结束\nfiles: one.txt/);
  assert.ok(!JSON.stringify(f.adapterCalls).includes("never-forward-scene-secret"));
  assert.ok(!fs.readFileSync(f.store.file, "utf8").includes("never-forward-scene-secret"));
});

test("unauthorized senders are only recorded as hashed candidates, never submitted or replied to", async (t) => {
  const f = await fixture(t);
  await f.make(f.store, []).handle(event());
  assert.equal(f.adapterCalls.length, 0); assert.equal(f.qqCalls.length, 0);
  assert.deepEqual(f.store.data.peers, [senderId(appId, "peer-a")]);
  assert.ok(!f.logs.join().includes("list files"));
});

test("interleaved senders and same opaque IDs never share task identity or reply targets", async (t) => {
  const f = await fixture(t);
  f.control.result = (body) => ({ status: "completed", task_id: body.message_id, reply: body.text });
  for (const [id, peer] of [["same-1", "peer-a"], ["same-1", "peer-b"], ["same-2", "peer-a"], ["same-2", "peer-b"]]) {
    await f.bridge.handle(event(id, peer, peer + id));
  }
  assert.equal(new Set(f.adapterCalls.map((c) => c.body.message_id)).size, 4);
  const sent = f.qqCalls.filter((c) => c.route.includes("/messages"));
  assert.deepEqual(sent.map((c) => c.route), ["/v2/users/peer-a/messages", "/v2/users/peer-b/messages", "/v2/users/peer-a/messages", "/v2/users/peer-b/messages"]);
  assert.ok(sent.every((c) => c.body.content.includes(c.route.includes("peer-a") ? "peer-a" : "peer-b")));
});

test("in-flight duplicates submit once while another sender can finish with its own reply", async (t) => {
  const f = await fixture(t, 2000);
  let release, arrived;
  const waiting = new Promise((resolve) => { release = resolve; });
  const started = new Promise((resolve) => { arrived = resolve; });
  f.control.wait = (body) => body.sender_id === senderId(appId, "peer-a") ? waiting : undefined;
  f.control.arrived = arrived;
  f.control.result = (body) => ({ status: "completed", task_id: body.message_id, reply: body.text });
  const first = f.bridge.handle(event("same", "peer-a", "result-a"));
  try {
    await started;
    await Promise.all([f.bridge.handle(event("same", "peer-a", "result-a")),
      f.bridge.handle(event("same", "peer-b", "result-b"))]);
    assert.equal(f.adapterCalls.length, 2);
    const replies = f.qqCalls.filter((c) => c.route.includes("/messages"));
    assert.equal(replies.length, 1);
    assert.equal(replies[0].route, "/v2/users/peer-b/messages");
    assert.match(replies[0].body.content, /result-b/);
  } finally { release(); await first; }
  const replies = f.qqCalls.filter((c) => c.route.includes("/messages"));
  assert.equal(replies.length, 2);
  assert.equal(replies[1].route, "/v2/users/peer-a/messages");
  assert.match(replies[1].body.content, /result-a/);
});

test("HTTP 503 never retries task submission, QQ delivery or gateway discovery", async (t) => {
  const f = await fixture(t);
  f.control.code = 503; f.control.result = () => ({ status: "error" });
  await f.bridge.handle(event()); await f.bridge.handle(event());
  assert.equal(f.adapterCalls.length, 1);
  assert.equal(Object.values(f.store.data.messages)[0].status, "error");
  assert.equal(Object.values(f.store.data.messages)[0].delivery, "sent");
  f.store.close();
  const restored = new State(f.directory, appId);
  try {
    await f.make(restored).handle(event());
    assert.equal(f.adapterCalls.length, 1);
    f.control.code = 200;
    f.control.result = (body) => ({ status: "completed", task_id: body.message_id, reply: "new task" });
    f.control.sendError = { err_code: 503 };
    // The QQ service returns a real HTTP 503, independently of the adapter response.
    f.control.sendHttpStatus = 503;
    await f.make(restored).handle(event("next"));
    await f.make(restored).handle(event("next"));
    assert.equal(f.adapterCalls.length, 2);
    assert.equal(Object.values(restored.data.messages)[1].delivery, "unknown");
    assert.equal(f.qqCalls.filter((c) => c.route.includes("/messages")).length, 2);
    f.control.gatewayHttpStatus = 503;
    let connections = 0;
    await assert.rejects(runGateway(f.client, f.make(restored), AbortSignal.timeout(2000), {
      socketFactory: () => { connections++; throw new Error("must not connect"); },
    }), { code: "qq_api_refused" });
    assert.equal(connections, 0);
    assert.equal(f.qqCalls.filter((c) => c.route === "/gateway/bot").length, 1);
  } finally { restored.close(); }
});

test("explicit unknown and repeated safe queries never unblock or replay a sender after restart", async (t) => {
  const f = await fixture(t);
  f.control.result = (body) => ({ status: "unknown", task_id: body.message_id });
  await f.bridge.handle(event());
  const id = f.adapterCalls[0].body.message_id;
  f.store.close();
  const restored = new State(f.directory, appId);
  try {
    const bridge = f.make(restored);
    await bridge.handle(event()); await bridge.handle(event("blocked"));
    f.control.result = (body) => ({ status: "completed", task_id: body.task_id || body.message_id, reply: "confirmed result" });
    await bridge.handle(event("query", "peer-a", "/lp status " + id));
    await bridge.handle(event("query", "peer-a", "/lp status " + id));
    await bridge.handle(event("query-again", "peer-a", "/lp status " + id));
    await bridge.handle(event("still-blocked"));
    await bridge.handle(event("new", "peer-b"));
    assert.deepEqual(f.adapterCalls.map((c) => c.route), ["/messages", "/tasks/query", "/tasks/query", "/messages"]);
    assert.equal(restored.data.blocked[senderId(appId, "peer-a")], true);
    assert.equal(bridge.task(senderId(appId, "peer-a"), id).status, "completed");
    assert.equal(JSON.parse(fs.readFileSync(restored.file)).blocked[senderId(appId, "peer-a")], true);
  } finally { restored.close(); }
});

test("result persistence failure after accepted submission recovers unknown without reexecution", async (t) => {
  const f = await fixture(t);
  const save = f.store.save.bind(f.store);
  f.store.save = () => {
    if (Object.values(f.store.data.messages).some((r) => r.status === "completed")) throw new Error("simulated disk failure");
    save();
  };
  await assert.rejects(f.bridge.handle(event()), /simulated disk failure/);
  assert.equal(f.adapterCalls.length, 1);
  assert.equal(f.qqCalls.length, 0);
  assert.equal(Object.values(JSON.parse(fs.readFileSync(f.store.file)).messages)[0].status, "submitting");
  f.store.close();
  const restored = new State(f.directory, appId);
  try {
    await f.make(restored).handle(event());
    await f.make(restored).handle(event("new"));
    assert.equal(f.adapterCalls.length, 1);
    assert.equal(Object.values(restored.data.messages)[0].status, "unknown");
    assert.equal(restored.data.blocked[senderId(appId, "peer-a")], true);
  } finally { restored.close(); }
});

test("dedupe persists across restart and conflicting text pauses only its sender", async (t) => {
  const f = await fixture(t);
  await f.bridge.handle(event());
  f.store.close(); const restored = new State(f.directory, appId);
  try {
    const bridge = f.make(restored);
    await bridge.handle(event());
    assert.equal(f.adapterCalls.length, 1);
    assert.equal(f.qqCalls.filter((c) => c.route.includes("/messages")).length, 1);
    await bridge.handle(event("message-1", "peer-a", "changed"));
    await bridge.handle(event("message-2", "peer-a"));
    await bridge.handle(event("message-2", "peer-b"));
    assert.equal(f.adapterCalls.length, 2);
    assert.equal(restored.data.blocked[senderId(appId, "peer-a")], true);
  } finally { restored.close(); }
});

test("interrupted submission and sending recover as unknown without replay", async (t) => {
  const f = await fixture(t);
  await f.bridge.handle(event());
  const record = Object.values(f.store.data.messages)[0];
  record.status = "submitting"; record.delivery = "sending";
  f.store.save(); f.store.close();
  const restored = new State(f.directory, appId);
  try {
    assert.equal(Object.values(restored.data.messages)[0].status, "unknown");
    assert.equal(Object.values(restored.data.messages)[0].delivery, "unknown");
    await f.make(restored).handle(event());
    await f.make(restored).handle(event("new"));
    assert.equal(f.adapterCalls.length, 1);
    assert.equal(restored.data.blocked[senderId(appId, "peer-a")], true);
  } finally { restored.close(); }
});

test("message index is preserved and changing its presence cannot bypass dedupe", async (t) => {
  const f = await fixture(t);
  for (const index of ["1", "2", "2"]) await f.bridge.handle(event("same", "peer-a", "task", { message_scene: { ext: ["msg_idx=" + index] } }));
  assert.equal(f.adapterCalls.length, 2);
  await f.bridge.handle(event("same"));
  assert.equal(f.adapterCalls.length, 2);
  assert.equal(f.store.data.blocked[senderId(appId, "peer-a")], true);
});

test("pending approval never executes a decision; authorized status query later returns result", async (t) => {
  const f = await fixture(t);
  f.control.result = (body) => ({ status: "pending_approval", task_id: body.message_id, approval_id: "operation-1" });
  await f.bridge.handle(event());
  const id = f.adapterCalls[0].body.message_id;
  assert.match(f.qqCalls.at(-1).body.content, /等待人工审批，尚未完成/);
  await f.bridge.handle(event("approve", "peer-a", "/lp approve " + id + " operation-1 d1"));
  assert.equal(f.adapterCalls.length, 1);
  f.control.result = (body) => ({ status: "completed", task_id: body.task_id, reply: "host approved result" });
  await f.bridge.handle(event("query", "peer-a", "/lp status " + id));
  await f.bridge.handle(event("query", "peer-a", "/lp status " + id));
  await f.bridge.handle(event("other-query", "peer-b", "/lp status " + id));
  assert.deepEqual(f.adapterCalls.map((c) => c.route), ["/messages", "/tasks/query"]);
  assert.match(f.qqCalls.filter((c) => c.route.includes("/messages")).at(-2).body.content, /host approved result/);
});

test("timeouts persist unknown and block new work across restart, but queries and other senders remain safe", async (t) => {
  const f = await fixture(t, 30);
  f.control.hang = true;
  await f.bridge.handle(event());
  const id = f.adapterCalls[0].body.message_id;
  f.store.close(); const restored = new State(f.directory, appId);
  try {
    const bridge = f.make(restored);
    await bridge.handle(event()); await bridge.handle(event("new", "peer-a"));
    assert.equal(f.adapterCalls.length, 1);
    f.control.hang = false; f.control.code = 404; f.control.result = () => ({ status: "error" });
    await bridge.handle(event("query", "peer-a", "/lp status " + id));
    f.control.code = 200;
    f.control.result = (body) => ({ status: "completed", task_id: body.message_id, reply: "b" });
    await bridge.handle(event("new", "peer-b"));
    assert.deepEqual(f.adapterCalls.map((c) => c.route), ["/messages", "/tasks/query", "/messages"]);
    assert.equal(restored.data.blocked[senderId(appId, "peer-a")], true);
  } finally { restored.close(); }
});

test("mismatched receipts and redirects fail closed without forwarding another task's output", async (t) => {
  const f = await fixture(t);
  f.control.result = () => ({ status: "completed", task_id: "wrong-task", reply: "DO_NOT_FORWARD" });
  await f.bridge.handle(event());
  assert.match(f.qqCalls.at(-1).body.content, /结果未知/);
  assert.ok(!f.qqCalls.at(-1).body.content.includes("DO_NOT_FORWARD"));
  f.control.adapterRedirect = true;
  await f.bridge.handle(event("b", "peer-b"));
  assert.equal(f.store.data.blocked[senderId(appId, "peer-b")], true);
});

test("lost QQ replies and business errors are never resent or reported as delivered", async (t) => {
  const f = await fixture(t, 30);
  f.control.sendLost = true;
  await f.bridge.handle(event()); await f.bridge.handle(event());
  assert.equal(f.qqCalls.filter((c) => c.route.includes("/messages")).length, 1);
  assert.equal(Object.values(f.store.data.messages)[0].delivery, "unknown");
  f.control.sendLost = false; f.control.sendError = { err_code: 40034005, message: f.secret };
  await f.bridge.handle(event("second"));
  assert.equal(Object.values(f.store.data.messages)[1].delivery, "unknown");
  assert.ok(!f.logs.join().includes(f.secret));
});

test("parser rejects groups, rich content, numeric IDs, stale and malformed events", () => {
  for (const patch of [{ message_type: 103 }, { attachments: [{}] }, { id: 9007199254740992 },
    { group_openid: "group" }, { timestamp: "invalid" }, { timestamp: "2020-01-01T00:00:00Z" },
    { author: { user_openid: "peer-a", bot: true } }, { author: { user_openid: 123 } },
    { message_scene: { ext: ["msg_idx=1", "msg_idx=2"] } }]) {
    assert.equal(parseMessage(event("1", "peer-a", "text", patch)), null);
  }
  assert.equal(parseMessage({ ...event(), t: "GROUP_AT_MESSAGE_CREATE" }), null);
});

test("expired reply window preserves task result and avoids sending or reexecuting", async (t) => {
  const f = await fixture(t);
  f.control.result = (body) => { f.control.now += 301000; return { status: "completed", task_id: body.message_id, reply: "done" }; };
  await f.bridge.handle(event());
  assert.equal(f.qqCalls.length, 0);
  assert.equal(Object.values(f.store.data.messages)[0].delivery, "expired");
});

test("state lock, app binding, corruption and failed persistence stop before submission", async (t) => {
  const f = await fixture(t);
  assert.throws(() => new State(f.directory, appId), { code: "state_locked_operator_required" });
  const save = f.store.save;
  f.store.save = () => { throw new Error("disk full"); };
  await assert.rejects(f.bridge.handle(event()));
  assert.equal(f.adapterCalls.length, 0);
  f.store.save = save;
  f.store.close();
  assert.throws(() => new State(f.directory, "987654321"), { code: "state_invalid_or_different_app" });
  fs.writeFileSync(f.store.file, "broken");
  assert.throws(() => new State(f.directory, appId), { code: "state_invalid_or_different_app" });
});

test("known credentials never enter logs, persisted results, replies or CLI info", async (t) => {
  const f = await fixture(t);
  await f.client.accessToken();
  f.control.result = (body) => ({ status: "completed", task_id: body.message_id, reply: [f.secret, f.token, f.key].join(" ") });
  await f.bridge.handle(event());
  f.store.close();
  const info = spawnSync(process.execPath, ["integrations/qq-bridge/cli.mjs", "info"], {
    cwd: new URL("..", import.meta.url), env: { ...process.env, LOCALPILOT_QQ_STATE_DIR: f.directory }, encoding: "utf8",
  });
  assert.equal(info.status, 0);
  const output = f.logs.join() + fs.readFileSync(f.store.file, "utf8") + info.stdout + info.stderr + JSON.stringify(f.qqCalls.filter((c) => c.route.includes("/messages")).map((c) => c.body));
  for (const credential of [f.secret, f.token, f.key]) assert.ok(!output.includes(credential));
});

class FakeSocket extends EventTarget {
  constructor(onIdentify, interval = 1000) {
    super(); this.sent = []; this.closed = false;
    this.onIdentify = onIdentify;
    queueMicrotask(() => this.frame({ op: 10, d: { heartbeat_interval: interval } }));
  }
  frame(value) { this.dispatchEvent(new MessageEvent("message", { data: JSON.stringify(value) })); }
  send(raw) { const frame = JSON.parse(raw); this.sent.push(frame); if (frame.op === 2) this.onIdentify(this); }
  close() { if (!this.closed) { this.closed = true; this.dispatchEvent(new Event("close")); } }
  ready() { this.frame({ op: 0, s: 1, t: "READY", d: { session_id: "mock-session", user: { bot: true } } }); }
}

test("mock gateway authenticates before serial processing and keeps original identities", async (t) => {
  const f = await fixture(t), controller = new AbortController();
  let socket;
  const reply = f.client.reply.bind(f.client);
  f.client.reply = async (...args) => { await reply(...args); if (f.adapterCalls.length === 2) controller.abort(); };
  await runGateway(f.client, f.bridge, controller.signal, { socketFactory: () => socket = new FakeSocket((s) => {
    s.ready(); s.frame(event("same", "peer-a")); s.frame({ ...event("same", "peer-b"), s: 3 });
  }) });
  assert.equal(socket.sent[0].op, 2);
  assert.equal(socket.sent[0].d.token, "QQBot " + f.token);
  assert.equal(socket.sent[0].d.intents, 1 << 25);
  assert.deepEqual(f.adapterCalls.map((c) => c.body.sender_id), [senderId(appId, "peer-a"), senderId(appId, "peer-b")]);
});

test("gateway rejects dispatch before READY, invalid sessions and missing heartbeat ACK without retries", async (t) => {
  for (const mode of ["before-ready", "invalid-session", "no-ack"]) {
    const f = await fixture(t);
    let connections = 0;
    await assert.rejects(runGateway(f.client, f.bridge, AbortSignal.timeout(4000), { socketFactory: () => {
      connections++;
      return new FakeSocket((s) => {
        if (mode !== "before-ready") s.ready();
        if (mode === "before-ready") s.frame(event());
        if (mode === "invalid-session") s.frame({ op: 9 });
      });
    } }));
    assert.equal(connections, 1); assert.equal(f.adapterCalls.length, 0);
  }
});

test("gateway burst delivery serializes duplicate messages and keeps each sender's reply target", async (t) => {
  const f = await fixture(t), controller = new AbortController();
  const send = f.client.reply.bind(f.client);
  let replies = 0;
  f.client.reply = async (...args) => { await send(...args); if (++replies === 4) controller.abort(); };
  f.control.result = (body) => ({ status: "completed", task_id: body.message_id, reply: body.text });
  await runGateway(f.client, f.bridge, AbortSignal.any([controller.signal, AbortSignal.timeout(3000)]), {
    socketFactory: () => new FakeSocket((s) => {
      s.ready();
      for (const [i, [id, peer]] of [["same", "peer-a"], ["same", "peer-b"], ["same", "peer-a"],
        ["next", "peer-a"], ["same", "peer-b"], ["next", "peer-b"]].entries()) {
        s.frame({ ...event(id, peer, peer + id), s: i + 2 });
      }
    }),
  });
  assert.equal(replies, 4);
  assert.equal(f.adapterCalls.length, 4);
  assert.equal(new Set(f.adapterCalls.map((c) => c.body.message_id)).size, 4);
  const sent = f.qqCalls.filter((c) => c.route.includes("/messages"));
  assert.deepEqual(sent.map((c) => c.route), ["/v2/users/peer-a/messages", "/v2/users/peer-b/messages",
    "/v2/users/peer-a/messages", "/v2/users/peer-b/messages"]);
  assert.ok(sent.every((c) => c.body.content.includes(c.route.includes("peer-a") ? "peer-a" : "peer-b")));
});

test("manual gateway restart deduplicates replayed events and preserves other senders", async (t) => {
  const f = await fixture(t);
  let socket, connections = 0;
  const send = f.client.reply.bind(f.client);
  f.client.reply = async (...args) => { await send(...args); socket.close(); };
  await assert.rejects(runGateway(f.client, f.bridge, AbortSignal.timeout(3000), {
    socketFactory: () => { connections++; return socket = new FakeSocket((s) => { s.ready(); s.frame(event()); }); },
  }), { code: "gateway_disconnected_restart_required" });
  assert.equal(connections, 1);
  assert.equal(f.adapterCalls.length, 1);
  f.store.close();
  const restored = new State(f.directory, appId), controller = new AbortController();
  try {
    f.client.reply = async (...args) => { await send(...args); if (f.adapterCalls.length === 3) controller.abort(); };
    await runGateway(f.client, f.make(restored), AbortSignal.any([controller.signal, AbortSignal.timeout(3000)]), {
      socketFactory: () => {
        connections++;
        return new FakeSocket((s) => {
          s.ready(); s.frame(event());
          s.frame({ ...event("message-1", "peer-b"), s: 3 });
          s.frame({ ...event("message-2", "peer-a"), s: 4 });
        });
      },
    });
    assert.equal(connections, 2);
    assert.equal(f.adapterCalls.length, 3);
    assert.equal(new Set(f.adapterCalls.map((c) => c.body.message_id)).size, 3);
    assert.deepEqual(f.qqCalls.filter((c) => c.route.includes("/messages")).map((c) => c.route),
      ["/v2/users/peer-a/messages", "/v2/users/peer-b/messages", "/v2/users/peer-a/messages"]);
  } finally { restored.close(); }
});

test("disconnect during submission persists unknown before gateway shutdown; never reconnects automatically", async (t) => {
  const f = await fixture(t);
  let socket;
  f.control.hang = true; f.control.arrived = () => socket.close();
  await assert.rejects(runGateway(f.client, f.bridge, AbortSignal.timeout(4000), {
    socketFactory: () => socket = new FakeSocket((s) => { s.ready(); s.frame(event()); }),
  }), { code: "gateway_disconnected_restart_required" });
  const saved = JSON.parse(fs.readFileSync(f.store.file));
  assert.equal(Object.values(saved.messages)[0].status, "unknown");
  assert.equal(saved.blocked[senderId(appId, "peer-a")], true);
  assert.equal(f.adapterCalls.length, 1);
});

test("retired reconnect message is never resubmitted or redelivered", async t => {
  const f=await fixture(t), message=event('reconnect-retired');
  await f.bridge.handle(message);
  const id=Object.keys(f.store.data.messages)[0];assert.ok(id);
  f.store.data.retired={[id]:true};f.store.data.messages={};f.store.save();f.store.close();
  const next=new State(f.directory,appId);f.bridge.store=next;
  const before=[f.adapterCalls.length,f.qqCalls.length];
  try {await f.bridge.handle(message);assert.deepEqual([f.adapterCalls.length,f.qqCalls.length],before);assert.deepEqual(next.data.messages,{});}
  finally {next.close();}
});
test("retired messages cannot repopulate sender discovery", async t => {
  const f=await fixture(t), message=event('reconnect-discovery');await f.bridge.handle(message);
  const id=Object.keys(f.store.data.messages)[0];f.store.data.retired={[id]:true};f.store.data.messages={};f.store.data.peers=[];f.store.save();f.bridge.allowed.clear();
  await f.bridge.handle(message);assert.deepEqual(f.store.data.peers,[]);assert.deepEqual(f.store.data.messages,{});
});
