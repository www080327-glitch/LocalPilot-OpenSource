//! Small-window edge presentation. This module never submits or approves tasks.
use super::*;
use serde::{Deserialize, Serialize};
use std::sync::atomic::Ordering;
use std::time::Instant;

#[derive(Clone, Copy, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "SCREAMING_SNAKE_CASE")]
pub enum Anchor {
    TopLeft,
    TopRight,
    LeftEdge,
    RightEdge,
    BottomLeft,
    BottomRight,
}
pub const VIEW_W: f64 = 240.0;
pub const VIEW_H: f64 = 220.0;
pub const ANIMATION_FPS: u64 = 30;
pub const ANCHORS: [Anchor; 6] = [
    Anchor::TopLeft,
    Anchor::TopRight,
    Anchor::LeftEdge,
    Anchor::RightEdge,
    Anchor::BottomLeft,
    Anchor::BottomRight,
];
#[derive(Clone, Copy, Debug, PartialEq, Eq, Serialize)]
#[serde(rename_all = "SCREAMING_SNAKE_CASE")]
pub enum Mode {
    Hidden,
    Peeking,
    IdleEdge,
    Retracting,
    Relocating,
    Dragging,
    ChatOpen,
    Working,
    Celebrating,
    IdlePot,
}
#[derive(Clone, Copy, Debug, PartialEq, Eq, Serialize)]
#[serde(rename_all = "UPPERCASE")]
#[cfg_attr(not(target_os = "macos"), allow(dead_code))]
pub enum Direction {
    Left,
    Right,
    Up,
    Down,
}
#[cfg(any(target_os = "macos", test))]
pub fn direction(dx: f64, dy: f64) -> Direction {
    if dx.abs() >= dy.abs() {
        if dx < 0.0 {
            Direction::Left
        } else {
            Direction::Right
        }
    } else if dy > 0.0 {
        Direction::Up
    } else {
        Direction::Down
    } // AppKit Y grows upwards.
}
pub fn origin(a: Anchor, area: (i32, i32, u32, u32), size: (u32, u32), offset: f64) -> (i32, i32) {
    let (x, y, w, h) = area;
    let (pw, ph) = size;
    let right = x + w.saturating_sub(pw) as i32;
    let bottom = y + h.saturating_sub(ph) as i32;
    let middle = y + ((h.saturating_sub(ph)) as f64 * offset.clamp(0.0, 1.0)) as i32;
    match a {
        Anchor::TopLeft => (x, y),
        Anchor::TopRight => (right, y),
        Anchor::LeftEdge => (x, middle),
        Anchor::RightEdge => (right, middle),
        Anchor::BottomLeft => (x, bottom),
        Anchor::BottomRight => (right, bottom),
    }
}
pub struct Extra {
    #[cfg_attr(not(target_os = "macos"), allow(dead_code))]
    pub sprite: pet_assets::Sprite,
    pub rect: [u32; 4],
}
pub struct Pack {
    #[cfg_attr(not(target_os = "macos"), allow(dead_code))]
    pub sprite: pet_assets::Sprite,
    pub rects: Vec<[u32; 4]>,
    pub identity: String,
    pub contact: [f64; 2],
    pub extras: HashMap<String, Extra>,
}
#[derive(Clone, PartialEq, Serialize)]
pub struct RenderPart {
    pub source: &'static str,
    pub rect: [u32; 4],
    #[serde(rename = "box")]
    pub bounds: [f64; 4],
    pub opacity: f64,
    pub angle: f64,
}
#[derive(Clone, PartialEq, Serialize)]
pub struct Render {
    #[serde(flatten)]
    pub part: RenderPart,
    pub clip: [f64; 4],
    pub frame: [u32; 2],
    pub tail: Option<RenderPart>,
    pub water: f64,
    pub pose_index: usize,
    pub pose_name: &'static str,
}
#[derive(Clone, PartialEq, Serialize)]
pub struct Presentation {
    pub anchor: Anchor,
    pub mode: Mode,
    pub direction: Direction,
    pub reveal: f64,
    pub stage: &'static str,
    pub relocations: u32,
    pub render: Render,
    pub chat_box: [f64; 4],
    pub viewport: [f64; 2],
    pub phase: f64,
    pub mini_visible: bool,
    pub mini_glass: bool,
    pub thought_left: bool,
    pub thought_up: bool,
    pub activity: String,
    pub motion: bool,
    pub drag_history: Vec<Value>,
    pub placements: Vec<Value>,
}
pub struct EdgeState {
    pub anchor: Anchor,
    pub mode: Mode,
    pub direction: Direction,
    pub reveal: f64,
    pub phase: f64,
    pub motion: bool,
    pub layout_dirty: bool,
    pub offset: f64,
    pub target: Option<Anchor>,
    pub since: Instant,
    pub touched: Instant,
    pub relocations: u32,
    pub pack: Option<Pack>,
    pub activity: String,
    pub last_sent: Option<Presentation>,
    pub drag_history: Vec<Value>,
    pub placements: Vec<Value>,
}
impl Default for EdgeState {
    fn default() -> Self {
        Self {
            anchor: Anchor::BottomRight,
            mode: Mode::IdleEdge,
            direction: Direction::Left,
            reveal: 1.0,
            phase: 1.0,
            motion: true,
            layout_dirty: false,
            offset: 0.5,
            target: None,
            since: Instant::now(),
            touched: Instant::now(),
            relocations: 0,
            pack: None,
            activity: "idle".into(),
            last_sent: None,
            drag_history: vec![],
            placements: vec![],
        }
    }
}
pub fn chat_box(a: Anchor) -> [f64; 4] {
    match a {
        Anchor::TopLeft => [100.0, 112.0, 140.0, 104.0],
        Anchor::TopRight => [0.0, 112.0, 140.0, 104.0],
        Anchor::LeftEdge => [100.0, 0.0, 140.0, 104.0],
        Anchor::RightEdge => [0.0, 0.0, 140.0, 104.0],
        Anchor::BottomLeft => [100.0, 0.0, 140.0, 104.0],
        Anchor::BottomRight => [0.0, 0.0, 140.0, 104.0],
    }
}
fn left(a: Anchor) -> bool {
    matches!(a, Anchor::TopLeft | Anchor::LeftEdge | Anchor::BottomLeft)
}
fn bottom(a: Anchor) -> bool {
    matches!(a, Anchor::BottomLeft | Anchor::BottomRight)
}
fn top(a: Anchor) -> bool {
    matches!(a, Anchor::TopLeft | Anchor::TopRight)
}
#[cfg(target_os = "macos")]
pub fn is_chat(app: &tauri::AppHandle, x: f64, y: f64) -> bool {
    let state = app.state::<pet_native::PetState>();
    let e = state.edge.lock().unwrap();
    if e.mode == Mode::ChatOpen {
        return false;
    }
    thought_hit(e.anchor, x, y)
}
#[cfg(any(target_os = "macos", test))]
fn thought_hit(anchor: Anchor, x: f64, y: f64) -> bool {
    let [bx, by, _, _] = chat_box(anchor);
    let mut x = x - bx;
    let mut y = y - by;
    if left(anchor) {
        x = 140.0 - x;
    }
    if top(anchor) {
        y = 104.0 - y;
    }
    ((x - 70.0) / 68.0).powi(2) + ((y - 38.0) / 36.0).powi(2) <= 1.0
        || (x - 99.0).hypot(y - 87.0) <= 6.0
        || (x - 116.0).hypot(y - 99.0) <= 3.5
}
fn ease_out(t: f64) -> f64 {
    1.0 - (1.0 - t.clamp(0.0, 1.0)).powi(3)
}
fn smooth(t: f64) -> f64 {
    let t = t.clamp(0.0, 1.0);
    t * t * (3.0 - 2.0 * t)
}
/// Grip contact, not transparent canvas bounds, is placed on the physical edge.
/// The bottom uses the comic portrait rather than a grasping-hand illustration.
fn render(e: &EdgeState, legacy: Option<&pet_assets::Atlas>) -> Render {
    let dragging = e.mode == Mode::Dragging;
    let frame = if dragging {
        match e.direction {
            Direction::Left => [
                if e.motion {
                    (e.since.elapsed().as_secs_f64() * ANIMATION_FPS as f64) as u32 % 8
                } else {
                    0
                },
                2,
            ],
            Direction::Right => [
                if e.motion {
                    (e.since.elapsed().as_secs_f64() * ANIMATION_FPS as f64) as u32 % 8
                } else {
                    0
                },
                1,
            ],
            Direction::Up => [0, 9],
            Direction::Down => [0, 10],
        }
    } else {
        [0, 0]
    };
    let index = match e.anchor {
        Anchor::TopLeft | Anchor::LeftEdge => 2,
        Anchor::TopRight | Anchor::RightEdge => 3,
        Anchor::BottomLeft => 4,
        Anchor::BottomRight => 5,
    };
    let comic = bottom(e.anchor)
        && !dragging
        && e.pack
            .as_ref()
            .is_some_and(|p| p.identity.starts_with("deepseek") && p.extras.contains_key("comic"));
    let source = if dragging {
        "legacy"
    } else if comic {
        "comic"
    } else {
        "edge"
    };
    let rect = if dragging {
        legacy.map(|s| s.frame_rect(frame[0], frame[1]))
    } else if comic {
        e.pack
            .as_ref()
            .and_then(|p| p.extras.get("comic"))
            .map(|p| p.rect)
    } else {
        e.pack.as_ref().and_then(|p| p.rects.get(index).copied())
    };
    let Some(rect) = rect else {
        return Render {
            part: RenderPart {
                source: "pending",
                opacity: 0.0,
                bounds: [0.0; 4],
                rect: [0, 0, 1, 1],
                angle: 0.0,
            },
            clip: [0.0, 0.0, VIEW_W, VIEW_H],
            frame,
            tail: None,
            water: 0.0,
            pose_index: index,
            pose_name: "PENDING",
        };
    };
    let (fw, fh) = (rect[2] as f64, rect[3] as f64);
    let scale = (174.0 / fw).min(164.0 / fh);
    let (w, h) = (fw * scale, fh * scale);
    let (mut x, mut y) = ((VIEW_W - w) / 2.0, VIEW_H - h);
    let mut angle = 0.0;
    if !dragging {
        if bottom(e.anchor) {
            x = if left(e.anchor) { 0.0 } else { VIEW_W - w };
            y = VIEW_H - h + 2.0;
        } else {
            let contact = e.pack.as_ref().map(|p| p.contact).unwrap_or([0.045, 0.955]);
            x = if left(e.anchor) {
                -contact[0] * w
            } else {
                VIEW_W - contact[1] * w
            };
            y = if top(e.anchor) {
                0.0
            } else {
                (VIEW_H - h) / 2.0
            };
        }
    }
    let mut opacity = 1.0;
    let mut tail = None;
    let mut water = 0.0;
    if e.mode == Mode::Hidden || e.mode == Mode::Relocating {
        opacity = 0.0;
    }
    if e.mode == Mode::Retracting {
        let t = e.phase;
        let sign = if left(e.anchor) { 1.0 } else { -1.0 };
        if bottom(e.anchor) {
            let anticipation = (t / 0.18).min(1.0);
            let dive = smooth((t - 0.18) / 0.65);
            y -= 6.0 * (std::f64::consts::PI * anticipation).sin();
            y += dive * (h + 20.0);
            x += sign * 10.0 * dive;
            angle = sign * 12.0 * (std::f64::consts::PI * dive).sin();
            let u = ((t - 0.60) / 0.40).clamp(0.0, 1.0);
            water = (std::f64::consts::PI * u).sin().max(0.0);
            if u > 0.0 && u < 1.0 {
                if let Some(p) = e.pack.as_ref().and_then(|p| p.extras.get("tail")) {
                    let r = p.rect;
                    let sc = (78.0 / r[2] as f64).min(65.0 / r[3] as f64);
                    let (tw, th) = (r[2] as f64 * sc, r[3] as f64 * sc);
                    tail = Some(RenderPart {
                        source: "tail",
                        rect: r,
                        bounds: [x + w / 2.0 - tw / 2.0, VIEW_H - th * water, tw, th],
                        angle: sign * (18.0 - 36.0 * u),
                        opacity: water,
                    });
                }
            }
        } else if top(e.anchor) {
            let u = smooth((t - 0.12) / 0.88);
            x -= sign * u * w * 0.72;
            y -= u * (h + 12.0);
            angle = -sign * 9.0 * (std::f64::consts::PI * u).sin();
        } else {
            let anticipate = 4.0 * (std::f64::consts::PI * (t / 0.18).min(1.0)).sin();
            x += sign * anticipate;
            x -= sign * smooth((t - 0.18) / 0.82) * (w + 12.0);
            angle = -sign * 7.0 * (std::f64::consts::PI * t).sin();
        }
    }
    if e.mode == Mode::Peeking {
        let u = ease_out(e.phase);
        let sign = if left(e.anchor) { 1.0 } else { -1.0 };
        if bottom(e.anchor) {
            y += (1.0 - u) * (h + 4.0);
        } else {
            x -= sign * (1.0 - u) * (w + 12.0);
            if top(e.anchor) {
                y -= 10.0 * (1.0 - u);
            }
        }
    }
    if !e.motion {
        angle = 0.0;
        tail = None;
        water = 0.0;
    }
    Render {
        part: RenderPart {
            source,
            rect,
            bounds: [x, y, w, h],
            opacity,
            angle,
        },
        clip: [0.0, 0.0, VIEW_W, VIEW_H],
        tail,
        water,
        frame,
        pose_index: index,
        pose_name: if dragging {
            "DIRECTIONAL_ATLAS"
        } else if comic {
            "COMIC_BOTTOM"
        } else if left(e.anchor) {
            "LEFT_EDGE_GRIP"
        } else {
            "RIGHT_EDGE_GRIP"
        },
    }
}
pub fn snapshot(app: &tauri::AppHandle) -> Presentation {
    let state = app.state::<pet_native::PetState>();
    let e = state.edge.lock().unwrap();
    let sprite = state.sprite.lock().unwrap();
    Presentation {
        anchor: e.anchor,
        mode: e.mode,
        direction: e.direction,
        reveal: e.reveal,
        stage: if e.reveal < 0.22 {
            "AHOGE"
        } else if e.reveal < 0.62 {
            "EYES"
        } else {
            "HEAD_AND_HANDS"
        },
        relocations: e.relocations,
        render: render(&e, sprite.as_ref()),
        chat_box: chat_box(e.anchor),
        viewport: [VIEW_W, VIEW_H],
        phase: e.phase,
        mini_visible: e.mode != Mode::ChatOpen,
        mini_glass: state.mini_glass.load(Ordering::Relaxed),
        thought_left: left(e.anchor),
        thought_up: top(e.anchor),
        activity: e.activity.clone(),
        motion: e.motion,
        drag_history: e.drag_history.clone(),
        placements: e.placements.clone(),
    }
}
#[cfg(target_os = "macos")]
pub fn hit(app: &tauri::AppHandle, x: f64, y: f64) -> bool {
    if is_chat(app, x, y) {
        return true;
    }
    let state = app.state::<pet_native::PetState>();
    let e = state.edge.lock().unwrap();
    let sprite = state.sprite.lock().unwrap();
    let v = render(&e, sprite.as_ref());
    let s = match v.part.source {
        "legacy" => sprite.as_ref().map(|atlas| &atlas.sprite),
        "edge" => e.pack.as_ref().map(|p| &p.sprite),
        name => e
            .pack
            .as_ref()
            .and_then(|p| p.extras.get(name))
            .map(|p| &p.sprite),
    };
    s.is_some_and(|s| sprite_hit(&v, s, x, y))
}
#[cfg(any(target_os = "macos", test))]
fn sprite_hit(v: &Render, s: &pet_assets::Sprite, x: f64, y: f64) -> bool {
    if v.part.opacity == 0.0 {
        return false;
    }
    let c = v.clip;
    if x < c[0] || y < c[1] || x >= c[0] + c[2] || y >= c[1] + c[3] {
        return false;
    }
    let b = v.part.bounds;
    let r = v.part.rect;
    let angle = -v.part.angle.to_radians();
    let (cx, cy) = (b[0] + b[2] / 2.0, b[1] + b[3] / 2.0);
    let (dx, dy) = (x - cx, y - cy);
    let (x, y) = (
        cx + dx * angle.cos() - dy * angle.sin(),
        cy + dx * angle.sin() + dy * angle.cos(),
    );
    if b[2] <= 0.0 || b[3] <= 0.0 || x < b[0] || y < b[1] || x >= b[0] + b[2] || y >= b[1] + b[3] {
        return false;
    }
    let px = (r[0] as f64 + (x - b[0]) / b[2] * r[2] as f64) as u32;
    let py = (r[1] as f64 + (y - b[1]) / b[3] * r[3] as f64) as u32;
    px < s.width && py < s.height && s.alpha[(py * s.width + px) as usize] > pet_assets::HIT_ALPHA
}
fn place(app: &tauri::AppHandle) -> Result<(), String> {
    let w = app.get_webview_window("pet").ok_or("宠物未开启")?;
    let Some(m) = w
        .current_monitor()
        .map_err(|e| e.to_string())?
        .or(w.primary_monitor().map_err(|e| e.to_string())?)
    else {
        return Ok(());
    };
    let a = m.work_area();
    let size = w.outer_size().map_err(|e| e.to_string())?;
    let state = app.state::<pet_native::PetState>();
    let e = state.edge.lock().unwrap();
    let (x, y) = origin(
        e.anchor,
        (a.position.x, a.position.y, a.size.width, a.size.height),
        (size.width, size.height),
        e.offset,
    );
    drop(e);
    w.set_position(tauri::PhysicalPosition::new(x, y))
        .map_err(|e| e.to_string())?;
    let _ = pet_native::follow(app);
    Ok(())
}
pub fn resized(app: &tauri::AppHandle) {
    app.state::<pet_native::PetState>()
        .edge
        .lock()
        .unwrap()
        .layout_dirty = true;
}
pub fn record_moved(app: &tauri::AppHandle, p: tauri::PhysicalPosition<i32>) {
    let state = app.state::<pet_native::PetState>();
    if state.restoring.load(Ordering::Relaxed) {
        return;
    }
    let Some(w) = app.get_webview_window("pet") else {
        return;
    };
    let Ok(z) = w.outer_size() else {
        return;
    };
    let mut e = state.edge.lock().unwrap();
    if e.mode == Mode::Dragging {
        return;
    }
    let anchor = e.anchor;
    if e.placements.len() >= 64 {
        e.placements.remove(0);
    }
    e.placements.push(json!({"event":"native_window_moved","anchor_state":anchor,"physical_x":p.x,"physical_y":p.y,"width":z.width,"height":z.height}));
}
pub fn persist(app: &tauri::AppHandle) -> Result<(), String> {
    let state = app.state::<pet_native::PetState>();
    let e = state.edge.lock().unwrap();
    save(
        &data(app)?.join("pet-edge-v1.json"),
        &json!({"version":1,"anchor":e.anchor,"offset":e.offset}),
    )
}
pub fn initialize(app: &tauri::AppHandle) -> Result<(), String> {
    if let Ok(v) = private_json(&data(app)?.join("pet-edge-v1.json")) {
        if let Ok(a) = serde_json::from_value(v["anchor"].clone()) {
            let state = app.state::<pet_native::PetState>();
            let mut e = state.edge.lock().unwrap();
            e.anchor = a;
            e.offset = v["offset"].as_f64().unwrap_or(0.5).clamp(0.0, 1.0);
        }
    }
    place(app)?;
    persist(app)
}
#[cfg(target_os = "macos")]
pub fn drag(app: &tauri::AppHandle, dx: f64, dy: f64) {
    let state = app.state::<pet_native::PetState>();
    let mut e = state.edge.lock().unwrap();
    let d = direction(dx, dy);
    if e.mode != Mode::Dragging {
        e.since = Instant::now();
    }
    e.mode = Mode::Dragging;
    e.direction = d;
    e.target = None;
    e.reveal = 1.0;
    e.touched = Instant::now();
    if e.drag_history.len() > 80 {
        e.drag_history.remove(0);
    }
    if e.drag_history
        .last()
        .is_none_or(|v| v["direction"] != serde_json::to_value(d).unwrap())
    {
        e.drag_history.push(json!({"direction":d,"dx":dx,"dy":dy,"row":match d {Direction::Left=>2,Direction::Right=>1,Direction::Up=>9,Direction::Down=>10}}));
    }
}
#[cfg(target_os = "macos")]
pub fn end_drag(app: &tauri::AppHandle) {
    let state = app.state::<pet_native::PetState>();
    let mut e = state.edge.lock().unwrap();
    e.since = Instant::now();
    e.touched = Instant::now();
    if let Some(w) = app.get_webview_window("pet") {
        if let (Ok(p), Ok(z), Ok(Some(m))) =
            (w.outer_position(), w.outer_size(), w.current_monitor())
        {
            let a = m.work_area();
            let area = (a.position.x, a.position.y, a.size.width, a.size.height);
            e.anchor = *ANCHORS
                .iter()
                .min_by_key(|anchor| {
                    let (x, y) = origin(**anchor, area, (z.width, z.height), 0.5);
                    let dx = p.x as i64 - x as i64;
                    let dy = p.y as i64 - y as i64;
                    dx * dx + dy * dy
                })
                .unwrap();
            if matches!(e.anchor, Anchor::LeftEdge | Anchor::RightEdge) {
                e.offset = ((p.y - a.position.y) as f64
                    / (a.size.height.saturating_sub(z.height).max(1)) as f64)
                    .clamp(0.08, 0.92);
            }
        }
    }
    drop(e);
    let _ = persist(app);
}
pub fn chat(app: &tauri::AppHandle, value: bool) {
    let state = app.state::<pet_native::PetState>();
    let mut e = state.edge.lock().unwrap();
    if value {
        e.mode = Mode::ChatOpen;
        e.target = None;
        e.reveal = 1.0;
    } else if e.mode == Mode::ChatOpen {
        e.mode = if e.activity == "executing" || e.activity == "thinking" {
            Mode::Working
        } else {
            Mode::IdleEdge
        };
    }
    e.touched = Instant::now();
}
fn resting(activity: &str) -> Mode {
    if ["executing", "thinking"].contains(&activity) {
        Mode::Working
    } else if ["success", "reply"].contains(&activity) {
        Mode::Celebrating
    } else {
        Mode::IdleEdge
    }
}
pub fn activity(app: &tauri::AppHandle, value: &str) {
    let state = app.state::<pet_native::PetState>();
    let mut e = state.edge.lock().unwrap();
    e.activity = value.into();
    if !matches!(
        e.mode,
        Mode::Dragging
            | Mode::Retracting
            | Mode::Hidden
            | Mode::Relocating
            | Mode::Peeking
            | Mode::ChatOpen
    ) {
        e.mode = resting(value);
        e.since = Instant::now();
    }
}
pub fn relocate(app: &tauri::AppHandle, target: Option<Anchor>) -> Result<(), String> {
    let state = app.state::<pet_native::PetState>();
    if state.expanded.load(Ordering::Relaxed) {
        return Ok(());
    }
    let mut e = state.edge.lock().unwrap();
    if matches!(
        e.mode,
        Mode::Retracting | Mode::Hidden | Mode::Relocating | Mode::Peeking | Mode::Dragging
    ) {
        return Ok(());
    }
    if target == Some(e.anchor) {
        return Ok(());
    }
    e.target = Some(relocation_target(e.anchor, target));
    e.mode = Mode::Retracting;
    e.since = Instant::now();
    e.touched = Instant::now();
    Ok(())
}
fn relocation_target(current: Anchor, requested: Option<Anchor>) -> Anchor {
    if let Some(anchor) = requested {
        return anchor;
    }
    let alternatives = ANCHORS
        .iter()
        .copied()
        .filter(|a| left(*a) != left(current))
        .collect::<Vec<_>>();
    let n = uuid::Uuid::new_v4().as_u128() as usize;
    alternatives[n % alternatives.len()]
}
fn advance(e: &mut EdgeState, now: Instant, motion: bool, quiet: bool, dragging: bool) -> bool {
    e.motion = motion;
    let elapsed = now.duration_since(e.since).as_secs_f64() * 1000.0;
    let mut reposition = e.layout_dirty && !dragging;
    if reposition {
        e.layout_dirty = false;
    }
    if !motion
        && matches!(
            e.mode,
            Mode::Retracting | Mode::Hidden | Mode::Relocating | Mode::Peeking
        )
    {
        if let Some(anchor) = e.target.take() {
            e.anchor = anchor;
            e.offset = 0.5;
            e.relocations += 1;
        }
        e.mode = resting(&e.activity);
        e.phase = 1.0;
        e.reveal = 1.0;
        e.since = now;
        return true;
    }
    match e.mode {
        Mode::Retracting => {
            let t = (elapsed / 1150.0).min(1.0);
            e.phase = t;
            e.reveal = 1.0 - t * t * (3.0 - 2.0 * t);
            if t >= 1.0 {
                e.mode = Mode::Hidden;
                e.since = now;
            }
        }
        Mode::Hidden => {
            if elapsed >= 120.0 {
                e.mode = Mode::Relocating;
                e.reveal = 0.0;
            }
        }
        Mode::Relocating => {
            if let Some(a) = e.target.take() {
                e.anchor = a;
                e.offset = 0.5;
                e.relocations += 1;
            }
            e.mode = Mode::Peeking;
            e.phase = 0.0;
            e.since = now;
            reposition = true;
        }
        Mode::Peeking => {
            let t = (elapsed / 1350.0).min(1.0);
            e.phase = t;
            e.reveal = t * t * (3.0 - 2.0 * t);
            if t >= 1.0 {
                e.mode = resting(&e.activity);
                e.since = now;
            }
        }
        Mode::Dragging => {
            if !dragging && elapsed >= 850.0 {
                e.mode = resting(&e.activity);
                e.reveal = 1.0;
                reposition = true;
            }
        }
        Mode::Celebrating => {
            if elapsed > 1600.0 {
                e.mode = Mode::IdleEdge;
                e.activity = "idle".into();
            }
        }
        Mode::IdleEdge => {
            if now.duration_since(e.touched).as_secs() > 180 && !quiet && e.activity == "idle" {
                e.mode = Mode::IdlePot;
            }
        }
        _ => {}
    }
    reposition
}
pub fn tick(app: &tauri::AppHandle) {
    let state = app.state::<pet_native::PetState>();
    let prefs = state.settings.lock().unwrap().clone();
    let motion = prefs.animation
        && !prefs.quiet
        && !platform::reduce_motion()
        && !state.browser_reduce_motion.load(Ordering::Relaxed);
    let reposition = advance(
        &mut state.edge.lock().unwrap(),
        Instant::now(),
        motion,
        prefs.quiet,
        state.dragging.load(Ordering::Relaxed),
    );
    if reposition {
        let _ = place(app);
        let _ = persist(app);
    }
    let _ = super::pet_macos::thought_glass(app);
    let v = snapshot(app);
    *state.pose.lock().unwrap() = (v.render.frame[0], v.render.frame[1]);
    let mut e = state.edge.lock().unwrap();
    if e.last_sent.as_ref() != Some(&v) {
        e.last_sent = Some(v.clone());
        drop(e);
        let _ = app.emit_to("pet", "pet-edge", v);
    }
}
#[tauri::command]
pub async fn pet_edge(
    app: tauri::AppHandle,
    action: String,
    value: Option<Value>,
) -> Result<Value, String> {
    let (tx, rx) = tokio::sync::oneshot::channel();
    let handle = app.clone();
    app.run_on_main_thread(move || {
        let result = (|| {
            match action.as_str() {
                "state" => {}
                "relocate" => {
                    pet_native::expand(&handle, false, false)?;
                    relocate(&handle, None)?;
                }
                "anchor" => {
                    let a =
                        serde_json::from_value(value.ok_or("缺少边缘")?).map_err(|_| "边缘无效")?;
                    relocate(&handle, Some(a))?;
                }
                "chat" => {
                    let open = !handle
                        .state::<pet_native::PetState>()
                        .expanded
                        .load(Ordering::Relaxed);
                    pet_native::expand(&handle, open, open)?;
                }
                _ => return Err("未知边缘操作".into()),
            };
            Ok(json!(snapshot(&handle)))
        })();
        let _ = tx.send(result);
    })
    .map_err(|e| e.to_string())?;
    rx.await.map_err(|e| e.to_string())?
}

