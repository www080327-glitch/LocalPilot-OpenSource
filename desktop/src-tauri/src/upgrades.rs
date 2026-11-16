//! Native artifact selection over Suite's persisted upgrade plans.
use crate::{cli_run, current, fail, Native, Profile};
use serde_json::{json, Value};
use tauri::State;

#[derive(Clone)]
pub struct ReviewedUpgrade {
    profile: Profile,
    fingerprint: String,
    desktop: bool,
    bundle_id: Option<String>,
}

fn identity_matches(bundle_id: Option<&str>, current: &str) -> bool {
    bundle_id.map_or(true, |id| id == current)
}

fn remember(n: &Native, profile: &Profile, plan: &Value) -> Result<String, String> {
    let id = plan["id"].as_str().ok_or("升级计划缺少身份")?;
    let fingerprint = plan["fingerprint"].as_str().ok_or("升级计划缺少摘要")?;
    let bundle_id = if plan["desktop"].is_null() {
        None
    } else {
        Some(
            plan["desktop"]["bundle_id"]
                .as_str()
                .ok_or("应用升级计划缺少 Bundle ID")?
                .to_string(),
        )
    };
    n.upgrades.lock().unwrap().insert(
        id.into(),
        ReviewedUpgrade {
            profile: profile.clone(),
            fingerprint: fingerprint.into(),
            desktop: !plan["desktop"].is_null(),
            bundle_id,
        },
    );
    Ok(id.into())
}

#[tauri::command]
pub async fn upgrade_plan(
    app: tauri::AppHandle,
    n: State<'_, Native>,
    module: String,
) -> Result<Value, String> {
    let profile = current(&n);
    if module == "history" {
        let mut result = cli_run(profile.clone(), vec!["upgrade".into(), "status".into()]).await?;
        if let Some(rows) = result["result"][0]["upgrades"].as_array_mut() {
            for row in rows {
                remember(&n, &profile, &row["plan"])?;
                let allowed = (cfg!(target_os = "macos") || row["plan"]["desktop"].is_null())
                    && identity_matches(
                        row["plan"]["desktop"]["bundle_id"].as_str(),
                        &app.config().identifier,
                    );
                row["execution_allowed"] = json!(allowed);
                if !allowed {
                    row["blocked_reason"] =
                        json!("此 APP 升级计划属于另一应用身份，请在对应日常或测试 APP 中查看执行");
                }
            }
        }
        return Ok(result);
    }
    if ![
        "core",
        "companion",
        "suite",
        "channels",
        "all",
        "desktop",
        "bundle",
    ]
    .contains(&module.as_str())
    {
        return Err(fail("未知升级范围"));
    }
    let mut args = vec!["upgrade".into(), module.clone()];
    if ["desktop", "bundle"].contains(&module.as_str()) {
        if !cfg!(target_os = "macos") {
            return Err(fail(
                "Linux GUI 由系统 DEB 包管理器升级；本入口仍可升级四个独立 Python 组件",
            ));
        }
        let selected = rfd::AsyncFileDialog::new()
            .set_title("选择已解包的目标 LocalPilot APP")
            .add_filter("macOS application", &["app"])
            .pick_file()
            .await
            .ok_or("已取消")?;
        args.extend(["--app".into(), selected.path().to_string_lossy().into()]);
        let test = app.config().identifier == "io.localpilot.desktop.test";
        if test {
            args.push("--test-app".into());
        }
    } else {
        let files = rfd::AsyncFileDialog::new()
            .set_title("选择目标组件 wheels（可多选）")
            .add_filter("Python wheel", &["whl"])
            .pick_files()
            .await
            .ok_or("已取消")?;
        for file in files {
            args.extend(["--wheel".into(), file.path().to_string_lossy().into()]);
        }
    }
    if module != "desktop" {
        let files = rfd::AsyncFileDialog::new()
            .set_title("选择各组件当前版本的回滚 wheels（可多选）")
            .add_filter("Python wheel", &["whl"])
            .pick_files()
            .await
            .ok_or("已取消：需要具体回滚包")?;
        for file in files {
            args.extend([
                "--previous-wheel".into(),
                file.path().to_string_lossy().into(),
            ]);
        }
    }
    let mut result = cli_run(profile.clone(), args).await?;
    if result["exit"] == 0 {
        result["plan_id"] = json!(remember(&n, &profile, &result["result"][0])?);
    }
    Ok(result)
}

#[tauri::command]
pub async fn execute_upgrade(
    app: tauri::AppHandle,
    n: State<'_, Native>,
    plan_id: String,
    rollback: Option<bool>,
) -> Result<Value, String> {
    let plan = n
        .upgrades
        .lock()
        .unwrap()
        .get(&plan_id)
        .cloned()
        .ok_or("先读取并审阅这个升级计划")?;
    let profile = current(&n);
    if plan.desktop && !cfg!(target_os = "macos") {
        return Err(fail(
            "macOS APP 事务不能在 Linux 执行，请使用对应发行版的系统包管理器",
        ));
    }
    if plan.profile.home != profile.home || plan.profile.cli != profile.cli {
        return Err(fail("连接已改变，拒绝执行旧升级计划"));
    }
    if !identity_matches(plan.bundle_id.as_deref(), &app.config().identifier) {
        return Err(fail(
            "此 APP 升级计划属于另一应用身份，拒绝替换日常或独立测试应用",
        ));
    }
    let mut args = vec![
        "upgrade".into(),
        "all".into(),
        "--plan".into(),
        plan_id,
        "--fingerprint".into(),
        plan.fingerprint,
        if rollback == Some(true) {
            "--rollback".into()
        } else {
            "--execute".into()
        },
    ];
    if plan.desktop {
        args.extend([
            "--launch".into(),
            "--wait-pid".into(),
            std::process::id().to_string(),
        ]);
    }
    let result = cli_run(profile, args).await?;
    if result["result"][0]["status"] == "awaiting_gui_exit" {
        app.exit(0);
    }
    Ok(result)
}

#[cfg(test)]
mod tests {
    use super::identity_matches;

    #[test]
    fn historical_app_plans_cannot_cross_daily_and_test_identities() {
        assert!(identity_matches(
            Some("io.localpilot.desktop.test"),
            "io.localpilot.desktop.test"
        ));
        assert!(!identity_matches(
            Some("io.localpilot.desktop"),
            "io.localpilot.desktop.test"
        ));
        assert!(!identity_matches(
            Some("io.localpilot.desktop.test"),
            "io.localpilot.desktop"
        ));
        assert!(identity_matches(None, "io.localpilot.desktop.test"));
    }
}
