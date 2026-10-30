//! Read-only desktop maintenance. No filesystem mutation or arbitrary URL/path IPC.
use semver::Version;
use serde_json::{json, Value};
use sha2::{Digest, Sha256};
use std::{
    collections::HashSet,
    fs,
    io::Read,
    os::unix::fs::MetadataExt,
    path::{Path, PathBuf},
    process::{Command, Stdio},
    sync::Mutex,
    time::{Duration, Instant, SystemTime, UNIX_EPOCH},
};
use tauri::State;

const REPO: &str = "https://github.com/www080327-glitch/LocalPilot";
const RELEASES: &str = "https://api.github.com/repos/www080327-glitch/LocalPilot/releases";
const MAX_BODY: usize = 4 * 1024 * 1024;
#[derive(Default)]
pub struct Maintenance {
    pub latest: Mutex<Value>,
}
fn stamp() -> u64 {
    SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .unwrap_or_default()
        .as_secs()
}
fn home() -> Result<PathBuf, String> {
    std::env::var_os("HOME")
        .map(PathBuf::from)
        .ok_or("用户目录不可用".into())
}
fn run(mut cmd: Command, timeout: u64, cap: usize) -> Result<String, String> {
    let mut child = cmd
        .stdin(Stdio::null())
        .stdout(Stdio::piped())
        .stderr(Stdio::null())
        .spawn()
        .map_err(|_| "无法启动只读系统工具")?;
    let stdout = child.stdout.take().ok_or("系统工具输出不可读")?;
    let reader = std::thread::spawn(move || {
        let mut bytes = Vec::new();
        let _ = stdout.take(cap as u64 + 1).read_to_end(&mut bytes);
        bytes
    });
    let start = Instant::now();
    let status = loop {
        match child.try_wait() {
            Ok(Some(s)) => break s,
            Ok(None) if start.elapsed() < Duration::from_secs(timeout) => {
                std::thread::sleep(Duration::from_millis(50))
            }
            _ => {
                let _ = child.kill();
                let _ = child.wait();
                let _ = reader.join();
                return Err("只读工具超时或失败；状态 UNKNOWN".into());
            }
        }
    };
    let bytes = reader.join().map_err(|_| "工具输出中断")?;
    if !status.success() || bytes.len() > cap {
        return Err("工具失败、未登录或响应超限；状态 UNKNOWN".into());
    }
    String::from_utf8(bytes).map_err(|_| "输出格式无效".into())
}
fn gh() -> Result<PathBuf, String> {
    for p in [
        PathBuf::from("/opt/homebrew/bin/gh"),
        PathBuf::from("/usr/local/bin/gh"),
        home()?.join("homebrew/bin/gh"),
        home()?.join(".local/bin/gh"),
    ] {
        if p.is_file() {
            return Ok(p);
        }
    }
    Err("未安装 GitHub CLI；请在可信终端安装并 gh auth login，或手动打开 Release".into())
}
fn tag_version(tag: &str) -> Option<Version> {
    let v = Version::parse(tag.strip_prefix("desktop-v")?).ok()?;
    (v.pre.is_empty() && v.build.is_empty()).then_some(v)
}
fn release_url(s: &str) -> bool {
    let Ok(u) = reqwest::Url::parse(s) else {
        return false;
    };
    u.scheme() == "https"
        && u.host_str() == Some("github.com")
        && u.port().is_none()
        && u.username().is_empty()
        && u.password().is_none()
        && u.query().is_none()
        && u.fragment().is_none()
        && u.path()
            .starts_with("/www080327-glitch/LocalPilot/releases/")
        && !u.path().contains("..")
}
fn select_release(rows: &Value, current: &str) -> Result<Value, String> {
    let list = rows.as_array().ok_or("GitHub Release JSON 格式错误")?;
    let mut candidates = list
        .iter()
        .filter_map(|r| {
            if r["draft"] != false || r["prerelease"] != false {
                return None;
            }
            let v = tag_version(r["tag_name"].as_str()?)?;
            Some((v, r))
        })
        .collect::<Vec<_>>();
    candidates.sort_by(|a, b| b.0.cmp(&a.0));
    let (version, r) = candidates
        .first()
        .ok_or("未发现正式 Desktop Release；Core/Suite Release 不参与 GUI 更新")?;
    let tag = r["tag_name"].as_str().ok_or("Release 缺少 tag")?;
    let url = format!("{REPO}/releases/tag/{tag}");
    if r["html_url"].as_str() != Some(url.as_str()) {
        return Err("Release 来源不匹配".into());
    }
    let assets = r["assets"]
        .as_array()
        .ok_or("Release 缺少制品")?
        .iter()
        .filter_map(|a| {
            let name = a["name"].as_str()?;
            let allowed = [
                format!("LocalPilot-{version}-arm64.dmg"),
                format!("LocalPilot-{version}-arm64.app.zip"),
            ];
            if !allowed.iter().any(|n| n == name) {
                return None;
            }
            let expected = format!("{REPO}/releases/download/{tag}/{name}");
            if a["browser_download_url"].as_str() != Some(expected.as_str())
                || !release_url(&expected)
            {
                return None;
            }
            let sha = a["digest"]
                .as_str()
                .and_then(|s| s.strip_prefix("sha256:"))
                .filter(|s| s.len() == 64 && s.bytes().all(|c| c.is_ascii_hexdigit()));
            Some(json!({"name":name,"url":expected,"bytes":a["size"],"sha256":sha}))
        })
        .collect::<Vec<_>>();
    if assets.is_empty() {
        return Err("Release 无有效 macOS arm64 GUI 制品".into());
    }
    let current = Version::parse(current).map_err(|_| "当前 GUI 版本无效")?;
    Ok(
        json!({"status":if *version>current{"UPDATE_AVAILABLE"}else if *version==current{"CURRENT"}else{"LOCAL_AHEAD"},"version":version.to_string(),"tag":tag,"url":url,"published_at":r["published_at"],"notes":r["body"].as_str().unwrap_or("暂无更新日志").chars().take(20000).collect::<String>(),"assets":assets}),
    )
}
async fn public_releases() -> Result<Value, String> {
    let client = reqwest::Client::builder()
        .redirect(reqwest::redirect::Policy::none())
        .connect_timeout(Duration::from_secs(5))
        .timeout(Duration::from_secs(15))
        .build()
        .map_err(|_| "GitHub 网络初始化失败")?;
    let mut all = Vec::new();
    for page in 1..=10 {
        let res = client
            .get(format!("{RELEASES}?per_page=100&page={page}"))
            .header("User-Agent", "LocalPilot-Desktop-Version-Check")
            .header("Accept", "application/vnd.github+json")
            .send()
            .await
            .map_err(|_| "GitHub 网络连接失败；状态 UNKNOWN，请检查网络后重试")?;
        let status = res.status();
        if !status.is_success() {
            return Err(format!("GitHub HTTP {}；无法确认最新版本。404 可能需要私有仓库权限；可主动使用本机 GitHub 登录。",status.as_u16()));
        }
        let mut stream = res.bytes_stream();
        let mut bytes = Vec::new();
        use futures_util::StreamExt;
        while let Some(part) = stream.next().await {
            let part = part.map_err(|_| "GitHub 响应中断")?;
            if bytes.len() + part.len() > MAX_BODY {
                return Err("GitHub 响应超过上限".into());
            }
            bytes.extend_from_slice(&part);
        }
        let value: Value = serde_json::from_slice(&bytes).map_err(|_| "GitHub 响应 JSON 无效")?;
        let rows = value.as_array().ok_or("GitHub Release 列表格式无效")?;
        all.extend(rows.iter().cloned());
        if rows.len() < 100 {
            return Ok(json!(all));
        }
    }
    Err("Release 分页超过 1000 条；无法完整确认最新版本".into())
}
async fn load_releases(authenticated: bool) -> Result<Value, String> {
    if !authenticated {
        return public_releases().await;
    }
    tauri::async_runtime::spawn_blocking(|| {
        let mut all = Vec::new();
        for page in 1..=10 {
            let mut cmd = Command::new(gh()?);
            cmd.args([
                "api",
                "--hostname",
                "github.com",
                &format!("repos/www080327-glitch/LocalPilot/releases?per_page=100&page={page}"),
            ])
            .env("GH_PROMPT_DISABLED", "1");
            let s = run(cmd, 20, MAX_BODY).map_err(|_| {
                "GitHub 登录检查失败或超时；请确认 gh auth status 及仓库访问权限。状态 UNKNOWN"
            })?;
            let v: Value = serde_json::from_str(&s).map_err(|_| "GitHub CLI JSON 无效")?;
            let rows = v.as_array().ok_or("GitHub CLI Release 列表无效")?;
            all.extend(rows.iter().cloned());
            if rows.len() < 100 {
                return Ok(json!(all));
            }
        }
        Err("Release 分页超过上限；状态 UNKNOWN".into())
    })
    .await
    .map_err(|_| "GitHub 检查中断")?
}
#[tauri::command]
pub async fn desktop_update_check(
    n: State<'_, Maintenance>,
    authenticated: bool,
) -> Result<Value, String> {
    let result = load_releases(authenticated)
        .await
        .and_then(|v| select_release(&v, env!("CARGO_PKG_VERSION")));
    let mut v = result.unwrap_or_else(|e| json!({"status":"UNKNOWN","error":e}));
    v["checked_at"] = json!(stamp());
    v["source"] = json!(if authenticated {
        "github-cli-authenticated"
    } else {
        "github-public-api"
    });
    *n.latest.lock().unwrap() = v.clone();
    Ok(v)
}
fn hash_file(path: &Path) -> Result<String, String> {
    let mut file = fs::File::open(path).map_err(|_| "文件不可读")?;
    let mut h = Sha256::new();
    let mut buf = [0u8; 65536];
    loop {
        let len = file.read(&mut buf).map_err(|_| "读取校验文件失败")?;
        if len == 0 {
            break;
        }
        h.update(&buf[..len]);
    }
    Ok(format!("{:x}", h.finalize()))
}
// Hash relative names, file bytes and symlink targets; never traverse bundle symlinks.
fn bundle_hash(path: &Path) -> Result<String, String> {
    fn walk(root: &Path, p: &Path, h: &mut Sha256, left: &mut usize) -> Result<(), String> {
        if *left == 0 {
            return Err("bundle 文件过多，无法完整核对".into());
        }
        *left -= 1;
        let m = fs::symlink_metadata(p).map_err(|_| "bundle 元数据不可读")?;
        h.update(
            p.strip_prefix(root)
                .map_err(|_| "bundle 路径越界")?
                .as_os_str()
                .as_encoded_bytes(),
        );
        h.update([0]);
        if m.file_type().is_symlink() {
            h.update(b"link:");
            h.update(
                fs::read_link(p)
                    .map_err(|_| "bundle 链接不可读")?
                    .as_os_str()
                    .as_encoded_bytes(),
            );
        } else if m.is_file() {
            h.update(b"file:");
            h.update(hash_file(p)?.as_bytes());
            h.update((m.mode() & 0o777).to_be_bytes());
        } else if m.is_dir() {
            h.update(b"dir:");
            let mut entries = fs::read_dir(p)
                .map_err(|_| "bundle 目录不可读")?
                .collect::<Result<Vec<_>, _>>()
                .map_err(|_| "bundle 条目不可读")?;
            entries.sort_by_key(|e| e.file_name());
            for e in entries {
                walk(root, &e.path(), h, left)?
            }
        } else {
            return Err("bundle 含特殊文件，保留".into());
        }
        h.update([0]);
        Ok(())
    }
    let mut h = Sha256::new();
    walk(path, path, &mut h, &mut 50000)?;
    Ok(format!("{:x}", h.finalize()))
}
fn app_info(path: &Path) -> Result<Value, String> {
    let mut c = Command::new("/usr/bin/plutil");
    c.args(["-convert", "json", "-o", "-"])
        .arg(path.join("Contents/Info.plist"));
    let s = run(c, 5, 64 * 1024)?;
    serde_json::from_str(&s).map_err(|_| "APP Info.plist 无效".into())
}
fn size(path: &Path, budget: &mut usize) -> (u64, u64) {
    if *budget == 0 {
        return (0, 0);
    }
    *budget -= 1;
    let Ok(m) = fs::symlink_metadata(path) else {
        return (0, 0);
    };
    if m.file_type().is_symlink() {
        return (0, 0);
    }
    let mut sum = (m.len(), m.blocks() * 512);
    if m.is_dir() {
        if let Ok(entries) = fs::read_dir(path) {
            for e in entries.flatten() {
                let b = size(&e.path(), budget);
                sum.0 += b.0;
                sum.1 += b.1;
            }
        }
    }
    sum
}
fn signature(path: &Path) -> Value {
    let mut c = Command::new("/usr/bin/codesign");
    c.args(["--verify", "--deep", "--strict"]).arg(path);
    let ok = run(c, 8, 16384).is_ok();
    // codesign -d writes signature identity to stderr. Capture only this public metadata.
    let detail = Command::new("/usr/bin/codesign")
        .args(["-dvv"])
        .arg(path)
        .output()
        .ok()
        .map(|o| {
            String::from_utf8_lossy(&o.stderr)
                .lines()
                .filter(|l| {
                    l.starts_with("Identifier=")
                        || l.starts_with("Signature=")
                        || l.starts_with("TeamIdentifier=")
                        || l.starts_with("CDHash=")
                        || l.starts_with("Authority=")
                })
                .collect::<Vec<_>>()
                .join("\n")
        })
        .unwrap_or_default();
    json!({"verified":ok,"details":detail,"notarization":"NOT_CHECKED"})
}
fn scan_roots() -> Result<Vec<PathBuf>, String> {
    let h = home()?;
    let mut roots = vec![
        PathBuf::from("/Applications"),
        h.join("Applications"),
        h.join("Downloads"),
        h.join(".local/share/localpilot-desktop-builds"),
    ];
    let base = h.join("Desktop/aic竞赛");
    let mut repos = vec![base.join("LocalPilot-GUI")];
    // Source-tree discovery belongs to development builds. Embedding the
    // manifest directory in a release leaks the maintainer's absolute path.
    #[cfg(debug_assertions)]
    {
        let compile_root = PathBuf::from(env!("CARGO_MANIFEST_DIR"))
            .parent()
            .unwrap()
            .to_path_buf();
        if compile_root.join("package.json").is_file() {
            repos.push(compile_root)
        }
    }
    for repo in repos {
        roots.push(repo.join("release"));
        for mode in ["debug", "release"] {
            roots.push(repo.join(format!("src-tauri/target/{mode}/bundle")))
        }
    }
    let mut seen = HashSet::new();
    roots.retain(|p| seen.insert(p.clone()));
    Ok(roots)
}
fn visit(
    path: &Path,
    depth: usize,
    remaining: &mut usize,
    items: &mut Vec<Value>,
    warnings: &mut Vec<String>,
    running: &str,
    current: &Path,
) {
    if *remaining == 0 {
        return;
    }
    *remaining -= 1;
    let Ok(m) = fs::symlink_metadata(path) else {
        return;
    };
    if m.file_type().is_symlink() {
        if path.extension().is_some_and(|s| s == "app") {
            // macOS system APPs also use symlinks (e.g. Safari). Identity is mandatory.
            let Ok(info) = app_info(path) else { return };
            let id = info["CFBundleIdentifier"].as_str().unwrap_or("");
            if id != "io.localpilot.desktop" && !id.starts_with("io.localpilot.desktop.acceptance.")
            {
                return;
            }
            items.push(json!({"path":path,"kind":"APP_REFERENCE","protected":true,"reason":"符号链接引用，不计重复空间","target":fs::canonicalize(path).ok()}))
        }
        return;
    }
    if m.is_dir() && path.extension().is_some_and(|s| s == "app") {
        let Ok(info) = app_info(path) else { return };
        let id = info["CFBundleIdentifier"].as_str().unwrap_or("");
        if id != "io.localpilot.desktop" && !id.starts_with("io.localpilot.desktop.acceptance.") {
            return;
        }
        let executable = info["CFBundleExecutable"].as_str().unwrap_or("");
        if executable.contains('/') || executable.is_empty() {
            return;
        }
        let exe = path.join("Contents/MacOS").join(executable);
        let mut budget = 50000;
        let bytes = size(path, &mut budget);
        let sign = signature(path);
        let active =
            running.contains(&exe.to_string_lossy().to_string()) || current.starts_with(path);
        items.push(json!({"path":path,"kind":if path.to_string_lossy().contains("/target/"){"BUILD_APP"}else{"APP"},"bundle_id":id,"version":info["CFBundleShortVersionString"],"executable_sha256":hash_file(&exe).ok(),"bundle_sha256":bundle_hash(path).ok(),"signature":sign,"bytes":bytes.0,"allocated_bytes":bytes.1,"running":active,"protected":true,"reason":if active{"当前运行 APP，受保护"}else{"APP 需核对保留副本、签名、引用与可恢复性"},"size_complete":budget>0}));
        return;
    }
    if m.is_file() {
        let name = path.file_name().unwrap_or_default().to_string_lossy();
        if name.starts_with("LocalPilot") && (name.ends_with(".dmg") || name.ends_with(".zip")) {
            items.push(json!({"path":path,"kind":if name.contains("source"){"SOURCE_ARCHIVE"}else if name.ends_with(".dmg"){"DMG"}else{"APP_ZIP"},"bytes":m.len(),"allocated_bytes":m.blocks()*512,"sha256":hash_file(path).ok(),"protected":true,"reason":"待与真实 Release 哈希核对；源码包始终保留"}));
        }
        return;
    }
    if depth == 0 {
        return;
    }
    match fs::read_dir(path) {
        Ok(entries) => {
            for e in entries.flatten() {
                visit(
                    &e.path(),
                    depth - 1,
                    remaining,
                    items,
                    warnings,
                    running,
                    current,
                );
            }
        }
        Err(_) => warnings.push(format!("无法读取 {}", path.display())),
    }
}
fn scan(release: &Value) -> Result<Value, String> {
    let roots = scan_roots()?;
    let current = std::env::current_exe().unwrap_or_default();
    let mut c = Command::new("/bin/ps");
    c.args(["-axo", "command="]);
    let running = run(c, 5, MAX_BODY);
    let mut warnings = Vec::new();
    let mut items = Vec::new();
    let mut remaining = 12000;
    if running.is_err() {
        warnings.push("运行进程不可读；全部 APP 受保护".into())
    }
    for root in &roots {
        if root.exists() {
            visit(
                root,
                5,
                &mut remaining,
                &mut items,
                &mut warnings,
                running.as_deref().unwrap_or(""),
                &current,
            )
        }
    }
    if remaining == 0 {
        warnings.push("扫描达到条目上限，结果不完整".into())
    }
    let assets = release["assets"].as_array().cloned().unwrap_or_default();
    // Only an exact archive digest from the latest live Release can establish recovery.
    for i in &mut items {
        if let Some(a) = assets
            .iter()
            .find(|a| !a["sha256"].is_null() && a["sha256"] == i["sha256"])
        {
            i["release_asset"] = a["url"].clone();
            i["recovery"] = json!("LATEST_RELEASE_HASH_MATCH");
        }
    }
    let mut groups = std::collections::HashMap::<String, Vec<String>>::new();
    for i in &items {
        if let (Some(hash), Some(path)) = (i["executable_sha256"].as_str(), i["path"].as_str()) {
            groups.entry(hash.into()).or_default().push(path.into());
        }
    }
    let h = home()?;
    let release_version = release["version"].as_str().unwrap_or("");
    let store = h.join(".local/share/localpilot-desktop-builds");
    // Preserve a signed copy of the actual latest released GUI, never a hardcoded version.
    let keeper = items
        .iter()
        .find(|i| {
            !release_version.is_empty()
                && i["version"] == release_version
                && i["path"]
                    .as_str()
                    .is_some_and(|p| Path::new(p).starts_with(&store))
        })
        .cloned();
    let mut total = 0;
    for i in &mut items {
        if let Some(hash) = i["executable_sha256"].as_str() {
            i["same_executable_copies"] = json!(groups.get(hash));
        }
        if let Some(k) = &keeper {
            let p = i["path"].as_str().unwrap_or("");
            let retained = h.join("Desktop/aic竞赛/LocalPilot-GUI/release");
            let in_retained = Path::new(p).strip_prefix(&retained).ok().is_some_and(|r| {
                r.components()
                    .next()
                    .is_some_and(|c| c.as_os_str().to_string_lossy().starts_with("retained-"))
            });
            if running.is_ok()
                && in_retained
                && i["kind"] == "APP"
                && i["running"] == false
                && !i["executable_sha256"].is_null()
                && i["executable_sha256"] == k["executable_sha256"]
                && !i["bundle_sha256"].is_null()
                && i["bundle_sha256"] == k["bundle_sha256"]
                && i["bundle_id"] == k["bundle_id"]
                && i["version"] == k["version"]
            {
                i["review_candidate"] = json!(true);
                i["reason"]=json!("已保留同版本、完整 bundle 和可执行文件哈希相同的有效签名 APP；仅供人工核对流程引用后确认，未授权清理");
                total += i["allocated_bytes"].as_u64().unwrap_or(0);
            }
        }
    }
    Ok(
        json!({"scanned_at":stamp(),"roots":roots,"items":items,"warnings":warnings,"review_candidate_bytes":total,"safe_to_delete_bytes":0,"dry_run":true,"deletion_supported":false,"scope":"白名单目录，最多五层；不进入用户数据、源码、模型、其它 worktree；无删除命令"}),
    )
}
#[tauri::command]
pub async fn desktop_storage_scan(n: State<'_, Maintenance>) -> Result<Value, String> {
    let latest = n.latest.lock().unwrap().clone();
    tauri::async_runtime::spawn_blocking(move || scan(&latest))
        .await
        .map_err(|_| "扫描中断")?
}
#[tauri::command]
pub fn desktop_installation(n: State<Maintenance>) -> Value {
    json!({"last_check":n.latest.lock().unwrap().clone(),"version":env!("CARGO_PKG_VERSION"),"executable":std::env::current_exe().ok(),"release_page":format!("{REPO}/releases"),"build":"本地维护候选，尚未发布"})
}
#[tauri::command]
pub async fn desktop_open_release(
    n: State<'_, Maintenance>,
    asset: Option<String>,
) -> Result<(), String> {
    let latest = n.latest.lock().unwrap().clone();
    let url = match asset {
        Some(name) => latest["assets"]
            .as_array()
            .and_then(|a| a.iter().find(|a| a["name"] == name))
            .and_then(|a| a["url"].as_str())
            .ok_or("请先成功检查 Release")?
            .to_string(),
        None => latest["url"]
            .as_str()
            .unwrap_or(&format!("{REPO}/releases"))
            .to_string(),
    };
    if !release_url(&url) {
        return Err("拒绝未授权的 Release 地址".into());
    }
    tauri::async_runtime::spawn_blocking(move || {
        let mut c = Command::new("/usr/bin/open");
        c.arg(url);
        run(c, 5, 1024).map(|_| ())
    })
    .await
    .map_err(|_| "打开 Release 中断")?
}
#[tauri::command]
pub async fn desktop_verify_archive(n: State<'_, Maintenance>) -> Result<Value, String> {
    let latest = n.latest.lock().unwrap().clone();
    if latest["status"] == "UNKNOWN"
        || latest["checked_at"]
            .as_u64()
            .is_none_or(|t| stamp().saturating_sub(t) > 3600)
    {
        return Err("请先在一小时内成功检查真实 Release".into());
    }
    let file = rfd::AsyncFileDialog::new()
        .set_title("选择从本次 GitHub Release 下载的 DMG 或 APP ZIP（只读校验）")
        .add_filter("Desktop 安装包", &["dmg", "zip"])
        .pick_file()
        .await
        .ok_or("已取消校验")?;
    let path = file.path().to_path_buf();
    tauri::async_runtime::spawn_blocking(move || verify_archive(&path, &latest))
        .await
        .map_err(|_| "校验中断")?
}
fn verify_archive(path: &Path, latest: &Value) -> Result<Value, String> {
    let m = fs::symlink_metadata(path).map_err(|_| "安装包不可读")?;
    if !m.is_file() || m.len() > 2 * 1024 * 1024 * 1024 {
        return Err("请选择不超过 2GB 的普通安装包文件；拒绝链接和目录".into());
    }
    let name = path
        .file_name()
        .and_then(|s| s.to_str())
        .ok_or("文件名无效")?;
    let asset = latest["assets"]
        .as_array()
        .and_then(|a| a.iter().find(|a| a["name"] == name))
        .ok_or("文件名不属于本次真实 GUI Release")?;
    let expected = asset["sha256"]
        .as_str()
        .ok_or("GitHub 未提供 SHA256 digest；此版本不允许跳过校验")?;
    if !asset["url"].as_str().is_some_and(release_url) {
        return Err("制品来源无效".into());
    }
    let actual = hash_file(path)?;
    let after = fs::symlink_metadata(path).map_err(|_| "安装包已改变")?;
    if actual != expected
        || asset["bytes"].as_u64() != Some(m.len())
        || after.ino() != m.ino()
        || after.dev() != m.dev()
        || after.len() != m.len()
        || after.mtime() != m.mtime()
        || after.mtime_nsec() != m.mtime_nsec()
    {
        return Err("SHA256、大小或文件身份不匹配，禁止安装此文件".into());
    }
    Ok(
        json!({"status":"SHA256_VERIFIED", "path":path, "sha256":actual, "bytes":m.len(),
        "source":asset["url"], "checked_at":stamp(), "signature":"ARCHIVE_ONLY_NOT_APP_SIGNATURE_VERIFIED",
        "guidance":"仅验证来自本次 Release 的安装包字节。解包后仍需 codesign --verify --deep --strict；ad-hoc 签名不证明开发者身份。请先退出 GUI，保留旧 APP 用于回滚，再在 Finder 人工安装；不要删除或替换后端和用户数据。"}),
    )
}

