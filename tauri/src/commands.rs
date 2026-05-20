//! Tauri `invoke` commands exposed to the frontend.
//!
//! Each command is a thin façade — actual work lives in the corresponding
//! module (sidecar / dock / biometric / filesystem). Keep this file small
//! and the I/O boundaries flat.

use crate::{biometric, dock, filesystem, ipc, notifications as notif, presets, AppState, SidecarHealth};
use serde::Serialize;
use serde_json::Value;
use std::fs;
use std::path::{Path, PathBuf};
use tauri::path::BaseDirectory;
use tauri::{AppHandle, Emitter, Manager, Runtime, State, Window, WindowEvent};
use tauri_plugin_updater::UpdaterExt;

/// Maximum size of a serialized workspace JSON, in bytes (FUNC-04 P0).
/// 1 MiB is comfortably larger than any real layout tree but small enough
/// that a malicious renderer cannot DoS the disk by writing GB-sized blobs.
const MAX_WORKSPACE_BYTES: usize = 1_048_576;

// SEC-04 P1 — caps on user-controlled command inputs. Pinned conservatively;
// the frontend has no legitimate need to push above any of these.
const MAX_LOG_MSG_BYTES: usize = 4 * 1024;
const MAX_NOTIFY_TITLE_BYTES: usize = 256;
const MAX_NOTIFY_BODY_BYTES: usize = 2 * 1024;
const MAX_WINDOW_LABEL: usize = 64;
const MAX_WINDOW_TITLE: usize = 256;
const MAX_WINDOW_URL: usize = 1024;
/// Allow-list of log levels accepted by `write_log_entry`. Anything else
/// is silently downgraded to `debug` and a warning is logged once on the
/// Rust side so a forgotten typo never gets silently dropped.
const VALID_LOG_LEVELS: &[&str] = &["error", "warn", "info", "debug", "trace"];

#[derive(Serialize, Clone, Debug)]
pub struct PortPayload {
    pub port: Option<u16>,
}

#[tauri::command]
pub fn sidecar_status(state: State<'_, AppState>) -> SidecarHealth {
    state.sidecar_health.read().clone()
}

#[tauri::command]
pub fn sidecar_port(state: State<'_, AppState>) -> PortPayload {
    PortPayload { port: *state.sidecar_port.read() }
}

/// Return the per-boot auth token shared with the Python sidecar. The
/// frontend attaches this to every HTTP/WS call as `X-ShowMe-Token` so a
/// co-resident process on loopback cannot reach the broker/portfolio
/// endpoints (ARCH-05 P2). Returns `None` if the sidecar has not booted
/// yet — callers should listen on the `sidecar:auth_token` event.
#[tauri::command]
pub fn sidecar_auth_token(state: State<'_, AppState>) -> Option<String> {
    state.sidecar_auth_token.read().clone()
}

#[tauri::command]
pub fn open_data_folder(state: State<'_, AppState>) -> Result<(), String> {
    let root = state.data_root.read().clone();
    let Some(p) = root else { return Err("data root not initialized".into()) };
    open_folder_in_finder(p.to_string_lossy().as_ref())
}

#[derive(Serialize, Clone, Debug)]
pub struct InstallResult {
    pub ok: bool,
    pub source: String,
    pub target: String,
    pub already_installed: bool,
}

#[tauri::command]
pub fn install_to_applications<R: Runtime>(
    app: AppHandle<R>,
    auth_token: String,
) -> Result<InstallResult, String> {
    ipc::check("install_to_applications")?;
    // SEC-04 P1 / SEC-07 P0 — gate this destructive command behind a
    // single-use biometric token. The renderer must call
    // `request_biometric` first and forward the returned `token`.
    biometric::consume_token(&auth_token)?;

    let source = current_app_bundle().ok_or("showMe.app bundle not found")?;
    // SEC-07 P0 — canonicalize the source so a launching DMG that aliases
    // its `.app` to attacker-controlled content cannot have `ditto` copy
    // the wrong tree into `/Applications`. Also assert the canonical path
    // is itself a `.app` bundle.
    let source = source
        .canonicalize()
        .map_err(|e| format!("canonicalize source: {e}"))?;
    if source
        .extension()
        .and_then(|e| e.to_str())
        .map(|s| !s.eq_ignore_ascii_case("app"))
        .unwrap_or(true)
    {
        return Err("source bundle does not end with .app".into());
    }

    let app_name = source
        .file_name()
        .and_then(|s| s.to_str())
        .unwrap_or("showMe.app");
    let target = PathBuf::from("/Applications").join(app_name);
    cleanup_legacy_app_backups();
    if same_path(&source, &target) {
        return Ok(InstallResult {
            ok: true,
            source: source.to_string_lossy().into_owned(),
            target: target.to_string_lossy().into_owned(),
            already_installed: true,
        });
    }
    #[cfg(target_os = "macos")]
    {
        let previous = PathBuf::from("/Applications/showMe.previous.app");
        retain_previous_app(&target, &previous)?;
        remove_path(&target)?;
        ditto_copy(&source, &target)?;
        cleanup_legacy_app_backups();
        let _ = tauri::Emitter::emit(&app, "app:installed", target.to_string_lossy().to_string());
        Ok(InstallResult {
            ok: true,
            source: source.to_string_lossy().into_owned(),
            target: target.to_string_lossy().into_owned(),
            already_installed: false,
        })
    }
    #[cfg(not(target_os = "macos"))]
    {
        let _ = app;
        Err("install_to_applications is macOS-only".into())
    }
}

