#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]
mod developer;
mod pet_agent;
mod pet_edge;
use pet_edge::pet_edge;
mod channels;
mod pet_assets;
mod pet_macos;
mod pet_native;
mod product;
use channels::channel_control;
use pet_agent::{pet_agent, pet_core};
use pet_assets::pet_asset;
use pet_native::{pet_action, pet_chat, pet_handoff_draft, pet_runtime, pet_service};
use product::{
    attachment_preview, attachment_thumbnail, companion_settings, configure_cloud_key,
    discover_suites, import_attachments, installation_backup, installation_location,
    open_attachment, pet_expand, pet_handoff, pet_window, pick_attachment_folder, pick_attachments,
    pick_workspace, product_control, remove_attachment, stage_attachment,
};
mod maintenance;
mod preferences;
use developer::{
    developer_command, developer_profile, pick_developer_python, pick_developer_source,
};
use futures_util::StreamExt;
use maintenance::{
    desktop_installation, desktop_open_release, desktop_storage_scan, desktop_update_check,
    desktop_verify_archive, Maintenance,
};
use preferences::{Global, Preferences};
use serde::{Deserialize, Serialize};
use serde_json::{json, Value};
use std::{
    collections::HashMap,
    fs,
    os::unix::fs::{MetadataExt, OpenOptionsExt, PermissionsExt},
    path::{Path, PathBuf},
    sync::Mutex,
    time::Duration,
};
use tauri::{Emitter, Manager, State};

