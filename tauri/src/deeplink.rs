//! `showme://` URL scheme.
//!
//! Examples:
//!   showme://function/AAPL/FA            → load function FA for AAPL
//!   showme://scan/<scan_id>              → open scanner result
//!   showme://alert/<alert_id>            → focus alert detail
//!
//! Tauri receives the URL via `tauri-plugin-deep-link`, we forward it to the
//! frontend through a `deeplink:received` event so the React router decides
//! which pane / window to open.

use tauri::{App, Manager};
use tauri_plugin_deep_link::DeepLinkExt;

pub fn register(app: &App) {
    let handle = app.handle().clone();
    let deep_link = app.deep_link();
    deep_link.on_open_url(move |event| {
        for url in event.urls() {
            let payload = url.to_string();
            log::info!("deeplink: {payload}");
            if let Some(w) = handle.get_webview_window("main") {
                let _ = w.show();
                let _ = w.set_focus();
            }
            let _ = tauri::Emitter::emit(&handle, "deeplink:received", payload);
        }
    });
}