#[cfg(test)]
mod tests {
    use super::*;
    fn row(tag: &str) -> Value {
        let v = tag.trim_start_matches("desktop-v");
        json!({"tag_name":tag,"draft":false,"prerelease":false,"html_url":format!("{REPO}/releases/tag/{tag}"),"assets":[{"name":format!("LocalPilot-{v}-arm64.dmg"),"browser_download_url":format!("{REPO}/releases/download/{tag}/LocalPilot-{v}-arm64.dmg"),"digest":format!("sha256:{}","a".repeat(64)),"size":10}]})
    }
    #[test]
    fn release_selection_ignores_other_modules_and_orders_semver() {
        let rows = json!([
            row("desktop-v0.2.0"),
            row("desktop-v0.10.0"),
            row("core-v99.0.0"),
            row("desktop-v2.0.0-rc1")
        ]);
        let r = select_release(&rows, "0.2.1-dev.1").unwrap();
        assert_eq!(r["version"], "0.10.0");
        assert_eq!(r["status"], "UPDATE_AVAILABLE");
    }
    #[test]
    fn recommended_v5_updates_legacy_and_edge_candidates() {
        let rows = json!([row("desktop-v0.2.0"), row("desktop-v5.0.0")]);
        for current in ["0.2.0", "5.0.0-beta.3-dev.17", "5.0.0-beta.3-dev.23-edge.4"] {
            let r = select_release(&rows, current).unwrap();
            assert_eq!(r["version"], "5.0.0");
            assert_eq!(r["status"], "UPDATE_AVAILABLE");
            assert_eq!(r["assets"][0]["name"], "LocalPilot-5.0.0-arm64.dmg");
        }
        assert_eq!(select_release(&rows, "5.0.0").unwrap()["status"], "CURRENT");
    }
    #[test]
    fn release_rejects_forged_origins_and_no_data() {
        let mut r = row("desktop-v0.2.0");
        r["assets"][0]["browser_download_url"] = json!("https://evil.test/LocalPilot.dmg");
        assert!(select_release(&json!([r]), "0.2.0").is_err());
        assert!(select_release(&json!([]), "0.2.0").is_err());
        assert!(!release_url(
            "https://github.com.evil.test/www080327-glitch/LocalPilot/releases/"
        ));
        assert!(!release_url(
            "https://github.com/www080327-glitch/LocalPilot/releases/?x=1"
        ));
    }
    #[test]
    fn prerelease_and_draft_cannot_become_latest() {
        let mut a = row("desktop-v9.0.0");
        a["draft"] = json!(true);
        assert!(select_release(&json!([a]), "0.2.0").is_err());
        assert_eq!(
            select_release(&json!([row("desktop-v0.2.0")]), "0.2.1-dev.1").unwrap()["status"],
            "LOCAL_AHEAD"
        );
    }
    #[test]
    fn scanner_rejects_unrelated_apps_and_symlink_traversal() {
        let root = std::env::temp_dir().join(format!("lp-scan-test-{}", uuid::Uuid::new_v4()));
        fs::create_dir_all(root.join("Other.app/Contents")).unwrap();
        let info = json!({"CFBundleIdentifier":"io.other.product","CFBundleExecutable":"other"});
        fs::write(
            root.join("Other.app/Contents/Info.plist"),
            serde_json::to_vec(&info).unwrap(),
        )
        .unwrap();
        std::os::unix::fs::symlink("/Applications", root.join("external")).unwrap();
        std::os::unix::fs::symlink(root.join("Other.app"), root.join("LocalPilotImpostor.app"))
            .unwrap();
        let mut items = vec![];
        let mut warnings = vec![];
        visit(
            &root,
            5,
            &mut 100,
            &mut items,
            &mut warnings,
            "",
            Path::new("/none"),
        );
        assert!(items.is_empty());
        assert!(root.join("external").exists());
        fs::remove_file(root.join("external")).unwrap();
        fs::remove_file(root.join("LocalPilotImpostor.app")).unwrap();
        fs::remove_file(root.join("Other.app/Contents/Info.plist")).unwrap();
        fs::remove_dir(root.join("Other.app/Contents")).unwrap();
        fs::remove_dir(root.join("Other.app")).unwrap();
        fs::remove_dir(root).unwrap();
    }
    #[test]
    fn archive_verification_rejects_wrong_hash_size_source_and_symlink() {
        let root = std::env::temp_dir().join(format!("lp-archive-test-{}", uuid::Uuid::new_v4()));
        fs::create_dir(&root).unwrap();
        let path = root.join("LocalPilot-0.2.0-arm64.dmg");
        fs::write(&path, b"known archive bytes").unwrap();
        let hash = hash_file(&path).unwrap();
        let mut latest = select_release(&json!([row("desktop-v0.2.0")]), "0.2.0").unwrap();
        latest["assets"][0]["sha256"] = json!(hash);
        latest["assets"][0]["bytes"] = json!(19);
        assert!(verify_archive(&path, &latest).is_ok());
        latest["assets"][0]["bytes"] = json!(20);
        assert!(verify_archive(&path, &latest).is_err());
        latest["assets"][0]["bytes"] = json!(19);
        latest["assets"][0]["sha256"] = json!("b".repeat(64));
        assert!(verify_archive(&path, &latest).is_err());
        latest["assets"][0]["sha256"] = Value::Null;
        assert!(verify_archive(&path, &latest).is_err());
        fs::remove_file(&path).unwrap();
        std::os::unix::fs::symlink("/etc/hosts", &path).unwrap();
        assert!(verify_archive(&path, &latest).is_err());
        fs::remove_file(&path).unwrap();
        fs::remove_dir(root).unwrap();
    }
    #[test]
    #[ignore = "Real GitHub client through a deliberately unreachable process proxy; no system network changes"]
    fn offline_release_failure_is_unknown() {
        assert_eq!(std::env::var("LP_OFFLINE_PROBE").unwrap_or_default(), "1");
        let rt = tokio::runtime::Runtime::new().unwrap();
        let result = rt.block_on(public_releases());
        assert!(result.is_err());
        let record = json!({"status":"UNKNOWN","error":result.err(),"class":"REAL_NETWORK_CLIENT_UNREACHABLE_PROCESS_PROXY","system_network_changed":false,"at":stamp()});
        let out = PathBuf::from(std::env::var_os("LP_MAINTENANCE_EVIDENCE").unwrap());
        fs::write(
            out.join("offline-check.json"),
            serde_json::to_vec_pretty(&record).unwrap(),
        )
        .unwrap();
    }
    #[test]
    #[ignore = "Real read-only GitHub and local APP scan; explicit low-power acceptance only"]
    fn live_read_only_maintenance() {
        let out = std::env::var_os("LP_MAINTENANCE_EVIDENCE")
            .map(PathBuf::from)
            .expect("set evidence directory");
        let rt = tokio::runtime::Runtime::new().unwrap();
        let public = rt.block_on(load_releases(false));
        let auth = rt
            .block_on(load_releases(true))
            .and_then(|v| select_release(&v, env!("CARGO_PKG_VERSION")));
        let report = json!({"public":public.unwrap_or_else(|e|json!({"status":"UNKNOWN","error":e})),"authenticated":auth.as_ref().unwrap_or(&Value::Null),"auth_error":auth.as_ref().err(),"at":stamp()});
        fs::write(
            out.join("live-release.json"),
            serde_json::to_vec_pretty(&report).unwrap(),
        )
        .unwrap();
        if let Ok(release) = &auth {
            let archive = home()
                .unwrap()
                .join("Desktop/aic竞赛/LocalPilot-GUI/release/LocalPilot-0.2.0-arm64.app.zip");
            let proof = verify_archive(&archive, release).unwrap();
            fs::write(
                out.join("live-archive-verification.json"),
                serde_json::to_vec_pretty(&proof).unwrap(),
            )
            .unwrap();
        }
        let scan = scan(auth.as_ref().unwrap_or(&Value::Null)).unwrap();
        fs::write(
            out.join("native-storage-scan.json"),
            serde_json::to_vec_pretty(&scan).unwrap(),
        )
        .unwrap();
        assert!(auth.is_ok(), "real authenticated release check failed");
    }
}
