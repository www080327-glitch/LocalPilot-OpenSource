#[cfg(any(not(target_os = "macos"), test))]
use std::fs;
use std::{ffi::OsStr, path::Path, process::Command};

pub fn open_command(target: impl AsRef<OsStr>) -> Command {
    let mut command = Command::new(if cfg!(target_os = "macos") {
        "/usr/bin/open"
    } else {
        "xdg-open"
    });
    command.arg(target);
    command
}

pub fn open_target(target: impl AsRef<OsStr>) -> Result<(), String> {
    open_command(target)
        .status()
        .map_err(|_| "无法启动系统浏览器或文件管理器".to_string())?
        .success()
        .then_some(())
        .ok_or_else(|| "系统浏览器或文件管理器未能打开目标".to_string())
}

pub fn reveal_command(path: &Path) -> Result<Command, String> {
    if cfg!(target_os = "macos") {
        let mut command = Command::new("/usr/bin/open");
        command.args(["-R", "--"]).arg(path);
        Ok(command)
    } else {
        // Opening the containing folder must not launch an executable attachment.
        Ok(open_command(path.parent().ok_or("文件没有父目录")?))
    }
}

pub fn reduce_motion() -> bool {
    #[cfg(target_os = "macos")]
    {
        objc2_app_kit::NSWorkspace::sharedWorkspace().accessibilityDisplayShouldReduceMotion()
    }
    #[cfg(not(target_os = "macos"))]
    {
        false
    }
}

pub fn copy_modules(source: &Path, destination: &Path) -> Result<(), String> {
    #[cfg(target_os = "macos")]
    {
        Command::new("/usr/bin/ditto")
            .args(["--norsrc", "--noextattr"])
            .arg(source)
            .arg(destination)
            .status()
            .map_err(|_| "无法复制离线模块".to_string())?
            .success()
            .then_some(())
            .ok_or_else(|| "离线模块复制失败".to_string())
    }
    #[cfg(not(target_os = "macos"))]
    {
        copy_tree(source, destination).map_err(|error| format!("离线模块复制失败：{error}"))
    }
}

#[cfg(not(target_os = "macos"))]
fn copy_tree(source: &Path, destination: &Path) -> std::io::Result<()> {
    fs::create_dir(destination)?;
    for entry in fs::read_dir(source)? {
        let entry = entry?;
        let target = destination.join(entry.file_name());
        let kind = entry.file_type()?;
        if kind.is_symlink() {
            std::os::unix::fs::symlink(fs::read_link(entry.path())?, target)?;
        } else if kind.is_dir() {
            copy_tree(&entry.path(), &target)?;
        } else if kind.is_file() {
            fs::copy(entry.path(), target)?;
        } else {
            return Err(std::io::Error::other("模块包含不支持的特殊文件"));
        }
    }
    fs::set_permissions(destination, fs::metadata(source)?.permissions())
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::os::unix::fs::PermissionsExt;

    #[test]
    fn revealing_attachment_does_not_execute_it() {
        let path = Path::new("/tmp/LocalPilot test/command.sh");
        let command = reveal_command(path).unwrap();
        let args = command.get_args().collect::<Vec<_>>();
        if cfg!(target_os = "macos") {
            assert_eq!(args, [OsStr::new("-R"), OsStr::new("--"), path.as_os_str()]);
        } else {
            assert_eq!(command.get_program(), "xdg-open");
            assert_eq!(args, [path.parent().unwrap().as_os_str()]);
        }
    }

    #[test]
    fn module_copy_preserves_executable_and_relative_link() {
        let root =
            std::env::temp_dir().join(format!("localpilot-module-copy-{}", uuid::Uuid::new_v4()));
        let source = root.join("source");
        let destination = root.join("relocated bundle");
        fs::create_dir_all(source.join("runtime")).unwrap();
        fs::write(source.join("runtime/entry"), "#!/bin/sh\nprintf copied").unwrap();
        fs::set_permissions(
            source.join("runtime/entry"),
            fs::Permissions::from_mode(0o755),
        )
        .unwrap();
        std::os::unix::fs::symlink("runtime/entry", source.join("localpilot")).unwrap();
        copy_modules(&source, &destination).unwrap();
        let output = Command::new(destination.join("localpilot"))
            .output()
            .unwrap();
        assert!(output.status.success());
        assert_eq!(output.stdout, b"copied");
        assert_eq!(
            fs::read_link(destination.join("localpilot")).unwrap(),
            Path::new("runtime/entry")
        );
        fs::remove_dir_all(root).unwrap();
    }
}
