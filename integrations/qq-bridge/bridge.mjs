import { canonicalPath, privateDirectory, readPrivateJson, acquireLock, releaseLock, savePrivateJson, redactText } from "../channel-common/security.mjs";
import { evidenceOf, evidenceText } from "../channel-common/evidence.mjs";
// Independent QQ bridge. Reuse only the existing proxy-free HTTP transport.
import { requestJson } from "../wechat-ilink-bridge/bridge.mjs";
import fs from "node:fs";
import path from "node:path";
import { createHash, randomBytes } from "node:crypto";

const hash = (value) => createHash("sha256").update(JSON.stringify(value)).digest("hex");
const ID = /^[A-Za-z0-9_.:@-]{1,128}$/;
const PEER = /^[A-Za-z0-9_-]{1,128}$/;
const KEY = /^[!-~]{16,4096}$/;
const statuses = ["submitting", "processing", "requires_human", "timed_out", "completed", "pending_approval", "rejected", "cancelled", "error", "unknown", "blocked"];
export const channelId = (appId) => "qq." + hash(appId).slice(0, 24);
export const senderId = (appId, peer) => "q_" + hash([appId, peer]);
const messageId = (appId, peer, id, index) => "q_m_" + hash([appId, peer, id, index]);
export class QQError extends Error { constructor(code) { super(code); this.code = code; } }

function origin(value, mock = false) {
  const url = new URL(value);
  if (url.username || url.password || url.pathname !== "/" || url.search || url.hash
      || !(url.origin === "https://api.bot.qq.com" || (mock && url.protocol === "http:" && url.hostname === "127.0.0.1"))) {
    throw new QQError("untrusted_qq_origin");
  }
  return url.origin;
}

export class QQClient {
  constructor(appId, secret, { base = "https://api.bot.qq.com", mock = false, timeout = 15000, now = Date.now } = {}) {
    if (typeof appId !== "string" || !/^\d{5,32}$/.test(appId) || typeof secret !== "string" || !KEY.test(secret)) throw new QQError("invalid_qq_credentials");
    this.appId = appId; this.secret = secret; this.base = origin(base, mock);
    this.mock = mock; this.timeout = timeout; this.now = now;
    this.token = null; this.tokens = new Set(); this.expires = 0;
  }
  safe(text) {
    return redactText(text,[this.secret,...this.tokens]);
  }
  async accessToken(signal) {
    if (this.token && this.now() < this.expires - 60000) return this.token;
    const { code, data } = await requestJson(this.base, "/app/getAppAccessToken", { signal, timeout: this.timeout,
      body: { appId: this.appId, clientSecret: this.secret } });
    const seconds = Number(data.expires_in);
    if (code !== 200 || (data.code !== undefined && data.code !== 0) || typeof data.access_token !== "string"
        || !/^[!-~]{1,4096}$/.test(data.access_token) || !Number.isFinite(seconds) || seconds <= 60 || seconds > 7200) {
      throw new QQError("qq_token_refused");
    }
    this.token = data.access_token; this.tokens.add(this.token); this.expires = this.now() + seconds * 1000;
    return this.token;
  }
  async call(route, body, signal) {
    const token = await this.accessToken(signal);
    const result = await requestJson(this.base, route, { method: body === undefined ? "GET" : "POST", body, signal,
      timeout: this.timeout, headers: { Authorization: "QQBot " + token } });
    if (result.code !== 200 || ["code", "err_code"].some((k) => result.data[k] !== undefined && result.data[k] !== 0)) {
      throw new QQError("qq_api_refused");
    }
    return result.data;
  }
  async gateway(signal) {
    const data = await this.call("/gateway/bot", undefined, signal);
    const url = new URL(data.url);
    if (url.protocol !== "wss:" || !["api.bot.qq.com", "api.sgroup.qq.com"].includes(url.hostname) || url.username || url.password
        || (url.port && url.port !== "443") || !/^\/websocket\/?$/.test(url.pathname) || url.search || url.hash
        || data.shards !== 1 || !Number.isSafeInteger(data.session_start_limit?.remaining)
        || data.session_start_limit.remaining <= 0) throw new QQError("qq_gateway_unavailable_or_sharded");
    return url.href;
  }
  async reply(peer, id, text, signal) {
    const data = await this.call("/v2/users/" + encodeURIComponent(peer) + "/messages",
      { msg_type: 0, content: text, msg_id: id, msg_seq: 1 }, signal);
    if (typeof data.id !== "string" || !data.id) throw new QQError("qq_delivery_unknown");
  }
}

