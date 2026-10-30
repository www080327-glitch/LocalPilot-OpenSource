use serde::{Deserialize, Serialize};
use serde_json::{json, Value};
use std::path::Path;
#[derive(Clone, Debug, Serialize, Deserialize, PartialEq)]
#[serde(rename_all = "snake_case")]
pub enum Source {
    LocalOnly,
    LocalFirst,
    Balanced,
    CloudFirst,
    CloudOnly,
}
#[derive(Clone, Debug, Serialize, Deserialize, PartialEq)]
#[serde(rename_all = "snake_case")]
pub enum Objective {
    Speed,
    Quality,
    Efficiency,
    Balanced,
}
#[derive(Clone, Debug, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct Preferences {
    pub source: Source,
    pub objective: Objective,
    pub effort: Option<String>,
}
impl Default for Preferences {
    fn default() -> Self {
        Self {
            source: Source::LocalFirst,
            objective: Objective::Balanced,
            effort: None,
        }
    }
}
#[derive(Clone, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct Global {
    pub version: u32,
    pub completed: bool,
    pub defaults: Preferences,
}
impl Default for Global {
    fn default() -> Self {
        Self {
            version: 1,
            completed: false,
            defaults: Preferences::default(),
        }
    }
}
pub fn load(root: &Path) -> Result<Global, String> {
    let p = root.join("preferences-v1.json");
    if !p.exists() {
        return Ok(Global::default());
    }
    let g: Global = serde_json::from_value(super::private_json(&p)?)
        .map_err(|_| "偏好文件无效；请修复后重试")?;
    if g.version != 1 {
        return Err("不支持此偏好文件版本；未覆盖原文件".into());
    }
    Ok(g)
}
pub fn is_cloud(route: &Value) -> bool {
    ["deepseek", "deepseek-native", "remote-openai"]
        .iter()
        .any(|a| route["adapter"] == *a)
        || route["cloud_egress"] != "LOCAL_ONLY"
}
pub fn source_allows(p: &Preferences, route: &Value) -> bool {
    match p.source {
        Source::LocalOnly => !is_cloud(route),
        Source::CloudOnly => is_cloud(route),
        _ => true,
    }
}
pub fn routing_supported(health: &Value, cap: &Value) -> bool {
    health["compatibility"]["capabilities"]
        .as_array()
        .is_some_and(|a| a.iter().any(|v| v == "routing_preferences_v1"))
        && cap["version"] == "1.0"
        && cap["task_create_field"] == "routing_preferences"
        && cap["evidence_field"] == "service.route_decision.routing_preferences"
        && [
            "local_only",
            "local_first",
            "balanced",
            "cloud_first",
            "cloud_only",
        ]
        .iter()
        .all(|s| {
            cap["sources"]
                .as_array()
                .is_some_and(|a| a.iter().any(|v| v == s))
        })
        && ["speed", "quality", "efficiency", "balanced"]
            .iter()
            .all(|s| {
                cap["objectives"]
                    .as_array()
                    .is_some_and(|a| a.iter().any(|v| v == s))
            })
}
pub fn wire(p: &Preferences) -> Value {
    json!({"version":"1.0","source":p.source,"objective":p.objective})
}
#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn fresh_user_is_not_completed() {
        let root = std::env::temp_dir().join(format!("lp-fresh-{}", uuid::Uuid::new_v4()));
        let g = load(&root).unwrap();
        assert!(!g.completed);
        assert_eq!(g.defaults.source, Source::LocalFirst);
        assert!(!root.exists());
    }
    #[test]
    fn strict_preference_validation() {
        assert!(serde_json::from_value::<Preferences>(
            json!({"source":"automatic","objective":"speed","effort":null})
        )
        .is_err());
        assert!(serde_json::from_value::<Preferences>(
            json!({"source":"local_only","objective":"speed","effort":null,"allow_cloud":true})
        )
        .is_err());
    }
    #[test]
    fn local_only_fails_closed_on_unknown_egress() {
        let p = Preferences {
            source: Source::LocalOnly,
            ..Preferences::default()
        };
        assert!(!source_allows(&p, &json!({"adapter":"local-openai"})));
        assert!(source_allows(
            &p,
            &json!({"adapter":"local-openai","cloud_egress":"LOCAL_ONLY"})
        ));
        assert!(!source_allows(
            &p,
            &json!({"adapter":"deepseek","cloud_egress":"LOCAL_ONLY"})
        ));
    }
    #[test]
    fn preferences_require_complete_negotiation() {
        let h = json!({"compatibility":{"capabilities":["routing_preferences_v1"]}});
        assert!(!routing_supported(&h, &json!({"version":"1.0"})));
    }
    #[test]
    fn persistence_and_no_implicit_completion() {
        let root = std::env::temp_dir().join(format!("lp-prefs-{}", uuid::Uuid::new_v4()));
        std::fs::create_dir(&root).unwrap();
        let mut g = Global::default();
        super::super::save(&root.join("preferences-v1.json"), &g).unwrap();
        assert!(!load(&root).unwrap().completed);
        g.completed = true;
        g.defaults.source = Source::CloudOnly;
        super::super::save(&root.join("preferences-v1.json"), &g).unwrap();
        assert_eq!(load(&root).unwrap().defaults.source, Source::CloudOnly);
        std::fs::remove_dir_all(root).unwrap();
    }
}
