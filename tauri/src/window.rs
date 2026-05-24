//! Multi-window state persistence.
//!
//! On close: serialize each window's frame + monitor identifier into
//! `state/window-state.json`. On launch: replay last session.
//!
//! SEC-04 P2 — every `unwrap()`/`expect()` was replaced with explicit early
//! returns so a malformed/corrupt state file never panics the shell.
//!
//! REL-04 P2 — store frames in **logical** pixels (DIPs) instead of outer
//! physical pixels. The previous version persisted `outer_position()` /
//! `outer_size()` (Physical) and restored with `LogicalPosition` /
//! `LogicalSize`, which on a 2× Retina display **doubled** the window
//! position on every relaunch until the window slid off-screen.
//!
//! We also remember the monitor identifier (`name`) the window was on at
//! save time. On restore we look up the monitor by name; if it is no
//! longer attached (external display unplugged), we fall back to the
//! primary monitor and clamp the position into its work area so the
//! window cannot land off-screen.

use serde::{Deserialize, Serialize};
use std::collections::HashMap;
use std::path::PathBuf;
use tauri::{
    App, LogicalPosition, LogicalSize, Manager, Monitor, PhysicalPosition, Window, WindowEvent,
};

#[derive(Default, Serialize, Deserialize)]
struct WindowFrame {
    /// Logical x position (DIP), top-left origin.
    x: f64,
    /// Logical y position (DIP).
    y: f64,
    /// Logical width (DIP).
    w: f64,
    /// Logical height (DIP).
    h: f64,
    /// Monitor identifier from `Monitor::name()`. Optional for
    /// backward compatibility with pre-REL-04 state files.
    #[serde(default, skip_serializing_if = "Option::is_none")]
    monitor: Option<String>,
}

fn state_path(app: &tauri::AppHandle) -> Option<PathBuf> {
    app.path().app_data_dir().ok().map(|p| p.join("state/window-state.json"))
}

pub fn restore_state(app: &App) {
    let handle = app.handle();
    let Some(path) = state_path(handle) else { return };
    if !path.exists() {
        return;
    }
    let Ok(text) = std::fs::read_to_string(&path) else { return };
    let frames: HashMap<String, WindowFrame> = match serde_json::from_str(&text) {
        Ok(v) => v,
        Err(err) => {
            log::warn!("window::restore_state: failed to parse {}: {err}", path.display());
            return;
        }
    };
    for (label, frame) in frames {
        if let Some(window) = handle.get_webview_window(&label) {
            // REL-04 P2 — validate the saved frame against currently
            // available monitors before restoring. If the monitor it was
            // saved on is gone, snap to primary.
            let monitors = window.available_monitors().unwrap_or_default();
            let primary = window.primary_monitor().ok().flatten();
            let (target_x, target_y) = resolve_position(&monitors, primary.as_ref(), &frame);
            let _ = window.set_position(LogicalPosition::new(target_x, target_y));
            let _ = window.set_size(LogicalSize::new(frame.w, frame.h));
        }
    }
}

/// REL-04 P2 — return a logical (x, y) that is guaranteed to fall inside
/// at least one currently-attached monitor's visible area. If the saved
/// monitor is gone (external display unplugged), the window snaps to the
/// primary monitor's top-left work area.
///
/// Pure function for testability — takes pre-resolved monitor lists so we
/// can exercise the multi-display fallback path without a live Tauri app.
fn resolve_position(
    monitors: &[Monitor],
    primary: Option<&Monitor>,
    frame: &WindowFrame,
) -> (f64, f64) {
    if monitors.is_empty() {
        return (frame.x, frame.y);
    }

    // Compute a per-monitor scale factor so we can compare logical position
    // against the monitor's physical bounds. `Monitor::position()` /
    // `::size()` are physical; we divide by `scale_factor()` to get DIPs.
    let in_bounds = |mon: &Monitor| -> bool {
        let sf = mon.scale_factor();
        let mp = mon.position();
        let ms = mon.size();
        let mx = mp.x as f64 / sf;
        let my = mp.y as f64 / sf;
        let mw = ms.width as f64 / sf;
        let mh = ms.height as f64 / sf;
        frame.x >= mx
            && frame.y >= my
            && frame.x + frame.w.min(64.0) <= mx + mw
            && frame.y + 24.0 <= my + mh
    };

    // 1. Preferred path: the saved monitor is still attached AND the saved
    //    position fits inside one of the available monitors.
    if let Some(name) = frame.monitor.as_deref() {
        if let Some(mon) = monitors.iter().find(|m| m.name().map(|n| n.as_str()) == Some(name)) {
            if in_bounds(mon) {
                return (frame.x, frame.y);
            }
        }
    }

    // 2. Even without the saved monitor name, if the saved logical position
    //    falls inside *any* currently-attached monitor, keep it.
    if monitors.iter().any(in_bounds) {
        return (frame.x, frame.y);
    }

    // 3. Fall back to primary monitor's top-left + small inset.
    let fallback = primary.or_else(|| monitors.first());
    if let Some(mon) = fallback {
        let sf = mon.scale_factor();
        let mp = mon.position();
        let ms = mon.size();
        let mx = mp.x as f64 / sf;
        let my = mp.y as f64 / sf;
        let mw = ms.width as f64 / sf;
        let mh = ms.height as f64 / sf;
        let clamped_x = mx + (mw - frame.w).max(0.0).min(48.0);
        let clamped_y = my + 32.0_f64.min(mh.max(32.0));
        return (clamped_x, clamped_y);
    }
    (frame.x, frame.y)
}

