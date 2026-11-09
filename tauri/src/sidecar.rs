//! Python sidecar lifecycle.
//!
//! Boot policy:
//! - `tauri::Builder::setup` → spawn the bundled `showme-backend` (or `python -m
//!   showme.server` in dev) with `--host 127.0.0.1 --port 0`.
//! - The sidecar prints exactly one line to stdout: `SIDECAR_PORT=<u16>`. We
//!   parse it and stash the port in `AppState`.
//! - 3× crash retry, exponential backoff (250 / 750 / 2250 ms). After that we
//!   surface an `NSAlert` and mark the sidecar `crashed`.
//! - `app::ExitRequested` → SIGTERM, 5 s grace, then SIGKILL.
//!
//! In dev (`cargo tauri dev`) we expect the user to have a Python venv with
//! the `showme` package installed; in release we look for the PyInstaller
//! output in TWO supported layouts so we can ship `--onefile` and `--onedir`
//! interchangeably without forking the spawn code:
//!
//!   1. PERF-06 (`--onedir`, preferred): the launcher and its `_internal/`
//!      sibling live at `Contents/Resources/binaries/showme-backend/showme-backend`.
//!      Tauri's `bundle.resources` glob (`binaries/showme-backend/**/*`)
//!      copies the entire directory tree into the bundle. Boot is ~10× faster
//!      than `--onefile` because PyInstaller doesn't have to unpack a self-
//!      extracting archive to `$TMPDIR` on first launch.
//!   2. Legacy `--onefile` fallback: the single binary still lives at
//!      `Contents/MacOS/showme-backend` because Tauri's `externalBin` field
//!      places it there. Boot involves a one-time self-extract.
//!
//! `build_command` tries layout (1) first and silently falls through to (2)
//! if the resource path is missing — so the backend sibling agent can flip
//! `backend/showme-backend.spec` from `--onefile` to `--onedir` without
//! coordinating a same-commit change here. Set `SHOWME_FORCE_ONEFILE=1` to
//! short-circuit the auto-detection (dev / debug aid).

use crate::{AppState, SidecarHealth, SidecarStatus};
use parking_lot::Mutex;
use std::io::{BufRead, BufReader, Read, Write};
use std::net::{SocketAddr, TcpStream};
use std::process::{Child, Command, Stdio};
#[cfg(target_os = "windows")]
use std::os::windows::process::CommandExt;
use std::sync::atomic::Ordering;
use std::sync::Arc;
use std::time::Duration;
use tauri::path::BaseDirectory;
use tauri::{AppHandle, Emitter, Manager};

static CHILD: once_cell::sync::Lazy<Arc<Mutex<Option<Child>>>> =
    once_cell::sync::Lazy::new(|| Arc::new(Mutex::new(None)));

const MAX_RETRIES: u32 = 3;

pub fn spawn(handle: AppHandle) {
    spawn_with_restarts(handle, 0);
}

/// Boot the sidecar, retrying spawn failures with exponential backoff
/// (250 / 750 / 2250 ms). `base_attempt` carries the restart count across
/// crash-triggered reboots (see `on_sidecar_exit`) so `MAX_RETRIES` bounds
/// the total boot attempts per session, not per crash.
fn spawn_with_restarts(handle: AppHandle, base_attempt: u32) {
    std::thread::spawn(move || {
        for attempt in base_attempt..=MAX_RETRIES {
            // HNT-07 — never spawn a fresh sidecar once the app has
            // started tearing down, or the process outlives the app and
            // keeps the DuckDB file lock.
            if is_shutting_down(&handle) {
                return;
            }
            match boot_one(&handle, attempt) {
                Ok(()) => return,
                Err(err) => {
                    log::warn!("sidecar attempt {attempt} failed: {err}");
                    {
                        let state = handle.state::<AppState>();
                        let mut h = state.sidecar_health.write();
                        h.status = SidecarStatus::Crashed;
                        h.restarts = attempt;
                        h.last_error = Some(err.to_string());
                    }
                    let _ = handle.emit("sidecar:status", health_snapshot(&handle));
                    if attempt == MAX_RETRIES {
                        let _ = handle.emit(
                            "sidecar:fatal",
                            format!("Python backend failed to boot: {err}"),
                        );
                        return;
                    }
                    let backoff = 250u64 * 3u64.pow(attempt);
                    sleep_while_alive(&handle, Duration::from_millis(backoff));
                }
            }
        }
    });
}

