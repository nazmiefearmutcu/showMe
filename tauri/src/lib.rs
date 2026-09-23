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
use tauri::{Emitter, Manager};
use tauri_plugin_log::{Target, TargetKind, RotationStrategy};

/// Shared application state passed to every Tauri command.
#[derive(Default)]
pub struct AppState {
    pub sidecar_port: Arc<RwLock<Option<u16>>>,
    pub sidecar_health: Arc<RwLock<SidecarHealth>>,
    pub data_root: Arc<RwLock<Option<std::path::PathBuf>>>,
    /// Random per-boot token shared with the Python sidecar via the
    /// `SHOWME_AUTH_TOKEN` env var. The frontend reads it via
    /// `sidecar_auth_token` and attaches an `X-ShowMe-Token` header to
    /// every HTTP/WS call so a co-resident process on loopback cannot
    /// hit the broker/portfolio endpoints (ARCH-05 P2).
    pub sidecar_auth_token: Arc<RwLock<Option<String>>>,
    /// HNT-07 — set by `sidecar::shutdown` right before the child is
    /// torn down. The sidecar backoff/retry loop and the crash-restart
    /// path poll it so a quit during a backoff window never leaves a
    /// freshly-spawned orphaned Python process behind.
    pub sidecar_shutdown: std::sync::atomic::AtomicBool,
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

/// Install a process-wide panic hook (TEST-10 P1).
///
/// On any unwinding panic in Rust code (Tauri shell, sidecar bookkeeping,
/// Tauri commands), we:
///   1. format a single-line summary plus the captured backtrace,
///   2. write it to `<app_data>/logs/crash/<utc>.log`,
///   3. emit `app:panic` so a still-running webview can render an alert,
///   4. delegate to the original hook so stderr / debugger output is
///      unchanged.
///
/// The hook is registered exactly once via `std::sync::Once`.
fn install_panic_hook() {
    use std::backtrace::Backtrace;
    use std::sync::Once;
    static ONCE: Once = Once::new();
    ONCE.call_once(|| {
        // Force the runtime to capture a backtrace even when RUST_BACKTRACE is
        // unset; cheap on macOS arm64.
        std::env::set_var("RUST_BACKTRACE", "1");
        let prev = std::panic::take_hook();
        std::panic::set_hook(Box::new(move |info| {
            let payload = if let Some(s) = info.payload().downcast_ref::<&str>() {
                s.to_string()
            } else if let Some(s) = info.payload().downcast_ref::<String>() {
                s.clone()
            } else {
                "<non-string panic payload>".to_string()
            };
            let location = info
                .location()
                .map(|l| format!("{}:{}:{}", l.file(), l.line(), l.column()))
                .unwrap_or_else(|| "<unknown>".into());
            let bt = Backtrace::force_capture();
            let body = format!(
                "showMe panic at {location}\npayload: {payload}\nbacktrace:\n{bt}\n"
            );
            // Write to the configured app data dir, falling back to temp dir so
            // even a panic before `ensure_layout` ran lands somewhere.
            let candidate_root = app_data_root_fallback();
            let crash_dir = candidate_root.join("logs/crash");
            let _ = std::fs::create_dir_all(&crash_dir);
            let stamp = chrono_like_stamp();
            let path = crash_dir.join(format!("panic-{stamp}.log"));
            let _ = std::fs::write(&path, body.as_bytes());
            // HNT-07 — release builds use `panic = "abort"`, so this hook
            // is the last code that runs before the process dies: no
            // `ExitRequested`, no `sidecar::shutdown`. Kill the sidecar
            // best-effort or it stays orphaned holding the DuckDB lock.
            crate::sidecar::kill_child_best_effort();
            // Best-effort log + delegate.
            log::error!("panic captured to {}: {payload}", path.display());
            prev(info);
        }));
    });
}

/// Tiny, allocation-light UTC timestamp helper. We avoid pulling `chrono`
/// into the crash hook because the panic context might already be on a
/// half-broken allocator path.
fn chrono_like_stamp() -> String {
    use std::time::{SystemTime, UNIX_EPOCH};
    let secs = SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .map(|d| d.as_secs())
        .unwrap_or(0);
    format!("{secs}")
}

fn dirs_home() -> Option<std::path::PathBuf> {
    if let Some(home) = std::env::var_os("HOME").map(std::path::PathBuf::from) {
        return Some(home);
    }
    // Windows: HOME is usually unset — fall back to USERPROFILE.
    std::env::var_os("USERPROFILE").map(std::path::PathBuf::from)
}

/// Cross-platform fallback for the app data root used by the panic hook
/// (no Tauri handle available there).
fn app_data_root_fallback() -> std::path::PathBuf {
    #[cfg(target_os = "windows")]
    {
        if let Some(appdata) = std::env::var_os("APPDATA").map(std::path::PathBuf::from) {
            return appdata.join("showMe");
        }
        if let Some(home) = dirs_home() {
            return home.join("AppData/Roaming/showMe");
        }
        return std::env::temp_dir().join("showMe");
    }
    #[cfg(target_os = "macos")]
    {
        if let Some(home) = dirs_home() {
            return home.join("Library/Application Support/showMe");
        }
        return std::env::temp_dir().join("showMe");
    }
    #[cfg(not(any(target_os = "windows", target_os = "macos")))]
    {
        if let Ok(xdg) = std::env::var("XDG_DATA_HOME") {
            return std::path::PathBuf::from(xdg).join("showMe");
        }
        if let Some(home) = dirs_home() {
            return home.join(".local/share/showMe");
        }
        return std::env::temp_dir().join("showMe");
    }
}

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    install_panic_hook();
    let state = AppState::default();

