//! Layout under `~/Library/Application Support/showMe`.
//!
//! Created on first launch; idempotent thereafter. Symlinks `Logs/showMe`
//! into `~/Library/Logs/showMe` so Console.app can stream them.

use crate::AppState;
use std::path::{Path, PathBuf};
use tauri::Manager;

/// Atomic write helper: write to a temp file in the same directory, fsync,
/// then rename into place. Mirrors the Python `state_store.py` pattern so
/// crashes/power-loss can never leave a half-written JSON file on disk.
/// FUNC-04 P0.
///
/// SEC-07 P1 — also enforces tight file permissions (0o600) on Unix so the
/// produced file is readable only by the current user.
pub fn atomic_write<P: AsRef<Path>>(path: P, contents: &[u8]) -> std::io::Result<()> {
    let path = path.as_ref();
    let parent = path.parent().ok_or_else(|| {
        std::io::Error::new(std::io::ErrorKind::InvalidInput, "no parent")
    })?;
    std::fs::create_dir_all(parent)?;
    let mut tmp = tempfile::NamedTempFile::new_in(parent)?;
    use std::io::Write as _;
    tmp.write_all(contents)?;
    tmp.as_file().sync_all()?;
    #[cfg(unix)]
    {
        use std::os::unix::fs::PermissionsExt;
        let mut perms = tmp.as_file().metadata()?.permissions();
        perms.set_mode(0o600);
        tmp.as_file().set_permissions(perms)?;
    }
    tmp.persist(path).map_err(|e| e.error)?;
    // best-effort fsync of parent dir
    if let Ok(dir) = std::fs::File::open(parent) {
        let _ = dir.sync_all();
    }
    Ok(())
}

pub fn ensure_layout(app: &tauri::App) -> tauri::Result<()> {
    let resolver = app.path();
    let root = resolver.app_data_dir()?; // ~/Library/Application Support/showMe

    // SEC-07 — refuse to scribble into source-tree-relative paths in
    // shipped (release) builds. If somehow the OS hands us a Desktop
    // path (e.g. an over-eager symlink, a misconfigured launcher),
    // bail loudly rather than silently writing over the developer's
    // working tree. Debug builds tolerate it for ergonomic dev runs.
    #[cfg(not(debug_assertions))]
    {
        let p = root.to_string_lossy();
        if p.contains("/Desktop/Projeler/") || p.contains("/Desktop/proje/") {
            return Err(tauri::Error::Io(std::io::Error::new(
                std::io::ErrorKind::PermissionDenied,
                format!("refusing to use developer source-tree path as data root: {p}"),
            )));
        }
    }
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
    //
    // SEC-07 P1 — verify the link target before trusting it. If a
    // pre-existing entry at the link path is anything other than a
    // symlink whose canonical target equals our `logs/` directory, we
    // refuse to use it. That stops an attacker who pre-creates
    // `~/Library/Logs/showMe` as a symlink into `/etc` from receiving
    // every line we write.
    if let Some(home) = dirs_home() {
        let console_link = home.join("Library/Logs/showMe");
        let logs_dir = root.join("logs");
        let canonical_logs = logs_dir.canonicalize().unwrap_or_else(|_| logs_dir.clone());
        match std::fs::symlink_metadata(&console_link) {
            Ok(meta) => {
                if meta.file_type().is_symlink() {
                    if let Ok(target) = std::fs::read_link(&console_link) {
                        let canonical_target = target.canonicalize().unwrap_or(target);
                        if canonical_target != canonical_logs {
                            log::warn!(
                                "filesystem: refusing to keep ~/Library/Logs/showMe → {}; expected {}",
                                canonical_target.display(),
                                canonical_logs.display()
                            );
                            // Best-effort relink: only remove if we can prove the
                            // current link points elsewhere; never touch a
                            // non-symlink directory of the same name.
                            let _ = std::fs::remove_file(&console_link);
                            #[cfg(unix)]
                            let _ = std::os::unix::fs::symlink(&logs_dir, &console_link);
                        }
                    }
                } else {
                    log::warn!(
                        "filesystem: ~/Library/Logs/showMe exists and is not a symlink; refusing to overwrite"
                    );
                }
            }
            Err(_) => {
                #[cfg(unix)]
                let _ = std::os::unix::fs::symlink(&logs_dir, &console_link);
            }
        }
    }

    let state = app.state::<AppState>();
    *state.data_root.write() = Some(root);
    Ok(())
}

fn dirs_home() -> Option<PathBuf> {
    std::env::var_os("HOME").map(PathBuf::from)
}
