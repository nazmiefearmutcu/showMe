//! Multi-window state persistence.
//!
//! On close: serialize each window's frame + monitor identifier into
//! `state/window-state.json`. On launch: replay last session.

use serde::{Deserialize, Serialize};
use std::collections::HashMap;
use tauri::{App, LogicalPosition, LogicalSize, Manager, Window, WindowEvent};

#[derive(Default, Serialize, Deserialize)]
struct WindowFrame {
    x: f64, y: f64, w: f64, h: f64,
}

fn state_path(app: &tauri::AppHandle) -> Option<std::path::PathBuf> {
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
        Err(_) => return,
    };
    for (label, frame) in frames {
        if let Some(window) = handle.get_webview_window(&label) {
            let _ = window.set_position(LogicalPosition::new(frame.x, frame.y));
            let _ = window.set_size(LogicalSize::new(frame.w, frame.h));
        }
    }
}

pub fn persist_state(window: &Window) {
    let app = window.app_handle();
    let Some(path) = state_path(app) else { return };
    let mut frames: HashMap<String, WindowFrame> = std::fs::read_to_string(&path)
        .ok()
        .and_then(|t| serde_json::from_str(&t).ok())
        .unwrap_or_default();
    for (label, w) in app.webview_windows() {
        if let (Ok(pos), Ok(size)) = (w.outer_position(), w.outer_size()) {
            frames.insert(
                label,
                WindowFrame {
                    x: pos.x as f64,
                    y: pos.y as f64,
                    w: size.width as f64,
                    h: size.height as f64,
                },
            );
        }
    }
    if let Ok(text) = serde_json::to_string_pretty(&frames) {
        let _ = std::fs::create_dir_all(path.parent().unwrap());
        let _ = std::fs::write(&path, text);
    }
}

#[allow(dead_code)]
pub fn handle_event(_window: &Window, _event: &WindowEvent) {
    // reserved for future per-window decisions (focus / resize debounce).
}
