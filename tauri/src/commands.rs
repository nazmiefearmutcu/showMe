//! Tauri `invoke` commands exposed to the frontend.
//!
//! Each command is a thin façade — actual work lives in the corresponding
//! module (sidecar / dock / biometric / filesystem). Keep this file small
//! and the I/O boundaries flat.

use crate::{biometric, dock, notifications as notif, presets, AppState, SidecarHealth};
use serde::Serialize;
use serde_json::Value;
use std::fs;
use std::path::{Path, PathBuf};
use tauri::{AppHandle, Manager, Runtime, State, Window, WindowEvent};
use tauri_plugin_updater::UpdaterExt;

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
pub fn install_to_applications<R: Runtime>(app: AppHandle<R>) -> Result<InstallResult, String> {
    let source = current_app_bundle().ok_or("showMe.app bundle not found")?;
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

#[tauri::command]
pub fn request_biometric(reason: String) -> biometric::BiometricResult {
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
    match level.as_str() {
        "error" => log::error!("{msg}"),
        "warn" => log::warn!("{msg}"),
        "info" => log::info!("{msg}"),
        _ => log::debug!("{msg}"),
    }
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
    if app.get_webview_window(&label).is_some() {
        if let Some(w) = app.get_webview_window(&label) {
            let _ = w.show();
            let _ = w.set_focus();
        }
        return Ok(());
    }
    let url = url.unwrap_or_else(|| "/".to_string());
    let webview_url = tauri::WebviewUrl::App(url.into());
    let mut builder =
        tauri::webview::WebviewWindowBuilder::new(&app, &label, webview_url)
            .title(title.unwrap_or_else(|| "showMe".into()))
            .inner_size(width.unwrap_or(1200.0), height.unwrap_or(800.0))
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

fn cleanup_legacy_app_backups() {
    let Ok(entries) = fs::read_dir("/Applications") else {
        return;
    };
    for entry in entries.flatten() {
        let name = entry.file_name();
        let name = name.to_string_lossy();
        if name.starts_with("showMe.app.bak-") || name.starts_with("showMe.app.backup-") {
            let _ = remove_path(&entry.path());
        }
    }
    let _ = remove_path(Path::new("/Applications/showMe.app.backups"));
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
    let severity = match args.severity.as_deref() {
        Some("warn") => notif::Severity::Warn,
        Some("critical") => notif::Severity::Critical,
        _ => notif::Severity::Info,
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
    let path = workspace_state_path(&app, label.as_deref())?;
    if let Some(parent) = path.parent() {
        std::fs::create_dir_all(parent).map_err(|e| e.to_string())?;
    }
    let text = serde_json::to_string_pretty(&content).map_err(|e| e.to_string())?;
    std::fs::write(path, text).map_err(|e| e.to_string())
}

#[tauri::command]
pub fn load_workspace<R: Runtime>(
    app: AppHandle<R>,
    label: Option<String>,
) -> Result<Option<Value>, String> {
    let path = workspace_state_path(&app, label.as_deref())?;
    if !path.exists() {
        // Fall back to the legacy global file for one-time migration.
        let legacy = workspace_state_path(&app, Some("main"))?;
        if legacy != path && legacy.exists() {
            let text = std::fs::read_to_string(&legacy).map_err(|e| e.to_string())?;
            return serde_json::from_str(&text).map(Some).map_err(|e| e.to_string());
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
) -> Result<Option<String>, String> {
    #[cfg(target_os = "macos")]
    {
        crate::secrets::get_secret(&account)
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

#[tauri::command]
pub async fn run_migration<R: Runtime>(
    app: AppHandle<R>,
    engine_path: Option<String>,
    writable: Option<bool>,
) -> Result<Value, String> {
    let root = app
        .state::<AppState>()
        .data_root
        .read()
        .clone()
        .ok_or("data root not initialized")?;
    let target = root.join("data/portfolio.db");
    if let Some(parent) = target.parent() {
        std::fs::create_dir_all(parent).map_err(|e| e.to_string())?;
    }
    // Discover the sidecar's bundled python entry point. Round 22 just shells
    // out — Round 27+ might promote this to a direct Python import via the
    // already-running sidecar to avoid re-pickling state.
    let mut cmd = std::process::Command::new("python3");
    cmd.arg("-m").arg("showme.migration")
        .arg("--to")
        .arg(target.as_os_str());
    if let Some(p) = engine_path.as_deref() {
        cmd.arg("--engine").arg(p);
    }
    if writable.unwrap_or(false) {
        cmd.arg("--writable");
    }
    cmd.env("PYTHONUNBUFFERED", "1");
    // Run with the same cwd the dev sidecar uses so `showme.migration`
    // resolves; in release the bundled binary embeds it. Post-unification
    // the backend lives at <repo>/backend/.
    if let Ok(cwd) = std::env::current_dir() {
        cmd.current_dir(cwd.join("../backend"));
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

/// Round 28 — Apply the pending update.
///
/// Downloads the bundle, verifies the signature against the embedded pubkey,
/// then installs and exits the app so the OS relaunches the new build. We
/// surface progress to the frontend via the standard `tauri-plugin-updater`
/// events; consumers may listen on `updater://download-progress`.
#[tauri::command]
pub async fn apply_update<R: Runtime>(app: AppHandle<R>) -> Result<(), String> {
    let updater = app.updater().map_err(|e| e.to_string())?;
    let pending = updater
        .check()
        .await
        .map_err(|e| e.to_string())?
        .ok_or_else(|| "no update available".to_string())?;
    pending
        .download_and_install(
            |_chunk, _total| {},
            || {},
        )
        .await
        .map_err(|e| e.to_string())?;
    app.restart();
}
