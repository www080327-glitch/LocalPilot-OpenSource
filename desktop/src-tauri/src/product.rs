use super::*;
use base64::{engine::general_purpose::STANDARD, Engine};

pub fn register_checked(n: &Native, paths: Vec<PathBuf>) -> Result<Vec<Value>, String> {
    let direct = paths.clone();
    let mut pending = paths;
    let mut files = Vec::new();
    let mut skipped = Vec::new();
    let mut total = 0u64;
    let mut entries = 0usize;
    let started = std::time::Instant::now();
    while let Some(path) = pending.pop() {
        entries += 1;
        if entries > 20000 || started.elapsed().as_secs() > 30 {
            return Err(fail("文件夹扫描超出资源预算，请选择更小的目录"));
        }
        let sensitive = path.components().any(|p| {
            let p = p.as_os_str().to_string_lossy();
            [
                ".git",
                ".ssh",
                ".env",
                "secrets",
                ".aws",
                ".gnupg",
                "Keychains",
            ]
            .contains(&p.as_ref())
                || (p.starts_with(".env.") && p != ".env.example")
        }) || path
            .file_name()
            .map(|n| n == "clients.env")
            .unwrap_or(false)
            || path
                .extension()
                .map(|e| {
                    ["key", "pem", "p12", "pfx"]
                        .contains(&e.to_string_lossy().to_lowercase().as_str())
                })
                .unwrap_or(false);
        if sensitive {
            if direct.contains(&path) {
                return Err(fail("凭据或受保护来源不可作为附件导入"));
            }
            skipped.push(
                path.file_name()
                    .unwrap_or_default()
                    .to_string_lossy()
                    .to_string(),
            );
            continue;
        }
        let meta = fs::symlink_metadata(&path).map_err(|_| fail("附件不可读取"))?;
        if meta.file_type().is_symlink() {
            return Err(fail("附件包含符号链接，请选择普通文件"));
        }
        if meta.is_dir() {
            for child in fs::read_dir(&path).map_err(|_| fail("目录不可读取"))? {
                entries += 1;
                if entries > 20000 {
                    return Err(fail("文件夹条目超出扫描预算"));
                }
                let child = child.map_err(|_| fail("目录条目不可读取"))?;
                if [".git", ".venv", "node_modules", "__pycache__"]
                    .contains(&child.file_name().to_string_lossy().as_ref())
                {
                    continue;
                }
                pending.push(child.path());
            }
        } else if meta.is_file() {
            total = total.saturating_add(meta.len());
            if total > 2 * 1024u64.pow(3) || meta.uid() != unsafe { libc::geteuid() } {
                return Err(fail("附件总大小或来源超出授权预算"));
            }
            files.push(path);
        } else {
            return Err(fail("仅支持普通文件与文件夹"));
        }
    }
    let prior_bytes: usize = n
        .selected_files
        .lock()
        .unwrap()
        .values()
        .map(|p| p.to_string_lossy().len() + 256)
        .sum();
    if prior_bytes
        + files
            .iter()
            .map(|p| p.to_string_lossy().len() + 256)
            .sum::<usize>()
        > 8 * 1024 * 1024
    {
        return Err(fail("附件元数据超出内存预算，请分批处理"));
    }
    let mut rows = register(n, files);
    if let Some(first) = rows.first_mut() {
        first["selection_skipped"] = json!(skipped);
    }
    Ok(rows)
}

