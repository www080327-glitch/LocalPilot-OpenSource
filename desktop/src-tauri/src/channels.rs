use super::*;
use base64::{engine::general_purpose::STANDARD, Engine};

const ACTIONS: &[&str] = &[
    "status",
    "diagnose",
    "install",
    "update",
    "uninstall",
    "cancel_download",
    "qq_credentials",
    "login",
    "login_status",
    "cancel_login",
    "discover",
    "configure",
    "start",
    "stop",
    "disconnect",
    "operator",
    "receipts",
    "rollback",
    "background",
    "skip",
    "workspace",
    "decision",
    "cancel_task",
    "history",
    "fresh",
    "restore_review",
    "qq_console",
    "logs",
];

fn request_ok(kind: &str, action: &str, args: &Value) -> bool {
    ["qq", "wechat"].contains(&kind)
        && ACTIONS.contains(&action)
        && args.is_object()
        && args.to_string().len() <= 16384
        && (!matches!(
            action,
            "qq_credentials" | "workspace" | "qq_console" | "logs"
        ) || args.as_object().is_some_and(|v| v.is_empty()))
        && (!matches!(action, "qq_credentials" | "qq_console") || kind == "qq")
        && (action != "login" || kind == "wechat")
}

fn native_input(app: &tauri::AppHandle, secret: bool) -> Result<Option<String>, String> {
    let (send, receive) = std::sync::mpsc::sync_channel(1);
    app.run_on_main_thread(move || {
        use objc2_app_kit::{NSAlert, NSSecureTextField, NSTextField};
        use objc2_foundation::{NSPoint, NSRect, NSSize, NSString};
        let result = (|| -> Result<Option<String>, String> {
            let mtm = objc2::MainThreadMarker::new().ok_or("原生输入必须在主线程显示")?;
            let alert = NSAlert::new(mtm);
            alert.setMessageText(&NSString::from_str(if secret {
                "LocalPilot · QQ AppSecret"
            } else {
                "LocalPilot · QQ AppID"
            }));
            alert.setInformativeText(&NSString::from_str(if secret {
                "输入官方机器人 AppSecret。仅写入本机私有渠道目录，不进入聊天或模型上下文。"
            } else {
                "输入在 QQ 官方机器人平台开发管理中获取的 AppID。"
            }));
            alert.addButtonWithTitle(&NSString::from_str(if secret {
                "保存"
            } else {
                "继续"
            }));
            let cancel = alert.addButtonWithTitle(&NSString::from_str("取消"));
            cancel.setKeyEquivalent(&NSString::from_str("\u{1b}"));
            let frame = NSRect::new(NSPoint::new(0.0, 0.0), NSSize::new(340.0, 26.0));
            if secret {
                let field = NSSecureTextField::initWithFrame(mtm.alloc(), frame);
                field.setEditable(true);
                field.setSelectable(true);
                field.setBezeled(true);
                alert.setAccessoryView(Some(&field));
                alert.window().setInitialFirstResponder(Some(&field));
                if alert.runModal() != 1000 {
                    return Ok(None);
                }
                Ok(Some(field.stringValue().to_string()))
            } else {
                let field = NSTextField::initWithFrame(mtm.alloc(), frame);
                field.setEditable(true);
                field.setSelectable(true);
                field.setBezeled(true);
                alert.setAccessoryView(Some(&field));
                alert.window().setInitialFirstResponder(Some(&field));
                if alert.runModal() != 1000 {
                    return Ok(None);
                }
                Ok(Some(field.stringValue().to_string()))
            }
        })();
        let _ = send.send(result);
    })
    .map_err(|_| fail("原生凭据输入不可用"))?;
    receive
        .recv()
        .map_err(|_| fail("原生输入已中断，未保存凭据"))?
}

