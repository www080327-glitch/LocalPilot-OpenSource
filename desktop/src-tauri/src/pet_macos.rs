//! Only LocalPilot's character window participates in this local event monitor.
//! Native event coordinates keep click/drag independent of WebKit/IPC latency.
use super::*;
use objc2_app_kit::{NSColor, NSEvent, NSEventMask, NSEventType, NSWindow};
use std::cell::RefCell;
use std::ptr::NonNull;
use std::sync::atomic::{AtomicBool, Ordering};

static INSTALLED: AtomicBool = AtomicBool::new(false);

pub fn transparent(window: &tauri::WebviewWindow) -> Result<(), String> {
    // Called by create on AppKit's main thread. Never apply glass to the sprite.
    let ptr = window.ns_window().map_err(|e| e.to_string())? as *mut NSWindow;
    let native = unsafe { &*ptr };
    native.setOpaque(false);
    native.setBackgroundColor(Some(&NSColor::clearColor()));
    native.setHasShadow(false);
    native.setMovableByWindowBackground(false);
    Ok(())
}

pub fn ignores_mouse(window: &tauri::WebviewWindow) -> Result<bool, String> {
    let native = unsafe { &*(window.ns_window().map_err(|e| e.to_string())? as *mut NSWindow) };
    Ok(native.ignoresMouseEvents())
}

pub fn diagnostics(app: &tauri::AppHandle) -> Result<Value, String> {
    let mut rows = Vec::new();
    for name in ["pet", "pet-bubble"] {
        if let Some(w) = app.get_webview_window(name) {
            let native = unsafe { &*(w.ns_window().map_err(|e| e.to_string())? as *mut NSWindow) };
            let f = native.frame();
            rows.push(json!({"label":name,"window_number":native.windowNumber(),"opaque":native.isOpaque(),
                "ignores_mouse":native.ignoresMouseEvents(),"level":native.level(),"visible":w.is_visible().unwrap_or(false),
                "frame_points":{"x":f.origin.x,"y":f.origin.y,"width":f.size.width,"height":f.size.height}}));
        }
    }
    let character = {
        let state = app.state::<pet_native::PetState>();
        let edge = state.edge.lock().unwrap();
        edge.pack.as_ref().map(|p| p.identity.clone())
    };
    Ok(
        json!({"character":character,"pid":std::process::id(),"bundle_id":app.config().identifier,"windows":rows,
        "edge":pet_edge::snapshot(app),"thought_glass":thought_glass_diagnostics(app),
        "pose":*app.state::<pet_native::PetState>().pose.lock().unwrap(),
        "drag_count":app.state::<pet_native::PetState>().drag_count.load(Ordering::Relaxed),
        "input_counts":{"down":app.state::<pet_native::PetState>().down_count.load(Ordering::Relaxed),"drag":app.state::<pet_native::PetState>().drag_event_count.load(Ordering::Relaxed),"up":app.state::<pet_native::PetState>().up_count.load(Ordering::Relaxed)},
        "monitors": app.available_monitors().unwrap_or_default().iter().map(|m| json!({"name":m.name(),"scale":m.scale_factor(),"position":m.position(),"size":m.size(),"work_area":m.work_area()})).collect::<Vec<_>>()}),
    )
}