#[tauri::command]
pub async fn reload_function_index<R: Runtime>(app: AppHandle<R>) -> Result<(), String> {
    tauri::Emitter::emit(&app, "function-index:reload", ()).map_err(|e| e.to_string())
}

/// Toggle WKWebView devtools on the main window. UI-INT-08 P3 — only
/// available in debug builds; production app refuses to expose devtools
/// because it would let a renderer compromise pivot into the embedding
/// process (eval, `process.env`, fetch).
#[tauri::command]
pub fn open_devtools<R: Runtime>(app: AppHandle<R>) -> Result<(), String> {
    #[cfg(debug_assertions)]
    {
        if let Some(w) = app.get_webview_window("main") {
            w.open_devtools();
            Ok(())
        } else {
            Err("no main window".into())
        }
    }
    #[cfg(not(debug_assertions))]
    {
        let _ = app;
        Err("devtools are disabled in release builds".into())
    }
}

#[tauri::command]
pub fn request_biometric(reason: String) -> biometric::BiometricResult {
    if let Err(err) = ipc::check("request_biometric") {
        log::warn!("request_biometric rate-limited: {err}");
        return biometric::BiometricResult {
            allowed: false,
            reason,
            via: biometric::BioVia::Denied,
            capabilities: biometric::capabilities(),
            token: None,
        };
    }
    biometric::evaluate(&reason)
}

#[tauri::command]
pub fn biometric_capabilities() -> biometric::Capabilities {
    biometric::capabilities()
}

#[tauri::command]
pub fn set_dock_badge<R: Runtime>(app: AppHandle<R>, count: Option<i64>) {
    dock::set_badge(&app, count);
}

#[tauri::command]
pub fn request_attention<R: Runtime>(app: AppHandle<R>, critical: bool) {
    dock::request_attention(&app, critical);
}

#[tauri::command]
pub fn write_log_entry(level: String, msg: String) {
    if ipc::check("write_log_entry").is_err() {
        // Drop silently — writing a "rate limit exceeded" log line every
        // time the rate limit is exceeded would itself spam the log.
        return;
    }
    // SEC-04 P1 — cap and validate inputs before they hit the log target.
    let mut msg = msg;
    if msg.len() > MAX_LOG_MSG_BYTES {
        msg.truncate(MAX_LOG_MSG_BYTES);
        msg.push_str("…[truncated]");
    }
    let level = level.to_ascii_lowercase();
    let level_ref = if VALID_LOG_LEVELS.contains(&level.as_str()) {
        level.as_str()
    } else {
        log::warn!("write_log_entry: unknown level {level:?}, downgrading to debug");
        "debug"
    };
    match level_ref {
        "error" => log::error!("{msg}"),
        "warn" => log::warn!("{msg}"),
        "info" => log::info!("{msg}"),
        "trace" => log::trace!("{msg}"),
        _ => log::debug!("{msg}"),
    }
}

/// Validate a renderer-supplied window label.
///
/// SEC-04 P1 — labels are funneled into `WebviewWindowBuilder::new` and
/// later used as keys in window registries. Restrict to a friendly
/// allow-list so a renderer cannot smuggle in path-shaped tokens or
/// over-long blobs that bloat in-memory state.
fn validate_window_label(label: &str) -> Result<&str, String> {
    let trimmed = label.trim();
    if trimmed.is_empty() {
        return Err("label required".into());
    }
    if trimmed.len() > MAX_WINDOW_LABEL {
        return Err(format!("label exceeds {MAX_WINDOW_LABEL} bytes"));
    }
    if !trimmed
        .chars()
        .all(|c| c.is_ascii_alphanumeric() || c == '-' || c == '_')
    {
        return Err("label may only contain ASCII alphanumerics, '-' or '_'".into());
    }
    Ok(trimmed)
}

