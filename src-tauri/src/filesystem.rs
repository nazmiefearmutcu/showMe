//! Layout under `~/Library/Application Support/showMe`.
//!
//! Created on first launch; idempotent thereafter. Symlinks `Logs/showMe`
//! into `~/Library/Logs/showMe` so Console.app can stream them.

use crate::AppState;
use std::path::PathBuf;
use tauri::Manager;

pub fn ensure_layout(app: &tauri::App) -> tauri::Result<()> {
    let resolver = app.path();
    let root = resolver.app_data_dir()?; // ~/Library/Application Support/showMe
    let subs = [
        "data/duckdb",
        "data/sqlite",
        "data/parquet",
        "cache",
        "logs",
        "logs/crash",
        "config",
        "state",
        "state/scans",
        "state/layout-presets",
    ];
    for s in subs {
        let p = root.join(s);
        if !p.exists() {
            std::fs::create_dir_all(&p)?;
        }
    }

    // Surface logs in Console.app via ~/Library/Logs/showMe.
    if let Some(home) = dirs_home() {
        let console_link = home.join("Library/Logs/showMe");
        let logs_dir = root.join("logs");
        if !console_link.exists() {
            #[cfg(unix)]
            let _ = std::os::unix::fs::symlink(&logs_dir, &console_link);
        }
    }

    let state = app.state::<AppState>();
    *state.data_root.write() = Some(root);
    Ok(())
}

fn dirs_home() -> Option<PathBuf> {
    std::env::var_os("HOME").map(PathBuf::from)
}