function validState(data) {
  const object = (value) => value && typeof value === "object" && !Array.isArray(value);
  return object(data) && (data.retired === undefined || (object(data.retired) && Object.keys(data.retired).length <= 65536 && Object.entries(data.retired).every(([key,value]) => /^q_m_[a-f0-9]{64}$/.test(key) && value === true))) && data.version === 1 && (data.appId === null || (typeof data.appId === "string" && /^\d{5,32}$/.test(data.appId)))
    && object(data.messages) && Object.keys(data.messages).length <= 4096
    && (data.appId !== null || Object.keys(data.messages).length === 0)
    && Object.entries(data.messages).every(([key, r]) => r && typeof r.peer === "string" && PEER.test(r.peer) && typeof r.messageId === "string"
      && (r.index === null || typeof r.index === "string") && key === messageId(data.appId, r.peer, r.messageId, r.index)
      && r.sender === senderId(data.appId, r.peer) && typeof r.taskId === "string" && ID.test(r.taskId)
      && /^[a-f0-9]{64}$/.test(r.fingerprint) && statuses.includes(r.status) && typeof r.reply === "string"
      && Number.isFinite(r.timestamp) && ["not_sent", "sending", "sent", "unknown", "expired"].includes(r.delivery)
      && ["task", "query", "help"].includes(r.kind))
    && object(data.blocked)
    && Object.entries(data.blocked).every(([s, v]) => /^q_[a-f0-9]{64}$/.test(s) && v === true)
    && Array.isArray(data.peers) && data.peers.length <= 128 && data.peers.every((s) => /^q_[a-f0-9]{64}$/.test(s));
}

export class State {
  constructor(directory, appId) {
    try { this.directory = privateDirectory(directory); }
    catch { throw new QQError("state_path_or_permissions_rejected"); }
    this.file = path.join(this.directory, "state.json");
    this.lock = path.join(this.directory, "bridge.lock");
    this.lockHandle = null;
    try { this.lockHandle = acquireLock(this.lock); }
    catch { throw new QQError("state_locked_operator_required"); }
    try {
      this.data = readPrivateJson(this.file, { version: 1, appId: appId || null, messages: {}, blocked: {}, peers: [] });
      if (!validState(this.data) || (appId && this.data.appId && this.data.appId !== appId)) throw new Error();
      if (appId) this.data.appId = appId;
      for (const r of Object.values(this.data.messages)) {
        if (r.status === "submitting") r.status = "unknown";
        if (r.status === "unknown") this.data.blocked[r.sender] = true;
        if (r.delivery === "sending") r.delivery = "unknown";
      }
      this.save();
    } catch { this.close(); throw new QQError("state_invalid_or_different_app"); }
  }
  save() {
    try { savePrivateJson(this.directory, this.file, this.data, this.lockHandle); }
    catch { throw new QQError("state_save_failed_stop_required"); }
  }
  close() {
    const handle = this.lockHandle;
    this.lockHandle = null;
    releaseLock(this.lock, handle);
  }
  static inspect(directory) {
    const file = path.join(privateDirectory(directory, false), "state.json");
    const data = readPrivateJson(file);
    if (!validState(data)) throw new QQError("state_invalid_operator_required");
    return data;
  }
}