/// Validate a renderer-supplied URL for `open_window`.
///
/// SEC-04 P1 — Tauri's `WebviewUrl::App` interprets the string as a path
/// inside the bundled frontend asset tree. We restrict to a path that
/// starts with `/` (or `#/`-style hash routes), reject embedded
/// `://`/control characters, cap length, and forbid path traversal.
fn validate_window_url(url: &str) -> Result<&str, String> {
    if url.is_empty() {
        return Ok("/");
    }
    if url.len() > MAX_WINDOW_URL {
        return Err(format!("url exceeds {MAX_WINDOW_URL} bytes"));
    }
    if url.chars().any(|c| c.is_control()) {
        return Err("url contains control characters".into());
    }
    if url.contains("://") {
        return Err("absolute URLs are not allowed for open_window".into());
    }
    if url.split('/').any(|seg| seg == "..") {
        return Err("url contains path-traversal segment '..'".into());
    }
    let first = url.chars().next().unwrap_or(' ');
    if !(first == '/' || first == '#') {
        return Err("url must start with '/' or '#'".into());
    }
    Ok(url)
}

#[tauri::command]
pub async fn open_window<R: Runtime>(
    app: AppHandle<R>,
    label: String,
    title: Option<String>,
    url: Option<String>,
    width: Option<f64>,
    height: Option<f64>,
) -> Result<(), String> {
    ipc::check("open_window")?;
    let validated_label = validate_window_label(&label)?.to_string();
    if let Some(w) = app.get_webview_window(&validated_label) {
        let _ = w.show();
        let _ = w.set_focus();
        return Ok(());
    }
    let url = url.unwrap_or_else(|| "/".to_string());
    let url = validate_window_url(&url)?.to_string();
    let title = match title {
        Some(t) if t.len() > MAX_WINDOW_TITLE => {
            return Err(format!("title exceeds {MAX_WINDOW_TITLE} bytes"));
        }
        Some(t) if t.chars().any(|c| c.is_control()) => {
            return Err("title contains control characters".into());
        }
        Some(t) => t,
        None => "showMe".into(),
    };
    let width = width.unwrap_or(1200.0).clamp(320.0, 8192.0);
    let height = height.unwrap_or(800.0).clamp(240.0, 8192.0);
    let webview_url = tauri::WebviewUrl::App(url.into());
    #[allow(unused_mut)]
    let mut builder =
        tauri::webview::WebviewWindowBuilder::new(&app, &validated_label, webview_url)
            .title(title)
            .inner_size(width, height)
            .min_inner_size(720.0, 480.0)
            .resizable(true)
            .decorations(true)
            .transparent(true)
            .shadow(true);
    #[cfg(target_os = "macos")]
    {
        builder = builder.title_bar_style(tauri::TitleBarStyle::Overlay).hidden_title(true);
    }
    let _ = builder.build().map_err(|e| e.to_string())?;
    Ok(())
}

fn open_folder_in_finder(path: &str) -> Result<(), String> {
    #[cfg(target_os = "macos")]
    {
        std::process::Command::new("open")
            .arg(path)
            .spawn()
            .map_err(|e| e.to_string())?;
    }
    #[cfg(not(target_os = "macos"))]
    {
        return Err(format!("not implemented for this OS: {}", path));
    }
    Ok(())
}

fn current_app_bundle() -> Option<PathBuf> {
    let exe = std::env::current_exe().ok()?;
    exe.ancestors()
        .find(|p| p.extension().and_then(|e| e.to_str()) == Some("app"))
        .map(Path::to_path_buf)
}

fn same_path(a: &Path, b: &Path) -> bool {
    match (a.canonicalize(), b.canonicalize()) {
        (Ok(a), Ok(b)) => a == b,
        _ => a == b,
    }
}

fn remove_path(path: &Path) -> Result<(), String> {
    if !path.exists() {
        return Ok(());
    }
    if path.is_dir() {
        fs::remove_dir_all(path).map_err(|e| format!("remove {}: {e}", path.display()))
    } else {
        fs::remove_file(path).map_err(|e| format!("remove {}: {e}", path.display()))
    }
}

