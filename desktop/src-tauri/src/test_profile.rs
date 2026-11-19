use crate::{fail, private_json};
use sha2::{Digest, Sha256};
use std::{
    fs,
    os::unix::{ffi::OsStrExt, fs::PermissionsExt},
    path::PathBuf,
};
use tauri::{
    utils::config::{AppDirectoriesOverride, AppDirectoryOverrides, Config},
    Manager, Runtime, WebviewWindowBuilder,
};

#[derive(Default)]
pub struct TestProfile {
    pub client: Option<PathBuf>,
    store: Option<[u8; 16]>,
}

impl TestProfile {
    pub fn configure(config: &mut Config, root: Option<PathBuf>) -> Result<Self, String> {
        if ![
            "io.localpilot.desktop.test",
            "io.localpilot.desktop.channels.test",
        ]
        .contains(&config.identifier.as_str())
        {
            return Ok(Self::default());
        }
        let root = root.ok_or("隔离测试应用需要指定测试目录；日常安装未改动")?;
        let marker = private_json(&root.join("test-owner.json"))?;
        if !root.is_absolute() || marker["purpose"] != "LocalPilot installation E2E" {
            return Err(fail("测试目录身份无效"));
        }
        let root = root.canonicalize().map_err(|_| fail("测试目录不可访问"))?;
        let client = root.join("client");
        fs::create_dir_all(&client).map_err(|_| fail("无法创建客户端目录"))?;
        fs::set_permissions(&client, fs::Permissions::from_mode(0o700))
            .map_err(|_| fail("客户端目录权限错误"))?;
        let mut hash = Sha256::new();
        hash.update(b"LocalPilot test WebView v1\0");
        hash.update(config.identifier.as_bytes());
        hash.update(b"\0");
        hash.update(root.as_os_str().as_bytes());
        let store: [u8; 16] = hash.finalize()[..16].try_into().unwrap();
        // WKWebView ignores data_directory; macOS 15+ supports a named
        // persistent store. Canonical paths keep /var and /private/var identical.
        for window in &mut config.app.windows {
            window.data_store_identifier = Some(store);
            window.data_directory = None;
        }
        config.app.app_directories_override =
            Some(AppDirectoriesOverride::Directories(AppDirectoryOverrides {
                local_data: Some(
                    client
                        .join("webview")
                        .join(uuid::Uuid::from_bytes(store).to_string()),
                ),
                ..Default::default()
            }));
        Ok(Self {
            client: Some(client),
            store: Some(store),
        })
    }

    pub fn webview<'a, R: Runtime, M: Manager<R>>(
        &self,
        builder: WebviewWindowBuilder<'a, R, M>,
    ) -> WebviewWindowBuilder<'a, R, M> {
        if let (Some(client), Some(store)) = (&self.client, self.store) {
            builder
                .data_directory(
                    client
                        .join("webview")
                        .join(uuid::Uuid::from_bytes(store).to_string()),
                )
                .data_store_identifier(store)
        } else {
            builder
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use serde_json::json;
    use std::os::unix::fs::symlink;
    use tauri::utils::config::WindowConfig;

    struct Fixture(PathBuf);
    impl Fixture {
        fn new() -> Self {
            let root = std::env::temp_dir().join(format!("lp-webview-{}", uuid::Uuid::new_v4()));
            fs::create_dir(&root).unwrap();
            crate::save(
                &root.join("test-owner.json"),
                &json!({"purpose":"LocalPilot installation E2E"}),
            )
            .unwrap();
            Self(root)
        }
    }
    impl Drop for Fixture {
        fn drop(&mut self) {
            fs::remove_dir_all(&self.0).unwrap();
        }
    }
    fn config(identifier: &str) -> Config {
        let mut config = Config::default();
        config.identifier = identifier.into();
        config.app.windows = ["main", "pet", "pet-bubble"]
            .into_iter()
            .map(|label| WindowConfig {
                label: label.into(),
                ..Default::default()
            })
            .collect();
        config
    }

    #[test]
    fn test_webviews_share_a_root_store_and_separate_other_roots() {
        let first = Fixture::new();
        let second = Fixture::new();
        let mut cfg = config("io.localpilot.desktop.test");
        let profile = TestProfile::configure(&mut cfg, Some(first.0.clone())).unwrap();
        assert!(cfg
            .app
            .windows
            .iter()
            .all(|w| w.data_store_identifier == profile.store && w.data_directory.is_none()));
        assert_eq!(
            cfg.app.app_directories_override,
            Some(AppDirectoriesOverride::Directories(AppDirectoryOverrides {
                local_data: Some(
                    first
                        .0
                        .canonicalize()
                        .unwrap()
                        .join("client/webview")
                        .join(uuid::Uuid::from_bytes(profile.store.unwrap()).to_string())
                ),
                ..Default::default()
            }))
        );
        let repeated = TestProfile::configure(&mut cfg, Some(first.0.clone())).unwrap();
        assert_eq!(profile.store, repeated.store);
        let different = TestProfile::configure(&mut cfg, Some(second.0.clone())).unwrap();
        assert_ne!(profile.store, different.store);
        let mut channels = config("io.localpilot.desktop.channels.test");
        let other_bundle = TestProfile::configure(&mut channels, Some(first.0.clone())).unwrap();
        assert_ne!(profile.store, other_bundle.store);
    }

    #[test]
    fn canonical_alias_reopens_the_same_test_store() {
        let root = Fixture::new();
        let alias = root.0.join("alias");
        symlink(&root.0, &alias).unwrap();
        let mut cfg = config("io.localpilot.desktop.test");
        let real = TestProfile::configure(&mut cfg, Some(root.0.clone())).unwrap();
        let aliased = TestProfile::configure(&mut cfg, Some(alias)).unwrap();
        assert_eq!(real.store, aliased.store);
        assert_eq!(real.client, aliased.client);
    }

    #[test]
    fn ordinary_app_keeps_its_original_webview_profile() {
        let mut cfg = config("io.localpilot.desktop");
        let before = serde_json::to_value(&cfg).unwrap();
        let profile =
            TestProfile::configure(&mut cfg, Some("/nonexistent/test-root".into())).unwrap();
        assert_eq!(serde_json::to_value(&cfg).unwrap(), before);
        assert!(profile.client.is_none() && profile.store.is_none());
    }

    #[test]
    fn invalid_test_root_fails_before_configuring_any_webview() {
        let mut cfg = config("io.localpilot.desktop.test");
        assert!(TestProfile::configure(&mut cfg, None).is_err());
        let root = Fixture::new();
        crate::save(&root.0.join("test-owner.json"), &json!({"purpose":"other"})).unwrap();
        assert!(TestProfile::configure(&mut cfg, Some(root.0.clone())).is_err());
        assert!(cfg
            .app
            .windows
            .iter()
            .all(|w| w.data_store_identifier.is_none()));
        assert!(cfg.app.app_directories_override.is_none());
    }
}