export function parseMessage(event, now = Date.now()) {
  const d = event?.d;
  if (event?.op !== 0 || event.t !== "C2C_MESSAGE_CREATE" || !d || d.message_type !== 0 || d.author?.bot
      || typeof d.author?.user_openid !== "string" || !PEER.test(d.author.user_openid) || d.group_openid || d.guild_id
      || (d.attachments !== undefined && (!Array.isArray(d.attachments) || d.attachments.length))
      || d.ark_data || d.msg_elements || typeof d.id !== "string" || !d.id || d.id.length > 512
      || typeof d.content !== "string" || !d.content.trim() || Buffer.byteLength(d.content) > 16000) return null;
  const timestamp = typeof d.timestamp === "string" ? Date.parse(d.timestamp) : NaN;
  // Official pages disagree (5 vs 60 minutes); use the shorter passive reply window.
  if (!Number.isFinite(timestamp) || now - timestamp > 300000 || timestamp - now > 60000) return null;
  const ext = d.message_scene?.ext;
  if (ext !== undefined && (!Array.isArray(ext) || ext.some((x) => typeof x !== "string"))) return null;
  const indices = (ext || []).filter((x) => x.startsWith("msg_idx="));
  if (indices.length > 1 || (indices.length && (indices[0].length <= 8 || indices[0].length > 1024))) return null;
  return { peer: d.author.user_openid, id: d.id, index: indices.length ? indices[0].slice(8) : null, text: d.content, timestamp };
}