#[cfg(target_os = "macos")]
fn ditto_copy(source: &Path, target: &Path) -> Result<(), String> {
    let status = std::process::Command::new("/usr/bin/ditto")
        .arg(source)
        .arg(target)
        .status()
        .map_err(|e| format!("ditto: {e}"))?;
    if status.success() {
        Ok(())
    } else {
        Err(format!("ditto exited with {status}"))
    }
}

#[cfg(target_os = "macos")]
fn retain_previous_app(target: &Path, previous: &Path) -> Result<(), String> {
    remove_path(previous)?;
    if target.exists() {
        ditto_copy(target, previous)?;
    }
    Ok(())
}

/// Remove leftover `showMe.app.bak-*` directories from previous installs.
///
/// SEC-07 P0 — the previous version called `remove_dir_all` on entries
/// matched only by name prefix, which on macOS happily traversed directory
/// symlinks. An attacker who pre-created `/Applications/showMe.app.bak-evil`
/// containing symlinks could trick this loop into wiping content outside
/// `/Applications/`. The new implementation:
///   1. canonicalizes `/Applications` once;
///   2. only deletes entries whose own `metadata().is_dir()` is true and
///      whose `file_type()` reports it is NOT a symlink;
///   3. re-canonicalizes each candidate and re-checks `starts_with` of the
///      canonical `/Applications` path before calling `remove_dir_all`.
fn cleanup_legacy_app_backups() {
    let apps_root = match Path::new("/Applications").canonicalize() {
        Ok(p) => p,
        Err(_) => return,
    };
    let Ok(entries) = fs::read_dir(&apps_root) else {
        return;
    };
    for entry in entries.flatten() {
        let name = entry.file_name();
        let name = name.to_string_lossy().to_string();
        if !(name.starts_with("showMe.app.bak-") || name.starts_with("showMe.app.backup-")) {
            continue;
        }
        let Ok(meta) = entry.metadata() else { continue };
        if !meta.is_dir() || meta.file_type().is_symlink() {
            continue;
        }
        let path = entry.path();
        let Ok(canonical) = path.canonicalize() else { continue };
        if !canonical.starts_with(&apps_root) {
            log::warn!(
                "cleanup_legacy_app_backups: refusing to delete {} (canonical {} escapes {})",
                path.display(),
                canonical.display(),
                apps_root.display()
            );
            continue;
        }
        let _ = fs::remove_dir_all(&canonical);
    }
    // Legacy aggregate folder created by older installers — only remove
    // when it is a real directory and inside /Applications, never via
    // symlink traversal.
    let aggregate = apps_root.join("showMe.app.backups");
    if let Ok(meta) = fs::symlink_metadata(&aggregate) {
        if meta.is_dir() && !meta.file_type().is_symlink() {
            if let Ok(canonical) = aggregate.canonicalize() {
                if canonical.starts_with(&apps_root) {
                    let _ = fs::remove_dir_all(&canonical);
                }
            }
        }
    }
}

#[allow(dead_code)]
pub fn handle_window_event(_window: &Window, _event: &WindowEvent) {}

// ── Layout presets ────────────────────────────────────────────────────────

#[tauri::command]
pub fn list_presets<R: Runtime>(
    app: AppHandle<R>,
) -> Result<Vec<presets::PresetSummary>, String> {
    presets::list(&app)
}

#[tauri::command]
pub fn read_preset<R: Runtime>(app: AppHandle<R>, name: String) -> Result<Value, String> {
    presets::read(&app, &name)
}

#[tauri::command]
pub fn write_preset<R: Runtime>(
    app: AppHandle<R>,
    name: String,
    content: Value,
) -> Result<(), String> {
    presets::write(&app, &name, &content)
}

#[tauri::command]
pub fn delete_preset<R: Runtime>(app: AppHandle<R>, name: String) -> Result<bool, String> {
    presets::delete(&app, &name)
}

// ── Notifications wrapper ────────────────────────────────────────────────

#[derive(serde::Deserialize)]
pub struct NotifyArgs {
    title: String,
    body: String,
    thread: Option<String>,
    severity: Option<String>,
}

