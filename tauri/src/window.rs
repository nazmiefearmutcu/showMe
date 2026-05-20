//! Multi-window state persistence.
//!
//! On close: serialize each window's frame + monitor identifier into
//! `state/window-state.json`. On launch: replay last session.
//!
//! SEC-04 P2 — every `unwrap()`/`expect()` was replaced with explicit early
//! returns so a malformed/corrupt state file never panics the shell.

use serde::{Deserialize, Serialize};
use std::collections::HashMap;
use std::path::PathBuf;
use tauri::{App, LogicalPosition, LogicalSize, Manager, Window, WindowEvent};

#[derive(Default, Serialize, Deserialize)]
struct WindowFrame {
    x: f64, y: f64, w: f64, h: f64,
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
