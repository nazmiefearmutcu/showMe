//! Global hotkeys.
//!
//! Currently registered:
//!   • ⌘⇧S — bring showMe to front from anywhere.
//!   • ⌘⇧K — open Command Palette across apps.
//!   • ⌘⇧A — surface latest critical alert.
//!
//! Round 16 may add Carbon HotKey fallback if `globalShortcut` collides on
//! arm64 Sonoma+.

use tauri::{App, Manager};
use tauri_plugin_global_shortcut::{GlobalShortcutExt, ShortcutState};

pub fn register(app: &App) {
    let handle = app.handle().clone();
    let gs = handle.global_shortcut();

    let _ = gs.on_shortcut("CmdOrCtrl+Shift+S", {
        let h = handle.clone();
        move |_app, _shortcut, evt| {
            if evt.state() == ShortcutState::Pressed {
                if let Some(w) = h.get_webview_window("main") {
                    let _ = w.unminimize();
                    let _ = w.show();
                    let _ = w.set_focus();
                }
            }
        }
    });
    let _ = gs.on_shortcut("CmdOrCtrl+Shift+K", {
        let h = handle.clone();
        move |_app, _shortcut, evt| {
            if evt.state() == ShortcutState::Pressed {
                if let Some(w) = h.get_webview_window("main") {
                    let _ = w.unminimize();
                    let _ = w.show();
                    let _ = w.set_focus();
                }
                let _ = tauri::Emitter::emit(&h, "palette:toggle", ());
            }
        }
    });
    let _ = gs.on_shortcut("CmdOrCtrl+Shift+A", {
        let h = handle.clone();
        move |_app, _shortcut, evt| {
            if evt.state() == ShortcutState::Pressed {
                let _ = tauri::Emitter::emit(&h, "alert:focus_critical", ());
            }
        }
    });
}