fn staging_budget(root: &Path, additional: usize) -> Result<(), String> {
    use std::os::unix::ffi::OsStrExt;
    if root.is_symlink() {
        return Err(fail("附件缓存目录不可用"));
    }
    let mut total = additional as u64;
    let mut entries = 0;
    for dir in fs::read_dir(root).map_err(|_| fail("附件缓存不可读"))? {
        let dir = dir.map_err(|_| fail("附件缓存不可读"))?;
        if !dir
            .file_type()
            .map_err(|_| fail("附件缓存不可读"))?
            .is_dir()
        {
            continue;
        }
        for file in fs::read_dir(dir.path()).map_err(|_| fail("附件缓存不可读"))? {
            entries += 1;
            if entries > 20000 {
                return Err(fail("附件缓存元数据超出预算"));
            }
            total = total.saturating_add(
                file.map_err(|_| fail("附件缓存不可读"))?
                    .metadata()
                    .map_err(|_| fail("附件缓存不可读"))?
                    .len(),
            );
        }
    }
    let name = std::ffi::CString::new(root.as_os_str().as_bytes())
        .map_err(|_| fail("附件缓存路径无效"))?;
    let mut info = std::mem::MaybeUninit::<libc::statvfs>::uninit();
    if unsafe { libc::statvfs(name.as_ptr(), info.as_mut_ptr()) } != 0 {
        return Err(fail("无法确认磁盘预算"));
    }
    let info = unsafe { info.assume_init() };
    if total > 2 * 1024u64.pow(3)
        || (info.f_bavail as u64).saturating_mul(info.f_frsize as u64)
            < 512 * 1024u64.pow(2) + additional as u64
    {
        return Err(fail("附件缓存或磁盘空间超出预算"));
    }
    Ok(())
}

