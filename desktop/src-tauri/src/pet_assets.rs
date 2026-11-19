//! Personal import only. Third-party character bytes never enter the APP.
use super::*;
use base64::Engine;
use sha2::{Digest, Sha256};
use std::io::Write;

pub(super) const HIT_ALPHA: u8 = 24;
const CHARACTER_IDS: [&str; 8] = [
    "deepseek-whale-maid-chibi-v4",
    "chatgpt-white-dragon-chibi-v5",
    "claude-orange-scholar-chibi-v3",
    "gemini-star-cat-chibi-v1",
    "grok-gothic-chibi-v1",
    "kimi-moon-maid-chibi-v2",
    "qwen-chibi-scholar-v3",
    "zhipu-chibi-tech-v2",
];

pub struct Sprite {
    pub width: u32,
    pub height: u32,
    #[cfg_attr(not(any(target_os = "macos", test)), allow(dead_code))]
    pub alpha: Vec<u8>,
}
pub struct Atlas {
    pub sprite: Sprite,
    rows: [[u32; 4]; 11],
}
impl Atlas {
    pub fn frame_rect(&self, column: u32, row: u32) -> [u32; 4] {
        let fw = self.sprite.width / 8;
        let fh = self.sprite.height / 11;
        let bounds = self.rows[row as usize];
        [
            column * fw + bounds[0],
            row * fh + bounds[1],
            bounds[2],
            bounds[3],
        ]
    }
}
pub(super) fn decode(bytes: &[u8]) -> Result<Atlas, String> {
    if bytes.len() > 16 * 1024 * 1024 {
        return Err("素材超过 16 MB".into());
    }
    let reader = image::ImageReader::new(std::io::Cursor::new(bytes))
        .with_guessed_format()
        .map_err(|_| "素材格式无效")?;
    let (w, h) = reader.into_dimensions().map_err(|_| "素材尺寸无效")?;
    if w == 0 || h == 0 || w % 8 != 0 || h % 11 != 0 || w > 4096 || h > 5632 {
        return Err("请选择 8 列、11 行的 v2 透明角色图集".into());
    }
    let rgba = image::load_from_memory(bytes)
        .map_err(|_| "角色素材无法解码")?
        .into_rgba8();
    let alpha: Vec<u8> = rgba.pixels().map(|p| p.0[3]).collect();
    if !alpha.iter().any(|a| *a == 0) || !alpha.iter().any(|a| *a > 128) {
        return Err("素材必须有真实透明区域和可见角色".into());
    }
    let (fw, fh) = (w / 8, h / 11);
    let mut rows = [[fw, fh, 0, 0]; 11];
    // A shared crop per row preserves stride registration without rescanning
    // the entire eight-frame row on every animation tick.
    for (y, scanline) in alpha.chunks_exact(w as usize).enumerate() {
        let bounds = &mut rows[y / fh as usize];
        for (x, a) in scanline.iter().enumerate() {
            if *a > HIT_ALPHA {
                let (x, y) = (x as u32 % fw, y as u32 % fh);
                bounds[0] = bounds[0].min(x);
                bounds[1] = bounds[1].min(y);
                bounds[2] = bounds[2].max(x + 1);
                bounds[3] = bounds[3].max(y + 1);
            }
        }
    }
    for bounds in &mut rows {
        *bounds = if bounds[2] > bounds[0] && bounds[3] > bounds[1] {
            [
                bounds[0],
                bounds[1],
                bounds[2] - bounds[0],
                bounds[3] - bounds[1],
            ]
        } else {
            [0, 0, fw, fh]
        };
    }
    Ok(Atlas {
        sprite: Sprite {
            width: w,
            height: h,
            alpha,
        },
        rows,
    })
}
#[tauri::command]
pub async fn pet_asset(
    app: tauri::AppHandle,
    action: String,
    id: Option<String>,
) -> Result<Value, String> {
    // Inspect only the user's existing local character packs. Never modify Codex.
    let library = app
        .path()
        .home_dir()
        .map_err(|e| e.to_string())?
        .join(".codex/pets");
    if action == "import_edge" {
        let meta = private_json(&data(&app)?.join("pet-asset-v1.json"))?;
        let identity = meta["id"]
            .as_str()
            .filter(|id| CHARACTER_IDS.contains(id))
            .ok_or("请先选择本机角色")?;
        let folder = rfd::AsyncFileDialog::new()
            .set_title("导入该角色的个人探头姿态包（pack.json 与 poses.png）")
            .pick_folder()
            .await;
        let Some(folder) = folder else {
            return Ok(json!({"cancelled":true}));
        };
        let packs = data(&app)?.join("edge-packs");
        let (pack, edge) = import_edge_pack(folder.path(), &packs, identity)?;
        app.state::<pet_native::PetState>()
            .edge
            .lock()
            .unwrap()
            .pack = Some(pack);
        app.emit("pet-edge-asset", &edge)
            .map_err(|e| e.to_string())?;
        return Ok(edge);
    }
    if action == "catalog" {
        let items: Vec<Value> = CHARACTER_IDS
            .iter()
            .filter_map(|id| {
                let (identity, label) = character_metadata(&library.join(id)).ok()?;
                if identity != *id || !library.join(id).join("spritesheet.webp").is_file() {
                    return None;
                }
                Some(json!({"id":id,"label":label}))
            })
            .collect();
        return Ok(
            json!({"items":items,"usage":"personal_local_import","redistribution":"not_granted"}),
        );
    }
    let target = data(&app)?.join("pet-sprite.webp");
    if ["import", "import_package", "select_local"].contains(&action.as_str()) {
        let selected;
        let mut identity = None;
        let chosen_path = if action == "import_package" {
            let folder = rfd::AsyncFileDialog::new()
                .set_title("选择角色文件夹（pet.json 和 spritesheet.webp）")
                .pick_folder()
                .await;
            let Some(folder) = folder else {
                return Ok(json!({"cancelled":true}));
            };
            identity = Some(character_metadata(folder.path())?);
            folder.path().join("spritesheet.webp")
        } else if action == "select_local" {
            let id = id
                .as_deref()
                .filter(|id| CHARACTER_IDS.contains(id))
                .ok_or("角色身份无效")?;
            let found = character_metadata(&library.join(id))?;
            if found.0 != id {
                return Err("角色文件夹与身份不一致".into());
            }
            identity = Some(found);
            library.join(id).join("spritesheet.webp")
        } else {
            let chosen = rfd::AsyncFileDialog::new()
                .set_title("导入有权个人使用的 8 列、11 行透明角色图集")
                .add_filter("透明 WebP 图集", &["webp"])
                .pick_file()
                .await;
            let Some(chosen) = chosen else {
                return Ok(json!({"cancelled":true}));
            };
            selected = chosen;
            selected.path().to_path_buf()
        };
        if identity.is_none() {
            identity = CHARACTER_IDS
                .iter()
                .find(|id| chosen_path == library.join(id).join("spritesheet.webp"))
                .and_then(|id| character_metadata(&library.join(id)).ok());
        }
        let (id, label) = identity
            .map(|(id, label)| (Some(id), label))
            .unwrap_or((None, "个人角色".into()));
        let info = fs::symlink_metadata(&chosen_path).map_err(|_| "素材不可读")?;
        if !info.is_file() || info.len() > 16 * 1024 * 1024 {
            return Err("素材必须是普通文件，且小于 16 MB".into());
        }
        let bytes = fs::read(&chosen_path).map_err(|_| "素材不可读")?;
        decode(&bytes)?;
        let mut output = fs::OpenOptions::new()
            .write(true)
            .create(true)
            .truncate(true)
            .mode(0o600)
            .custom_flags(libc::O_NOFOLLOW)
            .open(&target)
            .map_err(|e| e.to_string())?;
        std::io::Write::write_all(&mut output, &bytes).map_err(|e| e.to_string())?;
        fs::set_permissions(&target, fs::Permissions::from_mode(0o600))
            .map_err(|e| e.to_string())?;
        save(
            &data(&app)?.join("pet-asset-v1.json"),
            &json!({"version":1,"sha256":format!("{:x}",Sha256::digest(&bytes)),"usage":"personal_import","redistribution":"not_granted","id":id,"label":label}),
        )?;
    } else if action != "load" {
        return Err("未知素材操作".into());
    }
    if !target.exists() {
        let state = app.state::<pet_native::PetState>();
        *state.sprite.lock().unwrap() = None;
        state.edge.lock().unwrap().pack = None;
        return Ok(json!({"status":"asset_pending","label":"素材待确认"}));
    }
    let info = fs::symlink_metadata(&target).map_err(|_| "素材不可读")?;
    if !info.is_file()
        || info.uid() != unsafe { libc::getuid() }
        || info.mode() & 0o077 != 0
        || info.len() > 16 * 1024 * 1024
    {
        return Err("素材的本机身份或私有权限无效".into());
    }
    let bytes = fs::read(&target).map_err(|_| "素材不可读")?;
    let sha = format!("{:x}", Sha256::digest(&bytes));
    if private_json(&data(&app)?.join("pet-asset-v1.json"))?["sha256"] != sha {
        return Err("素材身份已变更，请重新导入".into());
    }
    let sprite = decode(&bytes)?;
    let width = sprite.sprite.width;
    let height = sprite.sprite.height;
    *app.state::<pet_native::PetState>().sprite.lock().unwrap() = Some(sprite);
    let meta = private_json(&data(&app)?.join("pet-asset-v1.json"))?;
    let edge = edge_pack(&app, meta["id"].as_str().unwrap_or(""))?;
    let payload = json!({"edge":edge,"status":"ready","id":meta["id"],"label":meta["label"].as_str().unwrap_or("DeepSeek 娘 · 个人导入"),"sha256":sha,
        "width":width,"height":height,"url":format!("data:image/webp;base64,{}",base64::engine::general_purpose::STANDARD.encode(&bytes))});
    app.emit("pet-asset", &payload).map_err(|e| e.to_string())?;
    Ok(payload)
}

