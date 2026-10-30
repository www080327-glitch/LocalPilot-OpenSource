import { canonicalPath, privateDirectory, readPrivateJson, acquireLock, releaseLock, savePrivateJson, redactText } from "../channel-common/security.mjs";
import { evidenceOf, evidenceText } from "../channel-common/evidence.mjs";
import { progress } from "../channel-common/control.mjs";
import http from "node:http";
import https from "node:https";
import fs from "node:fs";
import path from "node:path";
import { createHash, randomBytes } from "node:crypto";

export const ILINK_URL = "https://ilinkai.weixin.qq.com";
const ID = /^[A-Za-z0-9_.:@-]{1,128}$/;
const hash = (value) => createHash("sha256").update(JSON.stringify(value)).digest("hex");
export const senderId = (peer) => "s_" + hash(peer);
export const channelId = (bot) => "wechat.ilink." + hash(bot).slice(0, 24);

function validState(data) {
  const object = (value) => value && typeof value === "object" && !Array.isArray(value);
  const sender = (value) => typeof value === "string" && /^s_[a-f0-9]{64}$/.test(value);
  return object(data) && (data.retired === undefined || (object(data.retired) && Object.keys(data.retired).length <= 65536 && Object.entries(data.retired).every(([key,value]) => /^m_[a-f0-9]{64}$/.test(key) && value === true))) && data.version === 1 && typeof data.cursor === "string"
    && (data.account === null || (object(data.account) && typeof data.account.token === "string"
      && /^[!-~]{1,4096}$/.test(data.account.token) && typeof data.account.botId === "string"
      && !!data.account.botId && typeof data.account.baseUrl === "string"))
    && object(data.messages) && Object.keys(data.messages).length <= 4096
    && Object.entries(data.messages).every(([id, item]) => /^m_[a-f0-9]{64}$/.test(id)
      && object(item) && sender(item.sender) && typeof item.peer === "string" && !!item.peer
      && typeof item.messageId === "string" && typeof item.taskId === "string" && ID.test(item.taskId)
      && typeof item.fingerprint === "string" && /^[a-f0-9]{64}$/.test(item.fingerprint)
      && typeof item.context === "string" && typeof item.reply === "string"
      && ["submitting", "processing", "requires_human", "timed_out", "completed", "pending_approval", "rejected", "cancelled", "error", "unknown", "blocked"].includes(item.status)
      && ["not_sent", "sending", "sent", "unknown", "missing_context"].includes(item.delivery))
    && object(data.blocked) && Object.entries(data.blocked).every(([id, value]) => sender(id) && value === true)
    && Array.isArray(data.peers) && data.peers.length <= 128 && data.peers.every(sender);
}

export class BridgeError extends Error {
  constructor(code) { super(code); this.code = code; }
}

function origin(value, local = false, mock = false) {
  let url;
  try { url = new URL(value); } catch { throw new BridgeError("invalid_url"); }
  const loopback = url.protocol === "http:" && url.hostname === "127.0.0.1";
  if (url.username || url.password || url.pathname !== "/" || url.search || url.hash
      || (local ? !loopback : !(mock && loopback) && !(url.protocol === "https:"
        && (!url.port || url.port === "443") && (url.hostname === "ilinkai.weixin.qq.com"
          || url.hostname.endsWith(".weixin.qq.com"))))) throw new BridgeError("untrusted_origin");
  return url.origin;
}

// Direct sockets bypass environment proxies. No redirects or automatic retries.
export function requestJson(base, route, { method = "POST", body, headers = {}, timeout = 15000, signal } = {}) {
  return new Promise((resolve, reject) => {
    const url = new URL(route, base);
    const raw = body === undefined ? undefined : JSON.stringify(body);
    const transport = url.protocol === "https:" ? https : http;
    const req = transport.request(url, { method, agent: false, signal,
      headers: { ...headers, ...(raw === undefined ? {} : {
        "Content-Type": "application/json", "Content-Length": Buffer.byteLength(raw),
      }) } }, (res) => {
      const chunks = [];
      let size = 0;
      res.on("data", (chunk) => {
        size += chunk.length;
        if (size > 1_000_000) req.destroy(new BridgeError("response_limit"));
        else chunks.push(chunk);
      });
      res.on("error", () => reject(new BridgeError("network_unknown")));
      res.on("end", () => {
        try {
          const data = JSON.parse(Buffer.concat(chunks).toString("utf8"), (key, value, context) => {
            if (key !== "message_id" || typeof value !== "number") return value;
            // iLink sends 64-bit integers. Use the source lexeme before Number rounding loses identity.
            if (context?.source && /^[0-9]+$/.test(context.source)) return context.source;
            if (Number.isSafeInteger(value) && value >= 0) return String(value);
            throw new BridgeError("invalid_message_id");
          });
          if (!data || typeof data !== "object" || Array.isArray(data)) throw new Error();
          resolve({ code: res.statusCode, data });
        } catch { reject(new BridgeError("invalid_response")); }
      });
    });
    const timer = setTimeout(() => req.destroy(new BridgeError("timeout_unknown")), timeout);
    req.on("close", () => clearTimeout(timer));
    req.on("error", (error) => reject(error instanceof BridgeError ? error : new BridgeError("network_unknown")));
    req.end(raw);
  });
}