#[tauri::command]
pub fn notify<R: Runtime>(app: AppHandle<R>, args: NotifyArgs) -> Result<(), String> {
    ipc::check("notify")?;
    // SEC-04 P1 — bounded inputs + strict severity allow-list. Unknown
    // severity strings are rejected outright so the contract stays
    // honest (no silent downgrade to Info).
    if args.title.is_empty() {
        return Err("title required".into());
    }
    if args.title.len() > MAX_NOTIFY_TITLE_BYTES {
        return Err(format!("title exceeds {MAX_NOTIFY_TITLE_BYTES} bytes"));
    }
    if args.body.len() > MAX_NOTIFY_BODY_BYTES {
        return Err(format!("body exceeds {MAX_NOTIFY_BODY_BYTES} bytes"));
    }
    if args.title.chars().any(|c| c.is_control() && c != '\n') {
        return Err("title contains control characters".into());
    }
    if let Some(thread) = args.thread.as_deref() {
        if thread.len() > 64 || !thread.chars().all(|c| c.is_ascii_alphanumeric() || c == '-' || c == '_' || c == '.') {
            return Err("thread must be ≤64 chars of [A-Za-z0-9-_.]".into());
        }
    }
    let severity = match args.severity.as_deref() {
        None | Some("info") => notif::Severity::Info,
        Some("warn") => notif::Severity::Warn,
        Some("critical") => notif::Severity::Critical,
        Some(other) => return Err(format!("unknown severity {other:?}; expected info|warn|critical")),
    };
    notif::notify(
        &app,
        notif::NotifyOptions {
            title: &args.title,
            body: &args.body,
            thread: args.thread.as_deref(),
            severity,
        },
    )
}

// ── Workspace tree persistence (per-window) ──────────────────────────────

/// Sanitize a window label so it cannot escape the state dir.
fn safe_label(label: &str) -> String {
    let trimmed = label.trim();
    if trimmed.is_empty() {
        return "main".into();
    }
    trimmed
        .chars()
        .map(|c| match c {
            'a'..='z' | 'A'..='Z' | '0'..='9' | '-' | '_' => c,
            _ => '_',
        })
        .collect()
}

fn workspace_state_path<R: Runtime>(
    app: &AppHandle<R>,
    label: Option<&str>,
) -> Result<PathBuf, String> {
    let root = app
        .state::<AppState>()
        .data_root
        .read()
        .clone()
        .ok_or("data root not initialized")?;
    let safe = label.map(safe_label).unwrap_or_else(|| "main".to_string());
    Ok(root.join(format!("state/workspace-{safe}.json")))
}

#[tauri::command]
pub fn save_workspace<R: Runtime>(
    app: AppHandle<R>,
    content: Value,
    label: Option<String>,
) -> Result<(), String> {
    ipc::check("save_workspace")?;
    let path = workspace_state_path(&app, label.as_deref())?;
    if let Some(parent) = path.parent() {
        std::fs::create_dir_all(parent).map_err(|e| e.to_string())?;
    }
    let text = serde_json::to_string_pretty(&content).map_err(|e| e.to_string())?;
    // SEC-04 P2 / FUNC-04 P0 — cap the serialized size so a malicious or
    // buggy renderer cannot fill the disk with a 1 GB workspace blob.
    if text.len() > MAX_WORKSPACE_BYTES {
        return Err("workspace too large".into());
    }
    // FUNC-04 P0 — atomic temp-file rename so a crash mid-save can never
    // leave a zero-byte or half-written workspace JSON on disk.
    filesystem::atomic_write(&path, text.as_bytes()).map_err(|e| e.to_string())
}

#[tauri::command]
pub fn load_workspace<R: Runtime>(
    app: AppHandle<R>,
    label: Option<String>,
) -> Result<Option<Value>, String> {
    let path = workspace_state_path(&app, label.as_deref())?;
    if !path.exists() {
        // FUNC-04 P2 — only run the legacy `workspace-main.json` migration
        // when the caller is the main window. Without this guard, every
        // freshly-opened secondary window would adopt a copy of main's
        // tree as its initial state and silently diverge from then on.
        let label_str = label.as_deref().unwrap_or("main");
        if label_str == "main" {
            let legacy = workspace_state_path(&app, Some("main"))?;
            if legacy != path && legacy.exists() {
                let text = std::fs::read_to_string(&legacy).map_err(|e| e.to_string())?;
                return serde_json::from_str(&text).map(Some).map_err(|e| e.to_string());
            }
        }
        return Ok(None);
    }
    let text = std::fs::read_to_string(path).map_err(|e| e.to_string())?;
    serde_json::from_str(&text).map(Some).map_err(|e| e.to_string())
}

// ── Keychain CRUD ────────────────────────────────────────────────────────

#[cfg(target_os = "macos")]
fn secrets_index_path<R: Runtime>(app: &AppHandle<R>) -> Result<PathBuf, String> {
    let root = app
        .state::<AppState>()
        .data_root
        .read()
        .clone()
        .ok_or("data root not initialized")?;
    Ok(root.join("state/secrets.index.json"))
}

