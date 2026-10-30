import { canonicalPath, requireRuntime } from "../channel-common/security.mjs";
import os from "node:os";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { Bridge, BridgeError, ILink, State, channelId, login } from "./bridge.mjs";
import { progress } from "../channel-common/control.mjs";

const command = process.argv[2];
if (!["login", "run", "info"].includes(command) || process.argv.length !== 3) {
  console.log("用法：node integrations/wechat-ilink-bridge/cli.mjs login|run|info");
  process.exitCode = 1;
} else {
  let store;
  const controller = new AbortController();
  process.once("SIGINT", () => controller.abort());
  process.once("SIGTERM", () => controller.abort());
  try {
    try { requireRuntime(); } catch { throw new BridgeError("node_22_13_or_runtime_features_required"); }
    if (!process.env.LOCALPILOT_WECHAT_STATE_DIR || (command === "run" && !process.env.LOCALPILOT_MESSAGE_ADAPTER_URL)) {
      throw new BridgeError("explicit_migration_state_and_adapter_required");
    }
    const directory = canonicalPath(process.env.LOCALPILOT_WECHAT_STATE_DIR || path.join(os.homedir(), ".localpilot", "wechat-ilink"));
    const root = canonicalPath(path.resolve(path.dirname(fileURLToPath(import.meta.url)), "../.."));
    const relative = path.relative(root, directory);
    if (!relative || (!relative.startsWith(".." + path.sep) && relative !== ".." && !path.isAbsolute(relative))) {
      throw new BridgeError("state_directory_must_be_outside_repository");
    }
    if (command !== "info") store = new State(directory);
    const ilink = new ILink();
    if (command === "login") await login(ilink, store, { signal: controller.signal,
      emit: process.env.LOCALPILOT_CHANNEL_GUI === "1" ? () => {} : console.log });
    else if (command === "info") {
      const data = State.inspect(directory);
      console.log(JSON.stringify({ loggedIn: !!data.account,
      channel: data.account ? channelId(data.account.botId) : null,
      candidateSenders: data.peers, blockedSenders: Object.keys(data.blocked),
      messages: Object.keys(data.messages).length }, null, 2));
    }
    else {
      let allowed, approvers;
      try {
        allowed = JSON.parse(process.env.LOCALPILOT_WECHAT_SENDERS || "[]");
        approvers = JSON.parse(process.env.LOCALPILOT_WECHAT_APPROVERS || "[]");
      }
      catch { throw new BridgeError("invalid_sender_json"); }
      const bridge = new Bridge(store, ilink, { key: process.env.LOCALPILOT_MESSAGE_KEY, allowed,
        approvalKey: process.env.LOCALPILOT_APPROVAL_KEY, approvers,
        adapterUrl: process.env.LOCALPILOT_MESSAGE_ADAPTER_URL });
      // Process the first authenticated batch too: discarding this response can
      // swallow the exact first message needed for sender discovery.
      await bridge.poll(controller.signal);
      progress(store, "authenticated");
      await bridge.run(controller.signal);
    }
  } catch (error) {
    progress(store, controller.signal.aborted ? "cancelled" : error instanceof BridgeError && error.code === "qr_expired_run_login_again" ? "expired" : error instanceof BridgeError && error.code === "ilink_login_expired" ? "auth_expired" : "fault");
    // Never print remote response bodies, stack traces, URLs with credentials, or raw errors.
    console.error("桥接停止：" + (error instanceof BridgeError ? error.code : "local_failure_operator_required"));
    process.exitCode = 1;
  } finally { if (controller.signal.aborted) progress(store, "cancelled"); store?.close(); }
}
