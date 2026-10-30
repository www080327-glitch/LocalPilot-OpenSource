// Private UI progress only. No message bodies, tokens or remote error text.
import path from "node:path";
import { savePrivateJson } from "./security.mjs";
export function progress(store, status, extra = {}) {
  if (process.env.LOCALPILOT_CHANNEL_GUI !== "1" || !store?.lockHandle) return;
  savePrivateJson(store.directory, path.join(store.directory, "connection.json"),
    { status, pid: process.pid, observed: Date.now(), ...extra }, store.lockHandle);
}