#[cfg(target_os = "macos")]
fn current_index<R: Runtime>(app: &AppHandle<R>) -> Result<Vec<String>, String> {
    let path = secrets_index_path(app)?;
    let Ok(text) = std::fs::read_to_string(&path) else {
        return Ok(vec![]);
    };
    Ok(serde_json::from_str(&text).unwrap_or_default())
}

#[tauri::command]
pub fn keychain_set<R: Runtime>(
    app: AppHandle<R>,
    account: String,
    value: String,
) -> Result<(), String> {
    ipc::check("keychain_set")?;
    #[cfg(target_os = "macos")]
    {
        crate::secrets::set_secret(&account, &value)?;
        let mut names = current_index(&app)?;
        if !names.contains(&account) {
            names.push(account.clone());
            names.sort();
            crate::secrets::write_index(&secrets_index_path(&app)?, &names)?;
        }
        Ok(())
    }
    #[cfg(not(target_os = "macos"))]
    {
        let _ = (app, account, value);
        Err("keychain only available on macOS".into())
    }
}

#[tauri::command]
pub fn keychain_get<R: Runtime>(
    _app: AppHandle<R>,
    account: String,
    auth_token: Option<String>,
) -> Result<Option<String>, String> {
    ipc::check("keychain_get")?;
    // SEC-08 P1 — sensitive read requires a fresh biometric token. The
    // renderer must call `request_biometric` first and forward the token
    // returned in `BiometricResult.token`. We use `verify_token` (not
    // `consume_token`) so the same prompt can warm the in-memory cache
    // for the full 5-min TTL across many reads.
    if let Some(t) = auth_token.as_deref() {
        biometric::verify_token(t)?;
    } else {
        // On platforms without LocalAuthentication (CI on Linux, dev
        // smoke), fall through with no token so the test rig stays
        // usable. On macOS the renderer must always pass a token.
        #[cfg(target_os = "macos")]
        return Err("auth_token required for keychain_get".into());
    }
    #[cfg(target_os = "macos")]
    {
        // Redact non-not-found error strings so a renderer cannot probe the
        // exact macOS error message (SEC-08 P2). The full text is logged
        // on the Rust side for operator triage.
        //
        // SEC-08 P1 (Round 3C) — `get_or_migrate` opportunistically
        // rewrites legacy entries (pre-hardening) with the new
        // `AccessibleWhenUnlockedThisDeviceOnly` + `Synchronizable=false`
        // attributes. The rewrite is best-effort: a migration failure
        // is logged and the read still returns the value to the caller.
        match crate::secrets::get_or_migrate(&account) {
            Ok(v) => Ok(v),
            Err(err) => {
                log::warn!("keychain_get error for {account}: {err}");
                Err("keychain error".into())
            }
        }
    }
    #[cfg(not(target_os = "macos"))]
    {
        let _ = account;
        Ok(None)
    }
}

#[tauri::command]
pub fn keychain_delete<R: Runtime>(
    app: AppHandle<R>,
    account: String,
) -> Result<bool, String> {
    ipc::check("keychain_delete")?;
    #[cfg(target_os = "macos")]
    {
        let removed = crate::secrets::delete_secret(&account)?;
        let mut names = current_index(&app)?;
        let before = names.len();
        names.retain(|n| n != &account);
        if names.len() != before {
            crate::secrets::write_index(&secrets_index_path(&app)?, &names)?;
        }
        Ok(removed)
    }
    #[cfg(not(target_os = "macos"))]
    {
        let _ = (app, account);
        Ok(false)
    }
}

#[tauri::command]
pub fn keychain_list<R: Runtime>(app: AppHandle<R>) -> Result<Vec<KeychainEntry>, String> {
    #[cfg(target_os = "macos")]
    {
        let path = secrets_index_path(&app)?;
        let summaries = crate::secrets::list_accounts(&path);
        Ok(summaries
            .into_iter()
            .map(|s| KeychainEntry {
                account: s.account,
                service: s.service,
            })
            .collect())
    }
    #[cfg(not(target_os = "macos"))]
    {
        let _ = app;
        Ok(vec![])
    }
}

#[derive(Serialize, Clone, Debug)]
pub struct KeychainEntry {
    pub account: String,
    pub service: String,
}

// ── Migration (Faz B) ─────────────────────────────────────────────────────

