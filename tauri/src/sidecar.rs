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
use std::sync::Arc;
use std::time::Duration;
use tauri::path::BaseDirectory;
use tauri::{AppHandle, Emitter, Manager};

static CHILD: once_cell::sync::Lazy<Arc<Mutex<Option<Child>>>> =
    once_cell::sync::Lazy::new(|| Arc::new(Mutex::new(None)));

const MAX_RETRIES: u32 = 3;

pub fn spawn(handle: AppHandle) {
    std::thread::spawn(move || {
        for attempt in 0..=MAX_RETRIES {
            match boot_one(&handle) {
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
                    std::thread::sleep(Duration::from_millis(backoff));
                }
            }
        }
    });
}

fn boot_one(handle: &AppHandle) -> Result<(), String> {
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
        // stdout closed → process exited.
        let state = handle.state::<AppState>();
        if state.sidecar_health.read().status == SidecarStatus::Healthy {
            let mut h = state.sidecar_health.write();
            h.status = SidecarStatus::Stopped;
        }
        let _ = handle.emit("sidecar:status", health_snapshot(&handle));
    });

    Ok(())
}

fn build_command(handle: &AppHandle) -> Result<Command, String> {
    if cfg!(debug_assertions) {
        // Dev mode: assume a python venv with the `showme` package on PATH.
        let mut cmd = Command::new("python3");
        cmd.arg("-m").arg("showme.server")
            .arg("--host").arg("127.0.0.1")
            .arg("--port").arg("0")
            .arg("--engine-path")
            .arg(default_engine_path())
            .env("PYTHONUNBUFFERED", "1")
            .current_dir(default_sidecar_cwd());
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
fn resolve_bundled_sidecar(handle: &AppHandle) -> Result<std::path::PathBuf, String> {
    let resolver = handle.path();
    let force_onefile = std::env::var("SHOWME_FORCE_ONEFILE")
        .map(|v| v == "1" || v.eq_ignore_ascii_case("true"))
        .unwrap_or(false);

    if !force_onefile {
        // Layout 1: `--onedir` under Contents/Resources/.
        // Tauri's `BaseDirectory::Resource` resolves to `Contents/Resources`
        // on macOS; the spec's COLLECT step places the launcher in a
        // subdirectory of the same name so `_internal/` sits beside it.
        if let Ok(candidate) =
            resolver.resolve("binaries/showme-backend/showme-backend", BaseDirectory::Resource)
        {
            if candidate.exists() {
                log::info!("sidecar: using --onedir layout at {}", candidate.display());
                return Ok(candidate);
            }
        }
    }

    // Layout 2: legacy `--onefile` under Contents/MacOS/.
    let resource_path = resolver
        .resource_dir()
        .map_err(|e| format!("resource_dir: {e}"))?;
    let legacy = resource_path.join("../MacOS/showme-backend");
    if legacy.exists() {
        log::info!("sidecar: using --onefile layout at {}", legacy.display());
        return Ok(legacy);
    }
    Err(format!(
        "no sidecar binary found (looked under Resources/binaries/showme-backend/ and {})",
        legacy.display()
    ))
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
    // Tauri dev mode launches us from <repo>/tauri/, so backend/ is one level
    // up. SHOWME_BACKEND_PATH overrides the location entirely.
    if let Ok(p) = std::env::var("SHOWME_BACKEND_PATH") {
        return std::path::PathBuf::from(p);
    }
    std::env::current_dir()
        .map(|d| d.join("../backend"))
        .unwrap_or_else(|_| std::path::PathBuf::from("../backend"))
}

fn default_engine_path() -> String {
    // The engine is now a regular Python subpackage (showme.engine), but we
    // still publish SHOWME_ENGINE_PATH so engine code that loads adjacent
    // config/*.yaml files keeps resolving the right directory.
    std::env::var("SHOWME_ENGINE_PATH")
        .unwrap_or_else(|_| "../backend/showme/engine".to_string())
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
pub fn shutdown(_handle: &AppHandle) {
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