#[derive(Clone, Default, Serialize, Deserialize)]
struct Profile {
    home: String,
    cli: String,
    origin: String,
    workspace: String,
}
#[derive(Default)]
struct Native {
    profile: Mutex<Profile>,
    selected_files: Mutex<HashMap<String, PathBuf>>,
    selected_origins: Mutex<HashMap<String, String>>,
    selected_identities: Mutex<HashMap<String, (u64, u64, i64, u64)>>,
    upgrades: Mutex<HashMap<String, (Profile, String, String, String)>>,
    preference_lock: Mutex<()>,
    watchers: Mutex<HashMap<String, tauri::async_runtime::JoinHandle<()>>>,
    setup_lock: std::sync::Arc<tokio::sync::Mutex<()>>,
}
#[derive(Clone, Serialize, Deserialize)]
struct Pending {
    key: String,
    body: Value,
    task_id: Option<String>,
    origin: String,
    subject: String,
    #[serde(default = "unknown_submission")]
    status: String,
    #[serde(default)]
    rejection: Option<Value>,
    #[serde(default)]
    preferences: Option<Preferences>,
}
fn unknown_submission() -> String {
    "unknown".into()
}
fn pending_in_scope(v: &Value, origin: &str, subject: &Value) -> bool {
    v["task_id"].is_null()
        && v["status"] != "rejected"
        && v["origin"] == origin
        && v["subject"] == *subject
}
#[derive(Debug)]
struct TaskTransportError {
    message: String,
    rejection: Option<Value>,
}
fn definitive_rejection(status: u16, v: &Value, recovering: bool) -> bool {
    let code = v["error"]["code"].as_str().unwrap_or("");
    if !recovering && status == 503 && ["model_not_deployed", "model_unavailable"].contains(&code) {
        return true;
    }
    // Runtime checks these after accepted-key lookup. Conflict/unknown 5xx never clears a key.
    if status == 409
        && [
            "session_closed",
            "route_conflict",
            "session_busy",
            "stale_response",
            "context_changed",
        ]
        .contains(&code)
    {
        return true;
    }
    !recovering
        && [400, 401, 403, 404, 409, 413, 429].contains(&status)
        && [
            "invalid_request",
            "task_input_too_large",
            "invalid_input_encoding",
            "model_not_registered",
            "model_not_deployed",
            "model_unavailable",
            "model_capability_insufficient",
            "scope_forbidden",
            "session_not_found",
            "client_capacity_exceeded",
            "capacity_exceeded",
            "authentication_required",
            "invalid_token",
        ]
        .contains(&code)
}
async fn task_post(
    p: &Profile,
    body: Value,
    key: &str,
    recovering: bool,
) -> Result<Value, TaskTransportError> {
    let unknown = |message: String| TaskTransportError {
        message,
        rejection: None,
    };
    let token = core_token(p).map_err(unknown)?;
    let url = format!(
        "{}/localpilot/v1/tasks",
        origin(&p.origin).map_err(unknown)?
    );
    let response = client()
        .map_err(unknown)?
        .post(url)
        .bearer_auth(token)
        .header("Idempotency-Key", key)
        .json(&body)
        .send()
        .await
        .map_err(|_| unknown("服务连接中断，提交结果未知；请恢复原请求".into()))?;
    let status = response.status().as_u16();
    let bytes = response
        .bytes()
        .await
        .map_err(|_| unknown("响应中断，提交结果未知".into()))?;
    if bytes.len() > 8 * 1024 * 1024 {
        return Err(unknown("响应超过上限，提交结果未知".into()));
    }
    let v: Value = serde_json::from_slice(&bytes)
        .map_err(|_| unknown("响应不是有效 JSON，提交结果未知".into()))?;
    let v = redacted(v);
    if !(200..300).contains(&status) {
        return Err(TaskTransportError {
            message: format!("HTTP {status} · {v}"),
            rejection: definitive_rejection(status, &v, recovering).then_some(v),
        });
    }
    if !v["id"].as_str().is_some_and(id_ok) || !v["session_id"].as_str().is_some_and(id_ok) {
        return Err(unknown("响应缺少有效 Task/Session ID，提交结果未知".into()));
    }
    Ok(v)
}
async fn submit_record(
    p: &Profile,
    path: &Path,
    rec: &mut Pending,
    recovering: bool,
) -> Result<Value, String> {
    match task_post(p, rec.body.clone(), &rec.key, recovering).await {
        Ok(task) => {
            rec.task_id = task["id"].as_str().map(String::from);
            rec.status = "accepted".into();
            save(path, rec)?;
            Ok(task)
        }
        Err(e) => {
            if let Some(rejection) = e.rejection {
                rec.status = "rejected".into();
                rec.rejection = Some(rejection);
                save(path, rec)?;
                Err(format!(
                    "{} · 明确未创建任务；原请求已标记拒绝，可发起新提交。",
                    e.message
                ))
            } else {
                Err(format!(
                    "{} · 原请求已保存：{}。使用恢复原请求，勿重复发送。",
                    e.message, rec.key
                ))
            }
        }
    }
}
fn fail(msg: &str) -> String {
    msg.to_string()
}
fn private_json(path: &Path) -> Result<Value, String> {
    let m = fs::symlink_metadata(path).map_err(|_| fail("无法读取私有连接文件"))?;
    if !m.is_file() || m.uid() != unsafe { libc::geteuid() } || m.mode() & 0o077 != 0 {
        return Err(fail("连接文件必须由当前用户拥有、为普通文件且权限为 600"));
    }
    serde_json::from_slice(&fs::read(path).map_err(|_| fail("读取失败"))?)
        .map_err(|_| fail("连接文件 JSON 无效"))
}
fn save(path: &Path, value: &impl Serialize) -> Result<(), String> {
    let tmp = path.with_extension(format!("{}.tmp", uuid::Uuid::new_v4()));
    let mut f = fs::OpenOptions::new()
        .create_new(true)
        .write(true)
        .mode(0o600)
        .open(&tmp)
        .map_err(|_| fail("无法保存客户端状态"))?;
    use std::io::Write;
    f.write_all(&serde_json::to_vec(value).map_err(|_| fail("状态格式错误"))?)
        .map_err(|_| fail("保存失败"))?;
    f.sync_all().map_err(|_| fail("状态未能持久化"))?;
    fs::rename(&tmp, path).map_err(|_| fail("提交状态失败"))
}
fn data(app: &tauri::AppHandle) -> Result<PathBuf, String> {
    let p = if [
        "io.localpilot.desktop.test",
        "io.localpilot.desktop.channels.test",
    ]
    .contains(&app.config().identifier.as_str())
    {
        if let Some(root) = std::env::var_os("LP_INSTALL_TEST_ROOT") {
            let root = PathBuf::from(root);
            let marker = private_json(&root.join("test-owner.json"))?;
            if !root.is_absolute() || marker["purpose"] != "LocalPilot installation E2E" {
                return Err(fail("测试目录身份无效"));
            }
            root.join("client")
        } else {
            return Err(fail("隔离测试应用需要指定测试目录；日常安装未改动"));
        }
    } else {
        app.path()
            .app_data_dir()
            .map_err(|_| fail("客户端目录不可用"))?
    };
    fs::create_dir_all(&p).map_err(|_| fail("无法创建客户端目录"))?;
    fs::set_permissions(&p, fs::Permissions::from_mode(0o700))
        .map_err(|_| fail("客户端目录权限错误"))?;
    Ok(p)
}
#[tauri::command]
fn setup_progress(app: tauri::AppHandle, stage: Option<u8>) -> Result<Value, String> {
    let path = data(&app)?.join("setup-progress-v1.json");
    if let Some(stage) = stage {
        if stage > 3 {
            return Err(fail("首次设置步骤无效"));
        }
        if path.exists() {
            let prior = private_json(&path);
            if prior
                .as_ref()
                .is_ok_and(|v| v["version"] != 1 || !v["stage"].as_u64().is_some_and(|n| n <= 3))
                || prior.is_err()
            {
                let info = fs::symlink_metadata(&path).map_err(|_| fail("进度文件不可访问"))?;
                if !info.is_file()
                    || info.uid() != unsafe { libc::geteuid() }
                    || info.mode() & 0o077 != 0
                {
                    return Err(fail("进度文件归属需要人工核对，未覆盖原文件"));
                }
                fs::rename(
                    &path,
                    path.with_file_name(format!(
                        "setup-progress-invalid-{}.json",
                        uuid::Uuid::new_v4()
                    )),
                )
                .map_err(|_| fail("无法保留旧进度文件"))?;
            }
        }
        save(&path, &json!({"version":1,"stage":stage}))?;
    }
    let value = if path.exists() {
        private_json(&path)?
    } else {
        json!({"version":1,"stage":0})
    };
    if value["version"] != 1 || !value["stage"].as_u64().is_some_and(|n| n <= 3) {
        return Err(fail("首次设置进度需要重新检测；已保留原文件和所有组件数据"));
    }
    Ok(json!({"version":1,"stage":value["stage"]}))
}
fn core_token(p: &Profile) -> Result<String, String> {
    let root = Path::new(&p.home);
    let conn = private_json(&root.join("connection.json"))?;
    let name = conn["token_env"].as_str().ok_or("缺少普通客户端凭据引用")?;
    if name.to_ascii_uppercase().contains("OPERATOR")
        || name.to_ascii_uppercase().contains("RESOURCE")
    {
        return Err(fail("不接受控制身份"));
    }
    if root.join("service.json").exists() {
        let c = private_json(&root.join("service.json"))?;
        if c["clients"].as_array().is_some_and(|a| {
            a.iter()
                .any(|v| v["token_env"] == name && v["operator"] == true)
        }) {
            return Err(fail("GUI 只接受普通客户端"));
        }
    }
    credential_file(&root.join("clients.env"), name)
}
fn credential_file(path: &Path, name: &str) -> Result<String, String> {
    let meta = fs::symlink_metadata(path).map_err(|_| fail("普通客户端凭据文件不可用"))?;
    if !meta.is_file()
        || meta.uid() != unsafe { libc::geteuid() }
        || meta.mode() & 0o077 != 0
        || meta.len() > 65536
    {
        return Err(fail("凭据必须是当前用户的 600 普通文件"));
    }
    let content = fs::read_to_string(path).map_err(|_| fail("无法读取普通客户端凭据"))?;
    let prefix = format!("export {name}=");
    let token = content
        .lines()
        .find_map(|l| l.strip_prefix(&prefix))
        .ok_or("缺少指定普通客户端凭据")?;
    if token.len() < 16
        || !token
            .bytes()
            .all(|c| c.is_ascii_alphanumeric() || c == b'_' || c == b'-')
    {
        return Err(fail("不支持的凭据格式"));
    }
    Ok(token.to_string())
}
fn client() -> Result<reqwest::Client, String> {
    reqwest::Client::builder()
        .no_proxy()
        .redirect(reqwest::redirect::Policy::none())
        .connect_timeout(Duration::from_secs(4))
        .timeout(Duration::from_secs(140))
        .build()
        .map_err(|_| fail("网络初始化失败"))
}
fn origin(s: &str) -> Result<String, String> {
    let u = reqwest::Url::parse(s).map_err(|_| fail("服务地址无效"))?;
    if u.scheme() != "http"
        || ![Some("127.0.0.1"), Some("[::1]"), Some("::1")].contains(&u.host_str())
        || !u.username().is_empty()
        || u.password().is_some()
        || !["", "/"].contains(&u.path())
        || u.query().is_some()
        || u.fragment().is_some()
    {
        return Err(fail("此版本仅接受数字 loopback HTTP 服务根地址"));
    }
    Ok(s.trim_end_matches('/').to_string())
}
fn redacted(v: Value) -> Value {
    match v {
        Value::Object(m) => Value::Object(
            m.into_iter()
                .filter(|(k, _)| {
                    !["token", "api_key", "authorization", "_host_control_nonce"]
                        .contains(&k.to_lowercase().as_str())
                })
                .map(|(k, v)| (k, redacted(v)))
                .collect(),
        ),
        Value::Array(a) => Value::Array(a.into_iter().map(redacted).collect()),
        v => v,
    }
}
async fn request(
    p: &Profile,
    method: &str,
    path: &str,
    body: Option<Value>,
    key: Option<&str>,
) -> Result<Value, String> {
    let token = core_token(p)?;
    let mut req = client()?
        .request(
            reqwest::Method::from_bytes(method.as_bytes()).map_err(|_| fail("请求无效"))?,
            format!("{}{}", origin(&p.origin)?, path),
        )
        .bearer_auth(token);
    if let Some(b) = body {
        req = req.json(&b);
    }
    if let Some(k) = key {
        req = req.header("Idempotency-Key", k);
    }
    let response = req.send().await.map_err(|_| {
        if method == "POST" {
            fail("服务连接中断；提交状态可能未知，请查询原请求")
        } else {
            fail("服务不可达；请检查连接或启动服务")
        }
    })?;
    let status = response.status();
    let bytes = response
        .bytes()
        .await
        .map_err(|_| fail("读取服务响应失败"))?;
    if bytes.len() > 8 * 1024 * 1024 {
        return Err(fail("服务响应超过客户端上限"));
    }
    let value = serde_json::from_slice::<Value>(&bytes)
        .unwrap_or(json!({"error":"non-JSON service response"}));
    if !status.is_success() {
        return Err(format!("HTTP {} · {}", status.as_u16(), redacted(value)));
    }
    Ok(redacted(value))
}
fn current(n: &Native) -> Profile {
    n.profile.lock().unwrap().clone()
}
fn id_ok(s: &str) -> bool {
    !s.is_empty()
        && s.len() < 160
        && s.bytes()
            .all(|c| c.is_ascii_alphanumeric() || c == b'_' || c == b'-')
}
fn check_health(v: &Value) -> Result<(), String> {
    if !v["client_subject"].as_str().is_some_and(|s| !s.is_empty()) {
        return Err(fail("服务未声明认证客户端身份"));
    }
    if v["status"] != "ready" || v["persistence"] != true {
        return Err(fail("服务未就绪或未启用持久任务"));
    }
    let c = &v["compatibility"];
    for k in ["agent_service_api", "companion_client_contract"] {
        if !c[k]
            .as_str()
            .is_some_and(|s| s.starts_with("1.") && s[2..].parse::<u32>().is_ok())
        {
            return Err(fail("不兼容的 API / Companion 契约，需要 1.x"));
        }
    }
    for cap in [
        "durable_tasks",
        "durable_idempotency",
        "sse_cursor",
        "operator_approval",
        "cancel",
        "safe_resume",
        "unknown_quarantine",
        "verification_dimensions",
        "model_registry",
        "explicit_cloud_egress",
    ] {
        if !c["capabilities"]
            .as_array()
            .is_some_and(|a| a.iter().any(|v| v == cap))
        {
            return Err(format!("服务缺少能力：{cap}"));
        }
    }
    Ok(())
}
#[tauri::command]
fn appearance(
    app: tauri::AppHandle,
    glass: bool,
    theme: String,
    reduce_motion: bool,
) -> Result<Value, String> {
    let window = app.get_webview_window("main").ok_or("窗口不可用")?;
    let theme = match theme.as_str() {
        "system" => None,
        "dark" => Some(tauri::Theme::Dark),
        "light" => Some(tauri::Theme::Light),
        _ => return Err(fail("未知主题")),
    };
    window
        .set_theme(theme)
        .map_err(|_| fail("原生主题设置失败"))?;
    let workspace = objc2_app_kit::NSWorkspace::sharedWorkspace();
    let reduce = workspace.accessibilityDisplayShouldReduceTransparency();
    let motion = workspace.accessibilityDisplayShouldReduceMotion() || reduce_motion;
    if !glass || reduce {
        window_vibrancy::clear_liquid_glass(&window)
            .map_err(|e| format!("原生外观清理失败：{e}"))?;
        let _ = window_vibrancy::clear_vibrancy(&window);
        return Ok(
            json!({"active":false,"status":if reduce {"系统减少透明度 · 使用实色界面"} else {"已关闭原生玻璃"},"reduce_motion":motion}),
        );
    }
    let options =
        window_vibrancy::LiquidGlassOptions::new(window_vibrancy::NSGlassEffectViewStyle::Regular)
            .interactive(!motion)
            .radius(12.0);
    match window_vibrancy::apply_liquid_glass(&window, options) {
        Ok(()) => Ok(
            json!({"active":true,"status":"Apple 原生 Liquid Glass 已启用","reduce_motion":motion}),
        ),
        Err(window_vibrancy::Error::UnsupportedPlatformVersion(_)) => {
            window_vibrancy::apply_vibrancy(
                &window,
                window_vibrancy::NSVisualEffectMaterial::Sidebar,
                None,
                Some(12.0),
            )
            .map_err(|e| format!("原生材质不可用：{e}"))?;
            Ok(
                json!({"active":true,"status":"系统不支持 Liquid Glass · 使用原生 Sidebar 材质","reduce_motion":motion}),
            )
        }
        Err(e) => Err(format!("Liquid Glass 未启用：{e}")),
    }
}
#[tauri::command]
fn global_preferences(
    app: tauri::AppHandle,
    n: State<Native>,
    value: Option<Global>,
) -> Result<Global, String> {
    let _guard = n.preference_lock.lock().unwrap();
    let root = data(&app)?;
    let existing = preferences::load(&root)?;
    if let Some(v) = value {
        if !existing.completed && current(&n).home.is_empty() {
            return Err(fail("请先准备本机组件，再完成首次设置"));
        }
        if v.version != 1 || !v.completed || v.defaults.effort.is_some() {
            return Err(fail("必须明确完成设置；当前契约的思考强度由服务配置"));
        }
        save(&root.join("preferences-v1.json"), &v)?;
        Ok(v)
    } else {
        Ok(existing)
    }
}
#[tauri::command]
async fn session_preferences(
    app: tauri::AppHandle,
    n: State<'_, Native>,
    session_id: String,
    value: Option<Preferences>,
) -> Result<Value, String> {
    if !id_ok(&session_id) {
        return Err(fail("Session ID 无效"));
    }
    let p = current(&n);
    let h = request(&p, "GET", "/healthz", None, None).await?;
    check_health(&h)?;
    let subject = h["client_subject"].as_str().ok_or("服务未声明身份")?;
    let scope = format!("{}|{}|{}", p.home, p.origin, subject);
    let _guard = n.preference_lock.lock().unwrap();
    let file = data(&app)?.join("session-preferences-v1.json");
    let mut all = if file.exists() {
        private_json(&file)?
    } else {
        json!({})
    };
    if let Some(v) = value {
        if v.effort.as_ref().is_some_and(|s| {
            s.len() > 32 || !s.bytes().all(|b| b.is_ascii_alphanumeric() || b == b'_')
        }) {
            return Err(fail("思考强度格式无效"));
        }
        if !all.is_object() {
            return Err(fail("会话偏好记录损坏；未覆盖"));
        }
        if all.get(&scope).is_none() {
            all[&scope] = json!({});
        }
        all[&scope][&session_id] = serde_json::to_value(v).map_err(|_| fail("偏好格式错误"))?;
        save(&file, &all)?;
    }
    Ok(all[&scope][&session_id].clone())
}
#[tauri::command]
async fn routing_capabilities(n: State<'_, Native>) -> Result<Value, String> {
    let p = current(&n);
    let h = request(&p, "GET", "/healthz", None, None).await?;
    check_health(&h)?;
    if !h["compatibility"]["capabilities"]
        .as_array()
        .is_some_and(|a| a.iter().any(|v| v == "routing_preferences_v1"))
    {
        return Ok(
            json!({"supported":false,"reason":"Core has no routing_preferences_v1 contract"}),
        );
    }
    let cap = request(&p, "GET", "/localpilot/v1/routing-capabilities", None, None).await?;
    if !preferences::routing_supported(&h, &cap) {
        return Err(fail("路由扩展契约不完整，已拒绝自动路由"));
    }
    Ok(cap)
}
#[tauri::command]
async fn model_manager(
    n: State<'_, Native>,
    operation: String,
    id: Option<String>,
) -> Result<Value, String> {
    let p = current(&n);
    let h = request(&p, "GET", "/healthz", None, None).await?;
    check_health(&h)?;
    if !h["compatibility"]["capabilities"]
        .as_array()
        .is_some_and(|a| a.iter().any(|v| v == "model_manager_read_v1"))
    {
        return Ok(
            json!({"supported":false,"reason":"Model Manager endpoints are not exposed to this ordinary client"}),
        );
    }
    // Optional host facade at the authenticated Core origin; never import a mutation credential.
    match operation.as_str() {
        "catalog" => {
            let mh = request(&p, "GET", "/model-manager/v1/health", None, None).await?;
            let models = request(&p, "GET", "/model-manager/v1/models", None, None).await?;
            Ok(
                json!({"supported":true,"health":mh,"models":models,"resources_supported":h["compatibility"]["capabilities"].as_array().is_some_and(|a|a.iter().any(|v|v=="model_resource_v1"))}),
            )
        }
        "job" => {
            let id = id.filter(|s| id_ok(s)).ok_or("Job ID 无效")?;
            request(
                &p,
                "GET",
                &format!("/model-manager/v1/jobs/{id}"),
                None,
                None,
            )
            .await
        }
        _ => Err(fail(
            "不允许模型下载、加载或任意 Manager 操作；需要可信 Host",
        )),
    }
}
#[tauri::command]
fn profile(n: State<Native>) -> Profile {
    current(&n)
}
#[tauri::command]
async fn pick_suite(kind: String) -> Result<Option<String>, String> {
    let dialog = rfd::AsyncFileDialog::new();
    let selected = if ["home", "workspace"].contains(&kind.as_str()) {
        dialog
            .set_title("选择 LocalPilot Suite 数据目录")
            .pick_folder()
            .await
    } else {
        dialog
            .set_title("选择已安装的 localpilot 命令")
            .pick_file()
            .await
    };
    Ok(selected.map(|f| f.path().to_string_lossy().to_string()))
}
#[tauri::command]
async fn connect_suite(
    app: tauri::AppHandle,
    n: State<'_, Native>,
    home: String,
    cli: String,
) -> Result<Value, String> {
    let home = fs::canonicalize(home).map_err(|_| fail("Suite 目录不存在"))?;
    let m = fs::metadata(&home).map_err(|_| fail("Suite 目录不可用"))?;
    if m.uid() != unsafe { libc::geteuid() } || m.mode() & 0o077 != 0 {
        return Err(fail("Suite 目录必须由当前用户拥有且权限为 700"));
    }
    let conn = private_json(&home.join("connection.json"))?;
    let env_name = conn["token_env"]
        .as_str()
        .ok_or("connection.json 缺少 token_env")?;
    if env_name.to_ascii_uppercase().contains("OPERATOR")
        || env_name.to_ascii_uppercase().contains("RESOURCE")
    {
        return Err(fail("只接受普通客户端身份，审批交给可信终端"));
    }
    let path = home.join("clients.env");
    let meta = fs::symlink_metadata(&path).map_err(|_| fail("缺少 clients.env"))?;
    if !meta.is_file() || meta.uid() != unsafe { libc::geteuid() } || meta.mode() & 0o077 != 0 {
        return Err(fail("clients.env 必须为当前用户的 600 普通文件"));
    }
    let text = fs::read_to_string(path).map_err(|_| fail("无法读取普通客户端凭据"))?;
    let prefix = format!("export {env_name}=");
    let token = text
        .lines()
        .find_map(|l| l.strip_prefix(&prefix))
        .ok_or("缺少指定普通客户端凭据")?;
    if token.len() < 16
        || !token
            .bytes()
            .all(|c| c.is_ascii_alphanumeric() || c == b'_' || c == b'-')
    {
        return Err(fail("不支持的凭据文件格式"));
    }
    let endpoint = origin(conn["url"].as_str().ok_or("缺少 URL")?)?;
    let home = home.to_string_lossy().to_string();
    let workspace = if Path::new(&home).join("service.json").exists() {
        let c = private_json(&Path::new(&home).join("service.json"))?;
        c["routes"]
            .as_object()
            .and_then(|m| m.values().find_map(|v| v["workspace"].as_str()))
            .unwrap_or("")
            .to_string()
    } else {
        String::new()
    };
    if !cli.is_empty() {
        validate_cli(&cli)?;
    }
    let p = Profile {
        home: home.clone(),
        cli,
        origin: endpoint,
        workspace,
    };
    let _ = token;
    core_token(&p)?;
    // A stopped service can be configured and started from Settings; compatibility is checked before every submission.
    for (_, h) in n.watchers.lock().unwrap().drain() {
        h.abort();
    }
    *n.profile.lock().unwrap() = p.clone();
    save(&data(&app)?.join("profile.json"), &p)?;
    Ok(
        json!({"profile":p,"credential_storage":"Native-only reference to existing owner-only Suite files; no token copied"}),
    )
}
fn read_path(path: &str) -> bool {
    if [
        "/healthz",
        "/localpilot/v1/model-registry",
        "/localpilot/v1/tasks",
    ]
    .contains(&path)
    {
        return true;
    }
    let parts: Vec<_> = path.split('/').collect();
    (parts.len() == 5
        && ["tasks", "sessions"].contains(&parts[3])
        && parts[1] == "localpilot"
        && parts[2] == "v1"
        && id_ok(parts[4]))
        || (parts.len() == 6
            && parts[1] == "localpilot"
            && parts[2] == "v1"
            && parts[3] == "tasks"
            && id_ok(parts[4])
            && parts[5] == "children")
}
#[tauri::command]
async fn api(n: State<'_, Native>, method: String, path: String) -> Result<Value, String> {
    if method == "GET" && read_path(&path) {
        return request(&current(&n), &method, &path, None, None).await;
    }
    let parts: Vec<_> = path.split('/').collect();
    if method == "POST"
        && parts.len() == 6
        && parts[1] == "localpilot"
        && parts[2] == "v1"
        && parts[3] == "tasks"
        && id_ok(parts[4])
        && ["cancel", "pause"].contains(&parts[5])
    {
        return request(&current(&n), &method, &path, Some(json!({})), None).await;
    }
    Err(fail(
        "客户端不允许此 API 操作；审批与 Resume 需交还可信终端",
    ))
}
#[tauri::command]
async fn open_model_manager(n: State<'_, Native>) -> Result<(), String> {
    let p = current(&n);
    let health = request(&p, "GET", "/model-manager/v1/health", None, None).await?;
    let raw = health["services"]
        .as_array()
        .and_then(|a| a.first())
        .and_then(|s| s["management_url"].as_str())
        .ok_or("oMLX 管理入口不可用")?;
    let url = reqwest::Url::parse(raw).map_err(|_| fail("管理地址无效"))?;
    if url.scheme() != "http"
        || url.host_str() != Some("127.0.0.1")
        || url.path() != "/admin"
        || !url.username().is_empty()
        || url.password().is_some()
        || url.query().is_some()
        || url.fragment().is_some()
    {
        return Err(fail("只允许本机 oMLX 正式管理入口"));
    }
    std::process::Command::new("/usr/bin/open")
        .arg(url.as_str())
        .spawn()
        .map_err(|_| fail("无法打开管理入口"))?;
    Ok(())
}
#[tauri::command]
async fn model_resource(
    n: State<'_, Native>,
    model: String,
    operation: String,
    max_memory_bytes: u64,
    confirmed: bool,
) -> Result<Value, String> {
    if !confirmed
        || !id_ok(&model)
        || !["load", "unload"].contains(&operation.as_str())
        || max_memory_bytes > 128 * 1024 * 1024 * 1024
    {
        return Err(fail("需要独立确认模型和资源预算"));
    }
    checked_cli(
        current(&n),
        vec![
            "model-resource".into(),
            format!("--model={model}"),
            format!("--operation={operation}"),
            format!("--max-memory-bytes={max_memory_bytes}"),
            format!("--key=gui-model-{}", uuid::Uuid::new_v4()),
            "--confirmed".into(),
        ],
    )
    .await
}
#[tauri::command]
async fn import_omlx_models(n: State<'_, Native>, confirmed: bool) -> Result<Value, String> {
    if !confirmed {
        return Err(fail("导入模型路由需要明确确认"));
    }
    checked_cli(current(&n), vec!["sync-models".into()]).await
}
#[tauri::command]
fn open_omlx_setup() -> Result<(), String> {
    let user_app = std::env::var_os("HOME")
        .map(PathBuf::from)
        .unwrap_or_default()
        .join("Applications/oMLX.app");
    let target = if Path::new("/Applications/oMLX.app").is_dir() {
        PathBuf::from("/Applications/oMLX.app")
    } else if user_app.is_dir() {
        user_app
    } else {
        PathBuf::from("https://github.com/jundot/omlx/releases")
    };
    std::process::Command::new("/usr/bin/open")
        .arg(target)
        .spawn()
        .map_err(|_| fail("无法打开 oMLX 官方引导"))?;
    Ok(())
}
#[tauri::command]
async fn add_cloud_provider(n: State<'_, Native>) -> Result<Value, String> {
    let selected = rfd::AsyncFileDialog::new()
        .set_title("选择现有的 DeepSeek 私有密钥文件（内容不会进入界面）")
        .pick_file()
        .await;
    let file = selected.ok_or("已取消选择密钥")?;
    checked_cli(
        current(&n),
        vec![
            "cloud-configure".into(),
            format!("--key-file={}", file.path().display()),
        ],
    )
    .await
}
#[tauri::command]
async fn configure_cloud_scope(
    n: State<'_, Native>,
    paths: Vec<String>,
    confirmed: bool,
) -> Result<Value, String> {
    if !confirmed || paths.is_empty() || paths.len() > 32 {
        return Err(fail("请明确确认 1–32 个工作区文件的出站范围"));
    }
    let payload = serde_json::to_string(&paths).map_err(|_| fail("文件范围无效"))?;
    checked_cli(
        current(&n),
        vec!["cloud-scope".into(), format!("--paths-json={payload}")],
    )
    .await
}
#[tauri::command]
async fn task_control(
    app: tauri::AppHandle,
    n: State<'_, Native>,
    task_id: String,
    action_id: String,
    action: String,
    confirmed: bool,
) -> Result<Value, String> {
    if !confirmed
        || !id_ok(&task_id)
        || !id_ok(&action_id)
        || !["approve", "reject", "resume"].contains(&action.as_str())
    {
        return Err(fail("审批需要明确确认和绑定的任务票据"));
    }
    let p = current(&n);
    let task = request(
        &p,
        "GET",
        &format!("/localpilot/v1/tasks/{task_id}"),
        None,
        None,
    )
    .await?;
    if task["required_action"]["id"] != action_id
        || task["recovery"]["class"] == "UNKNOWN_BLOCKED"
        || task["receipt_summary"]["unknown_effects"]
            .as_u64()
            .unwrap_or(0)
            > 0
    {
        return Err(fail("票据已改变或 UNKNOWN 已隔离；没有发送审批"));
    }
    if action == "approve" {
        let window = app.get_webview_window("main").ok_or("主窗口不可用")?;
        let proposal = &task["required_action"]["requests"][0];
        let scope = &proposal["scope_request"];
        let details = if scope.is_object() {
            let operation = scope["operation"].as_str().unwrap_or("");
            let args = &scope["arguments"];
            let mut lines = Vec::new();
            if operation == "apply_patch" {
                for change in args["changes"].as_array().ok_or("文件变更内容不可用")? {
                    let verb = match change["operation"].as_str() {
                        Some("create") => "创建文件",
                        Some("update") => "修改文件",
                        Some("delete") => "删除文件",
                        _ => return Err(fail("无法核对文件操作")),
                    };
                    lines.push(format!(
                        "{}\n{}",
                        verb,
                        change["path"].as_str().ok_or("目标路径不可用")?
                    ));
                    for (field, label) in [
                        ("content", "写入内容"),
                        ("old_text", "替换原文"),
                        ("new_text", "替换为"),
                    ] {
                        if let Some(value) = change[field].as_str() {
                            lines.push(format!("{}：\n{}", label, value));
                        }
                    }
                }
            } else {
                let verb = match operation {
                    "move_file" => "移动或重命名文件",
                    "copy_file" => "复制文件",
                    "make_directory" => "创建文件夹",
                    "read_file" => "读取文件",
                    "list_entries" | "list_directory" => "查看文件夹",
                    "file_info" | "inspect_file" => "查看文件信息",
                    _ => return Err(fail("无法核对操作类型")),
                };
                lines.push(verb.into());
                for (field, label) in [
                    ("path", "位置"),
                    ("source", "来源"),
                    ("destination", "目标"),
                ] {
                    if let Some(value) = args[field].as_str() {
                        lines.push(format!("{}：{}", label, value));
                    }
                }
            }
            lines.push("仅本次操作。不会保存目录授权，也不会扩大云端披露权限。".into());
            lines.join("\n\n")
        } else {
            serde_json::to_string_pretty(proposal).map_err(|_| fail("操作内容不可用"))?
        };
        if details.len() > 12000 {
            return Err(fail("操作过大，请使用可信终端核对完整内容"));
        }
        let answer = rfd::AsyncMessageDialog::new()
            .set_parent(&window)
            .set_title("LocalPilot · 允许这一次操作？")
            .set_description(format!(
                "请核对操作、目标和影响。仅批准当前任务的这一个动作。\n\n{}",
                details
            ))
            .set_level(rfd::MessageLevel::Warning)
            .set_buttons(rfd::MessageButtons::OkCancelCustom(
                "允许一次".into(),
                "取消".into(),
            ))
            .show()
            .await;
        if answer != rfd::MessageDialogResult::Custom("允许一次".into()) {
            return Ok(json!({"status":"dismissed","action_sent":false}));
        }
    }
    cli_run(
        p,
        vec![
            "task".into(),
            action,
            task_id,
            "--action-id".into(),
            action_id,
            "--operator-token-env".into(),
            "LOCALPILOT_OPERATOR_TOKEN".into(),
        ],
    )
    .await
}
async fn companion_request(p: &Profile, body: Value) -> Result<Value, String> {
    let cfg = private_json(&Path::new(&p.home).join("companion.json"))?;
    let rec = private_json(
        &Path::new(cfg["data_dir"].as_str().ok_or("缺少 Companion data_dir")?).join("runtime.json"),
    )?;
    let port = rec["port"]
        .as_u64()
        .filter(|p| *p > 0 && *p < 65536)
        .ok_or("无效 Companion 端口")?;
    let token = rec["token"].as_str().ok_or("Companion 凭据缺失")?;
    let res = client()?
        .post(format!("http://127.0.0.1:{port}/command"))
        .bearer_auth(token)
        .json(&body)
        .send()
        .await
        .map_err(|_| fail("Companion 未连接；请启动服务"))?;
    if !res.status().is_success() {
        return Err(format!("Companion HTTP {}", res.status()));
    }
    Ok(redacted(
        res.json().await.map_err(|_| fail("Companion 响应无效"))?,
    ))
}
#[tauri::command]
async fn companion(
    n: State<'_, Native>,
    command: String,
    text: Option<String>,
    preferences: Option<Preferences>,
) -> Result<Value, String> {
    if !["status", "ask", "ui_snapshot", "escalation_status"].contains(&command.as_str()) {
        return Err(fail("未开放的 Companion 操作"));
    }
    let mut body = json!({"command":command});
    if command == "ask" {
        if let Some(ref prefs) = preferences {
            if prefs.source == preferences::Source::CloudOnly {
                return Err(fail("完全云端会话禁止本地轻量推理，请使用云端咨询"));
            }
            body["routing_preferences"] = preferences::wire(prefs);
        }
    }
    if let Some(value) = text {
        if value.len() > 12000 {
            return Err(fail("问题超出输入上限"));
        }
        body["text"] = json!(value);
    }
    companion_request(&current(&n), body).await
}
#[tauri::command]
async fn companion_control(
    n: State<'_, Native>,
    action: String,
    text: Option<String>,
    ticket: Option<String>,
    confirmed: bool,
    preferences: Preferences,
) -> Result<Value, String> {
    let mut body = json!({});
    match action.as_str() {
        "prepare_help" | "prepare_cloud" => {
            let question = text
                .filter(|s| !s.trim().is_empty() && s.len() <= 12000)
                .ok_or("缺少原问题")?;
            if action == "prepare_cloud" && preferences.source == preferences::Source::LocalOnly {
                return Err(fail("完全本地会话禁止云端咨询"));
            }
            body = json!({"command":if action=="prepare_help" {"escalate"} else {"consult_cloud"},"text":question});
        }
        "present" | "start" | "heartbeat" | "stop" => {
            let id = ticket.filter(|s| id_ok(s)).ok_or("缺少控制票据")?;
            body = json!({"command":match action.as_str() {"present"=>"desktop_control_presented","start"=>"inference_start","heartbeat"=>"inference_heartbeat",_=>"inference_stop"},"ticket_id":id});
            if action == "present" {
                body["pid"] = json!(std::process::id());
                body["routing_preferences"] = preferences::wire(&preferences);
            }
            if action == "start" {
                if !confirmed {
                    return Err(fail("需要明确的帮助或云端确认"));
                }
                body["confirmed"] = json!(true);
            }
        }
        _ => return Err(fail("未开放的委派控制")),
    }
    companion_request(&current(&n), body).await
}
fn journal_path(app: &tauri::AppHandle, key: &str) -> Result<PathBuf, String> {
    if !id_ok(key) {
        return Err(fail("请求键格式错误"));
    }
    let p = data(app)?.join("submissions");
    fs::create_dir_all(&p).map_err(|_| fail("无法创建提交记录"))?;
    fs::set_permissions(&p, fs::Permissions::from_mode(0o700))
        .map_err(|_| fail("提交目录权限错误"))?;
    Ok(p.join(format!("{key}.json")))
}
#[tauri::command]
async fn submit_task(
    app: tauri::AppHandle,
    n: State<'_, Native>,
    input: String,
    model: String,
    session_id: Option<String>,
    agent_consent: bool,
    cloud_consent: bool,
    effort: Option<String>,
    preferences: Preferences,
) -> Result<Value, String> {
    if !preferences::load(&data(&app)?)?.completed {
        return Err(fail("请先明确完成首次设置"));
    }
    let p = current(&n);
    let health = request(&p, "GET", "/healthz", None, None).await?;
    check_health(&health)?;
    let registry = request(&p, "GET", "/localpilot/v1/model-registry", None, None).await?;
    let automatic = model == "__auto__";
    let cap = if health["compatibility"]["capabilities"]
        .as_array()
        .is_some_and(|a| a.iter().any(|v| v == "routing_preferences_v1"))
    {
        request(&p, "GET", "/localpilot/v1/routing-capabilities", None, None).await?
    } else {
        Value::Null
    };
    let negotiated = preferences::routing_supported(&health, &cap);
    if automatic && !negotiated {
        return Err(fail("Core 未提供自动路由契约；请选择显式模型"));
    }
    let route = registry["models"]
        .as_array()
        .and_then(|a| a.iter().find(|r| r["id"] == model));
    if !automatic {
        let route = route.ok_or("模型未注册，已拒绝提交")?;
        if route["reasoning_only"] == true {
            return Err(fail("此路由仅供轻量对话或咨询，请选择标准 Agent 模型"));
        }
        if route["deployment_status"] != "ready" {
            return Err(fail("所选模型未部署，已拒绝提交"));
        }
        if !preferences::source_allows(&preferences, route) {
            return Err(fail("所选模型不符合本会话来源限制；未提交或替换模型"));
        }
    }
    if !agent_consent {
        return Err(fail("标准 Agent 需要明确的帮助确认"));
    }
    let cloud = if automatic {
        preferences.source != preferences::Source::LocalOnly
    } else {
        preferences::is_cloud(route.unwrap())
    };
    if cloud && !cloud_consent {
        return Err(fail("Cloud Egress 未授权，未提交任务"));
    }
    if cloud && route.is_some_and(|r| r["reasoning_only"] == true) && session_id.is_some() {
        return Err(fail("云端咨询或自动路由需要新的 Session"));
    }
    let selected_effort = effort.or(preferences.effort.clone());
    if let Some(ref value) = selected_effort {
        let supported = health["compatibility"]["capabilities"]
            .as_array()
            .is_some_and(|a| a.iter().any(|v| v == "session_thinking_v1"));
        if !supported
            || automatic
            || !route.is_some_and(|r| {
                r["reasoning_efforts"]
                    .as_array()
                    .is_some_and(|a| a.iter().any(|e| e == value))
            })
        {
            return Err(fail("所选模型未声明此思考档位；请选择支持该档位的显式模型"));
        }
    }
    if input.trim().is_empty() {
        return Err(fail("请输入问题"));
    }
    let limit = health["compatibility"]["limits"]["task_input_json_utf8_bytes"]
        .as_u64()
        .ok_or("服务未声明输入上限")?;
    if serde_json::to_vec(&input).unwrap().len() as u64 > limit {
        return Err(format!("原问题超过服务的 {limit} 字节上限；未截断、未提交"));
    }
    let mut low_power_consent = false;
    if !cloud && !automatic && route.is_some_and(|r| r["adapter"] == "omlx") {
        let power = std::process::Command::new("/usr/bin/pmset")
            .arg("-g")
            .output();
        let low = match power {
            Ok(value) if value.status.success() => {
                let text = String::from_utf8_lossy(&value.stdout);
                !text.lines().any(|line| {
                    let fields: Vec<_> = line.split_whitespace().collect();
                    fields.first() == Some(&"lowpowermode") && fields.get(1) == Some(&"0")
                })
            }
            _ => true,
        };
        if low {
            let dialog = rfd::AsyncMessageDialog::new()
                .set_title("LocalPilot · 低电量模式")
                .set_description("当前开启低电量模式，或暂时无法确认电源状态。运行本地模型可能增加耗电、发热，并使电脑变慢。\n\n是否允许本次任务继续？只授权这一次任务，不修改系统省电设置，后续任务会重新询问。")
                .set_level(rfd::MessageLevel::Warning)
                .set_buttons(rfd::MessageButtons::OkCancelCustom("本次允许".into(), "取消".into()));
            let answer = if let Some(window) = app.get_webview_window("main") {
                dialog.set_parent(&window).show().await
            } else {
                dialog.show().await
            };
            if answer != rfd::MessageDialogResult::Custom("本次允许".into()) {
                return Err(fail("已取消本次发送，没有提交任务。"));
            }
            if !health["compatibility"]["capabilities"]
                .as_array()
                .is_some_and(|a| a.iter().any(|v| v == "task_low_power_consent_v1"))
            {
                return Err(fail(
                    "Core 组件需更新以支持本次低电量授权，请在设置中更新内置组件。",
                ));
            }
            low_power_consent = true;
        }
    }
    let mut body = json!({"input":input,"timeout_seconds":600});
    if low_power_consent {
        body["low_power_consent"] = json!(true);
    }

    if !route.is_some_and(|r| r["reasoning_only"] == true) {
        body["required_capabilities"] = json!(["tool_calling"]);
    }
    if let Some(value) = selected_effort {
        body["reasoning_effort"] = json!(value);
    }
    if !automatic {
        body["model"] = json!(model);
    }
    if negotiated {
        body["routing_preferences"] = preferences::wire(&preferences);
    }
    if let Some(s) = session_id {
        if !id_ok(&s) {
            return Err(fail("Session ID 格式错误"));
        }
        body["session_id"] = json!(s);
    }
    let journal_root = data(&app)?.join("submissions");
    if journal_root.exists() {
        for file in fs::read_dir(&journal_root)
            .map_err(|_| fail("无法检查提交记录"))?
            .flatten()
        {
            if let Ok(rec) = private_json(&file.path()) {
                if pending_in_scope(&rec, &p.origin, &health["client_subject"]) {
                    return Err(fail(
                        "存在提交状态未确认的原请求。请恢复原请求，禁止另建重复任务。",
                    ));
                }
            }
        }
    }
    let key = format!("gui-{}", uuid::Uuid::new_v4());
    let mut pending = Pending {
        key: key.clone(),
        body: body.clone(),
        task_id: None,
        origin: p.origin.clone(),
        subject: health["client_subject"].as_str().unwrap_or("").into(),
        status: unknown_submission(),
        rejection: None,
        preferences: Some(preferences),
    };
    let path = journal_path(&app, &key)?;
    save(&path, &pending)?;
    submit_record(&p, &path, &mut pending, false).await
}