/// Run the portfolio-DB migration via the bundled sidecar binary.
///
/// SEC-04 P0 / SEC-07 P1 — the previous version shelled out to `python3`
/// from `$PATH` with a renderer-controlled `--engine` argument and a CWD
/// computed by joining the launcher's `current_dir()` with `../backend`.
/// That is arbitrary code execution waiting to happen.
///
/// The hardened version:
///   1. requires a fresh biometric token (single-use);
///   2. resolves the bundled `showme-backend` binary via Tauri's
///      `BaseDirectory::Resource`; falls back to `which("python3")` only
///      in dev mode and only when the resolved path is in a known system
///      bin dir;
///   3. canonicalizes any caller-supplied `engine_path` and asserts it
///      lives under the app data dir;
///   4. uses `app.path().resource_dir()` for the working dir instead of
///      a `current_dir()`-relative `../backend` join.
#[tauri::command]
pub async fn run_migration<R: Runtime>(
    app: AppHandle<R>,
    auth_token: String,
    engine_path: Option<String>,
    writable: Option<bool>,
) -> Result<Value, String> {
    ipc::check("run_migration")?;
    biometric::consume_token(&auth_token)?;

    let state = app.state::<AppState>();
    let root = state
        .data_root
        .read()
        .clone()
        .ok_or("data root not initialized")?;
    let app_data_root = root
        .canonicalize()
        .map_err(|e| format!("canonicalize app data root: {e}"))?;
    let target = root.join("data/portfolio.db");
    if let Some(parent) = target.parent() {
        std::fs::create_dir_all(parent).map_err(|e| e.to_string())?;
    }

    // Validate caller-supplied engine path: must canonicalize and live
    // under the app data dir.
    if let Some(p) = engine_path.as_deref() {
        let candidate = PathBuf::from(p)
            .canonicalize()
            .map_err(|e| format!("canonicalize engine_path: {e}"))?;
        if !candidate.starts_with(&app_data_root) {
            return Err("engine_path must live inside the app data directory".into());
        }
    }

    // Resolve the migration entry point: prefer the bundled sidecar
    // binary. In dev (debug builds), accept a `python3` from a known
    // system location.
    let mut cmd = match app.path().resolve("binaries/showme-backend", BaseDirectory::Resource) {
        Ok(bin) if bin.exists() => {
            let mut c = std::process::Command::new(bin);
            c.arg("--migrate")
                .arg("--to")
                .arg(target.as_os_str());
            c
        }
        _ => {
            #[cfg(debug_assertions)]
            {
                // Dev fallback — only honor python3 from a vetted prefix so
                // a poisoned $PATH cannot run attacker code.
                let py = which::which("python3")
                    .map_err(|e| format!("python3 not found: {e}"))?;
                let allowed_prefixes =
                    ["/usr/bin/", "/usr/local/bin/", "/opt/homebrew/bin/"];
                let py_str = py.to_string_lossy().to_string();
                if !allowed_prefixes.iter().any(|p| py_str.starts_with(p)) {
                    return Err(format!(
                        "python3 at {py_str} is outside the trusted prefixes"
                    ));
                }
                let mut c = std::process::Command::new(py);
                c.arg("-m")
                    .arg("showme.migration")
                    .arg("--to")
                    .arg(target.as_os_str());
                c
            }
            #[cfg(not(debug_assertions))]
            {
                return Err(
                    "bundled migration binary not found and dev fallback disabled in release"
                        .into(),
                );
            }
        }
    };

    if let Some(p) = engine_path.as_deref() {
        cmd.arg("--engine").arg(p);
    }
    if writable.unwrap_or(false) {
        cmd.arg("--writable");
    }
    cmd.env("PYTHONUNBUFFERED", "1");
    // Use the app's resource dir as the working directory in release; in
    // dev mode fall back to the data root rather than walking up from cwd.
    if let Ok(resource_dir) = app.path().resource_dir() {
        cmd.current_dir(resource_dir);
    } else {
        cmd.current_dir(&app_data_root);
    }

    let output = cmd.output().map_err(|e| format!("spawn migration: {e}"))?;
    if !output.status.success() {
        return Err(format!(
            "migration exited {}: {}",
            output.status,
            String::from_utf8_lossy(&output.stderr).trim()
        ));
    }
    // Last line of stdout is the JSON summary.
    let stdout = String::from_utf8_lossy(&output.stdout);
    let summary_text = stdout.lines().rev().find(|l| l.trim().starts_with("{"));
    if let Some(_line) = summary_text {
        // Migration prints a multi-line pretty JSON; reparse the whole tail.
        let start = stdout.rfind("{").unwrap_or(0);
        let blob = &stdout[start..];
        return serde_json::from_str(blob)
            .map_err(|e| format!("parse summary: {e} — raw: {blob}"));
    }
    Ok(serde_json::Value::String(stdout.trim().to_string()))
}