    tauri::Builder::default()
        .plugin(tauri_plugin_shell::init())
        .plugin(tauri_plugin_fs::init())
        .plugin(tauri_plugin_dialog::init())
        .plugin(tauri_plugin_notification::init())
        .plugin(tauri_plugin_os::init())
        .plugin(tauri_plugin_process::init())
        .plugin(tauri_plugin_store::Builder::default().build())
        // TEST-10 P1 — explicit log target + per-env level + 10 MiB rotation.
        // Default builder shipped Info to both stdout and the bundle log file
        // with no rotation cap; on a long-running cockpit that is unbounded
        // disk growth.
        //
        // REL-04 P3 — KeepAll left 50+ rotated log files on disk after a
        // few weeks of normal use (10 MiB each → 500+ MiB just in logs).
        // Cap to the last 5 rotations so total log disk usage stays under
        // ~60 MiB (10 MiB live + 5 × 10 MiB rotated).
        .plugin(
            tauri_plugin_log::Builder::default()
                .targets([
                    Target::new(TargetKind::Stdout),
                    Target::new(TargetKind::LogDir { file_name: None }),
                ])
                .level(if cfg!(debug_assertions) {
                    log::LevelFilter::Debug
                } else {
                    log::LevelFilter::Info
                })
                .max_file_size(10 * 1024 * 1024) // 10 MiB
                .rotation_strategy(RotationStrategy::KeepSome(5))
                .build(),
        )
        .plugin(tauri_plugin_global_shortcut::Builder::new().build())
        .plugin(tauri_plugin_deep_link::init())
        .plugin(tauri_plugin_updater::Builder::new().build())
        .manage(state)
        .invoke_handler(tauri::generate_handler![
            commands::sidecar_status,
            commands::sidecar_port,
            commands::sidecar_auth_token,
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
            commands::open_devtools,
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
                window::persist_state(window.app_handle());
            }
        })
        .build(tauri::generate_context!())
        .expect("error while building tauri application")
        .run(|handle, event| {
            if let tauri::RunEvent::ExitRequested { .. } = event {
                // HNT-04 — Cmd+Q and the tray "Quit" item close windows
                // without a `CloseRequested` event, so geometry for every
                // open window is persisted here before teardown.
                window::persist_state(handle);
                sidecar::shutdown(handle);
            }
        });
}
