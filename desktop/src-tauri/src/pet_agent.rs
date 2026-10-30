//! Reuse the Desktop submission journal and Core. No approval by Companion.
use super::*;

fn resolved_submission(record: &Value, attempted: bool) -> Result<(), String> {
    if attempted
        && record["session_id"].as_str().is_some()
        && !record["task_id"].as_str().is_some_and(id_ok)
    {
        return Err("原提交状态未知；请先恢复原请求，不会重复创建任务".into());
    }
    Ok(())
}

// submit_task persists its journal before any HTTP submission. A session with
// no journal has never attempted a task; a journaled UNKNOWN remains blocked.
fn submission_attempted(root: &Path, record: &Value) -> Result<bool, String> {
    let journals = root.join("submissions");
    if !journals.exists() {
        return Ok(false);
    }
    for entry in fs::read_dir(journals).map_err(|_| "无法核对原请求记录")? {
        let entry = entry.map_err(|_| "原请求记录不可读")?;
        let v = private_json(&entry.path())?;
        if v["body"]["session_id"] == record["session_id"]
            && v["origin"] == record["origin"]
            && v["subject"] == record["subject"]
        {
            return Ok(true);
        }
    }
    Ok(false)
}

/// Select a local existing Core installation; keep Companion's home independent.
#[tauri::command]
pub async fn pet_core(
    app: tauri::AppHandle,
    n: State<'_, Native>,
    action: String,
) -> Result<Value, String> {
    if action == "status" {
        let p = current(&n);
        if p.origin.is_empty() {
            return Ok(
                json!({"connected":false,"setup_complete":preferences::load(&data(&app)?)?.completed}),
            );
        }
        let health = request(&p, "GET", "/healthz", None, None).await?;
        check_health(&health)?;
        return Ok(
            json!({"connected":true,"workspace":p.workspace,"version":health["version"],"setup_complete":preferences::load(&data(&app)?)?.completed}),
        );
    }
    if action == "setup" {
        let window = if let Some(w) = app.get_webview_window("main") {
            w
        } else {
            tauri::WebviewWindowBuilder::new(
                &app,
                "main",
                tauri::WebviewUrl::App("index.html".into()),
            )
            .title("LocalPilot Test · 首次设置")
            .inner_size(1200.0, 800.0)
            .build()
            .map_err(|e| e.to_string())?
        };
        pet_native::expand(&app, false, false)?;
        window.show().map_err(|e| e.to_string())?;
        window.set_focus().map_err(|e| e.to_string())?;
        return Ok(json!({"opened":true}));
    }
    if action != "connect" {
        return Err("未知 Core 连接操作".into());
    }
    let state = app.state::<pet_native::PetState>();
    let _guard = state.submission_lock.lock().await;
    let old = private_json(&data(&app)?.join("pet-task-v1.json")).unwrap_or(Value::Null);
    resolved_submission(&old, submission_attempted(&data(&app)?, &old)?)?;
    if let Some(id) = old["task_id"].as_str().filter(|id| id_ok(id)) {
        let task = request(
            &current(&n),
            "GET",
            &format!("/localpilot/v1/tasks/{id}"),
            None,
            None,
        )
        .await?;
        if ![
            "completed",
            "incomplete",
            "failed",
            "cancelled",
            "timed_out",
        ]
        .contains(&task["status"].as_str().unwrap_or(""))
            || task["receipt_summary"]["unknown_effects"]
                .as_u64()
                .unwrap_or(0)
                > 0
        {
            return Err("原任务尚未结束或效果未知，请先在任务窗口核对".into());
        }
    }
    let selected = rfd::AsyncFileDialog::new()
        .set_title("连接已有的本机 LocalPilot Core 数据目录")
        .pick_folder()
        .await;
    let Some(folder) = selected else {
        return Ok(json!({"cancelled":true}));
    };
    let conn = private_json(&folder.path().join("connection.json"))?;
    let candidate = Profile {
        home: folder.path().to_string_lossy().into(),
        origin: origin(conn["url"].as_str().ok_or("Core 地址缺失")?)?,
        ..current(&n)
    };
    let health = request(&candidate, "GET", "/healthz", None, None).await?;
    check_health(&health)?;
    let cli = current(&n).cli;
    connect_suite(app.clone(), n, folder.path().to_string_lossy().into(), cli).await?;
    Ok(json!({"connected":true,"version":health["version"]}))
}