fn is_shutting_down(handle: &AppHandle) -> bool {
    handle
        .state::<AppState>()
        .sidecar_shutdown
        .load(Ordering::SeqCst)
}

/// HNT-07 — sleep in small steps so a shutdown request arriving during a
/// backoff window aborts the retry loop promptly instead of spawning a
/// new sidecar after the app has already quit.
fn sleep_while_alive(handle: &AppHandle, total: Duration) {
    let step = Duration::from_millis(100);
    let mut waited = Duration::ZERO;
    while waited < total {
        if is_shutting_down(handle) {
            return;
        }
        let chunk = step.min(total - waited);
        std::thread::sleep(chunk);
        waited += chunk;
    }
}

fn boot_one(handle: &AppHandle, attempt: u32) -> Result<(), String> {
    // Mint a random auth token for this sidecar boot. The Python process
    // reads it from `SHOWME_AUTH_TOKEN` and rejects any request missing the
    // `X-ShowMe-Token` header. Stash it in `AppState` so the frontend can
    // read it back via the `sidecar_auth_token` invoke (ARCH-05 P2).
    let token = format!("{:032x}", rand::random::<u128>());
    {
        let state = handle.state::<AppState>();
        *state.sidecar_auth_token.write() = Some(token.clone());
    }

    let mut command = build_command(handle)?;
    // Python and the frozen backend are console executables. Keep their pipe
    // protocol without allocating a visible terminal beside the desktop app.
    #[cfg(target_os = "windows")]
    command.creation_flags(0x08000000); // CREATE_NO_WINDOW
    command.env("SHOWME_AUTH_TOKEN", &token);

    // Bundle-id reconciliation: Tauri writes to `app.showme.terminal/`
    // (macOS bundle-id convention) while the Python sidecar's
    // `app_paths.py` defaults to `~/Library/Application Support/showMe/`.
    // Without publishing `SHOWME_HOME` the two halves silently maintain
    // two parallel data roots — portfolio.db never gets created in the
    // place the engine actually looks at, and every "no positions" UI
    // bug we saw on the live build traces back to this split. Pin the
    // sidecar to the Tauri-owned data root so both halves agree.
    if let Ok(data_root) = handle.path().app_data_dir() {
        command.env("SHOWME_HOME", &data_root);
    }
    let mut child = command
        .stdout(Stdio::piped())
        .stderr(Stdio::piped())
        .spawn()
        .map_err(|e| format!("spawn: {e}"))?;

    let stdout = child.stdout.take().ok_or("no stdout")?;
    let stderr = child.stderr.take();
    *CHILD.lock() = Some(child);
    // FR-04 — close the shutdown↔spawn race: shutdown() may have set the
    // flag and drained the OLD child between the check in
    // spawn_with_restarts and this store. Re-check now so the freshly
    // spawned sidecar can't outlive the app holding the DuckDB file lock.
    if is_shutting_down(handle) {
        let mut guard = CHILD.lock();
        if let Some(mut child) = guard.take() {
            let _ = child.kill();
            let _ = child.wait();
        }
        return Err("shutdown during spawn".into());
    }
    let handle = handle.clone();

    // Notify the frontend immediately so it can attach the header on the
    // very first fetch, even before the port arrives.
    let _ = handle.emit("sidecar:auth_token", &token);

    if let Some(stderr) = stderr {
        std::thread::spawn(move || {
            let reader = BufReader::new(stderr);
            for line in reader.lines().map_while(Result::ok) {
                log::debug!("[sidecar:stderr] {line}");
            }
        });
    }

    std::thread::spawn(move || {
        let reader = BufReader::new(stdout);
        for line in reader.lines().map_while(Result::ok) {
            log::debug!("[sidecar] {line}");
            if let Some(rest) = line.strip_prefix("SIDECAR_PORT=") {
                if let Ok(port) = rest.trim().parse::<u16>() {
                    if wait_for_health(port) {
                        let state = handle.state::<AppState>();
                        *state.sidecar_port.write() = Some(port);
                        {
                            let mut h = state.sidecar_health.write();
                            h.status = SidecarStatus::Healthy;
                            h.last_error = None;
                        }
                        let _ = handle.emit("sidecar:port", port);
                        let _ = handle.emit("sidecar:status", health_snapshot(&handle));
                    } else {
                        let state = handle.state::<AppState>();
                        let mut h = state.sidecar_health.write();
                        h.status = SidecarStatus::Crashed;
                        h.last_error = Some(format!("backend did not answer /api/health on {port}"));
                        let _ = handle.emit("sidecar:status", health_snapshot(&handle));
                    }
                }
            }
        }
        // stdout closed → the process exited.
        on_sidecar_exit(&handle, attempt);
    });

    Ok(())
}

