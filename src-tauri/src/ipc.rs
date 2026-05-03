//! Backend ↔ Tauri IPC helpers.
//!
//! For now the frontend talks to the sidecar over plain HTTP (the discovered
//! port is exposed via `commands::sidecar_port`). When we need server-push
//! we'll wire a websocket re-broadcaster here that mirrors `/ws/*` routes
//! into Tauri events.

use crate::AppState;
use tauri::{AppHandle, Manager};

#[allow(dead_code)]
pub fn base_url(app: &AppHandle) -> Option<String> {
    let port = *app.state::<AppState>().sidecar_port.read();
    port.map(|p| format!("http://127.0.0.1:{}", p))
}