pub(super) fn diagnostic_appearance(root: &Path, basic: bool) -> Value {
    let character = private_json(&root.join("pet-asset-v1.json"))
        .ok()
        .and_then(|meta| meta["id"].as_str().map(String::from));
    json!({"character":character,"appearance_mode":if basic {"basic"} else {"extended"}})
}

fn character_metadata(folder: &Path) -> Result<(String, String), String> {
    let bytes = fs::read(folder.join("pet.json"))
        .map_err(|_| "请选择包含 pet.json 和 spritesheet.webp 的角色文件夹")?;
    let meta: Value = serde_json::from_slice(&bytes).map_err(|_| "角色说明 pet.json 无法读取")?;
    let id = meta["id"]
        .as_str()
        .filter(|id| CHARACTER_IDS.contains(id))
        .ok_or("这个角色身份尚未支持，请选择角色列表中的图集")?;
    if meta["spriteVersionNumber"] != 2 {
        return Err("请选择第 2 版角色图集，包含 8 列、11 行动作".into());
    }
    Ok((
        id.to_owned(),
        meta["displayName"].as_str().unwrap_or(id).to_owned(),
    ))
}

#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn atlas_crops_each_row_once_and_preserves_frame_registration() {
        let mut image = image::RgbaImage::new(32, 44);
        image.put_pixel(1, 8, image::Rgba([255, 255, 255, 255]));
        image.put_pixel(7, 10, image::Rgba([255, 255, 255, 255]));
        let mut bytes = std::io::Cursor::new(Vec::new());
        image.write_to(&mut bytes, image::ImageFormat::Png).unwrap();
        let atlas = decode(bytes.get_ref()).unwrap();
        assert_eq!(atlas.frame_rect(0, 2), [1, 8, 3, 3]);
        assert_eq!(atlas.frame_rect(1, 2), [5, 8, 3, 3]);
        assert_eq!(atlas.frame_rect(7, 2), [29, 8, 3, 3]);
        assert_eq!(atlas.frame_rect(0, 0), [0, 0, 4, 4]);
    }

    #[test]
    fn package_identity_is_read_from_the_selected_folder() {
        let folder = std::env::temp_dir().join(format!("lp-character-{}", uuid::Uuid::new_v4()));
        fs::create_dir(&folder).unwrap();
        let path = folder.join("pet.json");
        let mut meta = json!({"id":"deepseek-whale-maid-chibi-v4","displayName":"我的蓝鲸","spriteVersionNumber":2});
        fs::write(&path, serde_json::to_vec(&meta).unwrap()).unwrap();
        assert_eq!(
            character_metadata(&folder).unwrap(),
            ("deepseek-whale-maid-chibi-v4".into(), "我的蓝鲸".into())
        );
        meta["spriteVersionNumber"] = json!(1);
        fs::write(&path, serde_json::to_vec(&meta).unwrap()).unwrap();
        assert!(character_metadata(&folder).is_err());
        meta["spriteVersionNumber"] = json!(2);
        meta["id"] = json!("unknown-character");
        fs::write(&path, serde_json::to_vec(&meta).unwrap()).unwrap();
        assert!(character_metadata(&folder).is_err());
        fs::remove_dir_all(folder).unwrap();
    }

    #[test]
    fn diagnostics_keep_imported_identity_without_an_optional_edge_pack() {
        let root =
            std::env::temp_dir().join(format!("lp-pet-diagnostics-{}", uuid::Uuid::new_v4()));
        fs::create_dir(&root).unwrap();
        let identity = "deepseek-whale-maid-chibi-v4";
        save(
            &root.join("pet-asset-v1.json"),
            &json!({"version":1,"id":identity}),
        )
        .unwrap();
        assert_eq!(
            diagnostic_appearance(&root, true),
            json!({"character":identity,"appearance_mode":"basic"})
        );
        assert_eq!(
            diagnostic_appearance(&root, false),
            json!({"character":identity,"appearance_mode":"extended"})
        );
        fs::remove_dir_all(root).unwrap();
    }

    #[test]
    fn rejected_edge_import_preserves_the_installed_pack_and_accepts_a_valid_replacement() {
        let root = std::env::temp_dir().join(format!("lp-pet-import-{}", uuid::Uuid::new_v4()));
        let source = root.join("source");
        let packs = root.join("installed");
        fs::create_dir_all(&source).unwrap();
        let id = "fixture";
        let installed = packs.join(id);
        let mut poses = serde_json::Map::new();
        for (i, name) in [
            "TOP_LEFT",
            "TOP_RIGHT",
            "LEFT_EDGE",
            "RIGHT_EDGE",
            "BOTTOM_LEFT",
            "BOTTOM_RIGHT",
            "RETRACTED",
            "WORKING",
            "IDLE_POT",
        ]
        .into_iter()
        .enumerate()
        {
            poses.insert(name.into(), json!([i * 2, 0, 2, 2]));
        }
        let mut metadata = json!({"id":id, "version":1, "poses":poses});
        save(&source.join("pack.json"), &metadata).unwrap();
        let sprite = |color: u8| {
            let mut image = image::RgbaImage::new(18, 2);
            for x in (0..18).step_by(2) {
                image.put_pixel(x, 0, image::Rgba([color, 30, 50, 255]));
            }
            let mut bytes = std::io::Cursor::new(Vec::new());
            image.write_to(&mut bytes, image::ImageFormat::Png).unwrap();
            bytes.into_inner()
        };
        let first = sprite(10);
        fs::write(source.join("poses.png"), &first).unwrap();
        let (_, original) = import_edge_pack(&source, &packs, id).unwrap();
        let manifest = fs::read(installed.join("pack.json")).unwrap();
        fs::write(installed.join("author-license.txt"), b"personal-use only").unwrap();
        let check_original = || {
            assert_eq!(
                fs::read(installed.join("author-license.txt")).unwrap(),
                b"personal-use only"
            );
            assert_eq!(fs::read(installed.join("poses.png")).unwrap(), first);
            assert_eq!(fs::read(installed.join("pack.json")).unwrap(), manifest);
            assert_eq!(read_edge_pack(&installed, id).unwrap().1, original);
        };
        let second = sprite(100);
        fs::write(source.join("poses.png"), &second).unwrap();
        metadata["extras"] = json!({"tail":{"rect":[0,0,2,2]}});
        save(&source.join("pack.json"), &metadata).unwrap();
        assert!(import_edge_pack(&source, &packs, id)
            .err()
            .unwrap()
            .contains("tail.png"));
        check_original();
        metadata.as_object_mut().unwrap().remove("extras");
        save(&source.join("pack.json"), &metadata).unwrap();
        fs::write(source.join("poses.png"), b"broken PNG").unwrap();
        assert!(import_edge_pack(&source, &packs, id)
            .err()
            .unwrap()
            .contains("PNG"));
        check_original();
        fs::write(source.join("poses.png"), &second).unwrap();
        metadata["sha256"] = json!("incorrect-source-checksum");
        save(&source.join("pack.json"), &metadata).unwrap();
        assert!(import_edge_pack(&source, &packs, id)
            .err()
            .unwrap()
            .contains("身份已变化"));
        check_original();
        metadata.as_object_mut().unwrap().remove("sha256");
        save(&source.join("pack.json"), &metadata).unwrap();
        metadata["poses"]["LEFT_EDGE"] = json!([0, 1, 2, 1]);
        save(&source.join("pack.json"), &metadata).unwrap();
        assert!(import_edge_pack(&source, &packs, id)
            .err()
            .unwrap()
            .contains("LEFT_EDGE 姿态区域没有可见像素"));
        check_original();
        metadata["poses"]["LEFT_EDGE"] = json!([4, 0, 2, 2]);
        save(&source.join("pack.json"), &metadata).unwrap();
        let (_, replacement) = import_edge_pack(&source, &packs, id).unwrap();
        assert_ne!(replacement, original);
        assert_eq!(
            fs::read(installed.join("author-license.txt")).unwrap(),
            b"personal-use only"
        );
        assert_eq!(read_edge_pack(&installed, id).unwrap().1, replacement);
        assert_eq!(fs::read(source.join("poses.png")).unwrap(), second);
        assert_eq!(fs::read_dir(&packs).unwrap().count(), 1);
        assert!(read_edge_pack(&installed, "different-fixture")
            .err()
            .unwrap()
            .contains("不属于当前角色"));
        fs::remove_dir_all(root).unwrap();
    }
}