/// HNT-03 — the sidecar process died. Distinguish an app-shutdown exit
/// from a crash:
///   * during shutdown: record the final `Stopped` status and stop;
///   * otherwise (regardless of the previous status — including
///     `Booting`, which used to hang forever): clear the stale port so
///     the frontend stops talking to a dead socket, mark the sidecar
///     `Crashed` with a `last_error`, and schedule a backoff restart
///     while retries remain.
fn on_sidecar_exit(handle: &AppHandle, attempt: u32) {
    let state = handle.state::<AppState>();
    if is_shutting_down(handle) {
        // Expected exit during teardown — `shutdown()` already reaped
        // the child; just record the final state.
        {
            let mut h = state.sidecar_health.write();
            if h.status != SidecarStatus::Crashed {
                h.status = SidecarStatus::Stopped;
            }
        }
        let _ = handle.emit("sidecar:status", health_snapshot(handle));
        return;
    }
    let next_attempt = attempt + 1;
    *state.sidecar_port.write() = None;
    {
        let mut h = state.sidecar_health.write();
        h.status = SidecarStatus::Crashed;
        h.restarts = next_attempt;
        h.last_error = Some("sidecar process exited unexpectedly".into());
    }
    let _ = handle.emit("sidecar:status", health_snapshot(handle));
    if next_attempt > MAX_RETRIES {
        let _ = handle.emit(
            "sidecar:fatal",
            "Python backend crashed repeatedly and exhausted retries".to_string(),
        );
        return;
    }
    let backoff = 250u64 * 3u64.pow(attempt);
    log::warn!("sidecar exited unexpectedly; restart {next_attempt} in {backoff} ms");
    sleep_while_alive(handle, Duration::from_millis(backoff));
    if is_shutting_down(handle) {
        return;
    }
    spawn_with_restarts(handle.clone(), next_attempt);
}

fn build_command(handle: &AppHandle) -> Result<Command, String> {
    if cfg!(debug_assertions) {
        // Dev / debug-exe mode: run the Python sidecar from source.
        // SHOWME_PYTHON overrides everything; otherwise prefer the
        // repo venv (`backend/.venv`) so a double-clicked debug exe
        // works without manual PATH setup. Fall back to system python.
        let cwd = default_sidecar_cwd();
        let python = resolve_dev_python(&cwd);
        let mut cmd = Command::new(python);
        cmd.arg("-m").arg("showme.server")
            .arg("--host").arg("127.0.0.1")
            .arg("--port").arg("0")
            .arg("--engine-path")
            .arg(default_engine_path(&cwd))
            .env("PYTHONUNBUFFERED", "1")
            .current_dir(cwd);
        Ok(cmd)
    } else {
        // Bundle mode: pick the PyInstaller layout that's actually
        // present in the bundle. See module docstring for the rationale.
        let exe = resolve_bundled_sidecar(handle)?;
        let mut cmd = Command::new(exe);
        cmd.arg("--host").arg("127.0.0.1")
            .arg("--port").arg("0")
            .env("PYTHONUNBUFFERED", "1");
        Ok(cmd)
    }
}

