import assert from "node:assert/strict";
import { test } from "node:test";
import { spawn } from "node:child_process";
import { fileURLToPath } from "node:url";

for (const mode of ["auto","SIGINT","SIGTERM"]) {
  test("native loopback WebSocket closes after " + mode,
       {skip:process.platform==="win32" && mode!=="auto" ? "POSIX signals; native Windows signal behavior NOT_RUN" : false,
        timeout:12000}, async () => {
    const env=Object.fromEntries(["PATH","HOME","SystemRoot","WINDIR","TMPDIR","TMP","TEMP","LANG"]
      .filter(name=>process.env[name]!==undefined).map(name=>[name,process.env[name]]));
    const child=spawn(process.execPath,[fileURLToPath(new URL("./channel_native_websocket_fixture.mjs",import.meta.url)),mode],
      {env,stdio:["ignore","pipe","pipe"]});
    let output="",errors="",signalled=false;
    child.stdout.setEncoding("utf8");child.stderr.setEncoding("utf8");
    child.stdout.on("data",chunk=>{
      output+=chunk;
      if (mode!=="auto" && !signalled && output.includes("READY\n")) {
        signalled=true;child.kill(mode);
      }
    });
    child.stderr.on("data",chunk=>{errors+=chunk;});
    const timer=setTimeout(()=>child.kill("SIGKILL"),10000);
    try {
      const result=await new Promise((resolve,reject)=>{
        child.once("error",reject);
        child.once("close",(code,signal)=>resolve({code,signal}));
      });
      assert.deepEqual(result,{code:0,signal:null},errors);
      assert.match(output,/NATIVE_SOCKET_CLOSED/);
      assert.ok(!output.includes("SYNTHETIC_NATIVE_TOKEN"));
      assert.ok(!errors.includes("SYNTHETIC_NATIVE_TOKEN"));
    } finally {clearTimeout(timer);if(child.exitCode===null && child.signalCode===null)child.kill("SIGKILL");}
  });
}
