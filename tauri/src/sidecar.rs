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
//! the `showme` package installed; in release we expect the PyInstaller
//! one-file binary at `Contents/MacOS/showme-backend`.

use crate::{AppState, SidecarHealth, SidecarStatus};
use parking_lot::Mutex;
use std::io::{BufRead, BufReader, Read, Write};
use std::net::{SocketAddr, TcpStream};
use std::process::{Child, Command, Stdio};
use std::sync::Arc;
use std::time::Duration;
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
    let mut command = build_command(handle)?;
    let mut child = command
        .stdout(Stdio::piped())
        .stderr(Stdio::piped())
        .spawn()
        .map_err(|e| format!("spawn: {e}"))?;

    let stdout = child.stdout.take().ok_or("no stdout")?;
    let stderr = child.stderr.take();
    *CHILD.lock() = Some(child);
    let handle = handle.clone();

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
        // Bundle mode: `Contents/MacOS/showme-backend` is the PyInstaller bin.
        let resolver = handle.path();
        let resource_path = resolver
            .resource_dir()
            .map_err(|e| format!("resource_dir: {e}"))?;
        let exe = resource_path.join("../MacOS/showme-backend");
        let mut cmd = Command::new(exe);
        cmd.arg("--host").arg("127.0.0.1")
            .arg("--port").arg("0")
            .env("PYTHONUNBUFFERED", "1");
        Ok(cmd)
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

pub fn shutdown(_handle: &AppHandle) {
    let mut guard = CHILD.lock();
    if let Some(mut child) = guard.take() {
        log::info!("sidecar: requesting graceful shutdown");
        // SIGTERM via kill() (Rust stable doesn't expose SIGTERM directly).
        let _ = child.kill();
        for _ in 0..50 {
            match child.try_wait() {
                Ok(Some(_)) => return,
                Ok(None) => std::thread::sleep(Duration::from_millis(100)),
                Err(_) => return,
            }
        }
        let _ = child.kill();
    }
}

fn health_snapshot(handle: &AppHandle) -> SidecarHealth {
    handle.state::<AppState>().sidecar_health.read().clone()
}