/// PERF-06 (Round 3C) — find the bundled sidecar binary, preferring the
/// `--onedir` layout under `Contents/Resources/binaries/showme-backend/`
/// and falling back to the legacy `--onefile` path under `Contents/MacOS/`.
///
/// The auto-detection means the backend agent can flip
/// `backend/showme-backend.spec` from `--onefile` to `--onedir` without
/// requiring a coordinated change here, and a bisect across the two
/// layouts always has at least one working binary.
///
/// Windows: the launcher carries a `.exe` suffix
/// (`resources/binaries/showme-backend/showme-backend.exe` for onedir,
/// `showme-backend.exe` next to the app exe for onefile).
fn resolve_bundled_sidecar(handle: &AppHandle) -> Result<std::path::PathBuf, String> {
    let resolver = handle.path();
    let force_onefile = std::env::var("SHOWME_FORCE_ONEFILE")
        .map(|v| v == "1" || v.eq_ignore_ascii_case("true"))
        .unwrap_or(false);

    if !force_onefile {
        // Layout 1: `--onedir` under Resources/.
        // macOS: `Contents/Resources/binaries/showme-backend/showme-backend`.
        // Windows: `resources/binaries/showme-backend/showme-backend.exe`.
        #[cfg(target_os = "windows")]
        const ONEDIR_CANDIDATES: &[&str] = &[
            "binaries/showme-backend/showme-backend.exe",
            "binaries/showme-backend/showme-backend",
        ];
        #[cfg(not(target_os = "windows"))]
        const ONEDIR_CANDIDATES: &[&str] = &["binaries/showme-backend/showme-backend"];
        for candidate_rel in ONEDIR_CANDIDATES {
            if let Ok(candidate) =
                resolver.resolve(candidate_rel, BaseDirectory::Resource)
            {
                if candidate.is_file() {
                    log::info!("sidecar: using --onedir layout at {}", candidate.display());
                    return Ok(candidate);
                }
            }
        }
    }

    // Layout 1b: Windows onefile next to the app exe.
    #[cfg(target_os = "windows")]
    {
        if let Ok(resource_dir) = resolver.resource_dir() {
            for name in ["showme-backend.exe", "showme-backend"] {
                let candidate = resource_dir.join(name);
                if candidate.is_file() {
                    log::info!("sidecar: using windows onefile at {}", candidate.display());
                    return Ok(candidate);
                }
                // PyInstaller onedir may also land directly under resources/.
                let nested = resource_dir.join("binaries/showme-backend").join(name);
                if nested.is_file() {
                    log::info!("sidecar: using windows nested at {}", nested.display());
                    return Ok(nested);
                }
            }
        }
    }

    // Layout 2: legacy `--onefile` under Contents/MacOS/ (macOS only).
    #[cfg(target_os = "macos")]
    {
        let resource_path = resolver
            .resource_dir()
            .map_err(|e| format!("resource_dir: {e}"))?;
        let legacy = resource_path.join("../MacOS/showme-backend");
        if legacy.exists() {
            log::info!("sidecar: using --onefile layout at {}", legacy.display());
            return Ok(legacy);
        }
        return Err(format!(
            "no sidecar binary found (looked under Resources/binaries/showme-backend/ and {})",
            legacy.display()
        ));
    }
    #[cfg(not(target_os = "macos"))]
    {
        let resource_path = resolver
            .resource_dir()
            .map_err(|e| format!("resource_dir: {e}"))?;
        return Err(format!(
            "no sidecar binary found under {} (looked for binaries/showme-backend/showme-backend.exe)",
            resource_path.display()
        ));
    }
}

fn wait_for_health(port: u16) -> bool {
    let addr = SocketAddr::from(([127, 0, 0, 1], port));
    for _ in 0..80 {
        if health_probe_once(addr) {
            return true;
        }
        std::thread::sleep(Duration::from_millis(250));
    }
    false
}