export class ILink {
  constructor({ baseUrl = ILINK_URL, mock = false, timeout = 15000 } = {}) {
    this.baseUrl = origin(baseUrl, false, mock);
    this.mock = mock;
    this.timeout = timeout;
  }
  async call(route, body, account, signal, timeout = this.timeout) {
    const base = account ? origin(account.baseUrl, false, this.mock) : this.baseUrl;
    const headers = account ? { AuthorizationType: "ilink_bot_token", Authorization: "Bearer " + account.token,
      "X-WECHAT-UIN": randomBytes(4).toString("base64") } : { "iLink-App-ClientVersion": "1" };
    const result = await requestJson(base, route, { method: body === undefined ? "GET" : "POST",
      body, headers, signal, timeout });
    if (result.code !== 200) throw new BridgeError("ilink_http_" + result.code);
    for (const field of ["ret", "errcode"]) {
      if (result.data[field] !== undefined && result.data[field] !== 0) {
        throw new BridgeError(result.data[field] === -14 ? "ilink_login_expired" : "ilink_business_error");
      }
    }
    return result.data;
  }
  startLogin(signal) { return this.call("/ilink/bot/get_bot_qrcode?bot_type=3", undefined, undefined, signal); }
  pollLogin(qr, signal) {
    return this.call("/ilink/bot/get_qrcode_status?qrcode=" + encodeURIComponent(qr), undefined, undefined, signal, 40000);
  }
  updates(account, cursor, signal) {
    return this.call("/ilink/bot/getupdates", { get_updates_buf: cursor,
      base_info: { channel_version: "localpilot-ilink/0.1" } }, account, signal, 40000);
  }
  send(account, peer, context, text, signal) {
    return this.call("/ilink/bot/sendmessage", { msg: { from_user_id: "", to_user_id: peer,
      client_id: "lp-" + randomBytes(16).toString("hex"), message_type: 2, message_state: 2,
      context_token: context, item_list: [{ type: 1, text_item: { text } }] },
      base_info: { channel_version: "localpilot-ilink/0.1" } }, account, signal);
  }
}

export class State {
  constructor(directory) {
    try { this.directory = privateDirectory(directory); }
    catch { throw new BridgeError("state_path_or_permissions_rejected"); }
    this.file = path.join(this.directory, "state.json");
    this.lock = path.join(this.directory, "bridge.lock");
    this.lockHandle = null;
    try { this.lockHandle = acquireLock(this.lock); }
    catch { throw new BridgeError("state_locked_operator_required"); }
    try {
      this.data = readPrivateJson(this.file, { version: 1, account: null, cursor: "", messages: {}, blocked: {}, peers: [] });
      if (!validState(this.data)) throw new Error();
      for (const item of Object.values(this.data.messages)) {
        if (item.status === "submitting") { item.status = "unknown"; this.data.blocked[item.sender] = true; }
        if (item.delivery === "sending") item.delivery = "unknown";
      }
      this.save();
    } catch { this.close(); throw new BridgeError("state_invalid_operator_required"); }
  }
  save() {
    try { savePrivateJson(this.directory, this.file, this.data, this.lockHandle); }
    catch { throw new BridgeError("state_save_failed_stop_required"); }
  }
  close() {
    const handle = this.lockHandle;
    this.lockHandle = null;
    releaseLock(this.lock, handle);
  }
  static inspect(directory) {
    const file = path.join(privateDirectory(directory, false), "state.json");
    const data = readPrivateJson(file);
    if (!validState(data)) throw new BridgeError("state_invalid_operator_required");
    return data;
  }
}