fn edge_pack(app: &tauri::AppHandle, id: &str) -> Result<Value, String> {
    let root = data(app)?.join("edge-packs").join(id);
    let state = app.state::<pet_native::PetState>();
    if !id_ok(id) || !root.join("pack.json").exists() {
        state.edge.lock().unwrap().pack = None;
        return Ok(json!({"status":"pending"}));
    }
    match read_edge_pack(&root, id) {
        Ok((pack, payload)) => {
            state.edge.lock().unwrap().pack = Some(pack);
            Ok(payload)
        }
        Err(error) => {
            state.edge.lock().unwrap().pack = None;
            Ok(json!({"status":"invalid","error":error}))
        }
    }
}

fn import_edge_pack(
    source: &Path,
    packs: &Path,
    id: &str,
) -> Result<(pet_edge::Pack, Value), String> {
    use std::os::unix::fs::DirBuilderExt;
    let mut metadata: Value =
        serde_json::from_slice(&fs::read(source.join("pack.json")).map_err(|_| "缺少姿态配置")?)
            .map_err(|_| "姿态配置无效")?;
    let work = packs.join(format!(".import-{}", uuid::Uuid::new_v4()));
    let candidate = work.join("candidate");
    fs::DirBuilder::new()
        .recursive(true)
        .mode(0o700)
        .create(&candidate)
        .map_err(|e| e.to_string())?;
    let target = packs.join(id);
    let mut preserve_backup = false;
    let result = (|| {
        for name in ["poses", "comic", "tail"] {
            if name != "poses" && !metadata["extras"][name].is_object() {
                continue;
            }
            let filename = format!("{name}.png");
            let origin = source.join(&filename);
            let info =
                fs::symlink_metadata(&origin).map_err(|_| format!("姿态文件缺失：{filename}"))?;
            if !info.is_file() || info.len() > 16 * 1024 * 1024 {
                return Err(format!("姿态必须是小于 16 MB 的普通文件：{filename}"));
            }
            let bytes = fs::read(origin).map_err(|e| e.to_string())?;
            let mut file = fs::OpenOptions::new()
                .write(true)
                .create_new(true)
                .mode(0o600)
                .open(candidate.join(filename))
                .map_err(|e| e.to_string())?;
            file.write_all(&bytes).map_err(|e| e.to_string())?;
            if name == "poses" && metadata.get("sha256").is_none() {
                metadata["sha256"] = json!(format!("{:x}", Sha256::digest(&bytes)));
            }
        }
        save(&candidate.join("pack.json"), &metadata)?;
        let ready = read_edge_pack(&candidate, id)?;
        fs::DirBuilder::new()
            .recursive(true)
            .mode(0o700)
            .create(&target)
            .map_err(|e| e.to_string())?;
        fs::set_permissions(&target, fs::Permissions::from_mode(0o700))
            .map_err(|e| e.to_string())?;
        let files: Vec<_> = ["poses.png", "comic.png", "tail.png", "pack.json"]
            .into_iter()
            .filter(|name| candidate.join(name).exists())
            .collect();
        // Replace only managed files. Keep source art, license notes and other user files in place.
        for name in &files {
            match fs::hard_link(target.join(name), work.join(name)) {
                Ok(()) => (),
                Err(e) if e.kind() == std::io::ErrorKind::NotFound => (),
                Err(e) => return Err(e.to_string()),
            }
        }
        for (index, name) in files.iter().enumerate() {
            if let Err(error) = fs::rename(candidate.join(name), target.join(name)) {
                for old in files[..index].iter().rev() {
                    let backup = work.join(old);
                    let restore = if backup.symlink_metadata().is_ok() {
                        fs::rename(backup, target.join(old))
                    } else {
                        fs::remove_file(target.join(old))
                    };
                    if restore.is_err() {
                        preserve_backup = true;
                    }
                }
                return Err(if preserve_backup {
                    format!(
                        "导入失败（{error}），未能完全恢复，原文件保存在 {}",
                        work.display()
                    )
                } else {
                    error.to_string()
                });
            }
        }
        Ok(ready)
    })();
    if !preserve_backup {
        let _ = fs::remove_dir_all(work);
    }
    result
}

