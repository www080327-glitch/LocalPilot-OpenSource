//! Personal import only. Third-party character bytes never enter the APP.
use super::*;
use base64::Engine;
use sha2::{Digest, Sha256};
use std::io::Write;

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
fn decode(bytes: &[u8]) -> Result<Atlas, String> {
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
            if *a > 24 {
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
    let allowed = [
        "deepseek-whale-maid-chibi-v4",
        "chatgpt-white-dragon-chibi-v5",
        "claude-orange-scholar-chibi-v3",
        "gemini-star-cat-chibi-v1",
        "grok-gothic-chibi-v1",
        "kimi-moon-maid-chibi-v2",
        "qwen-chibi-scholar-v3",
        "zhipu-chibi-tech-v2",
    ];
    if action == "import_edge" {
        let meta = private_json(&data(&app)?.join("pet-asset-v1.json"))?;
        let identity = meta["id"]
            .as_str()
            .filter(|id| allowed.contains(id))
            .ok_or("请先选择本机角色")?;
        let folder = rfd::AsyncFileDialog::new()
            .set_title("导入该角色的个人探头姿态包（pack.json 与 poses.png）")
            .pick_folder()
            .await;
        let Some(folder) = folder else {
            return Ok(json!({"cancelled":true}));
        };
        let metadata: Value = serde_json::from_slice(
            &fs::read(folder.path().join("pack.json")).map_err(|_| "缺少姿态配置")?,
        )
        .map_err(|_| "姿态配置无效")?;
        if metadata["id"] != identity || metadata["version"] != 1 {
            return Err("姿态包不属于当前角色".into());
        }
        let source = folder.path().join("poses.png");
        let info = fs::symlink_metadata(&source).map_err(|_| "姿态图片不可读")?;
        if !info.is_file() || info.len() > 16 * 1024 * 1024 {
            return Err("姿态必须是小于 16 MB 的普通 PNG 文件".into());
        }
        let bytes = fs::read(source).map_err(|_| "姿态不可读")?;
        let root = data(&app)?.join("edge-packs").join(identity);
        fs::create_dir_all(&root).map_err(|e| e.to_string())?;
        fs::set_permissions(&root, fs::Permissions::from_mode(0o700)).map_err(|e| e.to_string())?;
        let target = root.join("poses.png");
        let mut f = fs::OpenOptions::new()
            .write(true)
            .create(true)
            .truncate(true)
            .mode(0o600)
            .custom_flags(libc::O_NOFOLLOW)
            .open(target)
            .map_err(|e| e.to_string())?;
        f.write_all(&bytes).map_err(|e| e.to_string())?;
        for name in ["comic", "tail"] {
            if metadata["extras"][name].is_object() {
                let source = folder.path().join(format!("{name}.png"));
                let inf = fs::symlink_metadata(&source).map_err(|_| "补充姿态缺失")?;
                if !inf.is_file() || inf.len() > 16 * 1024 * 1024 {
                    return Err("补充姿态文件无效".into());
                }
                let bytes = fs::read(source).map_err(|_| "补充姿态不可读")?;
                let target = root.join(format!("{name}.png"));
                let mut f = fs::OpenOptions::new()
                    .write(true)
                    .create(true)
                    .truncate(true)
                    .mode(0o600)
                    .custom_flags(libc::O_NOFOLLOW)
                    .open(target)
                    .map_err(|e| e.to_string())?;
                f.write_all(&bytes).map_err(|e| e.to_string())?;
            }
        }
        let mut metadata = metadata;
        metadata["sha256"] = json!(format!("{:x}", Sha256::digest(&bytes)));
        save(&root.join("pack.json"), &metadata)?;
        let edge = edge_pack(&app, identity)?;
        app.emit("pet-edge-asset", &edge)
            .map_err(|e| e.to_string())?;
        return Ok(edge);
    }
    if action == "catalog" {
        let items: Vec<Value> = allowed
            .iter()
            .filter_map(|id| {
                let meta: Value =
                    serde_json::from_slice(&fs::read(library.join(id).join("pet.json")).ok()?)
                        .ok()?;
                if meta["id"] != *id
                    || meta["spriteVersionNumber"] != 2
                    || !library.join(id).join("spritesheet.webp").is_file()
                {
                    return None;
                }
                Some(json!({"id":id,"label":meta["displayName"]}))
            })
            .collect();
        return Ok(
            json!({"items":items,"usage":"personal_local_import","redistribution":"not_granted"}),
        );
    }
    let target = data(&app)?.join("pet-sprite.webp");
    if action == "import" || action == "select_local" {
        let selected;
        let chosen_path = if action == "select_local" {
            let id = id
                .as_deref()
                .filter(|id| allowed.contains(id))
                .ok_or("角色身份无效")?;
            library.join(id).join("spritesheet.webp")
        } else {
            let chosen = rfd::AsyncFileDialog::new()
                .set_title("导入有权个人使用的同系列 DeepSeek 娘图集")
                .add_filter("透明 WebP 图集", &["webp"])
                .pick_file()
                .await;
            let Some(chosen) = chosen else {
                return Ok(json!({"cancelled":true}));
            };
            selected = chosen;
            selected.path().to_path_buf()
        };
        let id = allowed
            .iter()
            .find(|id| chosen_path == library.join(id).join("spritesheet.webp"))
            .map(|id| (*id).to_string());
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
            &json!({"version":1,"sha256":format!("{:x}",Sha256::digest(&bytes)),"usage":"personal_import","redistribution":"not_granted","id":id,"label":id.as_deref().and_then(|id| fs::read(library.join(id).join("pet.json")).ok()).and_then(|b| serde_json::from_slice::<Value>(&b).ok()).and_then(|m| m["displayName"].as_str().map(String::from)).unwrap_or_else(||"个人角色".into())}),
        )?;
    } else if action != "load" {
        return Err("未知素材操作".into());
    }
    if !target.exists() {
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
}

fn edge_pack(app: &tauri::AppHandle, id: &str) -> Result<Value, String> {
    if !id_ok(id) {
        return Ok(json!({"status":"pending"}));
    }
    let root = data(app)?.join("edge-packs").join(id);
    if !root.join("pack.json").exists() {
        app.state::<pet_native::PetState>()
            .edge
            .lock()
            .unwrap()
            .pack = None;
        return Ok(json!({"status":"pending"}));
    }
    let metadata = private_json(&root.join("pack.json"))?;
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
        let r: &Value = &metadata["poses"][name];
        let r: [u32; 4] = serde_json::from_value(r.clone()).map_err(|_| "姿态边界无效")?;
        if r[2] == 0
            || r[3] == 0
            || r[0].checked_add(r[2]).is_none_or(|x| x > w)
            || r[1].checked_add(r[3]).is_none_or(|y| y > h)
        {
            return Err("姿态越界".into());
        }
        rects.push(r);
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
            let rect: [u32; 4] = serde_json::from_value(metadata["extras"][name]["rect"].clone())
                .map_err(|_| "补充姿态边界无效")?;
            if rect[2] == 0
                || rect[3] == 0
                || rect[0].checked_add(rect[2]).is_none_or(|x| x > ew)
                || rect[1].checked_add(rect[3]).is_none_or(|y| y > eh)
            {
                return Err("补充姿态越界".into());
            }
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
    app.state::<pet_native::PetState>()
        .edge
        .lock()
        .unwrap()
        .pack = Some(pet_edge::Pack {
        sprite: Sprite {
            width: w,
            height: h,
            alpha,
        },
        rects,
        identity: id.into(),
        contact,
        extras,
    });
    Ok(
        json!({"status":"ready","width":w,"height":h,"url":format!("data:image/png;base64,{}",base64::engine::general_purpose::STANDARD.encode(bytes)),"extras":extra_payload,"presentation":metadata["presentation"]}),
    )
}
