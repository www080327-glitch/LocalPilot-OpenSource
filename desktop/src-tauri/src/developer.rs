//! Full legacy CLI forms produce trusted-terminal commands; never execute Runtime here.
use super::{current, data, fail, private_json, save, Native};
use serde_json::{json, Value};
use std::path::{Path, PathBuf};
use tauri::State;
const CATALOG: &str = include_str!("../../src/developer-catalog.json");
fn catalog() -> Value {
    serde_json::from_str(CATALOG).expect("bundled developer catalog")
}
fn q(s: &str) -> String {
    format!("'{}'", s.replace('\'', "'\\''"))
}
fn python(app: &tauri::AppHandle, n: &Native) -> Result<PathBuf, String> {
    let file = data(app)?.join("developer-source-v1.json");
    if file.exists() {
        let cfg = private_json(&file)?;
        if let Some(path) = cfg["python"].as_str() {
            let path = PathBuf::from(path);
            if path.is_absolute() && path.is_file() {
                return Ok(path);
            }
        }
    }
    let p = current(n);
    let bin = Path::new(&p.cli)
        .parent()
        .ok_or("请先选择 Suite 命令")?
        .join("python");
    if !bin.is_absolute() || !bin.is_file() {
        return Err(fail("Suite 对应的 Python 解释器不存在"));
    }
    Ok(bin)
}
#[tauri::command]
pub fn developer_profile(app: tauri::AppHandle, n: State<Native>) -> Result<Value, String> {
    let file = data(&app)?.join("developer-source-v1.json");
    let source = if file.exists() {
        private_json(&file)?["source"].clone()
    } else {
        Value::Null
    };
    Ok(
        json!({"source":source,"python":python(&app, &n).ok().map(|p|p.to_string_lossy().to_string()),"execution":"trusted_terminal_only"}),
    )
}
#[tauri::command]
pub async fn pick_developer_source(app: tauri::AppHandle) -> Result<Value, String> {
    let selected = rfd::AsyncFileDialog::new()
        .set_title("选择含 pyproject.toml 的 LocalPilot 源码根目录")
        .pick_folder()
        .await
        .ok_or("已取消")?;
    let root = selected
        .path()
        .canonicalize()
        .map_err(|_| fail("源码目录不可用"))?;
    if !root.join("pyproject.toml").is_file()
        || !root.join("agent/__main__.py").is_file()
        || !root.join("localpilot_service/cli.py").is_file()
    {
        return Err(fail("此目录不是 LocalPilot 源码根目录"));
    }
    let file = data(&app)?.join("developer-source-v1.json");
    let mut value = if file.exists() {
        private_json(&file)?
    } else {
        json!({})
    };
    value["source"] = json!(root.to_string_lossy());
    save(&file, &value)?;
    Ok(value)
}
#[tauri::command]
pub async fn pick_developer_python(app: tauri::AppHandle) -> Result<Value, String> {
    let selected = rfd::AsyncFileDialog::new()
        .set_title("选择已安装的 Python 解释器（仅用于命令预览）")
        .pick_file()
        .await
        .ok_or("已取消")?;
    let path = selected.path();
    if !path.is_absolute() || !path.is_file() {
        return Err(fail("解释器路径无效"));
    }
    let file = data(&app)?.join("developer-source-v1.json");
    let mut cfg = if file.exists() {
        private_json(&file)?
    } else {
        json!({})
    };
    cfg["python"] = json!(path.to_string_lossy());
    save(&file, &cfg)?;
    Ok(cfg)
}
fn env_name(s: &str) -> bool {
    !s.is_empty()
        && s.len() < 128
        && s.bytes()
            .enumerate()
            .all(|(i, c)| c == b'_' || c.is_ascii_alphabetic() || (i > 0 && c.is_ascii_digit()))
}
fn values_for(f: &Value, v: &Value) -> Result<Vec<String>, String> {
    if f["type"] == "boolean" {
        if !v.is_boolean() {
            return Err(fail("布尔参数无效"));
        }
        return Ok(vec![]);
    }
    let text = v
        .as_str()
        .filter(|v| v.len() <= 32768 && !v.contains('\0'))
        .ok_or("参数必须是有界文本")?;
    if let Some(choices) = f["choices"].as_array() {
        if !choices
            .iter()
            .any(|c| c.as_str() == Some(text) || c.to_string() == text)
        {
            return Err(fail("参数不在 CLI 声明的选项内"));
        }
    }
    if f["type"] == "integer" {
        let digits = text
            .strip_prefix('-')
            .or_else(|| text.strip_prefix('+'))
            .unwrap_or(text);
        if digits.is_empty() || !digits.bytes().all(|b| b.is_ascii_digit()) {
            return Err(fail("此参数需要整数"));
        }
    }
    if f["type"] == "number" && !text.parse::<f64>().is_ok_and(|n| n.is_finite()) {
        return Err(fail("此参数需要有限数值"));
    }
    let dest = f["dest"].as_str().unwrap();
    if (dest.ends_with("key_env") || dest.ends_with("token_env")) && !env_name(text) {
        return Err(fail("这里只接受环境变量名，不接受凭据值"));
    }
    if f["action"] == "append"
        || f["action"] == "raw_argv"
        || f["nargs"] == "*"
        || f["nargs"] == "+"
    {
        Ok(text
            .lines()
            .map(str::trim)
            .filter(|s| !s.is_empty())
            .map(String::from)
            .collect())
    } else {
        Ok(vec![text.into()])
    }
}
pub fn command_args(entry: &Value, values: &Value) -> Result<Vec<String>, String> {
    let fields = entry["fields"].as_array().ok_or("参数目录错误")?;
    let supplied = values.as_object().ok_or("参数必须为对象")?;
    if supplied.len() > 200
        || supplied
            .keys()
            .any(|k| !fields.iter().any(|f| f["key"] == k.as_str()))
    {
        return Err(fail("拒绝未知参数；没有自由 argv 或 shell 输入"));
    }
    let commands = entry["command"].as_array().unwrap();
    let mut args = vec![];
    for group in 0..=commands.len() {
        let mut positional = vec![];
        let mut raw = vec![];
        for f in fields.iter().filter(|f| f["group"] == group) {
            let key = f["key"].as_str().unwrap();
            let value = &values[key];
            let absent = value.is_null() || value.as_str() == Some("") || value == false;
            if absent {
                if f["required"] == true && f["nargs"] != "*" && f["nargs"] != "?" {
                    return Err(format!("缺少必填参数：{}", f["dest"]));
                }
                continue;
            }
            let vals = values_for(f, value)?;
            if f["action"] == "raw_argv" {
                raw.extend(vals);
            } else if let Some(flag) = f["flag"].as_str() {
                if f["type"] == "boolean" {
                    args.push(flag.into());
                } else if f["action"] == "append" {
                    for v in vals {
                        args.push(format!("{flag}={v}"));
                    }
                } else if f["nargs"] == "*" || f["nargs"] == "+" {
                    args.push(flag.into());
                    args.extend(vals);
                } else {
                    args.push(format!("{flag}={}", vals.first().ok_or("参数不能为空")?));
                }
            } else {
                positional.extend(vals);
            }
        }
        if !positional.is_empty() {
            args.push("--".into());
            args.extend(positional);
        }
        args.extend(raw);
        if let Some(cmd) = commands.get(group) {
            args.push(cmd.as_str().unwrap().into());
        }
    }
    Ok(args)
}
#[tauri::command]
pub fn developer_command(
    app: tauri::AppHandle,
    n: State<Native>,
    entry_id: String,
    values: Value,
) -> Result<Value, String> {
    let catalog = catalog();
    let e = catalog["entrypoints"]
        .as_array()
        .unwrap()
        .iter()
        .find(|e| e["id"] == entry_id)
        .ok_or("未登记的开发工具")?;
    let file = data(&app)?.join("developer-source-v1.json");
    let cfg = private_json(&file)?;
    let root = Path::new(cfg["source"].as_str().ok_or("请选择源码目录")?);
    if !root.join(e["source"].as_str().unwrap()).is_file() {
        return Err(fail("所选源码目录缺少此入口，未生成命令"));
    }
    let python = python(&app, &n)?;
    let mut command = vec![q(&python.to_string_lossy())];
    if let Some(module) = e["module"].as_str() {
        command.extend(["-m".into(), q(module)]);
    } else {
        command.push(q(&root
            .join(e["source"].as_str().unwrap())
            .to_string_lossy()));
    }
    command.extend(command_args(e, &values)?.iter().map(|a| q(a)));
    Ok(
        json!({"command":format!("cd {} && {}",q(&root.to_string_lossy()),command.join(" ")),"execution":"trusted_terminal_only","catalog_source_commit":catalog["source_commit"],"notice":"仅生成命令，尚未执行。原 CLI 在可信终端独立校验权限；不会改变主工作台的路由或会话。"}),
    )
}
#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn complete_catalog_has_all_frozen_fields() {
        let c = catalog();
        assert_eq!(
            c["entrypoints"].as_array().unwrap().len() as u64,
            c["metrics"]["entrypoints"].as_u64().unwrap()
        );
        assert_eq!(
            c["entrypoints"]
                .as_array()
                .unwrap()
                .iter()
                .map(|e| e["fields"].as_array().unwrap().len())
                .sum::<usize>(),
            c["metrics"]["parameter_fields"].as_u64().unwrap() as usize
        );
    }
    #[test]
    fn all_developer_parameters_generate_bounded_argv() {
        let catalog = catalog();
        let mut cases = vec![];
        for entry in catalog["entrypoints"].as_array().unwrap() {
            let fields = entry["fields"].as_array().unwrap();
            let mut base = json!({});
            let sample = |f: &Value| -> Value {
                if f["type"] == "boolean" {
                    return json!(true);
                }
                if let Some(c) = f["choices"].as_array().and_then(|c| c.first()) {
                    return json!(c
                        .as_str()
                        .map(String::from)
                        .unwrap_or_else(|| c.to_string()));
                }
                if f["type"] == "integer" || f["type"] == "number" {
                    return json!("1");
                }
                if f["dest"].as_str().unwrap().ends_with("key_env")
                    || f["dest"].as_str().unwrap().ends_with("token_env")
                {
                    return json!("LOCALPILOT_TEST_REFERENCE");
                }
                json!("fixture")
            };
            for f in fields
                .iter()
                .filter(|f| f["required"] == true && f["nargs"] != "*" && f["nargs"] != "?")
            {
                base[f["key"].as_str().unwrap()] = sample(f);
            }
            cases.push(json!({"entry_id":entry["id"],"argv":command_args(entry,&base).unwrap(),"field":"required_only"}));
            for f in fields {
                let mut v = base.clone();
                v[f["key"].as_str().unwrap()] = sample(f);
                let args = command_args(entry, &v).unwrap();
                cases.push(json!({"entry_id":entry["id"],"argv":args,"field":f["key"]}));
            }
        }
        assert_eq!(
            cases.len(),
            catalog["metrics"]["entrypoints"].as_u64().unwrap() as usize
                + catalog["metrics"]["parameter_fields"].as_u64().unwrap() as usize
        );
        cases.retain(|c| !c["entry_id"].as_str().unwrap().starts_with("source:"));
        if let Ok(path) = std::env::var("LP_GUI_DEVELOPER_CASES") {
            std::fs::write(path, serde_json::to_vec_pretty(&cases).unwrap()).unwrap();
        }
    }
    #[test]
    fn quote_never_interpolates_shell() {
        assert_eq!(
            q("a'$(touch /tmp/never)`x`"),
            "'a'\\''$(touch /tmp/never)`x`'"
        );
    }
    #[test]
    fn unknown_fields_and_raw_secrets_rejected() {
        let c = catalog();
        let e = c["entrypoints"]
            .as_array()
            .unwrap()
            .iter()
            .find(|e| e["id"] == "agent.__main__")
            .unwrap();
        assert!(command_args(e, &json!({"argv":"--full-permission"})).is_err());
        let f = e["fields"]
            .as_array()
            .unwrap()
            .iter()
            .find(|f| f["dest"] == "local_api_key_env")
            .unwrap();
        assert!(values_for(f, &json!("sk-this-is-a-credential")).is_err());
    }
    #[test]
    fn data_cannot_become_extra_flags() {
        let c = catalog();
        let e = c["entrypoints"]
            .as_array()
            .unwrap()
            .iter()
            .find(|e| e["id"] == "agent.__main__")
            .unwrap();
        let f = e["fields"]
            .as_array()
            .unwrap()
            .iter()
            .find(|f| f["dest"] == "workspace")
            .unwrap();
        let mut v = json!({});
        v[f["key"].as_str().unwrap()] = json!("--permission-mode=full-permission");
        assert_eq!(
            command_args(e, &v).unwrap(),
            vec!["--workspace=--permission-mode=full-permission"]
        );
    }
}