pub fn run(cli: &Path, home: &str, kind: &str, action: &str, args: Value) -> Result<Value, String> {
    use std::io::{Read, Write};
    let request = json!({"version":1,"operation":"channels","args":{"kind":kind,"action":action,"args":args}});
    let mut child = std::process::Command::new(cli)
        .args([
            "--home",
            home,
            "--json",
            "product-control",
            "--request-stdin",
        ])
        .env_remove("LOCALPILOT_OPERATOR_TOKEN")
        .env_remove("DEEPSEEK_API_KEY")
        .env("PYTHONDONTWRITEBYTECODE", "1")
        .stdin(std::process::Stdio::piped())
        .stdout(std::process::Stdio::piped())
        .stderr(std::process::Stdio::null())
        .spawn()
        .map_err(|_| fail("渠道管理组件不可用"))?;
    if child
        .stdin
        .take()
        .unwrap()
        .write_all(request.to_string().as_bytes())
        .is_err()
    {
        let _ = child.kill();
        let _ = child.wait();
        return Err(fail("安全配置管道中断，未自动重试"));
    }
    let stdout = child.stdout.take().unwrap();
    let reader = std::thread::spawn(move || {
        let mut out = String::new();
        let _ = stdout.take(1024 * 1024).read_to_string(&mut out);
        out
    });
    let started = std::time::Instant::now();
    let status = loop {
        if let Some(status) = child.try_wait().map_err(|_| fail("渠道操作状态未知"))? {
            break status;
        }
        if started.elapsed() > Duration::from_secs(1200) {
            let _ = child.kill();
            let _ = child.wait();
            return Err(fail(
                "渠道操作超时，状态为 UNKNOWN。请重新诊断，不会重投任务",
            ));
        }
        std::thread::sleep(Duration::from_millis(80));
    };
    let mut value: Value = serde_json::from_str(&reader.join().unwrap_or_default())
        .map_err(|_| fail("渠道返回状态无法确认，请重新诊断"))?;
    if !status.success() || value.get("error").is_some() {
        // Suite only returns fixed local diagnostic codes; never echo arbitrary stderr.
        let code = value["error"]
            .as_str()
            .unwrap_or("CHANNEL_OPERATION_UNKNOWN");
        let code = code.split(';').next().unwrap_or(code);
        if !code
            .chars()
            .all(|c| c.is_ascii_uppercase() || c.is_ascii_digit() || c == '_')
        {
            return Err(fail(
                "渠道操作未完成。配置与任务已保留，请查看诊断并安全重试",
            ));
        }
        return Err(format!("渠道操作未完成：{code}"));
    }
    if let Some(url) = value
        .get("login_url")
        .and_then(Value::as_str)
        .map(str::to_owned)
    {
        value.as_object_mut().unwrap().remove("login_url");
        let parsed = reqwest::Url::parse(&url).map_err(|_| fail("平台登录地址无效"))?;
        let host = parsed.host_str().unwrap_or("");
        if parsed.scheme() != "https"
            || !parsed.username().is_empty()
            || parsed.password().is_some()
            || parsed.port().is_some_and(|p| p != 443)
            || url.len() > 4096
            || !(host == "weixin.qq.com" || host.ends_with(".weixin.qq.com"))
        {
            return Err(fail("平台登录地址未通过来源检查"));
        }
        let qr = qrcode::QrCode::new(url.as_bytes())
            .map_err(|_| fail("二维码无法显示，请取消后刷新"))?;
        let svg = qr
            .render::<qrcode::render::svg::Color>()
            .min_dimensions(240, 240)
            .build();
        value["qr_image"] = json!(format!(
            "data:image/svg+xml;base64,{}",
            STANDARD.encode(svg)
        ));
    }
    Ok(value)
}

