import { canonicalPath, requireRuntime } from "../channel-common/security.mjs";
import os from "node:os";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { Bridge, QQClient, QQError, State, channelId } from "./bridge.mjs";
import { runGateway } from "./gateway.mjs";
import { progress } from "../channel-common/control.mjs";

const command = process.argv[2];
if (!["run", "info"].includes(command) || process.argv.length !== 3) {
  console.log("用法：node integrations/qq-bridge/cli.mjs run|info");
  process.exitCode = 1;
} else {
  let store;
  const controller = new AbortController();
  process.once("SIGINT", () => controller.abort());
  process.once("SIGTERM", () => controller.abort());
  try {
    try { requireRuntime(); } catch { throw new QQError("node_22_13_or_runtime_features_required"); }
    if (!process.env.LOCALPILOT_QQ_STATE_DIR || (command === "run" && !process.env.LOCALPILOT_MESSAGE_ADAPTER_URL)) {
      throw new QQError("explicit_migration_state_and_adapter_required");
    }
    const directory = canonicalPath(process.env.LOCALPILOT_QQ_STATE_DIR || path.join(os.homedir(), ".localpilot", "qq-bridge"));
    const root = canonicalPath(path.resolve(path.dirname(fileURLToPath(import.meta.url)), "../.."));
    const relative = path.relative(root, directory);
    if (!relative || (!relative.startsWith(".." + path.sep) && relative !== ".." && !path.isAbsolute(relative))) {
      throw new QQError("state_directory_must_be_outside_repository");
    }
    if (command === "info") {
      const data = State.inspect(directory);
      console.log(JSON.stringify({ appIdConfigured: !!process.env.QQ_BOT_APP_ID,
        appSecretConfigured: !!process.env.QQ_BOT_APP_SECRET, messageKeyConfigured: !!process.env.LOCALPILOT_MESSAGE_KEY,
        channel: data.appId ? channelId(data.appId) : null,
        candidateSenders: data.peers, blockedSenders: Object.keys(data.blocked),
        messages: Object.keys(data.messages).length }, null, 2));
    } else {
      const client = new QQClient(process.env.QQ_BOT_APP_ID, process.env.QQ_BOT_APP_SECRET);
      let allowed;
      try { allowed = JSON.parse(process.env.LOCALPILOT_QQ_SENDERS || "[]"); }
      catch { throw new QQError("invalid_sender_json"); }
      store = new State(directory, client.appId);
      progress(store, "connecting");
      const bridge = new Bridge(store, client, { key: process.env.LOCALPILOT_MESSAGE_KEY, allowed,
        adapterUrl: process.env.LOCALPILOT_MESSAGE_ADAPTER_URL,
        emit: text => { if (process.env.LOCALPILOT_CHANNEL_GUI !== "1") console.log(text); if (text.startsWith("QQ 网关就绪")) progress(store, "authenticated"); } });
      console.log("QQ 桥接启动；channel=" + channelId(client.appId) + "；白名单人数=" + allowed.length);
      await runGateway(client, bridge, controller.signal);
    }
  } catch (error) {
    progress(store, error instanceof QQError && ["qq_token_refused", "invalid_qq_credentials"].includes(error.code) ? "auth_expired" : "fault");
    console.error("QQ 桥接停止：" + (error instanceof QQError ? error.code : "local_failure_operator_required"));
    process.exitCode = 1;
  } finally { if (controller.signal.aborted) progress(store, "stopped"); store?.close(); }
}
