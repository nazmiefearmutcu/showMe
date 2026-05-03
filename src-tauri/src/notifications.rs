//! UNUserNotificationCenter bridge.
//!
//! Round 16 wraps `tauri-plugin-notification` with thin helpers that:
//!
//!   • set a `threadIdentifier` so OS-level notification grouping fires
//!     (alerts grouped per-symbol, news grouped per-feed, …);
//!   • surface high-severity entries in the dock badge / bounce.
//!
//! The plugin's API is intentionally narrow on macOS — clickable action
//! buttons require the deeper `UNNotificationAction` flow which lives
//! behind a feature flag in tauri-plugin-notification 2.x. We expose the
//! helpers here so a future round can flip the switch without touching
//! every call site.

use crate::dock;
use serde::Serialize;
use tauri::{AppHandle, Runtime};
use tauri_plugin_notification::NotificationExt;

#[derive(Serialize, Clone, Copy, Debug)]
#[serde(rename_all = "lowercase")]
pub enum Severity {
    Info,
    Warn,
    Critical,
}

#[derive(Serialize, Clone, Debug)]
pub struct NotifyOptions<'a> {
    pub title: &'a str,
    pub body: &'a str,
    pub thread: Option<&'a str>,
    pub severity: Severity,
}

pub fn notify<R: Runtime>(app: &AppHandle<R>, opts: NotifyOptions<'_>) -> Result<(), String> {
    let mut builder = app.notification().builder().title(opts.title).body(opts.body);
    if let Some(group) = opts.thread {
        // Maps to UNMutableNotificationContent.threadIdentifier on macOS.
        builder = builder.group(group.to_string());
    }
    builder.show().map_err(|e| e.to_string())?;

    if matches!(opts.severity, Severity::Critical | Severity::Warn) {
        dock::request_attention(app, matches!(opts.severity, Severity::Critical));
    }
    Ok(())
}