#[tauri::command]
async fn pending_submissions(
    app: tauri::AppHandle,
    n: State<'_, Native>,
) -> Result<Vec<Value>, String> {
    let profile = current(&n);
    let h = request(&profile, "GET", "/healthz", None, None).await?;
    check_health(&h)?;
    let subject = h["client_subject"].as_str().ok_or("服务未声明客户端身份")?;
    let p = data(&app)?.join("submissions");
    if !p.exists() {
        return Ok(vec![]);
    }
    let mut list = vec![];
    for f in fs::read_dir(p)
        .map_err(|_| fail("无法读取提交记录"))?
        .flatten()
    {
        if let Ok(v) = private_json(&f.path()) {
            if pending_in_scope(&v, &profile.origin, &json!(subject)) {
                list.push(json!({"key":v["key"],"input":v["body"]["input"],"origin":v["origin"],"subject":subject}));
            }
        }
    }
    Ok(list)
}
#[tauri::command]
async fn submission_history(app: tauri::AppHandle, n: State<'_, Native>) -> Result<Value, String> {
    let p = current(&n);
    let h = request(&p, "GET", "/healthz", None, None).await?;
    let root = data(&app)?.join("submissions");
    let mut result = serde_json::Map::new();
    if root.exists() {
        for f in fs::read_dir(root)
            .map_err(|_| fail("无法读取客户端历史"))?
            .flatten()
        {
            if let Ok(v) = private_json(&f.path()) {
                if v["origin"] == p.origin && v["subject"] == h["client_subject"] {
                    if let Some(id) = v["task_id"].as_str() {
                        result.insert(
                            id.to_string(),
                            json!({"input":v["body"]["input"],"model":v["body"]["model"],"preferences":v["preferences"]}),
                        );
                    }
                }
            }
        }
    }
    Ok(Value::Object(result))
}
#[tauri::command]
async fn recover_submission(
    app: tauri::AppHandle,
    n: State<'_, Native>,
    key: String,
) -> Result<Value, String> {
    let path = journal_path(&app, &key)?;
    let mut rec: Pending =
        serde_json::from_value(private_json(&path)?).map_err(|_| fail("原请求损坏"))?;
    let p = current(&n);
    let health = request(&p, "GET", "/healthz", None, None).await?;
    check_health(&health)?;
    if rec.origin != p.origin || rec.subject != health["client_subject"].as_str().unwrap_or("") {
        return Err(fail("原请求所属服务/身份不符，拒绝跨身份重试"));
    }
    if rec.status == "rejected" {
        return Err(fail("此原请求已明确拒绝，不可再次恢复；可新建会话提交。"));
    }
    if let Some(task_id) = &rec.task_id {
        return request(
            &p,
            "GET",
            &format!("/localpilot/v1/tasks/{task_id}"),
            None,
            None,
        )
        .await;
    }
    submit_record(&p, &path, &mut rec, true).await
}

