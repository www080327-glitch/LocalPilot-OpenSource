// Official QQ WebSocket opcodes; WebSocket framing/TLS is Node's implementation.
import { QQError } from "./bridge.mjs";

export async function runGateway(client, bridge, signal, { socketFactory = (url) => new WebSocket(url), connectTimeout = 15000 } = {}) {
  if (signal.aborted) return;
  const controller = new AbortController(), active = AbortSignal.any([signal, controller.signal]);
  let socket, pulse, deadline, removeAbort, queue = Promise.resolve();
  try {
    const token = await client.accessToken(active), url = await client.gateway(active);
    await new Promise((resolve, reject) => {
      let settled = false, hello = false, ready = false, awaitingAck = false, sequence = null, pending = 0;
      const stop = (error) => {
        if (settled) return;
        settled = true; controller.abort(); clearInterval(pulse); clearTimeout(deadline);
        try { socket?.close(); } catch { /* No further connection attempts. */ }
        error ? reject(error) : resolve();
      };
      const heartbeat = () => {
        if (awaitingAck) return stop(new QQError("gateway_heartbeat_missing"));
        awaitingAck = true;
        socket.send(JSON.stringify({ op: 1, d: sequence }));
      };
      const aborted = () => stop();
      signal.addEventListener("abort", aborted, { once: true });
      removeAbort = () => signal.removeEventListener("abort", aborted);
      deadline = setTimeout(() => stop(new QQError("gateway_ready_timeout")), connectTimeout);
      socket = socketFactory(url);
      socket.addEventListener("error", () => stop(new QQError("gateway_network_unknown")));
      socket.addEventListener("close", () => stop(new QQError("gateway_disconnected_restart_required")));
      socket.addEventListener("message", (event) => {
        if (settled) return;
        try {
          if (typeof event.data !== "string" || Buffer.byteLength(event.data) > 1_000_000) throw new Error();
          const frame = JSON.parse(event.data);
          if (frame.op === 10) {
            const interval = frame.d?.heartbeat_interval;
            if (hello || !Number.isInteger(interval) || interval < 1000 || interval > 120000) throw new Error();
            hello = true;
            socket.send(JSON.stringify({ op: 2, d: { token: "QQBot " + token, intents: 1 << 25, shard: [0, 1] } }));
            pulse = setInterval(() => { try { heartbeat(); } catch { stop(new QQError("gateway_network_unknown")); } }, interval);
          } else if (frame.op === 11 && hello) awaitingAck = false;
          else if (frame.op === 1 && hello) heartbeat();
          else if (frame.op === 7 || frame.op === 9) stop(new QQError("gateway_session_restart_required"));
          else if (frame.op === 0) {
            if (!hello || !Number.isSafeInteger(frame.s) || frame.s < 0) throw new Error();
            if (frame.t === "READY") {
              if (ready || typeof frame.d?.session_id !== "string" || !frame.d.session_id || frame.d.user?.bot !== true) throw new Error();
              ready = true; sequence = frame.s; clearTimeout(deadline);
              bridge.emit("QQ 网关就绪；只接收私聊文本，不自动审批。");
            } else {
              if (!ready || pending >= 32) throw new Error();
              pending++;
              queue = queue.then(async () => {
                if (!active.aborted) { await bridge.handle(frame, active); sequence = frame.s; }
              }).catch(() => stop(new QQError("gateway_processing_failed_operator_required"))).finally(() => pending--);
            }
          } else throw new Error();
        } catch { stop(new QQError("gateway_protocol_or_queue_rejected")); }
      });
      if (signal.aborted) stop();
    });
  } finally {
    controller.abort(); clearInterval(pulse); clearTimeout(deadline); removeAbort?.();
    try { socket?.close(); } catch { /* Shutdown only. */ }
    await queue; // Persist unknown outcomes before the CLI releases its state lock.
  }
}