#[tauri::command]
pub async fn channel_control(
    app: tauri::AppHandle,
    n: State<'_, Native>,
    kind: String,
    action: String,
    args: Value,
) -> Result<Value, String> {
    if !request_ok(&kind, &action, &args) {
        return Err(fail("不支持的渠道操作"));
    }
    if action == "qq_console" {
        let opened = std::process::Command::new("/usr/bin/open")
            .arg("https://q.qq.com/")
            .status()
            .map_err(|_| fail("无法打开 QQ 官方平台"))?;
        if !opened.success() {
            return Err(fail("无法打开 QQ 官方平台"));
        }
        return Ok(
            json!({"status":"official_platform_opened","authentication":"requires_user_operation"}),
        );
    }
    let mut profile = current(&n);
    if profile.home.is_empty() {
        profile.home = data(&app)?.join("product-v5").to_string_lossy().into();
    }
    if action == "logs" {
        let home = PathBuf::from(&profile.home)
            .canonicalize()
            .map_err(|_| fail("请先准备本机组件"))?;
        let hub = home.join("message-platforms").join(&kind);
        let state = private_json(&hub.join("settings.json"))?;
        let generation = state["generation"].as_str().unwrap_or("preparation");
        if generation != "preparation"
            && !(generation.len() == 32 && generation.chars().all(|c| c.is_ascii_hexdigit()))
        {
            return Err(fail("连接信息需要核对"));
        }
        let folder = hub
            .join("generations")
            .join(generation)
            .join("channels")
            .canonicalize()
            .map_err(|_| fail("尚无运行记录，请先查看诊断"))?;
        if !folder.starts_with(&home) {
            return Err(fail("诊断目录归属无法确认"));
        }
        let opened = std::process::Command::new("/usr/bin/open")
            .arg(folder)
            .status()
            .map_err(|_| fail("无法打开诊断目录"))?;
        if !opened.success() {
            return Err(fail("无法打开诊断目录"));
        }
        return Ok(json!({"status":"diagnostic_folder_opened","messages_included":false}));
    }
    // Use the candidate's reviewed Suite resource; an old connected CLI cannot supply code.
    let cli = app
        .path()
        .resource_dir()
        .map_err(|_| fail("内置渠道资源不可用"))?
        .join("bundled-backends/localpilot");
    let args = if action == "workspace" {
        let window = app.get_webview_window("main").ok_or("主窗口不可用")?;
        let selected = rfd::AsyncFileDialog::new()
            .set_parent(&window)
            .set_title("选择此消息渠道可访问的工作文件夹")
            .pick_folder()
            .await;
        let Some(folder) = selected else {
            return Ok(json!({"status":"cancelled"}));
        };
        let chosen = folder
            .path()
            .canonicalize()
            .map_err(|_| fail("工作文件夹不可访问"))?;
        for protected in [
            app.path()
                .resource_dir()
                .map_err(|_| fail("组件目录不可用"))?,
            data(&app)?,
        ] {
            let protected = protected.canonicalize().unwrap_or(protected);
            if chosen.starts_with(&protected) || protected.starts_with(&chosen) {
                return Err(fail(
                    "请选择不包含 LocalPilot 私有数据或运行组件的工作文件夹",
                ));
            }
        }
        json!({"path":chosen.to_string_lossy(),"confirmed":true})
    } else {
        args
    };
    tauri::async_runtime::spawn_blocking(move || {
        let args = if action == "qq_credentials" {
            let Some(id) = native_input(&app, false)? else {
                return Ok(json!({"status":"cancelled"}));
            };
            let Some(secret) = native_input(&app, true)? else {
                return Ok(json!({"status":"cancelled"}));
            };
            json!({"app_id":id,"app_secret":secret,"confirmed":true})
        } else {
            args
        };
        run(&cli, &profile.home, &kind, &action, args)
    })
    .await
    .map_err(|_| fail("渠道管理中断，未自动重试"))?
}

#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn rejects_shell_paths_and_webview_secrets() {
        assert!(!request_ok("qq", "exec", &json!({"command":"sh"})));
        assert!(!request_ok("../qq", "status", &json!({})));
        assert!(!request_ok(
            "qq",
            "qq_credentials",
            &json!({"app_secret":"secret"})
        ));
        assert!(request_ok("qq", "qq_credentials", &json!({})));
        assert!(!request_ok("wechat", "qq_credentials", &json!({})));
        assert!(!request_ok("qq", "workspace", &json!({"path":"/private"})));
        assert!(request_ok("wechat", "workspace", &json!({})));
    }
}