pub fn register(n: &Native, paths: Vec<PathBuf>) -> Vec<Value> {
    let mut out = Vec::new();
    for path in paths {
        if path.is_symlink() {
            continue;
        }
        let Ok(path) = path.canonicalize() else {
            continue;
        };
        let Ok(meta) = path.metadata() else { continue };
        if !meta.is_file()
            || meta.len() > 2 * 1024 * 1024 * 1024
            || meta.uid() != unsafe { libc::geteuid() }
        {
            continue;
        }
        let id = uuid::Uuid::new_v4().to_string();
        n.selected_origins
            .lock()
            .unwrap()
            .insert(id.clone(), "native_selection".into());
        n.selected_files
            .lock()
            .unwrap()
            .insert(id.clone(), path.clone());
        n.selected_identities.lock().unwrap().insert(
            id.clone(),
            (
                meta.dev(),
                meta.ino(),
                meta.mtime() * 1_000_000_000 + meta.mtime_nsec(),
                meta.len(),
            ),
        );
        let name = path.file_name().unwrap().to_string_lossy().to_string();
        out.push(json!({"id":id,"name":name,"size":meta.len(),"status":"selected"}));
    }
    out
}
fn chosen(n: &Native, id: &str) -> Result<PathBuf, String> {
    let path = n
        .selected_files
        .lock()
        .unwrap()
        .get(id)
        .cloned()
        .ok_or("附件选择已失效，请重新选择")?;
    let meta = fs::symlink_metadata(&path).map_err(|_| fail("附件已不存在"))?;
    let identity = (
        meta.dev(),
        meta.ino(),
        meta.mtime() * 1_000_000_000 + meta.mtime_nsec(),
        meta.len(),
    );
    if !meta.is_file() || n.selected_identities.lock().unwrap().get(id) != Some(&identity) {
        return Err(fail("附件来源或内容已变化，请重新选择"));
    }
    Ok(path)
}
#[tauri::command]
pub async fn pick_attachments(
    app: tauri::AppHandle,
    n: State<'_, Native>,
) -> Result<Value, String> {
    let window = app.get_webview_window("main").ok_or("主窗口不可用")?;
    let paths = rfd::AsyncFileDialog::new()
        .set_parent(&window)
        .set_title("添加文件到 LocalPilot")
        .pick_files()
        .await;
    Ok(json!(register_checked(
        &n,
        paths
            .unwrap_or_default()
            .iter()
            .map(|p| p.path().to_path_buf())
            .collect()
    )?))
}
#[tauri::command]
pub async fn pick_attachment_folder(
    app: tauri::AppHandle,
    n: State<'_, Native>,
) -> Result<Value, String> {
    let window = app.get_webview_window("main").ok_or("主窗口不可用")?;
    let folder = rfd::AsyncFileDialog::new()
        .set_parent(&window)
        .set_title("导入附件文件夹（跳过依赖目录）")
        .pick_folder()
        .await;
    let Some(folder) = folder else {
        return Ok(json!([]));
    };
    let rows = register_checked(&n, vec![folder.path().to_path_buf()])?;
    for row in &rows {
        n.selected_origins
            .lock()
            .unwrap()
            .insert(row["id"].as_str().unwrap().into(), "folder".into());
    }
    Ok(json!(rows))
}
#[tauri::command]
pub async fn remove_attachment(
    app: tauri::AppHandle,
    n: State<'_, Native>,
    id: String,
) -> Result<(), String> {
    if let Ok(path) = chosen(&n, &id) {
        let staging = data(&app)?.join("attachment-staging");
        if path.starts_with(&staging)
            && path.parent().and_then(Path::parent) == Some(staging.as_path())
        {
            fs::remove_file(&path).map_err(|_| fail("无法释放粘贴附件缓存"))?;
            if let Some(parent) = path.parent() {
                let _ = fs::remove_dir(parent);
            }
        }
    }
    n.selected_files.lock().unwrap().remove(&id);
    n.selected_identities.lock().unwrap().remove(&id);
    n.selected_origins.lock().unwrap().remove(&id);
    Ok(())
}
#[tauri::command]
pub async fn pick_workspace(
    app: tauri::AppHandle,
    n: State<'_, Native>,
    scope: String,
    cloud_paths: Vec<String>,
) -> Result<Value, String> {
    if !["read", "organize", "modify"].contains(&scope.as_str()) {
        return Err(fail("请选择读取、整理或修改范围"));
    }
    let window = app.get_webview_window("main").ok_or("主窗口不可用")?;
    let selected = rfd::AsyncFileDialog::new()
        .set_parent(&window)
        .set_title("明确授权 LocalPilot 操作此文件夹")
        .pick_folder()
        .await;
    let Some(folder) = selected else {
        return Ok(Value::Null);
    };
    product_control_impl(app,n,"workspace_grants".into(),json!({"operation":"grant","folder":folder.path().to_string_lossy(),"scope":scope,"cloud_paths":cloud_paths})).await
}
#[tauri::command]
pub async fn stage_attachment(
    app: tauri::AppHandle,
    n: State<'_, Native>,
    name: String,
    bytes: Vec<u8>,
) -> Result<Value, String> {
    if name.is_empty()
        || name.contains('/')
        || name.contains('\\')
        || name.len() > 255
        || bytes.len() > 8 * 1024 * 1024
    {
        return Err(fail("粘贴文件过大或名称无效，请通过文件选择器添加"));
    }
    let root = data(&app)?.join("attachment-staging");
    fs::create_dir_all(&root).map_err(|_| fail("无法暂存附件"))?;
    staging_budget(&root, bytes.len())?;
    let dir = root.join(uuid::Uuid::new_v4().to_string());
    fs::create_dir(&dir).map_err(|_| fail("无法暂存附件"))?;
    let path = dir.join(name);
    fs::write(&path, bytes).map_err(|_| fail("磁盘空间不足或暂存失败"))?;
    fs::set_permissions(&path, fs::Permissions::from_mode(0o600))
        .map_err(|_| fail("附件权限失败"))?;
    let rows = register(&n, vec![path]);
    for row in &rows {
        n.selected_origins
            .lock()
            .unwrap()
            .insert(row["id"].as_str().unwrap().into(), "paste".into());
    }
    Ok(json!(rows))
}
fn image_payload(path: &Path, thumbnail: bool) -> Result<Value, String> {
    if path.metadata().map_err(|_| fail("图片不可用"))?.len() > 24 * 1024 * 1024 {
        return Err(fail("图片超出预览预算，请用系统应用打开"));
    }
    let header = image::ImageReader::open(path)
        .map_err(|_| fail("图片不可读"))?
        .with_guessed_format()
        .map_err(|_| fail("图片格式无效"))?;
    let format = header.format().ok_or("图片格式未知")?;
    let (width, height) = header.into_dimensions().map_err(|_| fail("图片尺寸无效"))?;
    if width == 0
        || height == 0
        || width > 16384
        || height > 16384
        || u64::from(width) * u64::from(height) > 32_000_000
    {
        return Err(fail("图片像素超出预览预算，请用系统应用打开"));
    }
    let bytes = if thumbnail || format == image::ImageFormat::Gif {
        let mut reader = image::ImageReader::open(path)
            .map_err(|_| fail("图片不可读"))?
            .with_guessed_format()
            .map_err(|_| fail("图片格式无效"))?;
        let mut limits = image::Limits::default();
        limits.max_image_width = Some(16384);
        limits.max_image_height = Some(16384);
        limits.max_alloc = Some(256 * 1024 * 1024);
        reader.limits(limits);
        let decoded = reader
            .decode()
            .map_err(|_| fail("图片解码失败或超出内存预算"))?;
        let rendered = if thumbnail {
            decoded.thumbnail(128, 128)
        } else {
            decoded
        };
        let mut encoded = std::io::Cursor::new(Vec::new());
        rendered
            .write_to(&mut encoded, image::ImageFormat::Png)
            .map_err(|_| fail("无法生成图片预览"))?;
        if encoded.get_ref().len() > 24 * 1024 * 1024 {
            return Err(fail("图片预览超出传输预算"));
        }
        encoded.into_inner()
    } else {
        fs::read(path).map_err(|_| fail("图片不可读"))?
    };
    let mime = if thumbnail || format == image::ImageFormat::Gif {
        "image/png"
    } else {
        match format {
            image::ImageFormat::Png => "image/png",
            image::ImageFormat::Jpeg => "image/jpeg",
            image::ImageFormat::WebP => "image/webp",
            _ => return Err(fail("此图片格式请用系统应用打开")),
        }
    };
    Ok(
        json!({"url":format!("data:{mime};base64,{}",STANDARD.encode(&bytes)),"width":width,"height":height,"representation":if thumbnail{"thumbnail"}else{"local_preview_not_model_input"}}),
    )
}
#[tauri::command]
pub async fn attachment_preview(n: State<'_, Native>, id: String) -> Result<Value, String> {
    let path = chosen(&n, &id)?;
    tauri::async_runtime::spawn_blocking(move || {
        use std::io::Read;
        let mut raw = Vec::new();
        fs::File::open(&path).map_err(|_| fail("文件不可读"))?.take(512 * 1024 + 1).read_to_end(&mut raw).map_err(|_| fail("文件不可读"))?;
        if raw.starts_with(b"\x89PNG") || raw.starts_with(b"\xff\xd8\xff") || raw.starts_with(b"RIFF") || raw.starts_with(b"GIF8") {
            image_payload(&path, false)
        } else if !raw.contains(&0) && std::str::from_utf8(&raw).is_ok() {
            let truncated = raw.len() > 512 * 1024;
            raw.truncate(512 * 1024);
            Ok(json!({"text":String::from_utf8_lossy(&raw),"truncated":truncated,"representation":"local_text_preview_not_model_input"}))
        } else {
            Ok(json!({"text":"结构化文件将在导入后通过文档引擎预览。", "representation":"metadata_only"}))
        }
    })
        .await
        .map_err(|_| fail("预览被中断"))?
}
#[tauri::command]
pub async fn attachment_thumbnail(n: State<'_, Native>, id: String) -> Result<Value, String> {
    static SLOTS: std::sync::OnceLock<tokio::sync::Semaphore> = std::sync::OnceLock::new();
    let _slot = SLOTS
        .get_or_init(|| tokio::sync::Semaphore::new(2))
        .acquire()
        .await
        .map_err(|_| fail("预览队列不可用"))?;
    let path = chosen(&n, &id)?;
    tauri::async_runtime::spawn_blocking(move || image_payload(&path, true))
        .await
        .map_err(|_| fail("缩略图被中断"))?
}
#[tauri::command]
pub async fn open_attachment(n: State<'_, Native>, id: String) -> Result<(), String> {
    let path = chosen(&n, &id)?;
    if path.is_symlink() || !path.is_file() {
        return Err(fail("文件来源已变化"));
    }
    // Reveal only. An extension is not proof that launching a document is safe.
    std::process::Command::new("/usr/bin/open")
        .arg("-R")
        .arg("--")
        .arg(path)
        .status()
        .map_err(|_| fail("无法打开文件"))?;
    Ok(())
}
#[tauri::command]
pub async fn product_control(
    app: tauri::AppHandle,
    n: State<'_, Native>,
    operation: String,
    args: Value,
) -> Result<Value, String> {
    if operation == "documents" && args["operation"] == "import" {
        return Err(fail("附件导入必须使用原生文件选择引用"));
    }
    if operation == "workspace_grants" && args["operation"] == "grant" {
        return Err(fail(
            "目录授权必须使用原生文件夹选择器；风险档位或文本不能授予路径",
        ));
    }
    product_control_impl(app, n, operation, args).await
}
async fn product_control_impl(
    app: tauri::AppHandle,
    n: State<'_, Native>,
    operation: String,
    args: Value,
) -> Result<Value, String> {
    if ![
        "inspect",
        "capabilities",
        "catalog",
        "search",
        "info",
        "download",
        "cancel",
        "retry",
        "settings",
        "install_backend",
        "initialize_backend",
        "installation_diagnostics",
        "service_control",
        "prepare_uninstall",
        "desktop_session",
        "desktop_profile",
        "documents",
        "workspace_grants",
        "preferences",
        "verify_model",
        "configure_pet_model",
        "delete",
    ]
    .contains(&operation.as_str())
    {
        return Err(fail("不支持的产品操作"));
    }
    let mut p = current(&n);
    if p.cli.is_empty() || operation == "inspect" {
        let home = data(&app)?.join("product-v5");
        fs::create_dir_all(&home).map_err(|_| fail("无法创建候选数据目录"))?;
        if p.home.is_empty() {
            p.home = home.to_string_lossy().into();
        }
        p.cli = app
            .path()
            .resource_dir()
            .map_err(|_| fail("模块资源不可用"))?
            .join("bundled-backends/localpilot")
            .to_string_lossy()
            .into();
    }
    checked_cli(
        p,
        vec![
            "product-control".into(),
            "--request-json".into(),
            json!({"version":1,"operation":operation,"args":args}).to_string(),
        ],
    )
    .await
}
#[tauri::command]
pub async fn installation_backup(
    app: tauri::AppHandle,
    n: State<'_, Native>,
    restore: bool,
) -> Result<Value, String> {
    let window = app.get_webview_window("main").ok_or("主窗口不可用")?;
    let p = current(&n);
    if p.cli.is_empty() {
        return Err(fail("请先准备本机组件"));
    }
    if restore {
        let selected = rfd::AsyncFileDialog::new()
            .set_parent(&window)
            .set_title("选择 LocalPilot 数据备份文件夹")
            .pick_folder()
            .await;
        let Some(source) = selected else {
            return Ok(Value::Null);
        };
        // A new private destination prevents any overwrite of the daily or post-upgrade installation.
        let destination = data(&app)?
            .join("restored")
            .join(uuid::Uuid::new_v4().to_string());
        fs::create_dir_all(destination.parent().unwrap()).map_err(|_| fail("无法创建恢复目录"))?;
        let result=checked_cli(p.clone(),vec!["product-control".into(),"--request-json".into(),
            json!({"version":1,"operation":"restore_installation","args":{"source":source.path(),"destination":destination}}).to_string()]).await?;
        let restored = Profile {
            home: destination.to_string_lossy().into(),
            ..p.clone()
        };
        for module in ["core", "companion"] {
            checked_cli(restored.clone(),vec!["product-control".into(),"--request-json".into(),json!({"version":1,"operation":"service_control","args":{"module":module,"action":"recover","confirmed":true}}).to_string()]).await?;
        }
        connect_suite(app, n, destination.to_string_lossy().into(), p.cli).await?;
        Ok(result)
    } else {
        let selected = rfd::AsyncFileDialog::new()
            .set_parent(&window)
            .set_title("选择备份保存位置（包含私有密钥，请妥善保管）")
            .pick_folder()
            .await;
        let Some(parent) = selected else {
            return Ok(Value::Null);
        };
        let destination = parent
            .path()
            .join(format!("LocalPilot Backup {}", uuid::Uuid::new_v4()));
        checked_cli(p,vec!["product-control".into(),"--request-json".into(),
            json!({"version":1,"operation":"backup_installation","args":{"destination":destination}}).to_string()]).await
    }
}
#[tauri::command]
pub async fn installation_location(app: tauri::AppHandle) -> Result<(), String> {
    std::process::Command::new("/usr/bin/open")
        .arg(data(&app)?)
        .status()
        .map_err(|_| fail("无法在 Finder 中显示用户数据"))?
        .success()
        .then_some(())
        .ok_or_else(|| fail("Finder 未能打开数据目录"))
}
#[tauri::command]
pub async fn import_attachments(
    n: State<'_, Native>,
    model: String,
    ids: Vec<String>,
    session_id: Option<String>,
) -> Result<Value, String> {
    if ids.is_empty() {
        return Err(fail("请选择附件"));
    }
    let paths: Result<Vec<_>, _> = ids
        .iter()
        .map(|id| chosen(&n, id).map(|p| p.to_string_lossy().to_string()))
        .collect();
    let request = if let Some(session) = session_id {
        let origins: Vec<String> = ids
            .iter()
            .map(|id| {
                n.selected_origins
                    .lock()
                    .unwrap()
                    .get(id)
                    .cloned()
                    .unwrap_or_else(|| "native_selection".into())
            })
            .collect();
        json!({"version":1,"operation":"documents","args":{"operation":"import","session_id":session,"paths":paths?,"origins":origins}})
    } else {
        json!({"version":1,"operation":"attachments","args":{"model":model,"paths":paths?}})
    };
    checked_cli(
        current(&n),
        vec![
            "product-control".into(),
            "--request-json".into(),
            request.to_string(),
        ],
    )
    .await
}
#[tauri::command]
pub async fn pet_window(app: tauri::AppHandle, enabled: bool) -> Result<Value, String> {
    if enabled {
        // A separate process keeps Companion alive after the main GUI exits.
        if app
            .state::<super::pet_native::PetState>()
            .standalone
            .load(std::sync::atomic::Ordering::Relaxed)
        {
            super::pet_native::create(&app)?;
        } else {
            if super::pet_native::control(&app, "show") {
                return Ok(json!({"enabled":true,"reused":true}));
            }
            let exe = std::env::current_exe().map_err(|e| e.to_string())?;
            std::process::Command::new(exe)
                .arg("--companion-pet")
                .spawn()
                .map_err(|e| e.to_string())?;
        }
    } else {
        if !app
            .state::<super::pet_native::PetState>()
            .standalone
            .load(std::sync::atomic::Ordering::Relaxed)
        {
            super::pet_native::control(&app, "quit");
        } else {
            super::pet_native::pet_action(app.clone(), "quit".into(), None).await?;
        }
    }
    Ok(json!({"enabled":enabled}))
}