#[cfg(test)]
mod tests {
    use super::*;
    fn character() -> EdgeState {
        let mut e = EdgeState::default();
        e.pack = Some(Pack {
            sprite: pet_assets::Sprite {
                width: 4,
                height: 4,
                alpha: vec![255; 16],
            },
            rects: vec![[0, 0, 4, 4]; 9],
            identity: "deepseek-fixture".into(),
            contact: [0.045, 0.955],
            extras: HashMap::new(),
        });
        e
    }
    #[test]
    fn explicit_positions_keep_the_requested_side() {
        for current in ANCHORS {
            for target in ANCHORS {
                assert_eq!(relocation_target(current, Some(target)), target);
            }
            assert_ne!(left(relocation_target(current, None)), left(current));
        }
    }
    #[test]
    fn optional_comic_art_falls_back_to_the_imported_edge_pose() {
        let e = character();
        let pose = render(&e, None);
        assert_eq!(pose.part.source, "edge");
        assert_eq!(pose.part.opacity, 1.0);
        assert!(pose.part.bounds[2] > 0.0);
    }
    #[test]
    fn reduced_motion_relocation_has_no_dive_or_reveal_frames() {
        let mut e = character();
        e.mode = Mode::Retracting;
        e.target = Some(Anchor::TopRight);
        let now = e.since + Duration::from_millis(16);
        assert!(advance(&mut e, now, false, false, false));
        assert_eq!(e.anchor, Anchor::TopRight);
        assert_eq!(e.mode, Mode::IdleEdge);
        assert_eq!(e.phase, 1.0);
        assert!(e.target.is_none());
        let pose = render(&e, None);
        assert_eq!(pose.part.opacity, 1.0);
        assert_eq!(pose.part.angle, 0.0);
        assert!(pose.tail.is_none());
        assert_eq!(pose.water, 0.0);
    }
    #[test]
    fn animation_steps_follow_elapsed_time_and_finish_at_the_selected_anchor() {
        let mut e = character();
        e.mode = Mode::Retracting;
        e.target = Some(Anchor::LeftEdge);
        let start = e.since;
        let mut positions = Vec::new();
        for i in 0..100 {
            advance(
                &mut e,
                start + pet_native::ANIMATION_INTERVAL * i,
                true,
                false,
                false,
            );
            let pose = render(&e, None);
            if positions.last() != Some(&pose.part.bounds) {
                positions.push(pose.part.bounds);
            }
        }
        assert!(positions.len() > 60);
        assert_eq!(e.anchor, Anchor::LeftEdge);
        assert_eq!(e.mode, Mode::IdleEdge);
        assert_eq!(e.reveal, 1.0);
    }
    #[test]
    fn native_sprite_hit_uses_the_rendered_crop_transform_and_alpha() {
        let e = character();
        let mut pose = render(&e, None);
        pose.part.bounds = [10.0, 20.0, 40.0, 80.0];
        let mut sprite = pet_assets::Sprite {
            width: 4,
            height: 4,
            alpha: vec![255; 16],
        };
        sprite.alpha[0] = 0;
        assert!(!sprite_hit(&pose, &sprite, 15.0, 30.0));
        assert!(sprite_hit(&pose, &sprite, 25.0, 50.0));
        assert!(!sprite_hit(&pose, &sprite, 9.0, 50.0));
        pose.part.angle = 90.0;
        assert!(!sprite_hit(&pose, &sprite, 60.0, 45.0));
        assert!(sprite_hit(&pose, &sprite, 40.0, 55.0));
    }
    #[test]
    fn thought_bubble_hit_matches_visible_ellipse_and_dots() {
        for a in ANCHORS {
            let b = chat_box(a);
            let cy = if top(a) { 66.0 } else { 38.0 };
            assert!(thought_hit(a, b[0] + 70.0, b[1] + cy));
            assert!(!thought_hit(a, b[0], b[1]));
            let x = if left(a) { 24.0 } else { 116.0 };
            let y = if top(a) { 5.0 } else { 99.0 };
            assert!(thought_hit(a, b[0] + x, b[1] + y));
        }
    }
    #[test]
    fn task_state_survives_visual_interrupts() {
        assert_eq!(resting("executing"), Mode::Working);
        assert_eq!(resting("thinking"), Mode::Working);
        assert_eq!(resting("success"), Mode::Celebrating);
        assert_eq!(resting("help"), Mode::IdleEdge);
    }
    #[test]
    fn signed_drag_uses_real_appkit_vector() {
        assert_eq!(direction(-90.0, 4.0), Direction::Left);
        assert_eq!(direction(90.0, -4.0), Direction::Right);
        assert_eq!(direction(2.0, 70.0), Direction::Up);
        assert_eq!(direction(2.0, -70.0), Direction::Down);
    }
    #[test]
    fn anchors_respect_dock_work_area_and_negative_monitors() {
        let a = (-2400, 66, 2400, 1600);
        assert_eq!(origin(Anchor::TopLeft, a, (352, 336), 0.5), (-2400, 66));
        assert_eq!(
            origin(Anchor::BottomRight, a, (352, 336), 0.5),
            (-352, 1330)
        );
        assert_eq!(origin(Anchor::LeftEdge, a, (352, 336), 0.5), (-2400, 698));
    }
}