pub fn install(app: &tauri::AppHandle) {
    if INSTALLED.swap(true, Ordering::Relaxed) {
        return;
    }
    let handle = app.clone();
    // Event coordinates are authoritative. Reading the current global cursor
    // here races queued/synthetic native events and can misclassify a drag as a
    // click. Track the initiating screen point and frame in AppKit points.
    let down = RefCell::new(None::<(f64, f64, f64, f64, bool, bool)>);
    let block = block2::RcBlock::new(move |ptr: NonNull<NSEvent>| -> *mut NSEvent {
        let event = unsafe { ptr.as_ref() };
        let Some(w) = handle.get_webview_window("pet") else {
            return ptr.as_ptr();
        };
        let Ok(raw) = w.ns_window() else {
            return ptr.as_ptr();
        };
        let native = unsafe { &*(raw as *mut NSWindow) };
        if event.windowNumber() != native.windowNumber() {
            if matches!(
                event.r#type(),
                NSEventType::LeftMouseDown | NSEventType::RightMouseDown
            ) && handle
                .get_webview_window("main")
                .and_then(|b| b.ns_window().ok())
                .is_some_and(|b| {
                    unsafe { &*(b as *mut NSWindow) }.windowNumber() == event.windowNumber()
                })
            {
                let _ = pet_native::expand(&handle, false, false);
            }
            return ptr.as_ptr();
        }
        let state = handle.state::<pet_native::PetState>();
        match event.r#type() {
            NSEventType::LeftMouseDown => {
                state.down_count.fetch_add(1, Ordering::Relaxed);
                let p = native.convertPointToScreen(event.locationInWindow());
                let origin = native.frame().origin;
                let local = event.locationInWindow();
                let factor = state.settings.lock().unwrap().size;
                let chat = pet_edge::is_chat(
                    &handle,
                    local.x / factor,
                    (native.frame().size.height - local.y) / factor,
                );
                *down.borrow_mut() = Some((p.x, p.y, origin.x, origin.y, false, chat));
                state.dragging.store(true, Ordering::Relaxed);
                let _ = w.set_ignore_cursor_events(false);
                // Native owns mouse click/drag; WebKit still owns keyboard activation.
                std::ptr::null_mut()
            }
            NSEventType::LeftMouseDragged => {
                state.drag_event_count.fetch_add(1, Ordering::Relaxed);
                let point = native.convertPointToScreen(event.locationInWindow());
                let mut gesture = down.borrow_mut();
                if let Some((x, y, ox, oy, moved, chat)) = gesture.as_mut() {
                    let (dx, dy) = (point.x - *x, point.y - *y);
                    if !*chat && (*moved || dx.hypot(dy) >= 5.0) {
                        pet_edge::drag(&handle, dx, dy);
                        if !*moved {
                            *moved = true;
                            state.drag_count.fetch_add(1, Ordering::Relaxed);
                            let _ = pet_native::expand(&handle, false, false);
                            let _ = handle.emit_to("pet", "pet-dragged", ());
                        }
                        let mut origin = native.frame().origin;
                        origin.x = *ox + dx;
                        origin.y = *oy + dy;
                        native.setFrameOrigin(origin);
                    }
                }
                std::ptr::null_mut()
            }
            NSEventType::LeftMouseUp => {
                state.up_count.fetch_add(1, Ordering::Relaxed);
                state.dragging.store(false, Ordering::Relaxed);
                if let Some((_, _, _, _, moved, chat)) = down.borrow_mut().take() {
                    if moved {
                        pet_edge::end_drag(&handle);
                        let _ = handle.emit_to("pet", "pet-drag-ended", ());
                    } else if chat {
                        let open = !state.expanded.load(Ordering::Relaxed);
                        let _ = pet_native::expand(&handle, open, open);
                    } else {
                        let _ = pet_native::expand(&handle, false, false);
                        let _ = pet_edge::relocate(&handle, None);
                    }
                }
                std::ptr::null_mut()
            }
            NSEventType::RightMouseDown => {
                let _ = pet_native::expand(&handle, true, true);
                ptr.as_ptr()
            }
            _ => ptr.as_ptr(),
        }
    });
    let mask = NSEventMask::LeftMouseDown
        | NSEventMask::LeftMouseDragged
        | NSEventMask::LeftMouseUp
        | NSEventMask::RightMouseDown;
    if let Some(token) =
        unsafe { NSEvent::addLocalMonitorForEventsMatchingMask_handler(mask, &block) }
    {
        // One monitor per process; its block resolves the current window each time.
        // It cannot consume another application's events or a destroyed pet window.
        std::mem::forget(token);
    }
    let handle = app.clone();
    let block = block2::RcBlock::new(move |_: NonNull<NSEvent>| {
        let _ = pet_native::expand(&handle, false, false);
    });
    if let Some(token) = NSEvent::addGlobalMonitorForEventsMatchingMask_handler(
        NSEventMask::LeftMouseDown | NSEventMask::RightMouseDown,
        &block,
    ) {
        std::mem::forget(token);
    }
}