#[tauri::command]
pub async fn pet_handoff(
    app: tauri::AppHandle,
    text: String,
    agent_profile: Option<String>,
) -> Result<(), String> {
    if text.len() > 4096 {
        return Err(fail("问题过长"));
    }
    let profile = agent_profile.unwrap_or_else(|| "standard".into());
    if !["minimal", "standard"].contains(&profile.as_str()) {
        return Err("未知 Agent 模式".into());
    }
    save(
        &data(&app)?.join("pet-handoff.json"),
        &json!({"text":text,"agent_profile":profile}),
    )?;
    let window = if let Some(w) = app.get_webview_window("main") {
        w
    } else {
        tauri::WebviewWindowBuilder::new(
            &app,
            "main",
            tauri::WebviewUrl::App("index.html?handoff".into()),
        )
        .title("LocalPilot · 审核宠物任务")
        .inner_size(1200.0, 800.0)
        .build()
        .map_err(|e| e.to_string())?
    };
    window.show().map_err(|_| fail("无法显示主窗口"))?;
    window.set_focus().map_err(|_| fail("无法切换窗口"))?;
    window
        .emit("pet-handoff", json!({"text":text,"agent_profile":profile}))
        .map_err(|_| fail("无法交还问题"))?;
    Ok(())
}
#[tauri::command]
pub async fn configure_cloud_key(
    app: tauri::AppHandle,
    n: State<'_, Native>,
    key: String,
    confirmed: bool,
) -> Result<Value, String> {
    if !confirmed
        || key.len() < 16
        || key.len() > 512
        || key.chars().any(|c| c.is_whitespace() || c.is_control())
    {
        return Err(fail("请提供有效的 API 密钥并明确确认"));
    }
    let root = data(&app)?.join("secrets");
    fs::create_dir_all(&root).map_err(|_| fail("无法保存密钥"))?;
    fs::set_permissions(&root, fs::Permissions::from_mode(0o700))
        .map_err(|_| fail("密钥目录权限错误"))?;
    let path = root.join(format!("deepseek-{}.key", uuid::Uuid::new_v4()));
    use std::io::Write;
    let mut f = fs::OpenOptions::new()
        .write(true)
        .create_new(true)
        .mode(0o600)
        .open(&path)
        .map_err(|_| fail("无法安全保存密钥"))?;
    f.write_all(key.as_bytes())
        .map_err(|_| fail("密钥保存失败"))?;
    f.sync_all().map_err(|_| fail("密钥未持久化"))?;
    checked_cli(
        current(&n),
        vec![
            "cloud-configure".into(),
            format!("--key-file={}", path.display()),
        ],
    )
    .await
}
#[tauri::command]
pub async fn pet_expand(app: tauri::AppHandle, expanded: bool) -> Result<(), String> {
    super::pet_native::expand(&app, expanded, expanded)
}
#[tauri::command]
pub async fn companion_settings(
    n: State<'_, Native>,
    enabled: Option<bool>,
    confirmed: bool,
) -> Result<Value, String> {
    if let Some(value) = enabled {
        if !confirmed {
            return Err(fail("更改主动提示需要明确确认"));
        }
        companion_request(&current(&n),json!({"command":"proactive_settings","level":if value{"low"}else{"off"},"delivery":if value{"enabled"}else{"silent"}})).await?;
    }
    companion_request(&current(&n), json!({"command":"ui_snapshot"})).await
}
#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn folder_import_skips_credentials_and_tracks_byte_budget() {
        let root =
            std::env::temp_dir().join(format!("localpilot-folder-test-{}", uuid::Uuid::new_v4()));
        fs::create_dir(&root).unwrap();
        fs::write(root.join("note.txt"), "public").unwrap();
        fs::write(root.join(".env"), "private").unwrap();
        let rows = register_checked(&Native::default(), vec![root]).unwrap();
        assert_eq!(rows.len(), 1);
        assert_eq!(rows[0]["name"], "note.txt");
        assert_eq!(rows[0]["selection_skipped"][0], ".env");
    }
    #[test]
    fn attachment_reference_is_native_selected_and_version_bound() {
        let root = std::env::temp_dir().join(format!(
            "localpilot-attachment-test-{}",
            uuid::Uuid::new_v4()
        ));
        fs::create_dir(&root).unwrap();
        let file = root.join("note.txt");
        fs::write(&file, "first").unwrap();
        let native = Native::default();
        assert!(chosen(&native, "not-selected").is_err());
        let rows = register(&native, vec![file.clone()]);
        assert_eq!(rows.len(), 1);
        let id = rows[0]["id"].as_str().unwrap();
        assert_eq!(chosen(&native, id).unwrap(), file.canonicalize().unwrap());
        fs::write(&file, "second version").unwrap();
        assert!(chosen(&native, id).is_err());
    }
    #[test]
    fn image_thumbnail_is_bounded_and_preserves_original_bytes() {
        let root =
            std::env::temp_dir().join(format!("localpilot-image-test-{}", uuid::Uuid::new_v4()));
        fs::create_dir(&root).unwrap();
        let path = root.join("source.png");
        image::RgbaImage::from_pixel(200, 100, image::Rgba([100, 150, 180, 255]))
            .save(&path)
            .unwrap();
        let before = fs::read(&path).unwrap();
        let result = image_payload(&path, true).unwrap();
        let bytes = STANDARD
            .decode(result["url"].as_str().unwrap().split_once(',').unwrap().1)
            .unwrap();
        let preview = image::load_from_memory(&bytes).unwrap();
        assert!(preview.width() <= 128 && preview.height() <= 128);
        assert_eq!(fs::read(&path).unwrap(), before);
    }
    #[test]
    fn attachment_symlink_cannot_bypass_source_selection() {
        let root = std::env::temp_dir().join(format!(
            "localpilot-attachment-test-{}",
            uuid::Uuid::new_v4()
        ));
        fs::create_dir(&root).unwrap();
        let file = root.join("source.txt");
        fs::write(&file, "data").unwrap();
        let link = root.join("link.txt");
        std::os::unix::fs::symlink(&file, &link).unwrap();
        assert!(register(&Native::default(), vec![link]).is_empty());
    }
}
#[tauri::command]
pub async fn discover_suites(app: tauri::AppHandle) -> Result<Value, String> {
    let home = app.path().home_dir().map_err(|_| fail("用户目录不可用"))?;
    let support = home.join("Library/Application Support");
    let mut found = Vec::new();
    if let Ok(entries) = fs::read_dir(&support) {
        for entry in entries.flatten().take(200) {
            if !entry
                .file_name()
                .to_string_lossy()
                .starts_with("io.localpilot.desktop")
            {
                continue;
            }
            if let Ok(value) = private_json(&entry.path().join("profile.json")) {
                if let Ok(profile) = serde_json::from_value::<Profile>(value) {
                    if !profile.home.is_empty()
                        && validate_cli(&profile.cli).is_ok()
                        && Path::new(&profile.home).join("connection.json").is_file()
                    {
                        found.push(json!({"label":format!("已有 LocalPilot · {}",entry.file_name().to_string_lossy()),"home":profile.home,"cli":profile.cli,"workspace":profile.workspace}));
                    }
                }
            }
        }
    }
    let stable = home.join(".local/share/localpilot");
    let cli = home.join(".local/bin/localpilot");
    if stable.join("connection.json").is_file() && validate_cli(&cli.to_string_lossy()).is_ok() {
        found.push(json!({"label":"已有 LocalPilot Suite","home":stable,"cli":cli}));
    }
    Ok(json!({"version":1,"installations":found,"automatic_mutation":false}))
}