fn read_edge_pack(root: &Path, id: &str) -> Result<(pet_edge::Pack, Value), String> {
    let metadata = private_json(&root.join("pack.json"))?;
    if metadata["id"] != id || metadata["version"] != 1 {
        return Err("姿态包不属于当前角色，或版本不受支持".into());
    }
    let file = root.join("poses.png");
    let info = fs::symlink_metadata(&file).map_err(|_| "姿态文件缺失")?;
    if !info.is_file()
        || info.uid() != unsafe { libc::getuid() }
        || info.mode() & 0o077 != 0
        || info.len() > 16 * 1024 * 1024
    {
        return Err("姿态文件权限无效".into());
    }
    let bytes = fs::read(&file).map_err(|_| "姿态文件不可读")?;
    if metadata["sha256"] != format!("{:x}", Sha256::digest(&bytes)) {
        return Err("姿态包身份已变化，请重新导入".into());
    }
    let im = image::load_from_memory(&bytes)
        .map_err(|_| "姿态 PNG 无效")?
        .into_rgba8();
    let (w, h) = im.dimensions();
    if w > 4096 || h > 4096 || w == 0 || h == 0 {
        return Err("姿态尺寸无效".into());
    }
    let alpha = im.pixels().map(|p| p.0[3]).collect::<Vec<_>>();
    if !alpha.contains(&0) {
        return Err("姿态缺少真实 Alpha".into());
    }
    let names = [
        "TOP_LEFT",
        "TOP_RIGHT",
        "LEFT_EDGE",
        "RIGHT_EDGE",
        "BOTTOM_LEFT",
        "BOTTOM_RIGHT",
        "RETRACTED",
        "WORKING",
        "IDLE_POT",
    ];
    let mut rects = vec![];
    for name in names {
        rects.push(visible_rect(&metadata["poses"][name], w, h, &alpha, name)?);
    }
    let mut extras = HashMap::new();
    let mut extra_payload = serde_json::Map::new();
    for name in ["comic", "tail"] {
        if metadata["extras"][name].is_object() {
            let file = root.join(format!("{name}.png"));
            let inf = fs::symlink_metadata(&file).map_err(|_| "补充姿态文件缺失")?;
            if !inf.is_file()
                || inf.uid() != unsafe { libc::getuid() }
                || inf.mode() & 0o077 != 0
                || inf.len() > 16 * 1024 * 1024
            {
                return Err("补充姿态权限无效".into());
            }
            let raw = fs::read(file).map_err(|_| "补充姿态不可读")?;
            if metadata["extras"][name]["sha256"] != format!("{:x}", Sha256::digest(&raw)) {
                return Err("补充姿态身份已变更".into());
            }
            let reader = image::ImageReader::new(std::io::Cursor::new(&raw))
                .with_guessed_format()
                .map_err(|_| "补充姿态格式无效")?;
            let (ew, eh) = reader.into_dimensions().map_err(|_| "补充姿态尺寸无效")?;
            if ew == 0 || eh == 0 || ew > 4096 || eh > 4096 {
                return Err("补充姿态过大".into());
            }
            let rgba = image::load_from_memory(&raw)
                .map_err(|_| "补充姿态无法解码")?
                .into_rgba8();
            let alpha = rgba.pixels().map(|p| p.0[3]).collect::<Vec<_>>();
            if !alpha.contains(&0) {
                return Err("补充姿态缺少真实透明区域".into());
            }
            let rect = visible_rect(&metadata["extras"][name]["rect"], ew, eh, &alpha, name)?;
            extras.insert(
                name.into(),
                pet_edge::Extra {
                    sprite: Sprite {
                        width: ew,
                        height: eh,
                        alpha,
                    },
                    rect,
                },
            );
            extra_payload.insert(name.into(),json!({"width":ew,"height":eh,"rect":rect,"url":format!("data:image/png;base64,{}",base64::engine::general_purpose::STANDARD.encode(raw))}));
        }
    }
    let contact = [
        metadata["presentation"]["gripContactX"][0]
            .as_f64()
            .unwrap_or(0.045)
            .clamp(0.0, 0.2),
        metadata["presentation"]["gripContactX"][1]
            .as_f64()
            .unwrap_or(0.955)
            .clamp(0.8, 1.0),
    ];
    let pack = pet_edge::Pack {
        sprite: Sprite {
            width: w,
            height: h,
            alpha,
        },
        rects,
        identity: id.into(),
        contact,
        extras,
    };
    Ok((
        pack,
        json!({"status":"ready","width":w,"height":h,"url":format!("data:image/png;base64,{}",base64::engine::general_purpose::STANDARD.encode(bytes)),"extras":extra_payload,"presentation":metadata["presentation"]}),
    ))
}

fn visible_rect(
    value: &Value,
    width: u32,
    height: u32,
    alpha: &[u8],
    name: &str,
) -> Result<[u32; 4], String> {
    let rect: [u32; 4] =
        serde_json::from_value(value.clone()).map_err(|_| format!("{name} 姿态边界无效"))?;
    let [x, y, w, h] = rect;
    if w == 0
        || h == 0
        || x.checked_add(w).is_none_or(|right| right > width)
        || y.checked_add(h).is_none_or(|bottom| bottom > height)
    {
        return Err(format!("{name} 姿态越界"));
    }
    if !(y..y + h).any(|row| {
        let start = (row * width + x) as usize;
        alpha[start..start + w as usize]
            .iter()
            .any(|pixel| *pixel > HIT_ALPHA)
    }) {
        return Err(format!("{name} 姿态区域没有可见像素"));
    }
    Ok(rect)
}