fn health_probe_once(addr: SocketAddr) -> bool {
    let timeout = Duration::from_millis(600);
    let Ok(mut stream) = TcpStream::connect_timeout(&addr, timeout) else {
        return false;
    };
    let _ = stream.set_read_timeout(Some(timeout));
    let _ = stream.set_write_timeout(Some(timeout));
    if stream
        .write_all(b"GET /api/health HTTP/1.1\r\nHost: 127.0.0.1\r\nConnection: close\r\n\r\n")
        .is_err()
    {
        return false;
    }
    let mut buf = [0u8; 512];
    let Ok(n) = stream.read(&mut buf) else {
        return false;
    };
    if n == 0 {
        return false;
    }
    let response = String::from_utf8_lossy(&buf[..n]);
    response.starts_with("HTTP/1.1 200") || response.starts_with("HTTP/1.0 200")
}

fn default_sidecar_cwd() -> std::path::PathBuf {
    // Post-unification the sidecar lives at <repo>/backend/.
    // SHOWME_BACKEND_PATH overrides the location entirely.
    if let Ok(p) = std::env::var("SHOWME_BACKEND_PATH") {
        return std::path::PathBuf::from(p);
    }
    // Candidate 1: cwd-relative (tauri dev launches from <repo>/tauri/).
    if let Ok(cwd) = std::env::current_dir() {
        let candidate = cwd.join("../backend");
        if candidate.join("showme/server.py").exists() {
            return candidate;
        }
    }
    // Candidate 2: exe-relative (double-clicked debug exe at
    // <repo>/tauri/target/debug/showme.exe → <repo>/backend/).
    if let Ok(exe) = std::env::current_exe() {
        if let Some(dir) = exe.parent() {
            // Walk up to 4 levels looking for backend/showme/server.py
            // (covers target/debug, target/release, and nested layouts).
            let mut cur = dir.to_path_buf();
            for _ in 0..5 {
                let candidate = cur.join("backend");
                if candidate.join("showme/server.py").exists() {
                    return candidate;
                }
                // Also handle <repo>/tauri/target/debug → <repo>/backend
                // via direct ../../../backend join.
                if let Some(parent) = cur.parent() {
                    cur = parent.to_path_buf();
                } else {
                    break;
                }
            }
            // Direct join for the known debug layout.
            let direct = dir.join("../../../backend");
            if direct.join("showme/server.py").exists() {
                return direct;
            }
        }
    }
    // Fallback: original cwd-relative (may not exist, spawn will error).
    std::env::current_dir()
        .map(|d| d.join("../backend"))
        .unwrap_or_else(|_| std::path::PathBuf::from("../backend"))
}

/// Resolve the Python interpreter for dev/debug sidecar boots.
///
/// Priority: SHOWME_PYTHON env → repo venv (`backend/.venv`) → system
/// python (`python` on Windows, `python3` elsewhere).
fn resolve_dev_python(sidecar_cwd: &std::path::Path) -> String {
    if let Ok(p) = std::env::var("SHOWME_PYTHON") {
        if !p.trim().is_empty() {
            return p;
        }
    }
    #[cfg(target_os = "windows")]
    const VENV_RELS: &[&str] = &[
        ".venv/Scripts/python.exe",
        "../backend/.venv/Scripts/python.exe",
    ];
    #[cfg(not(target_os = "windows"))]
    const VENV_RELS: &[&str] = &[
        ".venv/bin/python",
        "../backend/.venv/bin/python",
    ];
    for rel in VENV_RELS {
        let candidate = sidecar_cwd.join(rel);
        if candidate.is_file() {
            return candidate.to_string_lossy().into_owned();
        }
    }
    // Also try exe-relative venv (debug exe launched from target/).
    if let Ok(exe) = std::env::current_exe() {
        if let Some(dir) = exe.parent() {
            let mut cur = dir.to_path_buf();
            for _ in 0..5 {
                #[cfg(target_os = "windows")]
                let venv = cur.join("backend/.venv/Scripts/python.exe");
                #[cfg(not(target_os = "windows"))]
                let venv = cur.join("backend/.venv/bin/python");
                if venv.is_file() {
                    return venv.to_string_lossy().into_owned();
                }
                if let Some(parent) = cur.parent() {
                    cur = parent.to_path_buf();
                } else {
                    break;
                }
            }
        }
    }
    if cfg!(target_os = "windows") {
        "python".to_string()
    } else {
        "python3".to_string()
    }
}