pub fn persist_state(window: &Window) {
    let app = window.app_handle();
    let Some(path) = state_path(app) else { return };
    let mut frames: HashMap<String, WindowFrame> = std::fs::read_to_string(&path)
        .ok()
        .and_then(|t| serde_json::from_str(&t).ok())
        .unwrap_or_default();
    for (label, w) in app.webview_windows() {
        // REL-04 P2 — persist **inner** position+size as logical DIPs so
        // restore is symmetric and Retina-safe. `outer_position()` +
        // `LogicalPosition::new` was a units mismatch.
        let pos: Option<PhysicalPosition<i32>> = w.inner_position().ok();
        let size = w.inner_size().ok();
        let scale = w.scale_factor().unwrap_or(1.0).max(0.1);
        if let (Some(pos), Some(size)) = (pos, size) {
            let monitor_name = w
                .current_monitor()
                .ok()
                .flatten()
                .and_then(|m| m.name().cloned());
            frames.insert(
                label,
                WindowFrame {
                    x: pos.x as f64 / scale,
                    y: pos.y as f64 / scale,
                    w: size.width as f64 / scale,
                    h: size.height as f64 / scale,
                    monitor: monitor_name,
                },
            );
        }
    }
    let Ok(text) = serde_json::to_string_pretty(&frames) else {
        log::warn!("window::persist_state: failed to serialize frames");
        return;
    };
    let Some(parent) = path.parent() else {
        log::warn!("window::persist_state: state file has no parent dir");
        return;
    };
    if let Err(err) = std::fs::create_dir_all(parent) {
        log::warn!(
            "window::persist_state: create_dir_all({}): {err}",
            parent.display()
        );
        return;
    }
    // FUNC-04 P0 — use the same atomic temp-file rename helper that
    // `save_workspace` uses, so a crash mid-write can never leave a
    // half-written window-state.json on disk.
    if let Err(err) = crate::filesystem::atomic_write(&path, text.as_bytes()) {
        log::warn!(
            "window::persist_state: atomic_write({}): {err}",
            path.display()
        );
    }
}

#[allow(dead_code)]
pub fn handle_event(_window: &Window, _event: &WindowEvent) {
    // reserved for future per-window decisions (focus / resize debounce).
}

#[cfg(test)]
mod tests {
    use super::*;
    use serde_json;

    #[test]
    fn roundtrip_logical_frame() {
        let frame = WindowFrame {
            x: 100.5,
            y: 200.5,
            w: 1440.0,
            h: 900.0,
            monitor: Some("Built-in Retina Display".into()),
        };
        let json = serde_json::to_string(&frame).unwrap();
        let parsed: WindowFrame = serde_json::from_str(&json).unwrap();
        assert!((parsed.x - 100.5).abs() < f64::EPSILON);
        assert!((parsed.y - 200.5).abs() < f64::EPSILON);
        assert!((parsed.w - 1440.0).abs() < f64::EPSILON);
        assert!((parsed.h - 900.0).abs() < f64::EPSILON);
        assert_eq!(parsed.monitor.as_deref(), Some("Built-in Retina Display"));
    }

    #[test]
    fn parses_legacy_frame_without_monitor() {
        // Pre-REL-04 frames never wrote a `monitor` field. Make sure the
        // optional field still deserialises without error.
        let legacy = r#"{"x":10.0,"y":20.0,"w":1440.0,"h":900.0}"#;
        let parsed: WindowFrame = serde_json::from_str(legacy).unwrap();
        assert!(parsed.monitor.is_none());
        assert!((parsed.x - 10.0).abs() < f64::EPSILON);
    }
}
