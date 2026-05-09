//! showMe — Tauri shell entry.
//!
//! Wires every subsystem (sidecar lifecycle, tray, dock, deeplinks, global
//! shortcuts, biometric, filesystem layout) on `app::setup`. Each subsystem
//! lives in its own module so we can grow without one giant `main.rs`.

mod biometric;
mod commands;
mod deeplink;
mod dock;
mod filesystem;
mod ipc;
mod menu;
mod notifications;
mod presets;
#[cfg(target_os = "macos")]
mod secrets;
mod shortcuts;
mod sidecar;
mod tray;
mod window;

use parking_lot::RwLock;
use serde::Serialize;
use std::sync::Arc;
use tauri::Emitter;

/// Shared application state passed to every Tauri command.
#[derive(Default)]
pub struct AppState {
    pub sidecar_port: Arc<RwLock<Option<u16>>>,
    pub sidecar_health: Arc<RwLock<SidecarHealth>>,
    pub data_root: Arc<RwLock<Option<std::path::PathBuf>>>,
}

#[derive(Default, Clone, Debug, Serialize)]
pub struct SidecarHealth {
    pub status: SidecarStatus,
    pub restarts: u32,
    pub last_error: Option<String>,
}

#[derive(Default, Clone, Copy, Debug, Serialize, PartialEq, Eq)]
#[serde(rename_all = "lowercase")]
pub enum SidecarStatus {
    #[default]
    Booting,
    Healthy,
    Crashed,
    Stopped,
}

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    let state = AppState::default();

    tauri::Builder::default()
        .plugin(tauri_plugin_shell::init())
        .plugin(tauri_plugin_fs::init())
        .plugin(tauri_plugin_dialog::init())
        .plugin(tauri_plugin_notification::init())
        .plugin(tauri_plugin_os::init())
        .plugin(tauri_plugin_process::init())
        .plugin(tauri_plugin_store::Builder::default().build())
        .plugin(tauri_plugin_log::Builder::default().build())
        .plugin(tauri_plugin_global_shortcut::Builder::new().build())
        .plugin(tauri_plugin_deep_link::init())
        .plugin(tauri_plugin_updater::Builder::new().build())
        .manage(state)
        .invoke_handler(tauri::generate_handler![
            commands::sidecar_status,
            commands::sidecar_port,
            commands::open_data_folder,
            commands::install_to_applications,
            commands::reload_function_index,
            commands::request_biometric,
            commands::set_dock_badge,
            commands::request_attention,
            commands::write_log_entry,
            commands::open_window,
            commands::list_presets,
            commands::read_preset,
            commands::write_preset,
            commands::delete_preset,
            commands::notify,
            commands::save_workspace,
            commands::load_workspace,
            commands::biometric_capabilities,
            commands::keychain_set,
            commands::keychain_get,
            commands::keychain_delete,
            commands::keychain_list,
            commands::run_migration,
            commands::check_for_updates,
            commands::apply_update,
        ])
        .setup(|app| {
            // 1. Build app data layout under ~/Library/Application Support/showMe.
            filesystem::ensure_layout(app)?;

            // 2. Boot the Python sidecar (port 0 → discovered port).
            sidecar::spawn(app.handle().clone());

            // 3. Native chrome: tray, dock, menubar.
            tray::install(app)?;
            menu::install(app)?;
            dock::install(app)?;

            // 4. Window niceties — vibrancy/overlay handled in tauri.conf.json,
            //    here we restore last position + size.
            window::restore_state(app);

            // 5. Hotkeys + deep links.
            shortcuts::register(app);
            deeplink::register(app);

            // 6. Notify the front-end once shell is ready.
            let handle = app.handle().clone();
            tauri::async_runtime::spawn(async move {
                tokio::time::sleep(std::time::Duration::from_millis(80)).await;
                let _ = handle.emit("shell:ready", ());
            });

            Ok(())
        })
        .on_window_event(|window, event| {
            if let tauri::WindowEvent::CloseRequested { .. } = event {
                window::persist_state(window);
            }
        })
        .build(tauri::generate_context!())
        .expect("error while building tauri application")
        .run(|handle, event| {
            if let tauri::RunEvent::ExitRequested { .. } = event {
                sidecar::shutdown(handle);
            }
        });
}
