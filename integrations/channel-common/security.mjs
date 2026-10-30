// No npm dependencies. Fixed Darwin aliases are the only permitted symlinks.
import fs from "node:fs";
import path from "node:path";
import { randomBytes } from "node:crypto";

const aliases = new Map([["/var", "/private/var"], ["/tmp", "/private/tmp"], ["/etc", "/private/etc"]]);
const missing = (error) => error?.code === "ENOENT";
export function redactText(text, secrets) {
  const forms = new Set();
  for (const value of secrets.filter(Boolean)) {
    forms.add(value);
    forms.add(JSON.stringify(value).slice(1,-1));
  }
  for (const value of [...forms].sort((a,b)=>b.length-a.length)) text=text.split(value).join("[REDACTED]");
  return text;
}
function checked(info, directory, privateOnly = false) {
  if (!(directory ? info.isDirectory() : info.isFile()) || (!directory && info.nlink !== 1))
    throw new Error("private_path_type_invalid");
  if (process.platform !== "win32") {
    const uid = process.getuid();
    if (privateOnly ? info.uid !== uid || (info.mode & 0o077) :
      ![0, uid].includes(info.uid) || ((info.mode & 0o022) && !(info.uid === 0 && (info.mode & 0o1000))))
      throw new Error("private_path_permissions_invalid");
  }
}
export function canonicalPath(value) {
  if (typeof value !== "string" || value.split(/[\\/]/).includes("..")) throw new Error("state_parent_traversal_rejected");
  const full = path.resolve(value), root = path.parse(full).root;
  let current = root;
  for (const part of full.slice(root.length).split(path.sep).filter(Boolean)) {
    current = path.join(current, part);
    let info;
    try { info = fs.lstatSync(current); } catch (error) { if (missing(error)) continue; throw error; }
    if (info.isSymbolicLink()) {
      const target = aliases.get(current);
      if (!(process.platform === "darwin" && target && info.uid === 0 && path.resolve(path.dirname(current), fs.readlinkSync(current)) === target))
        throw new Error("state_symlink_rejected");
      current = target;
      const trusted = fs.lstatSync(current);
      if (!trusted.isDirectory() || trusted.uid !== 0 || (trusted.mode & 0o022)) throw new Error("untrusted_system_alias");
    }
  }
  return current;
}
export function privateDirectory(value, create = true) {
  const directory = canonicalPath(value), root = path.parse(directory).root;
  let current = root;
  for (const part of directory.slice(root.length).split(path.sep).filter(Boolean)) {
    current = path.join(current, part);
    let info;
    try { info = fs.lstatSync(current); }
    catch (error) {
      if (!missing(error) || !create) throw error;
      fs.mkdirSync(current, { mode: 0o700 });
      info = fs.lstatSync(current);
    }
    checked(info, true);
  }
  checked(fs.lstatSync(directory), true, true);
  return directory;
}
function privateFile(file) {
  const info = fs.lstatSync(file);
  if (info.isSymbolicLink()) throw new Error("state_symlink_rejected");
  checked(info, false, true);
  return info;
}
export function readPrivateJson(file, fallback) {
  try { privateFile(file); }
  catch (error) { if (missing(error) && fallback !== undefined) return fallback; throw error; }
  const fd = fs.openSync(file, fs.constants.O_RDONLY | (fs.constants.O_NOFOLLOW || 0) | (fs.constants.O_NONBLOCK || 0));
  try {
    const info = fs.fstatSync(fd);
    checked(info, false, true);
    if (info.size > 128 * 1024 * 1024) throw new Error("state_size_exceeded");
    return JSON.parse(fs.readFileSync(fd, "utf8"));
  } finally { fs.closeSync(fd); }
}
export function acquireLock(file) {
  const fd = fs.openSync(file, fs.constants.O_WRONLY | fs.constants.O_CREAT | fs.constants.O_EXCL |
    (fs.constants.O_NOFOLLOW || 0), 0o600);
  try {
    fs.writeFileSync(fd, String(process.pid)); fs.fsyncSync(fd);
    const info = fs.fstatSync(fd); checked(info, false, true);
    return { fd, dev: info.dev, ino: info.ino };
  } catch (error) { fs.closeSync(fd); throw error; }
}
export function releaseLock(file, handle) {
  if (!handle) return;
  try {
    const info = fs.lstatSync(file);
    // An already-closed State must never unlink the next State's live lock.
    if (!info.isSymbolicLink() && info.dev === handle.dev && info.ino === handle.ino) fs.unlinkSync(file);
  } catch (error) { if (!missing(error)) throw error; }
  finally { fs.closeSync(handle.fd); }
}
export function savePrivateJson(directory, file, data, handle) {
  if (!handle) throw new Error("state_closed");
  privateDirectory(directory, false);
  const lock = privateFile(path.join(directory, "bridge.lock"));
  if (lock.dev !== handle.dev || lock.ino !== handle.ino) throw new Error("state_lock_changed");
  try { privateFile(file); } catch (error) { if (!missing(error)) throw error; }
  const temporary = file + "." + randomBytes(8).toString("hex") + ".tmp";
  try {
    const fd = fs.openSync(temporary, "wx", 0o600);
    try { fs.writeFileSync(fd, JSON.stringify(data)); fs.fsyncSync(fd); }
    finally { fs.closeSync(fd); }
    fs.renameSync(temporary, file);
    if (process.platform !== "win32") {
      const fd = fs.openSync(directory, fs.constants.O_RDONLY | (fs.constants.O_NOFOLLOW || 0));
      try { checked(fs.fstatSync(fd), true, true); fs.fsyncSync(fd); }
      finally { fs.closeSync(fd); }
    }
  } finally {
    try { fs.unlinkSync(temporary); } catch (error) { if (!missing(error)) throw error; }
  }
}
export function requireRuntime() {
  const version = process.versions.node.split(".").map(Number);
  if (version[0] < 22 || (version[0] === 22 && version[1] < 13) ||
      typeof WebSocket !== "function" || typeof AbortSignal.any !== "function") throw new Error("node_22_13_required");
  let lexeme;
  JSON.parse('{"message_id":9007199254740993}', (key, value, context) => {
    if (key === "message_id") lexeme = context?.source;
    return value;
  });
  if (lexeme !== "9007199254740993") throw new Error("node_json_source_required");
}
