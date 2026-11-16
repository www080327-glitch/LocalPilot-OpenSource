use super::*;

pub fn transparent(_window: &tauri::WebviewWindow) -> Result<(), String> {
    Ok(())
}
pub fn install(_app: &tauri::AppHandle) {}
pub fn thought_glass(_app: &tauri::AppHandle) -> Result<(), String> {
    Ok(())
}

pub fn diagnostics(app: &tauri::AppHandle) -> Result<Value, String> {
    let windows = ["pet", "pet-bubble"]
        .into_iter()
        .filter_map(|label| {
            app.get_webview_window(label).map(|window| {
                json!({
                    "label":label, "visible":window.is_visible().ok(),
                    "position":window.outer_position().ok(), "size":window.outer_size().ok()
                })
            })
        })
        .collect::<Vec<_>>();
    Ok(
        json!({"pid":std::process::id(),"platform":std::env::consts::OS,
        "bundle_id":app.config().identifier,"windows":windows,
        "edge":pet_edge::snapshot(app),"pointer_input":"webview",
        "native_glass":"UNSUPPORTED","alpha_hit_testing":"UNSUPPORTED"}),
    )
}