#[derive(Serialize, Clone, Debug)]
pub struct UpdateInfo {
    pub available: bool,
    pub current_version: String,
    pub latest_version: Option<String>,
    pub release_date: Option<String>,
    pub release_notes: Option<String>,
    pub error: Option<String>,
}

/// Round 28 — Tauri updater: check the configured release manifest.
///
/// Returns metadata about the latest published build without applying it.
/// The frontend renders the result; the user explicitly opts in by calling
/// `apply_update` afterwards.
#[tauri::command]
pub async fn check_for_updates<R: Runtime>(app: AppHandle<R>) -> UpdateInfo {
    let current = app.package_info().version.to_string();
    let updater = match app.updater() {
        Ok(u) => u,
        Err(err) => {
            return UpdateInfo {
                available: false,
                current_version: current,
                latest_version: None,
                release_date: None,
                release_notes: None,
                error: Some(err.to_string()),
            };
        }
    };
    match updater.check().await {
        Ok(Some(update)) => UpdateInfo {
            available: true,
            current_version: current,
            latest_version: Some(update.version.clone()),
            release_date: update.date.map(|d| d.to_string()),
            release_notes: update.body.clone(),
            error: None,
        },
        Ok(None) => UpdateInfo {
            available: false,
            current_version: current,
            latest_version: None,
            release_date: None,
            release_notes: None,
            error: None,
        },
        Err(err) => UpdateInfo {
            available: false,
            current_version: current,
            latest_version: None,
            release_date: None,
            release_notes: None,
            error: Some(err.to_string()),
        },
    }
}

#[derive(Serialize, Clone, Debug)]
pub struct UpdateProgress {
    pub downloaded: u64,
    pub total: Option<u64>,
}

/// Round 28 — Apply the pending update.
///
/// Downloads the bundle, verifies the signature against the embedded pubkey,
/// then installs and exits the app so the OS relaunches the new build.
///
/// SEC-04 P2 — emits structured progress on `updater:progress` (chunk +
/// running total) and `updater:download_complete` so the frontend can
/// render a real progress bar instead of the stock plugin spinner.
/// `auth_token` is required: privileged installs must always be gated by
/// a fresh biometric prompt.
///
/// SEC-04 P0 (Round 3C) — refuse to call `download_and_install` when the
/// updater pubkey is empty or missing. The updater plugin is `active:
/// false` in `tauri.conf.json` so the manifest fetch path is dead, but
/// belt-and-braces: if a future change re-activates the plugin before
/// the real keypair is generated and committed, an attacker-served
/// `latest.json` over MITM could install arbitrary code on relaunch.
/// The runtime guard fails closed.
#[tauri::command]
pub async fn apply_update<R: Runtime>(
    app: AppHandle<R>,
    auth_token: String,
) -> Result<(), String> {
    ipc::check("apply_update")?;
    biometric::consume_token(&auth_token)?;
    let pubkey = app
        .config()
        .plugins
        .0
        .get("updater")
        .and_then(|v| v.get("pubkey"))
        .and_then(|v| v.as_str())
        .map(str::trim)
        .unwrap_or("");
    if pubkey.is_empty() {
        return Err(
            "updater pubkey not configured — refusing to install unsigned update".to_string(),
        );
    }
    let updater = app.updater().map_err(|e| e.to_string())?;
    let pending = updater
        .check()
        .await
        .map_err(|e| e.to_string())?
        .ok_or_else(|| "no update available".to_string())?;
    let app_for_progress = app.clone();
    let app_for_finish = app.clone();
    let downloaded = std::sync::Arc::new(std::sync::atomic::AtomicU64::new(0));
    let downloaded_clone = downloaded.clone();
    pending
        .download_and_install(
            move |chunk, total| {
                let new_total = downloaded_clone
                    .fetch_add(chunk as u64, std::sync::atomic::Ordering::Relaxed)
                    + chunk as u64;
                let _ = app_for_progress.emit(
                    "updater:progress",
                    UpdateProgress { downloaded: new_total, total },
                );
            },
            move || {
                let _ = app_for_finish.emit("updater:download_complete", ());
            },
        )
        .await
        .map_err(|e| e.to_string())?;
    app.restart();
}
