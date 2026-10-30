//! Independent presentation adapter. All intelligence stays in Companion and Core.
use super::*;
use serde::{Deserialize, Serialize};
use std::io::{Read, Write};
use std::os::unix::net::{UnixListener, UnixStream};
use std::sync::atomic::{AtomicBool, Ordering};

#[derive(Clone, Serialize, Deserialize)]
#[serde(default, deny_unknown_fields)]
pub struct PetSettings {
    pub version: u32,
    pub topmost: bool,
    pub size: f64,
    pub animation: bool,
    pub quiet: bool,
    pub focus: bool,
    pub proactive: bool,
    pub banter: bool,
    pub cooldown_minutes: u32,
    pub daily_limit: u32,
    pub quiet_start: u32,
    pub quiet_end: u32,
    pub event_allowlist: Vec<String>,
}
impl Default for PetSettings {
    fn default() -> Self {
        Self {
            version: 1,
            topmost: true,
            size: 1.0,
            animation: true,
            quiet: false,
            focus: true,
            proactive: false,
            banter: true,
            cooldown_minutes: 30,
            daily_limit: 4,
            quiet_start: 22,
            quiet_end: 8,
            event_allowlist: vec![
                "explicit_reminder".into(),
                "localpilot_completed".into(),
                "repeated_error".into(),
            ],
        }
    }
}
#[derive(Default)]
pub struct PetState {
    pub expanded: AtomicBool,
    pub mini_glass: AtomicBool,
    pub restoring: AtomicBool,
    pub ready_scheduled: AtomicBool,
    pub restore_target: Mutex<Option<tauri::PhysicalPosition<i32>>>,
    pub standalone: AtomicBool,
    pub settings: Mutex<PetSettings>,
    pub position_save: Mutex<Option<tauri::async_runtime::JoinHandle<()>>>,
    pub sprite: Mutex<Option<super::pet_assets::Sprite>>,
    pub pose: Mutex<(u32, u32)>,
    pub bubble_height: std::sync::atomic::AtomicU32,
    pub dragging: AtomicBool,
    pub instance_lock: Mutex<Option<fs::File>>,
    pub generation: std::sync::atomic::AtomicU64,
    pub down_count: std::sync::atomic::AtomicU32,
    pub drag_event_count: std::sync::atomic::AtomicU32,
    pub up_count: std::sync::atomic::AtomicU32,
    pub drag_count: std::sync::atomic::AtomicU32,
    pub edge: Mutex<pet_edge::EdgeState>,
    pub submission_lock: tokio::sync::Mutex<()>,
}
// Connecting Core must not redirect the independent lightweight Companion.
pub fn companion_profile(app: &tauri::AppHandle, mut p: Profile) -> Result<Profile, String> {
    if app.state::<PetState>().standalone.load(Ordering::Relaxed) {
        let independent = data(app)?.join("companion-home");
        if independent.join("companion.json").is_file() {
            p.home = independent.to_string_lossy().into();
        }
    }
    Ok(p)
}
pub fn standalone() -> bool {
    std::env::args().any(|a| a == "--companion-pet")
        || tauri::utils::platform::current_exe().ok().is_some_and(|p| {
            p.to_string_lossy()
                .contains("LocalPilot Companion Pet Test.app")
                || p.to_string_lossy()
                    .contains("LocalPilot DeepSeek Pet Test.app")
                || p.to_string_lossy().contains("LocalPilot Edge Pet Test.app")
        })
}
pub fn control(app: &tauri::AppHandle, action: &str) -> bool {
    let Ok(root) = data(app) else { return false };
    let Ok(mut socket) = UnixStream::connect(root.join("pet-control.sock")) else {
        return false;
    };
    socket.write_all(action.as_bytes()).is_ok()
}
pub fn control_server(app: &tauri::AppHandle) -> Result<bool, String> {
    let lock_path = data(app)?.join("pet-instance.lock");
    let lock = fs::OpenOptions::new()
        .read(true)
        .write(true)
        .create(true)
        .mode(0o600)
        .custom_flags(libc::O_NOFOLLOW)
        .open(lock_path)
        .map_err(|e| e.to_string())?;
    if unsafe {
        libc::flock(
            std::os::fd::AsRawFd::as_raw_fd(&lock),
            libc::LOCK_EX | libc::LOCK_NB,
        )
    } != 0
    {
        if control(app, "show") {
            return Ok(false);
        }
        return Err("已有宠物实例暂未响应；请用菜单栏恢复，未创建第二个角色".into());
    }
    *app.state::<PetState>().instance_lock.lock().unwrap() = Some(lock);
    let socket = data(app)?.join("pet-control.sock");
    if socket.exists() {
        fs::remove_file(&socket).map_err(|e| e.to_string())?;
    }
    let listener = UnixListener::bind(&socket).map_err(|e| e.to_string())?;
    fs::set_permissions(&socket, fs::Permissions::from_mode(0o600)).map_err(|e| e.to_string())?;
    let handle = app.clone();
    std::thread::spawn(move || {
        for stream in listener.incoming() {
            let Ok(mut stream) = stream else { break };
            let _ = stream.set_read_timeout(Some(Duration::from_secs(2)));
            let mut buffer = [0u8; 128];
            let Ok(n) = stream.read(&mut buffer) else {
                continue;
            };
            let command = String::from_utf8_lossy(&buffer[..n]).to_string();
            let app = handle.clone();
            let _ = handle.run_on_main_thread(move || match command.as_str() {
                "show" => {
                    if let Some(w) = app.get_webview_window("pet") {
                        let _ = w.show();
                        let _ = app.emit("pet-visibility", true);
                    }
                }
                "center" => {
                    if let Some(w) = app.get_webview_window("pet") {
                        if let Ok(Some(m)) = w.current_monitor() {
                            let a = m.work_area();
                            let z = w.outer_size().unwrap();
                            let _ = w.set_position(tauri::PhysicalPosition::new(
                                a.position.x + (a.size.width - z.width) as i32 / 2,
                                a.position.y + (a.size.height - z.height) as i32 / 2,
                            ));
                        }
                    }
                }
                "inspect" => {
                    if let (Ok(root), Ok(report)) =
                        (data(&app), super::pet_macos::diagnostics(&app))
                    {
                        let _ = save(&root.join("pet-window-diagnostics.json"), &report);
                    }
                }
                "hide" => {
                    let _ = expand(&app, false, false);
                    if let Some(w) = app.get_webview_window("pet") {
                        let _ = w.hide();
                    }
                    let _ = app.emit("pet-visibility", false);
                }
                "quit" => {
                    let _ = persist_position(&app);
                    app.exit(0)
                }
                _ => {
                    if let Some(raw) = command.strip_prefix("anchor:") {
                        if let Ok(anchor) = serde_json::from_value::<pet_edge::Anchor>(json!(raw)) {
                            let _ = expand(&app, false, false);
                            let _ = pet_edge::relocate(&app, Some(anchor));
                        }
                    }
                    if let Some(raw) = command.strip_prefix("character:") {
                        let id = match raw {
                            "deepseek" => Some("deepseek-whale-maid-chibi-v4"),
                            "claude" => Some("claude-orange-scholar-chibi-v3"),
                            "gemini" => Some("gemini-star-cat-chibi-v1"),
                            _ => None,
                        };
                        if let Some(id) = id {
                            let app = app.clone();
                            tauri::async_runtime::spawn(async move {
                                let _ = super::pet_assets::pet_asset(
                                    app,
                                    "select_local".into(),
                                    Some(id.into()),
                                )
                                .await;
                            });
                        }
                    }
                }
            });
        }
    });
    Ok(true)
}
#[tauri::command]
pub fn pet_handoff_draft(app: tauri::AppHandle) -> Result<Value, String> {
    let path = data(&app)?.join("pet-handoff.json");
    if !path.exists() {
        return Ok(Value::Null);
    }
    let v = private_json(&path)?;
    fs::remove_file(path).map_err(|e| e.to_string())?;
    Ok(v)
}
pub fn bootstrap_profile(app: &tauri::AppHandle) -> Result<(), String> {
    let mut p = current(&app.state::<Native>());
    if !p.home.is_empty() {
        return Ok(());
    }
    let root = data(app)?.join("companion-home");
    fs::create_dir_all(&root).map_err(|e| e.to_string())?;
    fs::set_permissions(&root, fs::Permissions::from_mode(0o700)).map_err(|e| e.to_string())?;
    let config = root.join("companion.json");
    if !config.exists() {
        save(
            &config,
            &json!({"data_dir":root.join("companion-data"),"backend":"disabled","watch_dirs":[],"native_observation_enabled":false,"notifications":false,"proactive_level":"off","proactive_delivery":"silent","localpilot_endpoint":"","localpilot_auto_local":false,"allow_automatic_cloud":false,"low_power_policy":"always","eco_unload_seconds":15}),
        )?;
    }
    p.home = root.to_string_lossy().to_string();
    p.cli = app
        .path()
        .resource_dir()
        .map_err(|e| e.to_string())?
        .join("bundled-backends/localpilot")
        .to_string_lossy()
        .to_string();
    save(&data(app)?.join("profile.json"), &p)?;
    *app.state::<Native>().profile.lock().unwrap() = p;
    Ok(())
}
#[tauri::command]
pub async fn pet_runtime(
    app: tauri::AppHandle,
    n: State<'_, Native>,
    action: String,
) -> Result<Value, String> {
    let p = companion_profile(&app, current(&n))?;
    let config = Path::new(&p.home).join("companion.json");
    let launch = data(&app)?.join("pet-runtime-v1.json");
    if action == "choose_python" {
        let file = rfd::AsyncFileDialog::new()
            .set_title("选择已有的 Python 模型运行程序（不下载）")
            .pick_file()
            .await;
        let Some(file) = file else {
            return Ok(json!({"cancelled":true}));
        };
        let path = file.path();
        let name = path
            .file_name()
            .and_then(|n| n.to_str())
            .ok_or("运行程序无效")?;
        if !name.starts_with("python")
            || fs::metadata(path)
                .map_err(|e| e.to_string())?
                .permissions()
                .mode()
                & 0o111
                == 0
        {
            return Err("请选择已有的 Python 可执行程序".into());
        }
        save(&launch, &json!({"version":1,"python":path}))?;
        return Ok(json!({"status":"ok","text":"模型运行程序已保存；重启轻聊服务后生效。"}));
    }
    if action == "choose_model" {
        let folder = rfd::AsyncFileDialog::new()
            .set_title("选择已有的轻量本地模型文件夹（不下载）")
            .pick_folder()
            .await;
        let Some(folder) = folder else {
            return Ok(json!({"cancelled":true}));
        };
        let path = folder.path();
        let meta: Value = serde_json::from_slice(
            &fs::read(path.join("config.json")).map_err(|_| "模型配置不存在")?,
        )
        .map_err(|_| "模型配置无效")?;
        let text = &meta["text_config"];
        if meta["model_type"] != "qwen3_5"
            || text["hidden_size"] != 1024
            || text["num_hidden_layers"] != 24
            || text["intermediate_size"] != 3584
        {
            return Err("省电模式当前仅接受已验证的 Qwen3.5-0.8B 结构".into());
        }
        let mut cfg = private_json(&config)?;
        cfg["backend"] = json!("mlx");
        cfg["model_path"] = json!(path);
        save(&config, &cfg)?;
        return Ok(json!({"status":"ok","text":"轻量模型已保存；重启轻聊服务后生效。"}));
    }
    if action != "start" && action != "stop" {
        return Err("未知轻聊服务操作".into());
    }
    if action == "start"
        && companion_request(&p, json!({"command":"status"}))
            .await
            .is_ok()
    {
        return Ok(json!({"status":"running"}));
    }
    let resources = app
        .path()
        .resource_dir()
        .map_err(|e| e.to_string())?
        .join("bundled-backends/runtime");
    let python = private_json(&launch)
        .ok()
        .and_then(|v| v["python"].as_str().map(PathBuf::from))
        .unwrap_or_else(|| resources.join("bin/python3.14"));
    let action = action.clone();
    tauri::async_runtime::spawn_blocking(move || {
        let mut cmd = std::process::Command::new(&python);
        cmd.env_clear();
        for key in ["HOME", "PATH", "TMPDIR", "LANG", "LC_CTYPE"] {
            if let Ok(value) = std::env::var(key) {
                cmd.env(key, value);
            }
        }
        // Only the reviewed packaged Companion is added. The selected Python's
        // own MLX installation supplies optional inference dependencies.
        cmd.env("PYTHONPATH", resources.join("lib/python3.14/site-packages"))
            .env("PYTHONNOUSERSITE", "1")
            .env("HF_HUB_OFFLINE", "1")
            .env("TRANSFORMERS_OFFLINE", "1");
        if python.starts_with(&resources) {
            cmd.env("PYTHONHOME", &resources);
        }
        let out = cmd
            .args(["-m", "companion", "--config"])
            .arg(config)
            .arg(action)
            .output()
            .map_err(|_| "无法启动已有的轻聊运行程序".to_string())?;
        if !out.status.success() {
            return Err("轻聊服务未启动；请检查模型运行程序与独立配置。".into());
        }
        let result: Value =
            serde_json::from_slice(&out.stdout).map_err(|_| "轻聊服务返回格式无效")?;
        Ok(redacted(result))
    })
    .await
    .map_err(|e| e.to_string())?
}
fn settings(app: &tauri::AppHandle) -> PetSettings {
    app.state::<PetState>().settings.lock().unwrap().clone()
}
fn persist_position(app: &tauri::AppHandle) -> Result<(), String> {
    if let Some(w) = app.get_webview_window("pet") {
        let p = w.outer_position().map_err(|e| e.to_string())?;
        let size = w.outer_size().map_err(|e| e.to_string())?;
        save(
            &data(app)?.join("pet-position-v2.json"),
            &json!({"version":2,"x":p.x,"y":p.y,"width":size.width,"height":size.height}),
        )?;
    }
    Ok(())
}
pub fn moved(app: &tauri::AppHandle) {
    if app.state::<PetState>().restoring.load(Ordering::Relaxed) {
        return;
    }
    let _ = follow(app);
    let state = app.state::<PetState>();
    let mut pending = state.position_save.lock().unwrap();
    if let Some(task) = pending.take() {
        task.abort()
    }
    let handle = app.clone();
    *pending = Some(tauri::async_runtime::spawn(async move {
        tokio::time::sleep(Duration::from_millis(500)).await;
        let app = handle.clone();
        let _ = handle.run_on_main_thread(move || {
            let _ = persist_position(&app);
        });
    }));
}
/// Pure physical-coordinate placement; work areas exclude menu bar and Dock.
pub fn bubble_origin(
    pet: (i32, i32, u32, u32),
    area: (i32, i32, u32, u32),
    size: (u32, u32),
) -> (i32, i32) {
    let (x, y, w, _h) = pet;
    let (ax, ay, aw, ah) = area;
    let (bw, bh) = size;
    let left = x + w as i32 - bw as i32;
    let above = y - bh as i32 - 8;
    let by = if above >= ay { above } else { y + 8 };
    (
        left.clamp(ax, ax + (aw.saturating_sub(bw)) as i32),
        by.clamp(ay, ay + (ah.saturating_sub(bh)) as i32),
    )
}
pub fn follow(app: &tauri::AppHandle) -> Result<(), String> {
    let (Some(pet), Some(bubble)) = (
        app.get_webview_window("pet"),
        app.get_webview_window("pet-bubble"),
    ) else {
        return Ok(());
    };
    let p = pet.outer_position().map_err(|e| e.to_string())?;
    let s = pet.outer_size().map_err(|e| e.to_string())?;
    let Some(m) = pet.current_monitor().map_err(|e| e.to_string())? else {
        return Ok(());
    };
    let area = m.work_area();
    let scale = m.scale_factor();
    let bw = (320.0 * scale).min(area.size.width as f64) as u32;
    let height = app
        .state::<PetState>()
        .bubble_height
        .load(Ordering::Relaxed)
        .clamp(180, 420);
    let bh = (height as f64 * scale).min(area.size.height as f64) as u32;
    let anchor = app.state::<PetState>().edge.lock().unwrap().anchor;
    let mini = pet_edge::chat_box(anchor);
    let factor = s.width as f64 / pet_edge::VIEW_W;
    let (mx, my, mw, mh) = (
        (mini[0] * factor) as i32,
        (mini[1] * factor) as i32,
        (mini[2] * factor) as i32,
        (mini[3] * factor) as i32,
    );
    let left = matches!(
        anchor,
        pet_edge::Anchor::TopLeft | pet_edge::Anchor::LeftEdge | pet_edge::Anchor::BottomLeft
    );
    let x = if left {
        p.x + mx
    } else {
        p.x + mx + mw - bw as i32
    };
    let y = match anchor {
        pet_edge::Anchor::TopLeft | pet_edge::Anchor::TopRight => p.y + my,
        pet_edge::Anchor::BottomLeft | pet_edge::Anchor::BottomRight => p.y + my + mh - bh as i32,
        _ => p.y + my + mh / 2 - bh as i32 / 2,
    };
    let (x, y) = (
        x.clamp(
            area.position.x,
            area.position.x + area.size.width.saturating_sub(bw) as i32,
        ),
        y.clamp(
            area.position.y,
            area.position.y + area.size.height.saturating_sub(bh) as i32,
        ),
    );
    bubble
        .set_size(tauri::PhysicalSize::new(bw, bh))
        .map_err(|e| e.to_string())?;
    bubble
        .set_position(tauri::PhysicalPosition::new(x, y))
        .map_err(|e| e.to_string())?;
    Ok(())
}
pub fn settle(app: &tauri::AppHandle) -> Result<(), String> {
    let w = app.get_webview_window("pet").ok_or("宠物未开启")?;
    let p = w.outer_position().map_err(|e| e.to_string())?;
    let s = w.outer_size().map_err(|e| e.to_string())?;
    if let Some(m) = w.current_monitor().map_err(|e| e.to_string())? {
        let a = m.work_area();
        w.set_position(tauri::PhysicalPosition::new(
            p.x.clamp(
                a.position.x,
                a.position.x + a.size.width.saturating_sub(s.width) as i32,
            ),
            p.y.clamp(
                a.position.y,
                a.position.y + a.size.height.saturating_sub(s.height) as i32,
            ),
        ))
        .map_err(|e| e.to_string())?;
    }
    follow(app)?;
    persist_position(app)
}
pub fn expand(app: &tauri::AppHandle, value: bool, focus: bool) -> Result<(), String> {
    let previous = app
        .state::<PetState>()
        .expanded
        .swap(value, Ordering::Relaxed);
    if previous == value {
        return Ok(());
    }
    pet_edge::chat(app, value);
    if let Some(b) = app.get_webview_window("pet-bubble") {
        if value {
            follow(app)?;
            b.show().map_err(|e| e.to_string())?;
            if focus {
                b.set_focus().map_err(|e| e.to_string())?;
            }
        } else {
            b.hide().map_err(|e| e.to_string())?;
        }
    }
    app.emit("pet-state", json!({"expanded":value}))
        .map_err(|e| e.to_string())?;
    Ok(())
}
pub fn create(app: &tauri::AppHandle) -> Result<(), String> {
    let prefs: PetSettings = private_json(&data(app)?.join("pet-settings-v1.json"))
        .ok()
        .and_then(|v| serde_json::from_value(v).ok())
        .unwrap_or_default();
    *app.state::<PetState>().settings.lock().unwrap() = prefs.clone();
    if let Some(w) = app.get_webview_window("pet") {
        w.show().map_err(|e| e.to_string())?;
        return Ok(());
    }
    app.state::<PetState>()
        .restoring
        .store(true, Ordering::Relaxed);
    app.state::<PetState>()
        .ready_scheduled
        .store(false, Ordering::Relaxed);
    let pet = tauri::WebviewWindowBuilder::new(
        app,
        "pet",
        tauri::WebviewUrl::App("index.html?pet=character".into()),
    )
    .title("Companion · DeepSeek 娘")
    .visible(false)
    .inner_size(pet_edge::VIEW_W * prefs.size, pet_edge::VIEW_H * prefs.size)
    .decorations(false)
    .transparent(true)
    .background_color(tauri::window::Color(0, 0, 0, 0))
    .shadow(false)
    .always_on_top(prefs.topmost)
    .skip_taskbar(true)
    .focused(false)
    .resizable(false)
    .build()
    .map_err(|e| e.to_string())?;
    super::pet_macos::transparent(&pet)?;
    pet.set_ignore_cursor_events(true)
        .map_err(|e| e.to_string())?;
    super::pet_macos::install(app);
    let bubble = tauri::WebviewWindowBuilder::new(
        app,
        "pet-bubble",
        tauri::WebviewUrl::App("index.html?pet=bubble".into()),
    )
    .title("Companion 对话")
    .inner_size(320.0, 180.0)
    .decorations(false)
    .transparent(true)
    .background_color(tauri::window::Color(0, 0, 0, 0))
    .always_on_top(prefs.topmost)
    .skip_taskbar(true)
    .visible(false)
    .focused(false)
    .resizable(false)
    .build()
    .map_err(|e| e.to_string())?;
    let workspace = objc2_app_kit::NSWorkspace::sharedWorkspace();
    let reduce = workspace.accessibilityDisplayShouldReduceTransparency();
    let material = if reduce {
        "solid"
    } else {
        let options = window_vibrancy::LiquidGlassOptions::new(
            window_vibrancy::NSGlassEffectViewStyle::Clear,
        )
        .opaque(false)
        .radius(26.0)
        .interactive(false);
        match window_vibrancy::apply_liquid_glass(&bubble, options) {
            Ok(()) => "liquid_glass",
            Err(_) => {
                window_vibrancy::apply_vibrancy(
                    &bubble,
                    window_vibrancy::NSVisualEffectMaterial::Popover,
                    None,
                    Some(26.0),
                )
                .map_err(|e| e.to_string())?;
                "native_vibrancy"
            }
        }
    };
    save(
        &data(app)?.join("pet-material.json"),
        &json!({"material":material,"reduce_motion":workspace.accessibilityDisplayShouldReduceMotion()}),
    )?;
    let _ = super::pet_macos::thought_glass(app);
    let _ = app.emit("pet-material", json!({"material":material}));
    let saved = private_json(&data(app)?.join("pet-position-v2.json")).ok();
    let monitors = pet.available_monitors().map_err(|e| e.to_string())?;
    let target = saved
        .as_ref()
        .and_then(|v| Some((v["x"].as_i64()? as i32, v["y"].as_i64()? as i32)));
    let monitor = target
        .and_then(|(x, y)| {
            monitors.iter().find(|m| {
                x >= m.position().x
                    && y >= m.position().y
                    && x < m.position().x + m.size().width as i32
                    && y < m.position().y + m.size().height as i32
            })
        })
        .cloned()
        .or_else(|| pet.primary_monitor().ok().flatten());
    if let Some(m) = monitor {
        let a = m.work_area();
        let (x, y) = target
            .filter(|(x, y)| {
                *x >= a.position.x
                    && *y >= a.position.y
                    && *x < a.position.x + a.size.width as i32
                    && *y < a.position.y + a.size.height as i32
            })
            .unwrap_or((
                a.position.x + a.size.width as i32 - (430.0 * m.scale_factor()) as i32,
                a.position.y + a.size.height as i32 - (170.0 * m.scale_factor()) as i32,
            ));
        *app.state::<PetState>().restore_target.lock().unwrap() =
            Some(tauri::PhysicalPosition::new(x, y));
        pet.set_position(tauri::PhysicalPosition::new(x, y))
            .map_err(|e| e.to_string())?;
    }
    let generation = app
        .state::<PetState>()
        .generation
        .fetch_add(1, Ordering::Relaxed)
        + 1;
    // Observe only pointer position to pass transparent pixels through. This
    // never posts input, activates another app, or records pointer history.
    let handle = app.clone();
    tauri::async_runtime::spawn(async move {
        loop {
            tokio::time::sleep(Duration::from_millis(50)).await;
            let Some(window) = handle.get_webview_window("pet") else {
                break;
            };
            let state = handle.state::<PetState>();
            if state.generation.load(Ordering::Relaxed) != generation {
                break;
            }
            if !window.is_visible().unwrap_or(false) {
                tokio::time::sleep(Duration::from_millis(500)).await;
                continue;
            }
            let main = handle.clone();
            let _ = handle.run_on_main_thread(move || {
                let Some(window) = main.get_webview_window("pet") else {
                    return;
                };
                pet_edge::tick(&main);
                let state = main.state::<PetState>();
                if state.generation.load(Ordering::Relaxed) != generation
                    || state.dragging.load(Ordering::Relaxed)
                    || !window.is_visible().unwrap_or(false)
                {
                    return;
                }
                if let (Ok(cursor), Ok(origin), Ok(size)) = (
                    window.cursor_position(),
                    window.outer_position(),
                    window.outer_size(),
                ) {
                    let (x, y) = (
                        (cursor.x - origin.x as f64) / size.width as f64 * pet_edge::VIEW_W,
                        (cursor.y - origin.y as f64) / size.height as f64 * pet_edge::VIEW_H,
                    );
                    let hit = pet_edge::hit(&main, x, y);
                    let ignore = !hit;
                    if super::pet_macos::ignores_mouse(&window).ok() != Some(ignore) {
                        let _ = window.set_ignore_cursor_events(ignore);
                    }
                }
            });
        }
    });
    Ok(())
}
#[tauri::command]
pub async fn pet_action(
    app: tauri::AppHandle,
    action: String,
    value: Option<Value>,
) -> Result<Value, String> {
    match action.as_str() {
        "ready" => {
            if !app
                .state::<PetState>()
                .ready_scheduled
                .swap(true, Ordering::Relaxed)
            {
                let handle = app.clone();
                tauri::async_runtime::spawn(async move {
                    // AppKit applies the initial WebView frame after setup. Do not
                    // overwrite the saved position with that transient frame.
                    tokio::time::sleep(Duration::from_millis(120)).await;
                    let app = handle.clone();
                    let _ = handle.run_on_main_thread(move || {
                        let _ = pet_edge::initialize(&app);
                        if let Some(w) = app.get_webview_window("pet") {
                            let _ = w.show();
                        }
                        app.state::<PetState>()
                            .restoring
                            .store(false, Ordering::Relaxed);
                    });
                });
            }
            Ok(json!({}))
        }
        "diagnostics" => {
            let (tx, rx) = tokio::sync::oneshot::channel();
            let handle = app.clone();
            app.run_on_main_thread(move || {
                let _ = tx.send(super::pet_macos::diagnostics(&handle));
            })
            .map_err(|e| e.to_string())?;
            rx.await.map_err(|e| e.to_string())?
        }
        "state" => Ok(
            json!({"settings":settings(&app),"material":private_json(&data(&app)?.join("pet-material.json")).ok(),"expanded":app.state::<PetState>().expanded.load(Ordering::Relaxed),"edge":pet_edge::snapshot(&app)}),
        ),
        "toggle" => {
            let v = !app.state::<PetState>().expanded.load(Ordering::Relaxed);
            expand(&app, v, v)?;
            Ok(json!({"expanded":v}))
        }
        "collapse" => {
            expand(&app, false, false)?;
            Ok(json!({}))
        }
        "drag" => {
            app.state::<PetState>()
                .dragging
                .store(true, Ordering::Relaxed);
            let window = app.get_webview_window("pet").ok_or("宠物未开启")?;
            let _ = window.set_ignore_cursor_events(false);
            let result = window.start_dragging();
            app.state::<PetState>()
                .dragging
                .store(false, Ordering::Relaxed);
            result.map_err(|e| e.to_string())?;
            settle(&app)?;
            Ok(json!({}))
        }
        "pose" => {
            let v = value.ok_or("缺少角色帧")?;
            let x = v["column"]
                .as_u64()
                .filter(|v| *v < 8)
                .ok_or("角色帧无效")? as u32;
            let y = v["row"]
                .as_u64()
                .filter(|v| *v < 11)
                .ok_or("角色状态无效")? as u32;
            *app.state::<PetState>().pose.lock().unwrap() = (x, y);
            Ok(json!({}))
        }
        "resize_bubble" => {
            let height = value
                .and_then(|v| v["height"].as_f64())
                .filter(|h| h.is_finite())
                .ok_or("气泡尺寸无效")?;
            app.state::<PetState>()
                .bubble_height
                .store(height.clamp(180.0, 420.0).ceil() as u32, Ordering::Relaxed);
            follow(&app)?;
            Ok(json!({}))
        }
        "save_position" => {
            settle(&app)?;
            Ok(json!({}))
        }
        "hide" => {
            persist_position(&app)?;
            expand(&app, false, false)?;
            if let Some(w) = app.get_webview_window("pet") {
                w.hide().map_err(|e| e.to_string())?;
            }
            app.emit("pet-visibility", false)
                .map_err(|e| e.to_string())?;
            Ok(json!({}))
        }
        "quit" => {
            persist_position(&app)?;
            if app.state::<PetState>().standalone.load(Ordering::Relaxed) {
                app.exit(0)
            } else {
                for name in ["pet-bubble", "pet"] {
                    if let Some(w) = app.get_webview_window(name) {
                        let _ = w.destroy();
                    }
                }
            }
            Ok(json!({}))
        }
        "settings" => {
            let s: PetSettings =
                serde_json::from_value(value.ok_or("缺少设置")?).map_err(|e| e.to_string())?;
            if s.version != 1
                || !s.size.is_finite()
                || !(0.7..=1.8).contains(&s.size)
                || s.cooldown_minutes < 1
                || s.cooldown_minutes > 1440
                || s.daily_limit > 20
                || s.quiet_start > 23
                || s.quiet_end > 23
                || s.event_allowlist.iter().any(|x| {
                    ![
                        "explicit_reminder",
                        "localpilot_completed",
                        "repeated_error",
                        "deadline",
                    ]
                    .contains(&x.as_str())
                })
            {
                return Err("设置超出允许范围".into());
            }
            save(&data(&app)?.join("pet-settings-v1.json"), &s)?;
            *app.state::<PetState>().settings.lock().unwrap() = s.clone();
            for name in ["pet", "pet-bubble"] {
                if let Some(w) = app.get_webview_window(name) {
                    w.set_always_on_top(s.topmost).map_err(|e| e.to_string())?;
                }
            }
            if let Some(w) = app.get_webview_window("pet") {
                w.set_size(tauri::LogicalSize::new(
                    pet_edge::VIEW_W * s.size,
                    pet_edge::VIEW_H * s.size,
                ))
                .map_err(|e| e.to_string())?;
            }
            settle(&app)?;
            app.emit("pet-settings", &s).map_err(|e| e.to_string())?;
            Ok(json!(s))
        }
        "activity" | "notice" => {
            if action == "notice" {
                expand(&app, true, false)?;
            }
            if let Some(state) = value.as_ref().and_then(|v| v["state"].as_str()) {
                pet_edge::activity(&app, state);
            }
            app.emit(
                if action == "notice" {
                    "pet-notice"
                } else {
                    "pet-activity"
                },
                value.unwrap_or(Value::Null),
            )
            .map_err(|e| e.to_string())?;
            Ok(json!({}))
        }
        _ => Err("未知宠物操作".into()),
    }
}
#[tauri::command]
pub async fn pet_service(
    app: tauri::AppHandle,
    n: State<'_, Native>,
    payload: Value,
) -> Result<Value, String> {
    let command = payload["command"].as_str().ok_or("缺少操作")?.to_string();
    if ![
        "ui_snapshot",
        "pet_memory",
        "pet_export",
        "clear",
        "pause_observation",
        "set_reminder",
        "delete_reminder",
        "reminders",
        "proactive_settings",
        "notice_action",
    ]
    .contains(&command.as_str())
    {
        return Err("宠物未开放此操作".into());
    }
    let result = companion_request(&companion_profile(&app, current(&n))?, payload).await?;
    if command == "pet_export" {
        let file = rfd::AsyncFileDialog::new()
            .set_file_name("Companion-data.json")
            .add_filter("JSON", &["json"])
            .save_file()
            .await;
        let Some(file) = file else {
            return Ok(json!({"cancelled":true}));
        };
        save(file.path(), &result)?;
        return Ok(json!({"path":file.path().to_string_lossy()}));
    }
    Ok(result)
}
#[tauri::command]
pub async fn pet_chat(
    app: tauri::AppHandle,
    n: State<'_, Native>,
    text: String,
    request_id: String,
) -> Result<Value, String> {
    if text.trim().is_empty() || text.chars().count() > 4000 || !id_ok(&request_id) {
        return Err("消息超出允许范围".into());
    }
    let p = companion_profile(&app, current(&n))?;
    let cfg = private_json(&Path::new(&p.home).join("companion.json"))?;
    let rec = private_json(
        &Path::new(cfg["data_dir"].as_str().ok_or("缺少 Companion data_dir")?).join("runtime.json"),
    )?;
    let port = rec["port"]
        .as_u64()
        .filter(|p| *p > 0 && *p < 65536)
        .ok_or("服务端口无效")?;
    let response = client()?
        .post(format!("http://127.0.0.1:{port}/pet-stream"))
        .bearer_auth(rec["token"].as_str().ok_or("服务未连接")?)
        .json(&json!({"command":"pet_ask","text":text}))
        .send()
        .await
        .map_err(|_| "Companion 未连接，请检查独立服务")?;
    if !response.status().is_success() {
        return Err(format!(
            "Companion HTTP {}；需要本轮宠物服务版本",
            response.status()
        ));
    }
    let mut stream = response.bytes_stream();
    let mut buffer = Vec::new();
    let mut total = 0;
    while let Some(chunk) = stream.next().await {
        let chunk = chunk.map_err(|_| "回复连接中断；请手动重试")?;
        total += chunk.len();
        if total > 2 * 1024 * 1024 {
            return Err("回复超过上限".into());
        }
        buffer.extend_from_slice(&chunk);
        while let Some(end) = buffer.windows(2).position(|w| w == b"\n\n") {
            let line: Vec<_> = buffer.drain(..end + 2).collect();
            if let Some(json) = line.strip_prefix(b"data: ") {
                let v: Value = serde_json::from_slice(json).map_err(|_| "回复格式无效")?;
                app.emit_to(
                    "pet-bubble",
                    "pet-stream",
                    json!({"id":request_id,"data":redacted(v.clone())}),
                )
                .map_err(|e| e.to_string())?;
                if v["event"] == "final" {
                    return Ok(redacted(v["result"].clone()));
                }
            }
        }
    }
    Err("回复在完成前中断；没有自动重发".into())
}
pub fn setup_tray(app: &tauri::AppHandle) -> Result<(), String> {
    use tauri::menu::{Menu, MenuItem};
    let show = MenuItem::with_id(app, "pet_show", "唤回 DeepSeek 娘", true, None::<&str>)
        .map_err(|e| e.to_string())?;
    let hide = MenuItem::with_id(app, "pet_hide", "隐藏", true, None::<&str>)
        .map_err(|e| e.to_string())?;
    let quit = MenuItem::with_id(app, "pet_quit", "退出 Companion 宠物", true, None::<&str>)
        .map_err(|e| e.to_string())?;
    let menu = Menu::with_items(app, &[&show, &hide, &quit]).map_err(|e| e.to_string())?;
    let mut tray = tauri::tray::TrayIconBuilder::new()
        .menu(&menu)
        .tooltip("Companion · DeepSeek 娘")
        .on_menu_event(|app, event| match event.id.as_ref() {
            "pet_show" => {
                if let Some(w) = app.get_webview_window("pet") {
                    let _ = w.show();
                    let _ = app.emit("pet-visibility", true);
                }
            }
            "pet_hide" => {
                let _ = expand(app, false, false);
                if let Some(w) = app.get_webview_window("pet") {
                    let _ = w.hide();
                    let _ = app.emit("pet-visibility", false);
                }
            }
            "pet_quit" => {
                let _ = persist_position(app);
                app.exit(0)
            }
            _ => {}
        });
    if let Some(icon) = app.default_window_icon() {
        tray = tray.icon(icon.clone());
    }
    tray.build(app).map_err(|e| e.to_string())?;
    Ok(())
}
#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn edge_placement() {
        assert_eq!(
            bubble_origin((950, 750, 160, 140), (0, 25, 1200, 830), (380, 460)),
            (730, 282)
        );
        assert_eq!(
            bubble_origin((5, 30, 160, 140), (0, 25, 1200, 830), (380, 460)),
            (0, 38)
        );
    }
    #[test]
    fn negative_monitor_and_small_workarea() {
        assert_eq!(
            bubble_origin((-1200, 50, 160, 140), (-1440, 24, 1440, 850), (380, 460)),
            (-1420, 58)
        );
        assert_eq!(
            bubble_origin((0, 0, 160, 140), (0, 0, 300, 200), (380, 460)),
            (0, 0)
        );
    }
}