const delay = (ms, signal) => new Promise((resolve) => {
  if (signal?.aborted) return resolve();
  const finish = () => { clearTimeout(timer); signal?.removeEventListener("abort", finish); resolve(); };
  const timer = setTimeout(finish, ms);
  signal?.addEventListener("abort", finish, { once: true });
});

export async function login(ilink, store, { emit = console.log, signal, interval = 1500, attempts = 120 } = {}) {
  const deadline = Date.now() + 180000;
  const transient = (error) => error instanceof BridgeError && ["network_unknown", "timeout_unknown", "ilink_http_502", "ilink_http_503", "ilink_http_504"].includes(error.code);
  let qr;
  for (let attempt = 0; attempt < 2; attempt++) {
    try { qr = await ilink.startLogin(signal); break; }
    catch (error) {
      if (!transient(error) || signal?.aborted || attempt === 1) throw error;
      await delay(1000, signal);
    }
  }
  let scan;
  try { scan = new URL(qr.qrcode_img_content); } catch { throw new BridgeError("qr_address_missing"); }
  if (!qr.qrcode || typeof qr.qrcode !== "string" || scan.protocol !== "https:" || scan.username || scan.password
      || !(scan.hostname === "weixin.qq.com" || scan.hostname.endsWith(".weixin.qq.com"))) {
    throw new BridgeError("invalid_qr_response");
  }
  emit("扫码地址（仅在本机打开，请勿转发）：" + scan.href);
  progress(store, "waiting_scan", { login_url: scan.href });
  let consecutiveErrors = 0;
  for (let n = 0; n < attempts && !signal?.aborted && Date.now() < deadline; n++) {
    let result;
    try { result = await ilink.pollLogin(qr.qrcode, signal); consecutiveErrors = 0; }
    catch (error) {
      if (!transient(error) || signal?.aborted || ++consecutiveErrors >= 3) throw error;
      // Polling is read-only: retain the same QR and never replay task/message effects.
      await delay(interval, signal);
      continue;
    }
    if (result.status === "confirmed") {
      if (typeof result.bot_token !== "string" || !/^[!-~]{1,4096}$/.test(result.bot_token)
          || typeof result.ilink_bot_id !== "string" || !result.ilink_bot_id) throw new BridgeError("login_confirmation_incomplete");
      const baseUrl = origin(result.baseurl || ilink.baseUrl, false, ilink.mock);
      if (store.data.account && store.data.account.botId !== result.ilink_bot_id) throw new BridgeError("different_bot_use_new_state_directory");
      store.data.account = { token: result.bot_token, botId: result.ilink_bot_id, baseUrl };
      store.save();
      progress(store, "logged_in");
      emit("登录已保存。LocalPilot channel=" + channelId(result.ilink_bot_id));
      return;
    }
    if (result.status === "expired") throw new BridgeError("qr_expired_run_login_again");
    if (!["wait", "scaned", "scanned"].includes(result.status)) throw new BridgeError("login_status_unknown");
    emit(result.status === "wait" ? "等待扫码" : "已扫码，等待手机确认");
    progress(store, result.status === "wait" ? "waiting_scan" : "waiting_confirmation", { login_url: scan.href });
    await delay(interval, signal);
  }
  throw new BridgeError("login_not_confirmed");
}

