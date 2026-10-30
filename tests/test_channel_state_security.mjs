import assert from "node:assert/strict";
import { test } from "node:test";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { State as QQState } from "../integrations/qq-bridge/bridge.mjs";
import { State as WXState } from "../integrations/wechat-ilink-bridge/bridge.mjs";
import { canonicalPath, requireRuntime } from "../integrations/channel-common/security.mjs";

test("Node runtime features, including precise JSON integer source, are available", () => requireRuntime());

for (const [kind, State] of [["qq", QQState], ["wechat", WXState]]) {
  function fixture(t) {
    const root = fs.mkdtempSync(path.join(os.tmpdir(), "渠道 安全 "));
    t.after(() => fs.rmSync(root, {recursive:true,force:true}));
    return {root, make: directory => kind === "qq" ? new State(directory, "123456789") : new State(directory)};
  }
  test(kind + ": default system temp paths and Unicode work, close cannot remove a successor lock", t => {
    const f = fixture(t);
    const first = f.make(f.root);
    first.close();
    const second = f.make(f.root);
    try {
      first.close();
      assert.equal(fs.existsSync(second.lock), true);
      assert.throws(() => f.make(f.root));
      const before = fs.readFileSync(second.file);
      State.inspect(f.root); // Read-only diagnostics work while the bridge owns its lock.
      assert.deepEqual(fs.readFileSync(second.file), before);
    } finally {second.close();}
  });
  test(kind + ": null/corrupt state is never reset to fresh state", t => {
    const f = fixture(t);
    const state = f.make(f.root);
    state.close();
    fs.writeFileSync(state.file, "null");
    assert.throws(() => f.make(f.root));
    assert.equal(fs.readFileSync(state.file,"utf8"),"null");
  });
  test(kind + ": insecure state directory, file links, hardlinks and parent links are rejected",
      {skip:process.platform === "win32" ? "POSIX permission/symlink matrix; Windows ACL remains NOT_RUN" : false}, t => {
    const f = fixture(t);
    const real = canonicalPath(f.root);
    const loose = path.join(real,"loose");
    fs.mkdirSync(loose,{mode:0o755});fs.chmodSync(loose,0o755);
    assert.throws(() => f.make(loose));
    const alias = path.join(real,"alias");
    fs.symlinkSync(real,alias,"dir");
    assert.throws(() => f.make(path.join(alias,"new-state")));
    assert.equal(fs.existsSync(path.join(real,"new-state")),false);
    for (const link of ["symlink","hardlink","permissions"]) {
      const stateDir = path.join(real,link);
      fs.mkdirSync(stateDir,{mode:0o700});
      const outside = path.join(real,link+".outside");
      fs.writeFileSync(outside,"{}",{mode:0o600});
      const file = path.join(stateDir,"state.json");
      if (link === "symlink") fs.symlinkSync(outside,file);
      else if (link === "hardlink") fs.linkSync(outside,file);
      else fs.writeFileSync(file,"{}",{mode:0o644});
      assert.throws(() => f.make(stateDir));
      assert.equal(fs.readFileSync(outside,"utf8"),"{}");
    }
  });
}