fn default_engine_path(sidecar_cwd: &std::path::Path) -> String {
    // The engine is now a regular Python subpackage (showme.engine), but we
    // still publish SHOWME_ENGINE_PATH so engine code that loads adjacent
    // config/*.yaml files keeps resolving the right directory.
    if let Ok(p) = std::env::var("SHOWME_ENGINE_PATH") {
        if !p.trim().is_empty() {
            return p;
        }
    }
    // Absolute path based on the resolved sidecar cwd so a double-clicked
    // debug exe (cwd = target/debug) still points at <repo>/backend/showme/engine.
    let abs = sidecar_cwd.join("showme/engine");
    if abs.is_dir() {
        return abs.to_string_lossy().into_owned();
    }
    "../backend/showme/engine".to_string()
}

/// Graceful sidecar shutdown — REL-04 P1.
///
/// `Child::kill()` on macOS sends SIGKILL, which short-circuits the
/// Python `atexit` handlers we rely on for:
///   - DuckDB WAL truncation (otherwise the next boot triggers replay
///     and we leak ~MB-per-shutdown of orphan WAL).
///   - Broker websocket close frames (otherwise ccxt's per-session
///     sockets stay half-open until the exchange-side keepalive kicks
///     them ~60s later).
///
/// Instead we send SIGTERM via `libc::kill` (Rust stable doesn't expose
/// SIGTERM directly), poll `try_wait` for up to 5 seconds, and only
/// escalate to SIGKILL if the sidecar still hasn't exited.
pub fn shutdown(handle: &AppHandle) {
    // HNT-07 — flip the shutdown flag first so the backoff/retry loop
    // and the crash-restart path stop respawning while we tear the
    // child down.
    handle
        .state::<AppState>()
        .sidecar_shutdown
        .store(true, Ordering::SeqCst);
    let mut guard = CHILD.lock();
    if let Some(mut child) = guard.take() {
        let pid = child.id();
        log::info!("sidecar: requesting graceful shutdown (SIGTERM pid={pid})");
        // SIGTERM via libc to give Python's atexit a chance to run.
        #[cfg(unix)]
        unsafe {
            // pid is a u32 from Child; cast to i32 (pid_t) for libc::kill.
            let rc = libc::kill(pid as libc::pid_t, libc::SIGTERM);
            if rc != 0 {
                let err = std::io::Error::last_os_error();
                log::warn!("sidecar: SIGTERM failed (pid={pid}): {err}");
            }
        }
        // Non-unix fallback (Windows in CI): just use Child::kill which is
        // a hard terminate. We don't ship Windows builds today but the
        // type system still has to compile here.
        #[cfg(not(unix))]
        {
            let _ = child.kill();
        }

        // Poll up to 5 seconds (50 × 100ms) for the sidecar to honor SIGTERM.
        for _ in 0..50 {
            match child.try_wait() {
                Ok(Some(_status)) => {
                    log::info!("sidecar: exited cleanly after SIGTERM (pid={pid})");
                    return;
                }
                Ok(None) => std::thread::sleep(Duration::from_millis(100)),
                Err(err) => {
                    log::warn!("sidecar: try_wait failed (pid={pid}): {err}");
                    return;
                }
            }
        }
        // Last resort: SIGKILL.
        log::warn!(
            "sidecar: still alive after 5s SIGTERM grace, escalating to SIGKILL (pid={pid})"
        );
        let _ = child.kill();
        // Give the OS one more beat to reap so we don't leak a zombie.
        let _ = child.wait();
    }
}

fn health_snapshot(handle: &AppHandle) -> SidecarHealth {
    handle.state::<AppState>().sidecar_health.read().clone()
}

/// HNT-07 — best-effort child kill for the process-wide panic hook.
/// Release builds use `panic = "abort"`, so a Rust panic kills the
/// process before `ExitRequested`/`shutdown` can run; without this the
/// Python sidecar is orphaned holding the DuckDB file lock. Uses
/// `try_lock` so a panic fired while the `CHILD` lock is held can never
/// deadlock the hook.
pub fn kill_child_best_effort() {
    if let Some(mut guard) = CHILD.try_lock() {
        if let Some(mut child) = guard.take() {
            let _ = child.kill();
            let _ = child.wait();
        }
    }
}