#[derive(Default)]
struct Sse {
    buffer: Vec<u8>,
}
impl Sse {
    fn push(&mut self, bytes: &[u8]) -> Result<Vec<Value>, String> {
        self.buffer.extend_from_slice(bytes);
        if self.buffer.len() > 1024 * 1024 {
            return Err(fail("SSE 帧超过上限"));
        }
        let mut result = vec![];
        loop {
            let lf = self
                .buffer
                .windows(2)
                .position(|w| w == b"\n\n")
                .map(|i| (i, 2));
            let crlf = self
                .buffer
                .windows(4)
                .position(|w| w == b"\r\n\r\n")
                .map(|i| (i, 4));
            let end = match (lf, crlf) {
                (Some(a), Some(b)) => Some(if a.0 < b.0 { a } else { b }),
                (a, None) => a,
                (None, b) => b,
            };
            let Some((end, sep)) = end else { break };
            let frame = String::from_utf8(self.buffer.drain(..end + sep).collect())
                .map_err(|_| fail("SSE 编码错误"))?;
            let mut lines = vec![];
            for line in frame.lines() {
                if let Some(d) = line.strip_prefix("data:") {
                    lines.push(d.trim_start());
                }
            }
            let data = lines.join("\n");
            if data.is_empty() {
                continue;
            }
            if let Ok(v) = serde_json::from_str(&data) {
                result.push(v);
            }
        }
        Ok(result)
    }
}
async fn stream_task(app: tauri::AppHandle, p: Profile, id: String, mut cursor: u64) {
    let cursor_path = match data(&app) {
        Ok(d) => d.join(format!("cursor-{id}.json")),
        Err(_) => return,
    };
    if let Ok(v) = private_json(&cursor_path) {
        if v["origin"] == p.origin {
            cursor = cursor.max(v["after"].as_u64().unwrap_or(0));
        }
    }
    for attempt in 0..6u32 {
        let outcome = async {
            let token = core_token(&p)?;
            let res = client()?
                .get(format!(
                    "{}/localpilot/v1/tasks/{id}/events?after={cursor}",
                    p.origin
                ))
                .bearer_auth(token)
                .header("Last-Event-ID", cursor)
                .send()
                .await
                .map_err(|_| fail("SSE 连接中断"))?;
            if res.status() == 409 {
                let snap =
                    request(&p, "GET", &format!("/localpilot/v1/tasks/{id}"), None, None).await?;
                cursor = snap["last_event_id"].as_u64().unwrap_or(cursor);
                save(&cursor_path, &json!({"origin":p.origin,"after":cursor}))?;
                let settled = snap["quiescent"] == true;
                let _ = app.emit(
                    "task-stream",
                    json!({"taskId":id,"kind":"snapshot","data":snap,"reconciled":true}),
                );
                return Ok::<bool, String>(settled);
            }
            if !res.status().is_success() {
                return Err(format!("SSE HTTP {}", res.status()));
            }
            let _ = app.emit(
                "task-stream",
                json!({"taskId":id,"kind":"connected","attempt":attempt}),
            );
            let mut bytes = res.bytes_stream();
            let mut decoder = Sse::default();
            while let Some(part) = bytes.next().await {
                for event in decoder.push(&part.map_err(|_| fail("SSE 连接断开"))?)? {
                    if let Some(s) = event["sequence"].as_u64() {
                        if s <= cursor {
                            continue;
                        }
                        cursor = s;
                        save(&cursor_path, &json!({"origin":p.origin,"after":cursor}))?;
                    }
                    let _ = app.emit(
                        "task-stream",
                        json!({"taskId":id,"kind":"event","data":redacted(event)}),
                    );
                }
            }
            let snap =
                request(&p, "GET", &format!("/localpilot/v1/tasks/{id}"), None, None).await?;
            let settled = snap["quiescent"] == true;
            let _ = app.emit(
                "task-stream",
                json!({"taskId":id,"kind":"snapshot","data":snap}),
            );
            Ok(settled)
        }
        .await;
        if matches!(outcome, Ok(true)) {
            return;
        }
        let _ = app.emit(
            "task-stream",
            json!({"taskId":id,"kind":"reconnecting","attempt":attempt+1,"error":outcome.err()}),
        );
        tokio::time::sleep(Duration::from_secs((1u64 << attempt).min(16))).await;
    }
    let _=app.emit("task-stream",json!({"taskId":id,"kind":"disconnected","error":"重连已达上限。重新查询原任务，不会重新提交。"}));
}
#[tauri::command]
fn watch_task(
    app: tauri::AppHandle,
    n: State<Native>,
    task_id: String,
    after: u64,
) -> Result<(), String> {
    if !id_ok(&task_id) {
        return Err(fail("Task ID 无效"));
    }
    let mut watchers = n.watchers.lock().unwrap();
    if let Some(old) = watchers.remove(&task_id) {
        old.abort();
    }
    let h = tauri::async_runtime::spawn(stream_task(app, current(&n), task_id.clone(), after));
    watchers.insert(task_id, h);
    Ok(())
}
#[tauri::command]
fn unwatch_task(n: State<Native>, task_id: String) {
    if let Some(h) = n.watchers.lock().unwrap().remove(&task_id) {
        h.abort();
    }
}
fn validate_cli(p: &str) -> Result<(), String> {
    let p = Path::new(p);
    if !p.is_absolute()
        || p.file_name().and_then(|s| s.to_str()) != Some("localpilot")
        || !p.is_file()
    {
        return Err(fail("请选择已安装 Suite 的 bin/localpilot"));
    }
    Ok(())
}
async fn cli_run(p: Profile, args: Vec<String>) -> Result<Value, String> {
    validate_cli(&p.cli)?;
    let cmd = p.cli.clone();
    let home = p.home.clone();
    tauri::async_runtime::spawn_blocking(move || {
        let mut process = std::process::Command::new(cmd);
        if args == ["--version"] {
            process.arg("--version");
        } else {
            process.args(["--home", &home, "--json"]).args(&args);
        }
        use std::os::unix::process::CommandExt;
        unsafe {
            process.pre_exec(|| {
                libc::umask(0o077);
                Ok(())
            });
        }
        process
            .current_dir(&home)
            .env("PYTHONDONTWRITEBYTECODE", "1")
            .env_remove("LOCALPILOT_OPERATOR_TOKEN")
            .env_remove("DEEPSEEK_API_KEY");
        let mut child = process
            .stdout(std::process::Stdio::piped())
            .stderr(std::process::Stdio::null())
            .spawn()
            .map_err(|_| fail("无法启动 Suite CLI"))?;
        // Drain stdout concurrently so diagnostics cannot deadlock the child.
        let stdout = child.stdout.take().unwrap();
        let output_budget = if args.first().is_some_and(|a| a == "product-control") {
            8 * 1024 * 1024
        } else {
            512 * 1024
        };
        let reader = std::thread::spawn(move || {
            use std::io::Read;
            let mut s = String::new();
            let _ = stdout.take(output_budget).read_to_string(&mut s);
            s
        });
        let start = std::time::Instant::now();
        let status = loop {
            if let Some(s) = child.try_wait().map_err(|_| fail("CLI 状态不可读"))? {
                break s;
            }
            let deadline = if args.first().is_some_and(|a| a == "product-control") {
                1200
            } else if args.first().is_some_and(|a| a == "cloud-configure") {
                200
            } else if args.first().is_some_and(|a| a == "desktop-init") {
                200
            } else if args.first().is_some_and(|a| a == "model-resource") {
                140
            } else {
                45
            };
            if start.elapsed() > Duration::from_secs(deadline) {
                let _ = child.kill();
                let _ = child.wait();
                return Err(fail("管理命令超时，请重新查询服务状态"));
            }
            std::thread::sleep(Duration::from_millis(100));
        };
        let out = reader.join().unwrap_or_default();
        let lines: Vec<Value> = match serde_json::from_str::<Value>(&out) {
            Ok(v) => vec![redacted(v)],
            Err(_) => out
                .lines()
                .filter_map(|l| serde_json::from_str(l).ok())
                .map(redacted)
                .collect(),
        };
        Ok(json!({"exit":status.code(),"result":lines}))
    })
    .await
    .map_err(|_| fail("CLI 管理中断"))?
}
async fn checked_cli(p: Profile, args: Vec<String>) -> Result<Value, String> {
    let value = cli_run(p, args).await?;
    let result = value["result"]
        .as_array()
        .and_then(|a| a.last())
        .cloned()
        .unwrap_or(Value::Null);
    if value["exit"] != 0 || result.is_null() || result.get("error").is_some() {
        return Err(format!(
            "管理操作未完成：{}",
            result
                .get("error")
                .and_then(Value::as_str)
                .unwrap_or("请检查服务状态；操作未完成")
        ));
    }
    Ok(result)
}
fn tool_args(operation: &str, values: &Value, confirmed: bool) -> Result<Vec<String>, String> {
    let catalog: Value = serde_json::from_str(include_str!("../../src/cli-tools.json"))
        .map_err(|_| fail("命令目录无效"))?;
    let entry = catalog
        .as_array()
        .unwrap()
        .iter()
        .find(|c| c["id"] == operation)
        .ok_or("未开放的 Suite 功能")?;
    if entry["confirm"] == true && !confirmed {
        return Err(fail("需核对并确认此操作范围"));
    }
    let fields = entry["fields"].as_array().unwrap();
    let supplied = values.as_object().ok_or("参数必须是对象")?;
    if supplied
        .keys()
        .any(|k| !fields.iter().any(|f| f["key"] == k.as_str()))
    {
        return Err(fail("不接受未知命令参数"));
    }
    let mut args: Vec<String> = entry["command"]
        .as_array()
        .unwrap()
        .iter()
        .map(|s| s.as_str().unwrap().into())
        .collect();
    if let Some(flags) = entry["fixed_flags"].as_array() {
        args.extend(flags.iter().map(|v| v.as_str().unwrap().to_string()));
    }
    let mut positional = vec![];
    for f in fields {
        let key = f["key"].as_str().unwrap();
        let v = &values[key];
        let empty = v.is_null() || v.as_str() == Some("");
        if empty && (f["optional"] == true || f["type"] == "boolean") {
            continue;
        }
        if empty {
            return Err(format!("缺少参数：{key}"));
        }
        let mut list = vec![];
        match f["type"].as_str().unwrap() {
            "boolean" => {
                if !v.is_boolean() {
                    return Err(fail("布尔参数格式错误"));
                }
                if v == false {
                    continue;
                }
            }
            "number" => {
                let n = v.as_f64().filter(|v| v.is_finite()).ok_or("数值无效")?;
                if n < f["min"].as_f64().unwrap() || n > f["max"].as_f64().unwrap() {
                    return Err(fail("数值超过允许范围"));
                }
                list.push(n.to_string());
            }
            "choice" => {
                let text = v.as_str().ok_or("选项无效")?;
                if !f["options"].as_array().unwrap().iter().any(|o| o == text) {
                    return Err(fail("选项不在白名单内"));
                }
                list.push(text.to_string());
            }
            "text" => {
                let text = v
                    .as_str()
                    .filter(|s| s.len() <= 12000 && !s.contains('\0'))
                    .ok_or("文本无效或过长")?;
                if f["id"] == true && !id_ok(text) {
                    return Err(fail("ID 无效"));
                }
                if f["many"] == true {
                    for line in text.lines() {
                        let line = line.trim();
                        if line.is_empty() {
                            continue;
                        }
                        if line.len() > 200
                            || !line.bytes().all(|b| {
                                b.is_ascii_alphanumeric() || b == b'.' || b == b'-' || b == b'_'
                            })
                            || line.starts_with('-')
                        {
                            return Err(fail("应用 ID 无效"));
                        }
                        list.push(line.into());
                    }
                } else {
                    list.push(text.into());
                }
            }
            _ => return Err(fail("参数类型无效")),
        }
        if let Some(flag) = f["flag"].as_str() {
            args.push(flag.into());
            args.extend(list);
        } else {
            positional.extend(list);
        }
    }
    if !positional.is_empty() {
        args.push("--".into());
        args.extend(positional);
    }
    Ok(args)
}
#[tauri::command]
async fn initialize_suite(
    n: State<'_, Native>,
    home: String,
    cli: String,
    workspace: String,
    model: String,
    base_url: String,
    port: u16,
    managed: bool,
    confirmed: bool,
) -> Result<Value, String> {
    if !confirmed {
        return Err(fail("初始化需要明确确认"));
    }
    validate_cli(&cli)?;
    let root = Path::new(&home)
        .canonicalize()
        .map_err(|_| fail("请选择已存在的空数据目录"))?;
    if fs::read_dir(&root)
        .map_err(|_| fail("目录不可读"))?
        .next()
        .is_some()
    {
        return Err(fail("数据目录必须为空；不会覆盖既有配置"));
    }
    let work = Path::new(&workspace)
        .canonicalize()
        .map_err(|_| fail("工作区不存在"))?;
    if !work.is_dir() || root.starts_with(&work) || work.starts_with(&root) {
        return Err(fail("工作区和私有数据目录必须独立"));
    }
    if model.is_empty() || model.len() > 200 || model.chars().any(|c| c.is_control()) || port == 0 {
        return Err(fail("模型名或端口无效"));
    }
    let u = reqwest::Url::parse(&base_url).map_err(|_| fail("后端地址无效"))?;
    if u.scheme() != "http"
        || ![Some("127.0.0.1"), Some("[::1]"), Some("::1")].contains(&u.host_str())
        || !u.username().is_empty()
        || u.password().is_some()
        || u.path() != "/v1"
        || u.query().is_some()
        || u.fragment().is_some()
    {
        return Err(fail("本地后端须为数字 loopback /v1 地址"));
    }
    let p = Profile {
        home: root.to_string_lossy().into(),
        cli,
        ..Profile::default()
    };
    let mut args = vec![
        "init".to_string(),
        format!("--workspace={}", work.display()),
        format!("--port={port}"),
    ];
    if managed {
        args.push("--managed-qwen35".into());
    } else {
        args.push(format!("--model={model}"));
        args.push(format!("--base-url={base_url}"));
    }
    let _ = n;
    cli_run(p, args).await
}
#[tauri::command]
async fn bootstrap_product(
    app: tauri::AppHandle,
    n: State<'_, Native>,
    confirmed: bool,
) -> Result<Value, String> {
    if !confirmed {
        return Err(fail("安装独立模块和启动服务需要明确确认"));
    }
    let lock = n.setup_lock.clone();
    let _setup = lock.lock().await;
    let source = app
        .path()
        .resource_dir()
        .map_err(|_| fail("应用资源不可用"))?
        .join("bundled-backends");
    if !source.join("localpilot").is_file() {
        return Err(fail("此构建没有离线模块资源"));
    }
    let root = data(&app)?;
    let modules = root.join("modules");
    fs::create_dir_all(&modules).map_err(|_| fail("无法创建模块目录"))?;
    fs::set_permissions(&modules, fs::Permissions::from_mode(0o700))
        .map_err(|_| fail("模块目录权限错误"))?;
    use sha2::{Digest, Sha256};
    let verified =
        fs::read(source.join("verified-modules.json")).map_err(|_| fail("组件校验清单缺失"))?;
    let bundled_versions: Value =
        serde_json::from_slice(&verified).map_err(|_| fail("组件校验清单无效"))?;
    let identity = Sha256::digest(&verified)
        .iter()
        .take(10)
        .map(|b| format!("{b:02x}"))
        .collect::<String>();
    let module = modules.join(format!("bundle-{identity}"));
    if !module.exists() {
        fn bytes(path: &Path) -> Result<u64, String> {
            let mut total = 0;
            for entry in fs::read_dir(path).map_err(|_| fail("离线组件不可读"))? {
                let entry = entry.map_err(|_| fail("离线组件不可读"))?;
                let kind = entry.file_type().map_err(|_| fail("离线组件不可读"))?;
                if kind.is_dir() {
                    total += bytes(&entry.path())?;
                } else if kind.is_file() {
                    total += entry.metadata().map_err(|_| fail("离线组件不可读"))?.len();
                }
            }
            Ok(total)
        }
        use std::os::unix::ffi::OsStrExt;
        let path = std::ffi::CString::new(modules.as_os_str().as_bytes())
            .map_err(|_| fail("组件位置无效"))?;
        let mut space = std::mem::MaybeUninit::<libc::statvfs>::uninit();
        if unsafe { libc::statvfs(path.as_ptr(), space.as_mut_ptr()) } != 0 {
            return Err(fail("无法确认可用磁盘空间，请重试"));
        }
        let space = unsafe { space.assume_init() };
        if (space.f_bavail as u64).saturating_mul(space.f_frsize as u64)
            < bytes(&source)?.saturating_add(256 * 1024 * 1024)
        {
            return Err(fail(
                "磁盘空间不足。请释放空间后重试；现有配置、模型和历史未改动。",
            ));
        }
        let stage = modules.join(format!("install-{}", uuid::Uuid::new_v4()));
        let src = source.clone();
        let staging = stage.clone();
        tauri::async_runtime::spawn_blocking(move || {
            std::process::Command::new("/usr/bin/ditto")
                .args(["--norsrc", "--noextattr"])
                .arg(src)
                .arg(staging)
                .status()
        })
        .await
        .map_err(|_| fail("模块安装被中断"))?
        .map_err(|_| fail("无法复制离线模块"))?
        .success()
        .then_some(())
        .ok_or("离线模块复制失败")?;
        fs::rename(&stage, &module).map_err(|_| fail("模块目录已存在或无法提交安装"))?;
    }
    let prior = current(&n);
    let home = if !prior.home.is_empty() {
        PathBuf::from(&prior.home)
    } else {
        root.join("product-v5")
    };
    fs::create_dir_all(&home).map_err(|_| fail("无法创建产品配置目录"))?;
    fs::set_permissions(&home, fs::Permissions::from_mode(0o700))
        .map_err(|_| fail("产品目录权限错误"))?;
    let workspace = root.join("Workspace");
    let cli = module.join("localpilot").to_string_lossy().to_string();
    let p = Profile {
        home: home.to_string_lossy().to_string(),
        cli: cli.clone(),
        ..Profile::default()
    };
    let mut backup = Value::Null;
    if prior.home == p.home && !prior.cli.is_empty() && prior.cli != p.cli {
        // Stop only this candidate's owned services. Core refuses active work.
        if let Ok(health) = request(&prior, "GET", "/healthz", None, None).await {
            let parse = |v: &str| {
                semver::Version::parse(v).or_else(|_| {
                    semver::Version::parse(
                        &v.replace("rc", "-rc.")
                            .replace('a', "-alpha.")
                            .replace('b', "-beta."),
                    )
                })
            };
            if let (Ok(existing), Ok(bundled)) = (
                parse(health["version"].as_str().unwrap_or("")),
                parse(
                    bundled_versions["actual_module_versions"]["localpilot-agent-service"]
                        .as_str()
                        .ok_or("组件版本缺失")?,
                ),
            ) {
                if existing > bundled {
                    return Err(fail(
                        "已有 Core 比内置候选更新，未降级或改动数据。请继续连接现有版本。",
                    ));
                }
            }
        }
        let stopped = checked_cli(prior.clone(), vec!["stop".into()]).await?;
        if stopped["status"] != "stopped" {
            return Err(fail("原服务仍在停止；未启动第二个实例，请稍后检查状态。"));
        }
        checked_cli(prior.clone(), vec!["companion".into(), "stop".into()]).await?;
        let destination = root
            .join("module-backups")
            .join(uuid::Uuid::new_v4().to_string());
        match checked_cli(p.clone(),vec!["product-control".into(),"--request-json".into(),json!({"version":1,"operation":"backup_installation","args":{"destination":destination}}).to_string()]).await {
            Ok(value)=>backup=value,
            Err(error)=>{
                let core=checked_cli(prior.clone(),vec!["start".into()]).await;
                let companion=checked_cli(prior.clone(),vec!["companion".into(),"start".into()]).await;
                return Err(format!("备份未完成，升级已停止。原 Core 恢复：{}；Companion 恢复：{}。{error}",core.is_ok(),companion.is_ok()));
            }
        }
    }
    let result = match checked_cli(
        p.clone(),
        vec![
            "desktop-init".into(),
            format!("--workspace={}", workspace.display()),
        ],
    )
    .await
    {
        Ok(value) => value,
        Err(error) => {
            // A CLI timeout can leave the owned service healthy. Reconcile
            // through its authenticated API; never launch a duplicate or
            // accept a merely live PID as a completed installation.
            let mut probe = p.clone();
            let connection = private_json(&home.join("connection.json"))?;
            probe.origin = origin(connection["url"].as_str().ok_or("服务地址缺失")?)?;
            let health = request(&probe, "GET", "/healthz", None, None).await;
            let expected = bundled_versions["actual_module_versions"]["localpilot-agent-service"]
                .as_str()
                .ok_or("组件版本缺失")?;
            if !health
                .as_ref()
                .is_ok_and(|v| setup_recovery_ready(v, expected))
            {
                if !backup.is_null() {
                    let stopped = checked_cli(p.clone(), vec!["stop".into()]).await;
                    let safe = stopped.as_ref().is_ok_and(|v| v["status"] == "stopped");
                    let restored = if safe {
                        checked_cli(prior.clone(), vec!["start".into()])
                            .await
                            .is_ok()
                    } else {
                        false
                    };
                    if restored {
                        let _ =
                            checked_cli(prior.clone(), vec!["companion".into(), "start".into()])
                                .await;
                    }
                    save(
                        &root.join("upgrade-recovery.json"),
                        &json!({"status":if restored {"previous_runtime_restarted"}else{"UNKNOWN"},"backup":backup,"data_restored_in_place":false}),
                    )?;
                    return Err(format!(
                        "升级未完成。原运行环境恢复：{}；升级前备份已保留，未覆盖数据库。{error}",
                        if restored {
                            "已启动"
                        } else {
                            "尚未确认，请在服务诊断中检查"
                        }
                    ));
                }
                return Err(error);
            }
            let companion_ready = checked_cli(p.clone(), vec!["companion".into(), "start".into()])
                .await
                .is_ok();
            json!({"status":if companion_ready {"ready"} else {"partial"},"recovered_from_cli_error":true,"core_health_verified":true,"companion_ready":companion_ready,"setup_diagnostic":error})
        }
    };
    let connection = connect_suite(app, n, home.to_string_lossy().to_string(), cli).await?;
    Ok(json!({"connection":connection,"setup":result,"backup":backup}))
}
fn setup_recovery_ready(health: &Value, expected: &str) -> bool {
    health["status"] == "ready"
        && health["version"] == expected
        && health["persistence"] == true
        && health["compatibility"]["capabilities"]
            .as_array()
            .is_some_and(|caps| {
                [
                    "desktop_session_v1",
                    "desktop_profile_switch_v1",
                    "durable_tasks",
                ]
                .iter()
                .all(|required| caps.iter().any(|v| v.as_str() == Some(required)))
            })
}
#[tauri::command]
async fn suite_tool(
    n: State<'_, Native>,
    operation: String,
    values: Value,
    confirmed: bool,
) -> Result<Value, String> {
    let args = tool_args(&operation, &values, confirmed)?;
    cli_run(current(&n), args).await
}
#[tauri::command]
async fn lifecycle(n: State<'_, Native>, action: String) -> Result<Value, String> {
    let args: Vec<&str> = match action.as_str() {
        "start" => vec!["start"],
        "stop" => vec!["stop"],
        "doctor" => vec!["doctor"],
        "status" => vec!["status"],
        "restart" => vec!["restart"],
        "logs" => vec!["logs"],
        "config" => vec!["config"],
        "models" => vec!["models"],
        "version" => vec!["--version"],
        "companion_status" => vec!["companion", "status"],
        "companion_privacy" => vec!["companion", "privacy"],
        "companion_start" => vec!["companion", "start"],
        "companion_stop" => vec!["companion", "stop"],
        _ => return Err(fail("未开放的管理动作")),
    };
    cli_run(current(&n), args.into_iter().map(String::from).collect()).await
}
#[tauri::command]
async fn upgrade_plan(n: State<'_, Native>, module: String) -> Result<Value, String> {
    if !["core", "companion", "suite"].contains(&module.as_str()) {
        return Err(fail("未知模块"));
    }
    let wheel = rfd::AsyncFileDialog::new()
        .set_title("选择目标发布 wheel")
        .add_filter("Python wheel", &["whl"])
        .pick_file()
        .await
        .ok_or("已取消")?
        .path()
        .to_string_lossy()
        .to_string();
    let previous = rfd::AsyncFileDialog::new()
        .set_title("选择回滚用的旧 wheel")
        .add_filter("Python wheel", &["whl"])
        .pick_file()
        .await
        .ok_or("已取消：执行升级必须有具体回滚包")?
        .path()
        .to_string_lossy()
        .to_string();
    let p = current(&n);
    let mut result = cli_run(
        p.clone(),
        vec![
            "upgrade".into(),
            module.clone(),
            "--wheel".into(),
            wheel.clone(),
            "--previous-wheel".into(),
            previous.clone(),
        ],
    )
    .await?;
    if result["exit"] == 0 {
        let id = uuid::Uuid::new_v4().to_string();
        n.upgrades
            .lock()
            .unwrap()
            .insert(id.clone(), (p, module, wheel, previous));
        result["plan_id"] = json!(id);
    }
    Ok(result)
}
#[tauri::command]
async fn execute_upgrade(n: State<'_, Native>, plan_id: String) -> Result<Value, String> {
    let plan = n
        .upgrades
        .lock()
        .unwrap()
        .remove(&plan_id)
        .ok_or("升级计划已过期，请重新选择发布包")?;
    let p = current(&n);
    if plan.0.home != p.home || plan.0.cli != p.cli {
        return Err(fail("连接已改变，拒绝执行旧升级计划"));
    }
    cli_run(
        p,
        vec![
            "upgrade".into(),
            plan.1,
            "--wheel".into(),
            plan.2,
            "--previous-wheel".into(),
            plan.3,
            "--execute".into(),
        ],
    )
    .await
}
#[tauri::command]
async fn open_control_terminal(
    n: State<'_, Native>,
    task_id: String,
    action: String,
) -> Result<String, String> {
    if !id_ok(&task_id) || !["approve", "reject", "resume"].contains(&action.as_str()) {
        return Err(fail("控制动作格式无效"));
    }
    let p = current(&n);
    validate_cli(&p.cli)?;
    let snap = request(
        &p,
        "GET",
        &format!("/localpilot/v1/tasks/{task_id}"),
        None,
        None,
    )
    .await?;
    if snap["recovery"]["class"] == "UNKNOWN_BLOCKED"
        || snap["receipt_summary"]["unknown_effects"]
            .as_u64()
            .unwrap_or(0)
            > 0
    {
        return Err(fail("UNKNOWN 已隔离，只允许查询或取消"));
    }
    if action == "resume" && snap["recovery"]["class"] != "SAFE_TO_RESUME" {
        return Err(fail("当前任务不是 SAFE_TO_RESUME，拒绝生成恢复控制"));
    }
    let action_id = snap["required_action"]["id"]
        .as_str()
        .ok_or("当前没有待处理动作，请重新查询")?;
    if !id_ok(action_id) {
        return Err(fail("Action ID 无效"));
    }
    let quote = |s: &str| format!("'{}'", s.replace('\'', "'\\''"));
    // Only a command preview is returned. Operator credential remains in the user's trusted terminal.
    Ok(format!(
        "{} --home {} task {} {} --action-id {} --operator-token-env LOCALPILOT_OPERATOR_TOKEN",
        quote(&p.cli),
        quote(&p.home),
        action,
        quote(&task_id),
        quote(action_id)
    ))
}
fn main() {
    let mut context = tauri::generate_context!();
    if std::env::args()
        .collect::<Vec<_>>()
        .get(1)
        .is_some_and(|a| a == "--bundle-self-check")
    {
        // Read-only engineering smoke: no WebView, profile, user data or services.
        let result = (|| -> Result<Value, String> {
            use sha2::{Digest, Sha256};
            let executable = std::env::current_exe().map_err(|_| "executable unavailable")?;
            let resources = executable
                .parent()
                .and_then(Path::parent)
                .ok_or("bundle layout invalid")?
                .join("Resources/bundled-backends");
            let manifest: Value = serde_json::from_slice(
                &fs::read(resources.join("verified-modules.json"))
                    .map_err(|_| "resource manifest unavailable")?,
            )
            .map_err(|_| "resource manifest invalid")?;
            let hashes = manifest["wheel_hashes"]
                .as_object()
                .ok_or("wheel hashes unavailable")?;
            for (name, expected) in hashes {
                if name.contains('/') || name.contains("..") {
                    return Err("wheel name rejected".into());
                }
                let bytes = fs::read(resources.join("wheels").join(name))
                    .map_err(|_| "wheel unavailable")?;
                if format!("{:x}", Sha256::digest(bytes)) != expected.as_str().unwrap_or("") {
                    return Err("wheel integrity failed".into());
                }
            }
            Ok(
                json!({"status":"bundle_self_check_passed","version":env!("CARGO_PKG_VERSION"),"bundle_id":context.config().identifier,"architecture":std::env::consts::ARCH,"verified_wheels":hashes.len(),"modules":manifest["actual_module_versions"],"user_data_opened":false,"services_started":false}),
            )
        })();
        match result {
            Ok(value) => println!("{value}"),
            Err(code) => {
                eprintln!("{code}");
                std::process::exit(2);
            }
        }
        return;
    }
    if pet_native::standalone() {
        // Do not construct and immediately destroy a hidden WebView: AppKit's
        // file dialog can otherwise resurrect its empty native parent window.
        context.config_mut().app.windows.clear();
    }
    tauri::Builder::default()
        .manage(Native::default())
        .manage(pet_native::PetState::default())
        .on_window_event(|window, event| {
            if window.label() == "pet" {
                if matches!(
                    event,
                    tauri::WindowEvent::Resized(_) | tauri::WindowEvent::ScaleFactorChanged { .. }
                ) {
                    pet_edge::resized(&window.app_handle());
                }
                if let tauri::WindowEvent::Moved(position) = event {
                    pet_edge::record_moved(&window.app_handle(), *position);
                }
                if matches!(
                    event,
                    tauri::WindowEvent::Moved(_) | tauri::WindowEvent::ScaleFactorChanged { .. }
                ) {
                    pet_native::moved(&window.app_handle());
                }
            }
            if let tauri::WindowEvent::DragDrop(tauri::DragDropEvent::Drop { paths, .. }) = event {
                let state = window.state::<Native>();
                match product::register_checked(&state, paths.clone()) {
                    Ok(cards) => {
                        for row in &cards {
                            state
                                .selected_origins
                                .lock()
                                .unwrap()
                                .insert(row["id"].as_str().unwrap().into(), "drop".into());
                        }
                        let _ = window.emit("localpilot-files", cards);
                    }
                    Err(error) => {
                        let _ = window.emit("localpilot-files-error", error);
                    }
                }
            }
        })
        .manage(Maintenance::default())
        .setup(|app| {
            let path = data(app.handle())
                .map_err(std::io::Error::other)?
                .join("profile.json");
            if path.exists() {
                if let Ok(v) = private_json(&path) {
                    if let Ok(p) = serde_json::from_value(v) {
                        *app.state::<Native>().profile.lock().unwrap() = p;
                    }
                }
            }
            if pet_native::standalone() {
                if !pet_native::control_server(app.handle()).map_err(std::io::Error::other)? {
                    std::process::exit(0)
                }
                app.state::<pet_native::PetState>()
                    .standalone
                    .store(true, std::sync::atomic::Ordering::Relaxed);
                app.set_activation_policy(tauri::ActivationPolicy::Accessory);
                if let Some(w) = app.get_webview_window("main") {
                    w.destroy()?;
                }
                pet_native::bootstrap_profile(app.handle()).map_err(std::io::Error::other)?;
                pet_native::create(app.handle()).map_err(std::io::Error::other)?;
                pet_native::setup_tray(app.handle()).map_err(std::io::Error::other)?;
                let handle = app.handle().clone();
                tauri::async_runtime::spawn(async move {
                    let _ = pet_native::pet_runtime(
                        handle.clone(),
                        handle.state::<Native>(),
                        "start".into(),
                    )
                    .await;
                });
            }
            Ok(())
        })
        .invoke_handler(tauri::generate_handler![
            desktop_update_check,
            desktop_storage_scan,
            pick_attachments,
            pick_attachment_folder,
            remove_attachment,
            pick_workspace,
            stage_attachment,
            attachment_preview,
            attachment_thumbnail,
            open_attachment,
            product_control,
            channel_control,
            setup_progress,
            import_attachments,
            pet_window,
            pet_action,
            pet_edge,
            pet_service,
            pet_chat,
            pet_handoff_draft,
            pet_runtime,
            pet_asset,
            pet_agent,
            pet_core,
            pet_handoff,
            pet_expand,
            companion_settings,
            discover_suites,
            configure_cloud_key,
            desktop_installation,
            desktop_open_release,
            desktop_verify_archive,
            profile,
            appearance,
            suite_tool,
            initialize_suite,
            bootstrap_product,
            installation_backup,
            installation_location,
            developer_profile,
            pick_developer_python,
            pick_developer_source,
            developer_command,
            global_preferences,
            session_preferences,
            routing_capabilities,
            model_manager,
            open_model_manager,
            model_resource,
            import_omlx_models,
            open_omlx_setup,
            add_cloud_provider,
            configure_cloud_scope,
            task_control,
            connect_suite,
            api,
            companion,
            companion_control,
            submit_task,
            recover_submission,
            pending_submissions,
            submission_history,
            watch_task,
            unwatch_task,
            pick_suite,
            lifecycle,
            upgrade_plan,
            execute_upgrade,
            open_control_terminal
        ])
        .build(context)
        .expect("LocalPilot desktop failed")
        .run(|app, event| {
            if let tauri::RunEvent::Exit = event {
                if !pet_native::standalone() {
                    let profile = current(&app.state::<Native>());
                    if !profile.home.is_empty() {
                        if let Ok(resources) = app.path().resource_dir() {
                            for kind in ["qq", "wechat"] {
                                let _ = channels::run(
                                    &resources.join("bundled-backends/localpilot"),
                                    &profile.home,
                                    kind,
                                    "exit",
                                    json!({}),
                                );
                            }
                        }
                    }
                }
            }
        });
}
#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn startup_recovery_requires_the_exact_healthy_authenticated_service() {
        let health = json!({"status":"ready","version":"5.0.0b10","persistence":true,"compatibility":{"capabilities":["desktop_session_v1","desktop_profile_switch_v1","durable_tasks"]}});
        assert!(setup_recovery_ready(&health, "5.0.0b10"));
        assert!(!setup_recovery_ready(&health, "5.0.0b9"));
        for key in ["status", "version", "persistence", "compatibility"] {
            let mut invalid = health.clone();
            invalid.as_object_mut().unwrap().remove(key);
            assert!(!setup_recovery_ready(&invalid, "5.0.0b10"));
        }
    }
    #[test]
    fn suite_tools_cannot_inject_commands_or_unreviewed_authority() {
        assert!(tool_args("approve", &json!({}), true).is_err());
        assert!(tool_args("companion-authorize-observation", &json!({}), false).is_err());
        assert!(tool_args("doctor", &json!({"args":"--execute"}), true).is_err());
        assert!(tool_args("companion-launchd", &json!({"operation":"sudo"}), true).is_err());
        let args = tool_args(
            "companion-remember",
            &json!({"type":"preference","text":"--config=/private/never"}),
            true,
        )
        .unwrap();
        assert_eq!(
            args,
            vec![
                "companion",
                "remember",
                "--",
                "preference",
                "--config=/private/never"
            ]
        );
        let args = tool_args(
            "companion-proactive",
            &json!({"level":"off","delivery":"silent"}),
            true,
        )
        .unwrap();
        assert_eq!(
            args,
            vec![
                "companion",
                "proactive",
                "--level",
                "off",
                "--delivery",
                "silent"
            ]
        );
    }
    #[test]
    fn definitive_refusal_is_not_an_ambiguous_failure() {
        assert!(definitive_rejection(
            503,
            &json!({"error":{"code":"model_unavailable"}}),
            false
        ));
        assert!(!definitive_rejection(
            503,
            &json!({"error":{"code":"model_unavailable"}}),
            true
        ));
        assert!(definitive_rejection(
            409,
            &json!({"error":{"code":"session_closed"}}),
            false
        ));
        assert!(definitive_rejection(
            409,
            &json!({"error":{"code":"session_closed"}}),
            true
        ));
        for status in [409, 500, 502, 503] {
            assert!(!definitive_rejection(
                status,
                &json!({"error":{"code":"idempotency_conflict"}}),
                false
            ));
        }
        assert!(!definitive_rejection(
            409,
            &json!({"error":{"code":"model_not_deployed"}}),
            true
        ));
    }
    #[test]
    fn pending_namespace_includes_origin_subject_and_disposition() {
        let mut v = json!({"origin":"http://127.0.0.1:1","subject":"a","task_id":null});
        assert!(pending_in_scope(&v, "http://127.0.0.1:1", &json!("a")));
        assert!(!pending_in_scope(&v, "http://127.0.0.1:1", &json!("b")));
        assert!(!pending_in_scope(&v, "http://127.0.0.1:2", &json!("a")));
        v["status"] = json!("rejected");
        assert!(!pending_in_scope(&v, "http://127.0.0.1:1", &json!("a")));
    }
    #[test]
    #[ignore = "starts released Core HTTP with a scripted model; set LP_GUI_TEST_PYTHON"]
    fn real_core_recovery_and_identity() {
        use std::io::{BufRead, BufReader};
        let python = std::env::var("LP_GUI_TEST_PYTHON").expect("set installed Suite python");
        let script = Path::new(env!("CARGO_MANIFEST_DIR")).join("../scripts/recovery-fixture.py");
        let mut child = std::process::Command::new(python)
            .arg(script)
            .stdin(std::process::Stdio::piped())
            .stdout(std::process::Stdio::piped())
            .stderr(std::process::Stdio::inherit())
            .spawn()
            .unwrap();
        let mut line = String::new();
        BufReader::new(child.stdout.take().unwrap())
            .read_line(&mut line)
            .unwrap();
        let cfg: Value = serde_json::from_str(&line).expect("fixture startup");
        let root = PathBuf::from(cfg["state"].as_str().unwrap());
        fs::create_dir(&root).unwrap();
        let rt = tokio::runtime::Runtime::new().unwrap();
        rt.block_on(async {
            let p = Profile {home:cfg["home_a"].as_str().unwrap().into(),origin:cfg["origin"].as_str().unwrap().into(),..Profile::default()};
            let h=request(&p,"GET","/healthz",None,None).await.unwrap();check_health(&h).unwrap();
            let mut rec=Pending{key:"native-rejected".into(),body:json!({"input":"fixture","model":"localpilot","session_id":cfg["closed_session"]}),task_id:None,origin:p.origin.clone(),subject:"fixture-a".into(),status:unknown_submission(),rejection:None,preferences:Some(Preferences::default())};
            let path=root.join("closed.json");save(&path,&rec).unwrap();
            let err=submit_record(&p,&path,&mut rec,false).await.unwrap_err();assert!(err.contains("session_closed"));assert_eq!(rec.status,"rejected");assert!(!pending_in_scope(&private_json(&path).unwrap(),&p.origin,&json!("fixture-a")));
            let mut next=Pending {key:"native-new".into(),body:json!({"input":"fixture","model":"localpilot"}),task_id:None,origin:p.origin.clone(),subject:"fixture-a".into(),status:unknown_submission(),rejection:None,preferences:Some(Preferences::default())};
            let next_task=submit_record(&p,&root.join("next.json"),&mut next,false).await.unwrap();assert!(next_task["id"].is_string());
            let proxy=Profile {origin:cfg["proxy"].as_str().unwrap().into(),..p.clone()};
            let mut unknown=Pending {key:"native-cut-once".into(),body:json!({"input":"fixture","model":"localpilot"}),task_id:None,origin:proxy.origin.clone(),subject:"fixture-a".into(),status:unknown_submission(),rejection:None,preferences:Some(Preferences::default())};
            let path=root.join("unknown.json");save(&path,&unknown).unwrap();assert!(submit_record(&proxy,&path,&mut unknown,false).await.is_err());assert_eq!(unknown.status,"unknown");
            let v=private_json(&path).unwrap();assert!(pending_in_scope(&v,&proxy.origin,&json!("fixture-a")));assert!(!pending_in_scope(&v,&proxy.origin,&json!("fixture-b")));
            let recovered=submit_record(&proxy,&path,&mut unknown,true).await.unwrap();let repeated=submit_record(&proxy,&path,&mut unknown,true).await.unwrap();assert_eq!(recovered["id"],repeated["id"]);
            let tasks=request(&p,"GET","/localpilot/v1/tasks",None,None).await.unwrap();assert_eq!(tasks["tasks"].as_array().unwrap().len(),2);
            let b=Profile{home:cfg["home_b"].as_str().unwrap().into(),..p.clone()};assert_eq!(request(&b,"GET","/localpilot/v1/tasks",None,None).await.unwrap()["tasks"].as_array().unwrap().len(),0);
            println!("REAL_CORE_SCRIPTED_MODEL: closed-session rejected, next submission accepted, lost-POST same-key recovery yields one task, two identities isolated; tasks=2");
        });
        drop(child.stdin.take());
        assert!(child.wait().unwrap().success());
    }
    #[test]
    fn loopback_only() {
        for s in [
            "https://example.com",
            "http://localhost:8765",
            "http://127.0.0.1:80/token",
            "http://x@127.0.0.1:80",
            "http://127.0.0.1:80?x=1",
        ] {
            assert!(origin(s).is_err());
        }
        assert!(origin("http://127.0.0.1:8765").is_ok());
    }
    #[test]
    fn read_allowlist() {
        assert!(read_path("/localpilot/v1/tasks/resp_123"));
        for s in [
            "/localpilot/v1/tasks/../approve",
            "/localpilot/v1/tasks/resp_1/approve",
            "/secret",
            "/v1/responses",
        ] {
            assert!(!read_path(s));
        }
    }
    #[test]
    fn sse_fragmented_unicode_and_crlf() {
        let mut s = Sse::default();
        let b = "id: 2\r\ndata: {\"sequence\":2,\"text\":\"你好\"}\r\n\r\n".as_bytes();
        let mut values = vec![];
        for c in b.chunks(3) {
            values.extend(s.push(c).unwrap());
        }
        assert_eq!(values[0]["text"], "你好");
        assert_eq!(values.len(), 1);
    }
    #[test]
    fn strips_credentials() {
        let v = redacted(
            json!({"token":"secret","status":"ok","nested":{"_host_control_nonce":"x","text":"hello"}}),
        );
        assert!(v.get("token").is_none());
        assert!(v["nested"].get("_host_control_nonce").is_none());
    }
    #[test]
    fn mixed_sse_line_endings() {
        let mut d = Sse::default();
        let frames = d
            .push(b"data: {\"sequence\":1}\r\n\r\ndata: {\"sequence\":2}\n\n")
            .unwrap();
        assert_eq!(frames.len(), 2);
        assert_eq!(frames[0]["sequence"], 1);
    }
    #[test]
    fn private_credentials_reject_public_permissions_and_shell() {
        let root = std::env::temp_dir().join(format!("lp-test-{}", uuid::Uuid::new_v4()));
        fs::create_dir(&root).unwrap();
        let p = root.join("clients.env");
        fs::write(
            &p,
            "export TOKEN=abcdefghijklmnop012345
",
        )
        .unwrap();
        fs::set_permissions(&p, fs::Permissions::from_mode(0o644)).unwrap();
        assert!(credential_file(&p, "TOKEN").is_err());
        fs::set_permissions(&p, fs::Permissions::from_mode(0o600)).unwrap();
        assert!(credential_file(&p, "TOKEN").is_ok());
        fs::write(
            &p,
            "export TOKEN=$(touch /tmp/never-run)
",
        )
        .unwrap();
        assert!(credential_file(&p, "TOKEN").is_err());
        let _ = fs::remove_file(p);
        let _ = fs::remove_dir(root);
    }
}