#[tauri::command]
pub async fn pet_agent(
    app: tauri::AppHandle,
    n: State<'_, Native>,
    action: String,
    text: Option<String>,
    agent_profile: Option<String>,
) -> Result<Value, String> {
    let state = app.state::<pet_native::PetState>();
    let _guard = state.submission_lock.lock().await;
    let path = data(&app)?.join("pet-task-v1.json");
    let p = current(&n);
    let health = request(&p, "GET", "/healthz", None, None).await?;
    check_health(&health)?;
    let old = private_json(&path).unwrap_or(Value::Null);
    let same_host = old["origin"] == p.origin && old["subject"] == health["client_subject"];
    let id = old["task_id"].as_str().filter(|id| id_ok(id));
    if action == "submit" {
        if !preferences::load(&data(&app)?)?.completed {
            return Err("请在宠物设置中打开主窗口，明确完成首次设置后再提交".into());
        }
        if same_host {
            resolved_submission(&old, submission_attempted(&data(&app)?, &old)?)?;
            if let Some(id) = id {
                let prior =
                    request(&p, "GET", &format!("/localpilot/v1/tasks/{id}"), None, None).await?;
                if ![
                    "completed",
                    "incomplete",
                    "failed",
                    "cancelled",
                    "timed_out",
                ]
                .contains(&prior["status"].as_str().unwrap_or(""))
                {
                    return Err("已有任务正在处理；请先查看或取消原任务".into());
                }
                if prior["recovery"]["class"] == "UNKNOWN_BLOCKED"
                    || prior["receipt_summary"]["unknown_effects"]
                        .as_u64()
                        .unwrap_or(0)
                        > 0
                {
                    return Err("原任务仍有效果未知的操作，请先在主窗口核对".into());
                }
            }
        }
        let profile = agent_profile.unwrap_or_else(|| "standard".into());
        if !["standard", "minimal"].contains(&profile.as_str()) {
            return Err("Agent 模式无效".into());
        }
        let question = text
            .filter(|s| !s.trim().is_empty() && s.len() <= 16384)
            .ok_or("请输入任务")?;
        let session = product::product_control(app.clone(), app.state::<Native>(), "desktop_session".into(),
            json!({"model":"__auto__","source":"local_only","permission_mode":"request","agent_profile":profile,
                "key":format!("pet-{}",uuid::Uuid::new_v4())})).await?;
        let session_id = session["id"].as_str().ok_or("Core 未返回会话")?.to_string();
        save(
            &path,
            &json!({"origin":p.origin,"subject":health["client_subject"],"session_id":session_id,"task_id":null}),
        )?;
        let preferences = Preferences {
            source: preferences::Source::LocalOnly,
            ..Preferences::default()
        };
        let task = submit_task(
            app.clone(),
            app.state::<Native>(),
            question,
            session["model"].as_str().ok_or("Core 未返回模型")?.into(),
            Some(session_id.clone()),
            true,
            false,
            None,
            preferences,
        )
        .await?;
        save(
            &path,
            &json!({"origin":p.origin,"subject":health["client_subject"],"session_id":session_id,"task_id":task["id"]}),
        )?;
        if let Some(id) = task["id"].as_str() {
            watch_task(app.clone(), app.state::<Native>(), id.into(), 0)?;
        }
        return Ok(task);
    }
    if old.is_null() {
        return Ok(json!({"status":"no_task"}));
    }
    if !same_host {
        return Err("原任务属于其它服务或身份，未重新提交".into());
    }
    let id = match id {
        Some(id) => id.to_string(),
        None if action == "reconnect" => {
            // Recover only the original persisted request from this pet session.
            let root = data(&app)?.join("submissions");
            let mut found = None;
            for entry in fs::read_dir(root)
                .map_err(|_| "原请求待确认，请在主窗口恢复")?
                .flatten()
            {
                if let Ok(record) = private_json(&entry.path()) {
                    if record["body"]["session_id"] == old["session_id"]
                        && record["origin"] == p.origin
                        && record["subject"] == health["client_subject"]
                    {
                        let key = record["key"].as_str().ok_or("原请求身份无效")?.to_string();
                        let task =
                            recover_submission(app.clone(), app.state::<Native>(), key).await?;
                        found = task["id"].as_str().map(String::from);
                        break;
                    }
                }
            }
            let id = found.ok_or("原请求状态尚未确认；不会新建任务")?;
            let mut record = old.clone();
            record["task_id"] = json!(id);
            save(&path, &record)?;
            id
        }
        _ => return Err("原提交状态未知；请恢复原请求".into()),
    };
    if action == "review" {
        let window = if let Some(window) = app.get_webview_window("main") {
            window
        } else {
            tauri::WebviewWindowBuilder::new(
                &app,
                "main",
                tauri::WebviewUrl::App(format!("index.html?petTask={id}").into()),
            )
            .title("LocalPilot · 查看宠物原任务")
            .inner_size(1200.0, 800.0)
            .build()
            .map_err(|e| e.to_string())?
        };
        window.show().map_err(|e| e.to_string())?;
        window.set_focus().map_err(|e| e.to_string())?;
        window
            .emit("pet-review-task", json!({"task_id":id}))
            .map_err(|e| e.to_string())?;
        return request(&p, "GET", &format!("/localpilot/v1/tasks/{id}"), None, None).await;
    }
    if action == "cancel" {
        request(
            &p,
            "POST",
            &format!("/localpilot/v1/tasks/{id}/cancel"),
            Some(json!({})),
            None,
        )
        .await?;
    } else if !["status", "reconnect"].contains(&action.as_str()) {
        return Err("宠物不能批准工具；请在主窗口核对操作".into());
    }
    watch_task(app.clone(), app.state::<Native>(), id.clone(), 0)?;
    request(&p, "GET", &format!("/localpilot/v1/tasks/{id}"), None, None).await
}

#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn ambiguous_submission_cannot_be_replaced() {
        assert!(
            resolved_submission(&json!({"session_id":"sess_old","task_id":null}), true).is_err()
        );
        assert!(
            resolved_submission(&json!({"session_id":"sess_old","task_id":"bad/id"}), true)
                .is_err()
        );
        assert!(resolved_submission(
            &json!({"session_id":"sess_old","task_id":"task_original"}),
            true
        )
        .is_ok());
        assert!(resolved_submission(&Value::Null, false).is_ok());
        assert!(resolved_submission(
            &json!({"session_id":"sess_unsubmitted","task_id":null}),
            false
        )
        .is_ok());
    }
}
