// Native Node WebSocket to loopback only. No QQ credential/API connection.
import http from "node:http";
import { createHash } from "node:crypto";
import { runGateway } from "../integrations/qq-bridge/gateway.mjs";
import { requireRuntime } from "../integrations/channel-common/security.mjs";

requireRuntime();
const controller = new AbortController();
process.once("SIGINT", () => controller.abort());
process.once("SIGTERM", () => controller.abort());
const sockets = new Set();
const server = http.createServer();
let nativeSocket, closedResolve;
const closed = new Promise(resolve => { closedResolve = resolve; });
const frame = value => {
  const data = Buffer.from(JSON.stringify(value));
  if (data.length >= 126) throw new Error("fixture_frame_too_large");
  return Buffer.concat([Buffer.from([0x81,data.length]),data]);
};
server.on("upgrade", (req,socket) => {
  sockets.add(socket);
  socket.on("close", () => sockets.delete(socket));
  socket.on("error", () => {});
  const accept = createHash("sha1").update(req.headers["sec-websocket-key"] +
    "258EAFA5-E914-47DA-95CA-C5AB0DC85B11").digest("base64");
  socket.write("HTTP/1.1 101 Switching Protocols\r\nUpgrade: websocket\r\nConnection: Upgrade\r\nSec-WebSocket-Accept: " + accept + "\r\n\r\n");
  socket.write(frame({op:10,d:{heartbeat_interval:1000}}));
  let buffered = Buffer.alloc(0);
  socket.on("data", chunk => {
    buffered = Buffer.concat([buffered,chunk]);
    try {
      while (buffered.length >= 2) {
        const opcode = buffered[0] & 15, masked = (buffered[1]&128)!==0;
        let size = buffered[1]&127, offset = 2;
        if (size===126) {
          if (buffered.length<4) return;
          size=buffered.readUInt16BE(2);offset=4;
        }
        if (size===127 || !masked || size>65535) throw new Error("fixture_frame_rejected");
        if (buffered.length<offset+4+size) return;
        const key=buffered.subarray(offset,offset+4), data=Buffer.from(buffered.subarray(offset+4,offset+4+size));
        buffered=buffered.subarray(offset+4+size);
        for (let i=0;i<data.length;i++) data[i]^=key[i%4];
        if (opcode===8) {socket.end(Buffer.from([0x88,0x00]));return;}
        if (opcode!==1) throw new Error("fixture_opcode_rejected");
        const message=JSON.parse(data);
        if (message.op===2) socket.write(frame({op:0,s:1,t:"READY",d:{session_id:"synthetic-native",user:{bot:true}}}));
        else if (message.op===1) socket.write(frame({op:11}));
        else throw new Error("fixture_message_rejected");
      }
    } catch {socket.destroy();}
  });
});
await new Promise(resolve => server.listen(0,"127.0.0.1",resolve));
const timeout = setTimeout(() => {controller.abort();process.exitCode=2;},8000);
try {
  await runGateway({accessToken:async()=>"SYNTHETIC_NATIVE_TOKEN",gateway:async()=>"wss://api.bot.qq.com/websocket"},
    {emit:()=>{
      process.stdout.write("READY\n");
      if (process.argv[2]==="auto") setTimeout(()=>controller.abort(),30);
    },handle:async()=>{throw new Error("No task should be dispatched");}},controller.signal,{
      socketFactory:()=>{
        nativeSocket=new WebSocket("ws://127.0.0.1:"+server.address().port);
        nativeSocket.addEventListener("close",()=>closedResolve(),{once:true});
        return nativeSocket;
      },
    });
  await Promise.race([closed,new Promise((_,reject)=>setTimeout(()=>reject(new Error("close_handshake_timeout")),2000).unref())]);
  process.stdout.write("NATIVE_SOCKET_CLOSED\n");
} finally {
  clearTimeout(timeout);
  for (const socket of sockets) socket.destroy();
  await new Promise(resolve=>server.close(resolve));
}