export class Bridge {
  constructor(store, client, { key, allowed = [], adapterUrl = "http://127.0.0.1:8003", timeout = 135000, emit = console.log, now = Date.now } = {}) {
    const url = new URL(adapterUrl);
    if (typeof key !== "string" || !KEY.test(key) || key === client.secret || !Array.isArray(allowed)
        || allowed.some((s) => typeof s !== "string" || !/^q_[a-f0-9]{64}$/.test(s))) throw new QQError("invalid_message_key_or_allowlist");
    if (url.protocol !== "http:" || url.hostname !== "127.0.0.1" || url.pathname !== "/" || url.username || url.password || url.search || url.hash) {
      throw new QQError("adapter_must_be_loopback");
    }
    if (store.data.appId !== client.appId) throw new QQError("state_app_mismatch");
    this.store = store; this.client = client; this.key = key; this.allowed = new Set(allowed);
    this.adapterUrl = url.origin; this.timeout = timeout; this.emit = emit; this.now = now;
  }
  safe(text) { return this.client.safe(redactText(text,[this.key])); }
  task(sender, id) { return Object.values(this.store.data.messages).find((r) => r.kind === "task" && r.sender === sender && r.taskId === id); }
  async adapter(route, body, signal) {
    if (Object.values(body).some(value=>typeof value==="string" && this.safe(value)!==value)) throw new QQError("credential_in_input_rejected");
    const { code, data } = await requestJson(this.adapterUrl, route, { body, timeout: this.timeout, signal,
      headers: { Authorization: "Bearer " + this.key } });
    if (![200, 400, 401, 403, 404, 409, 413, 429, 502, 503, 504].includes(code)
        || !statuses.includes(data.status) || ["submitting", "blocked"].includes(data.status)
        || (code !== 200 && !["error", "unknown", "pending_approval"].includes(data.status))) throw new QQError("adapter_outcome_unknown");
    const existing = route === "/messages" && data.status === "pending_approval"
      && this.task(body.sender_id, data.task_id)?.status === "pending_approval";
    if ((data.task_id === undefined && !["error", "unknown"].includes(data.status))
        || (data.task_id !== undefined && (typeof data.task_id !== "string" || !ID.test(data.task_id)
          || (data.task_id !== (body.task_id || body.message_id) && !existing)))) throw new QQError("adapter_task_mismatch");
    const rejection = Array.isArray(data.decisions) ? data.decisions.findLast((d) => d.decision === "reject" && d.outcome === "applied") : null;
    return { ...evidenceOf(data), status: data.status, taskId: data.task_id || body.task_id || body.message_id, httpStatus: code,
      approvalId: typeof data.approval_id === "string" && ID.test(data.approval_id) ? data.approval_id : "",
      rejectionReason: typeof rejection?.reason === "string" ? this.safe(rejection.reason).slice(0, 500) : "",
      reply: typeof data.reply === "string" ? this.safe(data.reply).slice(0, 12000) : "" };
  }
  format(record) {
    const label = { processing: "官方任务正在处理，请查询原任务", requires_human: "等待宿主人工处理，尚未完成", timed_out: "官方任务已超时，不自动重试", completed: "官方任务结束", pending_approval: "等待人工审批，尚未完成", rejected: "操作被拒绝",
      cancelled: "已取消", error: "请求失败，请宿主核实", unknown: "结果未知，请勿重试", blocked: "发送者已暂停，请宿主核实" };
    let text = `LocalPilot ${record.taskId}：${label[record.status] || "状态未知"}`;
    if (["completed", "rejected"].includes(record.status)) text += "\n" + record.reply;
    if (record.status === "rejected" && record.rejectionReason) text += "\n拒绝原因：" + record.rejectionReason;
    if (record.status === "pending_approval") text += "\n请在宿主独立审批端核对具体操作；QQ 不提供批准/拒绝命令。\n操作 ID：" + (record.approvalId || "未提供");
    if (record.kind === "task" || record.kind === "query") text += "\n查询：/lp status " + record.taskId;
    text += evidenceText(record);
    return this.safe(text.length > 3000 ? text.slice(0, 2900) + "\n[结果截断，请宿主查询]" : text);
  }
  async handle(event, signal) {
    const message = parseMessage(event, this.now());
    if (!message) return;
    const { peer, id, index, text, timestamp } = message;
    const sender = senderId(this.client.appId, peer);
    if (this.store.data.retired?.[messageId(this.client.appId, peer, id, index)]) return;
    if (!this.allowed.has(sender)) {
      if (!this.store.data.peers.includes(sender) && this.store.data.peers.length < 128) {
        this.store.data.peers.push(sender); this.store.save(); this.emit("未授权消息已拒绝。候选 sender_id=" + sender);
      }
      return;
    }
    const identity = messageId(this.client.appId, peer, id, index), fingerprint = hash([peer, id, index, text]);
    if (this.store.data.retired?.[identity]) return;
    const old = this.store.data.messages[identity];
    if (old) {
      if (old.fingerprint !== fingerprint) { this.store.data.blocked[sender] = true; this.store.save(); }
      return;
    }
    if (Object.values(this.store.data.messages).some((r) => r.peer === peer && r.messageId === id && (r.index === null) !== (index === null))) {
      this.store.data.blocked[sender] = true; this.store.save(); return;
    }
    if (Object.keys(this.store.data.messages).length >= 4096) throw new QQError("message_capacity_operator_required");
    const record = { peer, sender, messageId: id, index, timestamp, fingerprint, taskId: identity,
      kind: "task", status: "submitting", delivery: "not_sent", reply: "" };
    this.store.data.messages[identity] = record; this.store.save();
    const owner = { channel: channelId(this.client.appId), sender_id: sender };
    const query = /^\/lp status ([A-Za-z0-9_.:@-]{1,128})$/.exec(text.trim());
    if (query) {
      record.kind = "query"; record.taskId = query[1];
      const target = this.task(sender, query[1]);
      if (!target) record.status = "error";
      else {
        try {
          const result = await this.adapter("/tasks/query", { ...owner, task_id: query[1] }, signal);
          if (result.httpStatus === 404 && ["pending_approval", "unknown"].includes(target.status)) result.status = "unknown";
          Object.assign(record, result);
          if (result.httpStatus === 200) Object.assign(target, result);
        } catch { record.status = "unknown"; }
      }
    } else if (text.trim().startsWith("/lp")) {
      record.kind = "help"; record.status = "completed";
      record.reply = "查询：/lp status <任务ID>。QQ 不支持审批命令；请使用宿主独立审批端。";
    } else if (this.store.data.blocked[sender]) record.status = "blocked";
    else {
      try { Object.assign(record, await this.adapter("/messages", { ...owner, message_id: identity, text }, signal)); }
      catch { record.status = "unknown"; }
    }
    if (record.status === "unknown") this.store.data.blocked[sender] = true;
    this.store.save();
    if (this.now() - timestamp > 300000) { record.delivery = "expired"; this.store.save(); return; }
    record.delivery = "sending"; this.store.save();
    try { await this.client.reply(peer, id, this.format(record), signal); record.delivery = "sent"; }
    catch { record.delivery = "unknown"; this.emit("QQ 回复未确认；不自动重发，请用新消息查询任务。"); }
    this.store.save();
  }
}
