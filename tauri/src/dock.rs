//! Dock badge + attention bridge.
//!
//! Round 16 swaps the Round-12 log-only stubs for Tauri 2's first-party
//! `set_badge_count` / `request_user_attention` APIs. They sit on top of
//! NSDockTile + `-[NSApp requestUserAttention:]` on macOS, no-op on other
//! targets.

use tauri::{App, AppHandle, Manager, Runtime, UserAttentionType};

pub fn install<R: Runtime>(_app: &App<R>) -> tauri::Result<()> {
    Ok(())
}

/// Set the dock badge to a textual count, or clear it with `None`.
pub fn set_badge<R: Runtime>(handle: &AppHandle<R>, count: Option<i64>) {
    let Some(window) = handle.get_webview_window("main") else {
        log::debug!("dock::set_badge no main window yet");
        return;
    };
    if let Err(err) = window.set_badge_count(count) {
        log::warn!("dock::set_badge failed: {err}");
    }
}

/// Request user attention — `critical=true` bounces forever until the
/// app is foregrounded, `critical=false` does a single subtle bounce.
pub fn request_attention<R: Runtime>(handle: &AppHandle<R>, critical: bool) {
    let Some(window) = handle.get_webview_window("main") else {
        log::debug!("dock::request_attention no main window yet");
        return;
    };
    let kind = if critical {
        UserAttentionType::Critical
    } else {
        UserAttentionType::Informational
    };
    if let Err(err) = window.request_user_attention(Some(kind)) {
        log::warn!("dock::request_attention failed: {err}");
    }
}