export class Bridge {
  constructor(store, ilink, { key, allowed = [], approvalKey, approvers = [], adapterUrl = "http://127.0.0.1:8003", timeout = 135000,
    emit = console.log, capacity = 4096 } = {}) {
    if (typeof key !== "string" || !/^[!-~]{16,}$/.test(key)
        || !Array.isArray(allowed) || allowed.some((s) => typeof s !== "string" || !/^s_[a-f0-9]{64}$/.test(s))) throw new BridgeError("invalid_message_key_or_allowlist");
    if (!store.data.account) throw new BridgeError("login_required");
    this.store = store;
    this.ilink = ilink;
    this.key = key;
    this.allowed = new Set(allowed);
    if (!Array.isArray(approvers) || approvers.some((s) => !this.allowed.has(s))
        || (approvalKey !== undefined && (typeof approvalKey !== "string" || !/^[!-~]{16,}$/.test(approvalKey)
          || approvalKey === key)) || (approvers.length > 0 && !approvalKey)) throw new BridgeError("invalid_approval_key_or_allowlist");
    this.approvalKey = approvalKey;
    this.approvers = new Set(approvers);
    this.adapterUrl = origin(adapterUrl, true);
    this.timeout = timeout;
    this.emit = emit;
    this.capacity = capacity;
  }
  safe(text) {
    return redactText(text,[this.key,this.approvalKey,this.store.data.account.token]);
  }
  async adapter(route, body, signal) {
    if (Object.values(body).some(value=>typeof value==="string" && this.safe(value)!==value)) throw new BridgeError("credential_in_input_rejected");
    const { code, data } = await requestJson(this.adapterUrl, route, { body, timeout: this.timeout, signal,
      headers: { Authorization: "Bearer " + (route === "/tasks/decision" ? this.approvalKey : this.key) } });
    if (![200, 400, 401, 403, 404, 409, 413, 429, 502, 503, 504].includes(code)
        || !["processing", "requires_human", "timed_out", "completed", "pending_approval", "rejected", "cancelled", "error", "unknown"].includes(data.status)
        || (code !== 200 && !["error", "pending_approval", "unknown"].includes(data.status))
        || (data.task_id !== undefined && (typeof data.task_id !== "string" || !ID.test(data.task_id)))) throw new BridgeError("adapter_outcome_unknown");
    // The adapter may return this sender's existing pending task instead of accepting a new message.
    const existingPending = route === "/messages" && data.status === "pending_approval"
      && this.task(body.sender_id, data.task_id)?.status === "pending_approval";
    if ((data.task_id === undefined && !["error", "unknown"].includes(data.status))
        || (data.task_id !== undefined && data.task_id !== (body.task_id || body.message_id) && !existingPending)) {
      throw new BridgeError("adapter_outcome_unknown");
    }
    const hasApproval = data.approval && typeof data.approval === "object" && Object.keys(data.approval).length > 0;
    const preview = data.status === "pending_approval" && hasApproval ? this.safe(JSON.stringify(data.approval)) : "";
    const approvalId = data.status === "pending_approval" && typeof data.approval_id === "string" && ID.test(data.approval_id) ? data.approval_id : "";
    const rejection = Array.isArray(data.decisions) ? data.decisions.findLast((d) => d.decision === "reject" && d.outcome === "applied") : null;
    return { ...evidenceOf(data), status: data.status, taskId: data.task_id, httpStatus: code, approvalId,
      approvalPreview: preview.slice(0, 1600), approvalTruncated: data.status === "pending_approval" && (!hasApproval || preview.length > 1600),
      rejectionReason: typeof rejection?.reason === "string" ? this.safe(rejection.reason).slice(0, 500) : "",
      reply: typeof data.reply === "string" ? this.safe(data.reply).slice(0, 16000) : "" };
  }
  task(sender, id, current) {
    return Object.values(this.store.data.messages).find((r) => r !== current && r.sender === sender
      && r.taskId === id && !r.kind && !r.validationOnly);
  }
  async decide(record, command, owner, signal) {
    const [, action, taskId, approvalId, decisionId, rawReason] = command;
    const reason = (rawReason || "").trim();
    record.kind = "decision";
    record.taskId = taskId;
    record.status = "error";
    if (!this.approvalKey || !this.approvers.has(record.sender)) {
      record.notice = "没有微信审批权限；未转交审批。"; return;
    }
    if (reason.length > 500 || (action === "reject" && !reason)) {
      record.notice = "拒绝必须填写原因，原因最多 500 字符；未转交审批。"; return;
    }
    const fingerprint = hash([taskId, approvalId, action, reason]);
    const previous = Object.values(this.store.data.messages).find((r) => r !== record
      && r.sender === record.sender && r.decisionId === decisionId);
    record.decisionId = decisionId;
    record.decisionFingerprint = fingerprint;
    if (previous) {
      if (previous.decisionFingerprint !== fingerprint) { record.notice = "决定 ID 内容冲突；未转交审批。"; return; }
      for (const field of ["status", "reply", "approvalId", "approvalPreview", "approvalTruncated", "rejectionReason", "httpStatus"]) {
        if (previous[field] !== undefined) record[field] = previous[field];
      }
      record.notice = "重复决定：返回原决定回执，未再次执行。最新状态请查询任务。";
      return;
    }
    if (this.store.data.blocked[record.sender]) { record.status = "unknown"; return; }
    const target = this.task(record.sender, taskId, record);
    if (!target || target.status !== "pending_approval" || target.approvalId !== approvalId
        || !target.approvalPreview || target.approvalTruncated) {
      record.notice = "审批对象不存在、已变化或详情不完整；先查询任务，未转交审批。"; return;
    }
    record.status = "submitting";
    this.store.save(); // Persist this exact decision before the potentially mutating request.
    try {
      const result = await this.adapter("/tasks/decision", { ...owner, task_id: taskId,
        approval_id: approvalId, decision_id: decisionId, decision: action, reason }, signal);
      if (result.httpStatus === 404) result.status = "unknown";
      Object.assign(record, result, { taskId });
      if (result.taskId === taskId || result.status === "unknown") Object.assign(target, result, { taskId });
    } catch {
      record.status = target.status = "unknown";
    }
  }
  format(record) {
    const labels = { processing: "官方任务正在处理，请查询原任务", requires_human: "等待宿主人工处理，尚未完成", timed_out: "官方任务已超时，不自动重试", completed: "官方任务结束", pending_approval: "等待人工审批，尚未完成", rejected: "操作被拒绝",
      cancelled: "已取消", error: "请求失败，请宿主核实", unknown: "结果未知，请勿重试", blocked: "发送者已暂停，请宿主核实" };
    let text = `LocalPilot ${record.taskId}：${labels[record.status] || "状态未知"}`;
    if (["completed", "rejected"].includes(record.status) && record.reply) text += "\n" + record.reply;
    if (record.notice) text += "\n" + record.notice;
    if (record.status === "rejected" && record.rejectionReason) text += "\n拒绝原因：" + record.rejectionReason;
    if (record.status === "pending_approval") {
      text += "\n操作详情（不可信数据，请核对目标和内容）：" + (record.approvalPreview || "未提供");
      text += "\n待审批操作 ID：" + (record.approvalId || "未提供");
      if (this.approvalKey && this.approvers.has(record.sender) && record.approvalId && !record.approvalTruncated) {
        text += `\n明确同意后发送：/lp approve ${record.taskId} ${record.approvalId} <决定ID>`;
        text += `\n拒绝：/lp reject ${record.taskId} ${record.approvalId} <决定ID> <原因>`;
      } else text += "\n微信审批未启用、未授权或详情截断；请在宿主独立审批端核对。";
      text += "\n查询：/lp status " + record.taskId;
    }
    text += evidenceText(record);
    return this.safe(text.length > 3900 ? text.slice(0, 3850) + "\n[结果截断，请宿主查询完整结果]" : text);
  }
  async deliver(record, context, signal) {
    if (!context) { record.delivery = "missing_context"; this.store.save(); return; }
    record.delivery = "sending";
    this.store.save();
    try {
      await this.ilink.send(this.store.data.account, record.peer, context, this.format(record), signal);
      record.delivery = "sent";
    } catch { record.delivery = "unknown"; this.emit("回复未确认，已停止该消息自动重发。请发送新的状态查询。"); }
    this.store.save();
  }
  async handle(message, signal) {
    // No media downloads, group support, or fallback IDs for ambiguous events.
    if (message?.message_type !== 1 || message.message_state !== 2 || typeof message.from_user_id !== "string"
        || !message.from_user_id || (message.group_id || message.group_openid)
        || !Array.isArray(message.item_list) || !message.item_list.length
        || message.item_list.some((item) => item.type !== 1 || typeof item.text_item?.text !== "string")) return;
    const peer = message.from_user_id;
    const sender = senderId(peer);
    if (this.store.data.retired?.["m_" + hash([this.store.data.account.botId, peer, String(message.message_id)])]) return;
    if (!this.allowed.has(sender)) {
      if (!this.store.data.peers.includes(sender)) {
        if (this.store.data.peers.length < 128) this.store.data.peers.push(sender);
        this.store.save();
        this.emit("未授权消息已拒绝。候选 sender_id=" + sender);
      }
      return;
    }
    const account = this.store.data.account;
    if (message.to_user_id && message.to_user_id !== account.botId) return;
    const rawId = message.message_id;
    if (!((typeof rawId === "string" && rawId) || (Number.isSafeInteger(rawId) && rawId > 0))) return;
    const text = message.item_list.map((item) => item.text_item.text).join("");
    if (!text.trim() || Buffer.byteLength(text) > 16000) return;
    const context = typeof message.context_token === "string" && message.context_token.length <= 16000 ? message.context_token : "";
    if (!context) { this.emit("消息缺少回复上下文，未提交任务。"); return; }
    const taskId = "m_" + hash([account.botId, peer, String(rawId)]);
    const fingerprint = hash([peer, String(rawId), text]);
    if (this.store.data.retired?.[taskId]) return;
    const old = this.store.data.messages[taskId];
    if (old) {
      if (old.fingerprint !== fingerprint) { this.store.data.blocked[sender] = true; this.store.save(); }
      return; // Neither execution nor delivery is replayed, including after restart.
    }
    if (Object.keys(this.store.data.messages).length >= this.capacity) throw new BridgeError("message_capacity_operator_required");
    const record = { sender, peer, messageId: String(rawId), taskId, fingerprint, context,
      status: "submitting", delivery: "not_sent", reply: "" };
    this.store.data.messages[taskId] = record;
    this.store.save(); // Must succeed before any LocalPilot request.
    const query = /^\/lp status ([A-Za-z0-9_.:@-]{1,128})$/.exec(text.trim());
    const decision = /^\/lp (approve|reject) ([A-Za-z0-9_.:@-]{1,128}) ([A-Za-z0-9_.:@-]{1,128}) ([A-Za-z0-9_.:@-]{1,128})(?:\s+([\s\S]+))?$/.exec(text.trim());
    const owner = { channel: channelId(account.botId), sender_id: sender };
    if (decision) {
      await this.decide(record, decision, owner, signal);
    } else if (text.trim().startsWith("/lp") && !query) {
      record.status = "completed";
      record.reply = "查询：/lp status <任务ID>；批准：/lp approve <任务ID> <操作ID> <决定ID>；拒绝：/lp reject <任务ID> <操作ID> <决定ID> <原因>。必须逐项核对操作，不自动批准。";
    } else if (query) {
      record.kind = "query";
      const target = this.task(sender, query[1], record);
      if (!target) { record.status = "error"; }
      else {
        try {
          const result = await this.adapter("/tasks/query", { ...owner, task_id: query[1] }, signal);
          // A missing adapter receipt after restart must never trigger resubmission.
          if (result.httpStatus === 404 && ["pending_approval", "unknown", "submitting"].includes(target.status)) result.status = "unknown";
          Object.assign(record, result, { taskId: query[1] });
          if (result.httpStatus === 200) Object.assign(target, result, { taskId: query[1] });
        } catch { record.status = "unknown"; }
      }
    } else if (this.store.data.blocked[sender]) {
      record.status = "blocked";
    } else {
      try {
        const result = await this.adapter("/messages", { ...owner, message_id: taskId, text }, signal);
        Object.assign(record, result, { taskId: result.taskId || taskId });
      } catch { record.status = "unknown"; }
    }
    if (record.status === "unknown") this.store.data.blocked[sender] = true;
    this.store.save();
    await this.deliver(record, context, signal);
  }
  async poll(signal) {
    const batch = await this.ilink.updates(this.store.data.account, this.store.data.cursor, signal);
    if (batch.msgs !== undefined && !Array.isArray(batch.msgs)) throw new BridgeError("invalid_updates");
    for (const message of batch.msgs || []) await this.handle(message, signal);
    if (typeof batch.get_updates_buf === "string") {
      this.store.data.cursor = batch.get_updates_buf;
      this.store.save();
    }
  }
  async run(signal) {
    this.emit("桥接运行中；channel=" + channelId(this.store.data.account.botId) + "；白名单人数=" + this.allowed.size);
    let failures = 0;
    while (!signal.aborted) {
      try { await this.poll(signal); failures = 0; progress(this.store, "authenticated"); await delay(1000, signal); }
      catch (error) {
        if (signal.aborted) break;
        if (["network_unknown", "timeout_unknown", "ilink_http_502", "ilink_http_503", "ilink_http_504"].includes(error.code)) {
          this.emit("轮询暂不可用；只重试接收，不重放任务或回复。");
          progress(this.store, "UNKNOWN");
          await delay(Math.min(30000, 1000 * 2 ** Math.min(failures++, 5)), signal);
        } else { throw error; }
      }
    }
  }
}
