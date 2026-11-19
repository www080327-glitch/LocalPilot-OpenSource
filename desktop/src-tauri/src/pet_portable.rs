use super::*;
#[cfg(target_os = "linux")]
use gtk::{gdk, glib, prelude::*};
use std::sync::atomic::Ordering;

#[cfg(target_os = "linux")]
pub fn global_positions_supported() -> bool {
    gdk::Display::default().is_some_and(|display| display.backend().is_x11())
}

#[cfg(target_os = "linux")]
pub fn begin_drag(app: &tauri::AppHandle) -> Result<(), String> {
    let window = app.get_webview_window("pet").ok_or("宠物未开启")?;
    let native = window.gtk_window().map_err(|e| e.to_string())?;
    let surface = native.window().ok_or("角色窗口尚未显示，请稍后重试")?;
    let pointer = surface
        .display()
        .default_seat()
        .and_then(|seat| seat.pointer())
        .ok_or("当前桌面未提供鼠标指针，请检查输入设备")?;
    if !surface
        .device_position(&pointer)
        .3
        .contains(gdk::ModifierType::BUTTON1_MASK)
    {
        return Err("请按住鼠标左键拖动角色".into());
    }
    let state = app.state::<pet_native::PetState>();
    if state.dragging.swap(true, Ordering::Relaxed) {
        return Ok(());
    }
    // Tao can return cached zero coordinates on Wayland without an error.
    let positions_available = global_positions_supported();
    let mut previous = positions_available
        .then(|| window.outer_position().ok())
        .flatten();
    if let Err(error) = window.start_dragging() {
        state.dragging.store(false, Ordering::Relaxed);
        return Err(error.to_string());
    }
    pet_edge::drag(app, 0.0, 0.0);
    let app = app.clone();
    // GTK begins the compositor move asynchronously. Observe the actual button
    // release before ending the shared drag state or selecting the closest edge.
    glib::timeout_add_local(pet_native::ANIMATION_INTERVAL, move || {
        let state = app.state::<pet_native::PetState>();
        let Some(window) = app.get_webview_window("pet") else {
            state.dragging.store(false, Ordering::Relaxed);
            return glib::ControlFlow::Break;
        };
        if surface.is_destroyed() || !window.is_visible().unwrap_or(false) {
            state.dragging.store(false, Ordering::Relaxed);
            pet_edge::end_drag(&app);
            return glib::ControlFlow::Break;
        }
        let current = positions_available
            .then(|| window.outer_position().ok())
            .flatten();
        if let Some((dx, dy)) = physical_drag_delta(previous, current) {
            pet_edge::drag(&app, dx, dy);
        }
        previous = current;
        if surface
            .device_position(&pointer)
            .3
            .contains(gdk::ModifierType::BUTTON1_MASK)
        {
            glib::ControlFlow::Continue
        } else {
            state.dragging.store(false, Ordering::Relaxed);
            pet_edge::end_drag(&app);
            if positions_available {
                let _ = pet_native::follow(&app);
            }
            glib::ControlFlow::Break
        }
    });
    Ok(())
}

#[cfg(target_os = "linux")]
fn physical_drag_delta(
    previous: Option<tauri::PhysicalPosition<i32>>,
    current: Option<tauri::PhysicalPosition<i32>>,
) -> Option<(f64, f64)> {
    let (previous, current) = previous.zip(current)?;
    let dx = current.x as f64 - previous.x as f64;
    let dy = previous.y as f64 - current.y as f64;
    (dx != 0.0 || dy != 0.0).then_some((dx, dy))
}

pub fn transparent(_window: &tauri::WebviewWindow) -> Result<(), String> {
    Ok(())
}
pub fn install(_app: &tauri::AppHandle) {}
pub fn thought_glass(_app: &tauri::AppHandle) -> Result<(), String> {
    Ok(())
}

pub fn diagnostics(app: &tauri::AppHandle) -> Result<Value, String> {
    #[cfg(target_os = "linux")]
    let positions_available = global_positions_supported();
    #[cfg(not(target_os = "linux"))]
    let positions_available = true;
    let windows = ["pet", "pet-bubble"]
        .into_iter()
        .filter_map(|label| {
            app.get_webview_window(label).map(|window| {
                json!({
                    "label":label, "visible":window.is_visible().ok(),
                    "position":positions_available.then(||window.outer_position().ok()).flatten(), "size":window.outer_size().ok()
                })
            })
        })
        .collect::<Vec<_>>();
    let appearance = pet_assets::diagnostic_appearance(
        &data(app)?,
        app.state::<pet_native::PetState>()
            .settings
            .lock()
            .unwrap()
            .basic_appearance,
    );
    Ok(
        json!({"pid":std::process::id(),"platform":std::env::consts::OS,
        "bundle_id":app.config().identifier,"windows":windows,
        "character":appearance["character"],"appearance_mode":appearance["appearance_mode"],
        "edge":pet_edge::snapshot(app),"pointer_input":"webview",
        "drag_active":app.state::<pet_native::PetState>().dragging.load(Ordering::Relaxed),
        "global_position_available":positions_available && app.get_webview_window("pet").is_some_and(|w|w.outer_position().is_ok()),
        "native_glass":"UNSUPPORTED","alpha_hit_testing":"UNSUPPORTED"}),
    )
}

#[cfg(all(test, target_os = "linux"))]
mod tests {
    use super::*;

    #[test]
    fn physical_drag_preserves_direction_across_negative_screen_coordinates() {
        let start = Some(tauri::PhysicalPosition::new(-400, 200));
        assert_eq!(
            physical_drag_delta(start, Some(tauri::PhysicalPosition::new(-450, 190))),
            Some((-50.0, 10.0))
        );
        assert_eq!(
            physical_drag_delta(start, Some(tauri::PhysicalPosition::new(-390, 230))),
            Some((10.0, -30.0))
        );
        assert_eq!(physical_drag_delta(start, start), None);
        assert_eq!(physical_drag_delta(start, None), None);
        assert_eq!(physical_drag_delta(None, start), None);
    }
}