const THOUGHT_GLASS_TAG: isize = 0x4c505447;
/// A native glass view below WKWebView, masked to the thought ellipse and dots.
/// It never reparents the character webview or applies material to its viewport.
pub fn thought_glass(app: &tauri::AppHandle) -> Result<(), String> {
    use objc2_app_kit::{
        NSAutoresizingMaskOptions, NSBezierPath, NSGlassEffectViewStyle, NSView,
        NSWindowOrderingMode,
    };
    use objc2_foundation::{NSPoint, NSRect, NSSize};
    use objc2_quartz_core::{CAShapeLayer, CATransaction};
    let mtm = objc2::MainThreadMarker::new().ok_or("Thought glass requires the main thread")?;
    let state = app.state::<pet_native::PetState>();
    let Some(w) = app.get_webview_window("pet") else {
        return Ok(());
    };
    let native = unsafe { &*(w.ns_window().map_err(|e| e.to_string())? as *mut NSWindow) };
    let Some(content) = native.contentView() else {
        return Ok(());
    };
    let reduce = objc2_app_kit::NSWorkspace::sharedWorkspace()
        .accessibilityDisplayShouldReduceTransparency();
    if reduce || unsafe { objc2_app_kit::NSAppKitVersionNumber } < 2685.0 {
        if let Some(view) = content.viewWithTag(THOUGHT_GLASS_TAG) {
            view.setHidden(true);
        }
        state.mini_glass.store(false, Ordering::Relaxed);
        return Ok(());
    }
    let (anchor, chat_open) = {
        let e = state.edge.lock().unwrap();
        (e.anchor, e.mode == pet_edge::Mode::ChatOpen)
    };
    let mini = pet_edge::chat_box(anchor);
    let bounds = content.bounds();
    let scale = bounds.size.width / pet_edge::VIEW_W;
    let frame = NSRect::new(
        NSPoint::new(
            mini[0] * scale,
            if content.isFlipped() {
                mini[1] * scale
            } else {
                bounds.size.height - (mini[1] + mini[3]) * scale
            },
        ),
        NSSize::new(mini[2] * scale, mini[3] * scale),
    );
    let existing = content.viewWithTag(THOUGHT_GLASS_TAG);
    let created = existing.is_none();
    let view = if let Some(view) = existing {
        view
    } else {
        let glass = unsafe {
            window_vibrancy::NSGlassEffectViewTagged::initWithFrame(
                mtm.alloc(),
                frame,
                THOUGHT_GLASS_TAG,
            )
        };
        glass.setStyle(NSGlassEffectViewStyle::Clear);
        glass.setCornerRadius(0.0);
        glass.setEffectIsInteractive(false);
        glass.setTintColor(Some(&NSColor::colorWithRed_green_blue_alpha(
            0.94, 0.97, 1.0, 0.07,
        )));
        let v: &NSView = &glass;
        v.setAutoresizingMask(NSAutoresizingMaskOptions::empty());
        v.setWantsLayer(true);
        content.addSubview_positioned_relativeTo(v, NSWindowOrderingMode::Below, None);
        content
            .viewWithTag(THOUGHT_GLASS_TAG)
            .ok_or("Thought glass insertion failed")?
    };
    let needs_mask =
        created || view.frame() != frame || view.layer().is_none_or(|layer| layer.mask().is_none());
    if needs_mask {
        CATransaction::begin();
        CATransaction::setDisableActions(true);
        view.setFrame(frame);
        view.setWantsLayer(true);
        let path = NSBezierPath::bezierPath();
        let to_left = matches!(
            anchor,
            pet_edge::Anchor::TopLeft | pet_edge::Anchor::LeftEdge | pet_edge::Anchor::BottomLeft
        );
        let to_up = matches!(
            anchor,
            pet_edge::Anchor::TopLeft | pet_edge::Anchor::TopRight
        );
        for (cx, cy, rx, ry) in [
            (70.0, 38.0, 66.0, 35.0),
            (99.0, 87.0, 6.0, 6.0),
            (116.0, 99.0, 3.0, 3.0),
        ] {
            let x = if to_left { 140.0 - cx } else { cx };
            let y = if to_up { 104.0 - cy } else { cy };
            path.appendBezierPathWithOvalInRect(NSRect::new(
                NSPoint::new((x - rx) * scale, (104.0 - y - ry) * scale),
                NSSize::new(2.0 * rx * scale, 2.0 * ry * scale),
            ));
        }
        if let Some(layer) = view.layer() {
            let mask = CAShapeLayer::layer();
            unsafe {
                mask.setFrame(view.bounds());
            }
            mask.setPath(Some(&path.CGPath()));
            unsafe {
                layer.setMask(Some(&mask));
            }
        }
        CATransaction::commit();
    }
    view.setHidden(chat_open);
    state.mini_glass.store(true, Ordering::Relaxed);
    Ok(())
}

pub fn thought_glass_diagnostics(app: &tauri::AppHandle) -> Value {
    let Some(w) = app.get_webview_window("pet") else {
        return Value::Null;
    };
    let Ok(raw) = w.ns_window() else {
        return Value::Null;
    };
    let native = unsafe { &*(raw as *mut NSWindow) };
    let Some(content) = native.contentView() else {
        return Value::Null;
    };
    let Some(v) = content.viewWithTag(THOUGHT_GLASS_TAG) else {
        return json!({"present":false});
    };
    let f = v.frame();
    let masked = v.layer().is_some_and(|layer| layer.mask().is_some());
    json!({"present":true,"class":"NSGlassEffectViewTagged","style":"Clear","hidden":v.isHidden(),"ellipse_and_dots_mask":masked,"frame_points":{"x":f.origin.x,"y":f.origin.y,"width":f.size.width,"height":f.size.height},"character_has_material_panel":false,"local_flipped":v.isFlipped()})
}
