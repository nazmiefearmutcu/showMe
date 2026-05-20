//! Backend ↔ Tauri IPC helpers.
//!
//! For now the frontend talks to the sidecar over plain HTTP (the discovered
//! port is exposed via `commands::sidecar_port`). When we need server-push
//! we'll wire a websocket re-broadcaster here that mirrors `/ws/*` routes
//! into Tauri events.
//!
//! ## Rate limiting (SEC-04 P1)
//!
//! Every privileged Tauri command is fronted by a per-handler token bucket.
//! A renderer compromise (XSS in a rendered XSEN payload, malicious
//! browser extension overlaying the WKWebView, etc.) cannot drive
//! `keychain_get`, `notify`, or `write_log_entry` faster than the
//! configured rate. The bucket is process-wide so multiple windows share
//! the same budget — defense in depth, not a per-window quota.

use crate::AppState;
use parking_lot::Mutex;
use std::collections::HashMap;
use std::sync::OnceLock;
use std::time::Instant;
use tauri::{AppHandle, Manager};

#[allow(dead_code)]
pub fn base_url(app: &AppHandle) -> Option<String> {
    let port = *app.state::<AppState>().sidecar_port.read();
    port.map(|p| format!("http://127.0.0.1:{}", p))
}

/// Token bucket for an individual command name.
struct Bucket {
    tokens: f64,
    capacity: f64,
    refill_per_sec: f64,
    last_refill: Instant,
}

impl Bucket {
    fn new(capacity: f64, refill_per_sec: f64) -> Self {
        Self { tokens: capacity, capacity, refill_per_sec, last_refill: Instant::now() }
    }

    fn try_take(&mut self) -> bool {
        let now = Instant::now();
        let elapsed = now.duration_since(self.last_refill).as_secs_f64();
        self.tokens = (self.tokens + elapsed * self.refill_per_sec).min(self.capacity);
        self.last_refill = now;
        if self.tokens >= 1.0 {
            self.tokens -= 1.0;
            true
        } else {
            false
        }
    }
}

fn registry() -> &'static Mutex<HashMap<&'static str, Bucket>> {
    static REGISTRY: OnceLock<Mutex<HashMap<&'static str, Bucket>>> = OnceLock::new();
    REGISTRY.get_or_init(|| Mutex::new(HashMap::new()))
}

/// Public limits per command. Tuned for a real cockpit: notifications and
/// logs can fire bursty (e.g. on alert storms) but cannot sustain abuse.
fn limits_for(cmd: &str) -> (f64, f64) {
    // (capacity, refill per second)
    match cmd {
        // Privileged / state-changing — hard caps.
        "install_to_applications" => (3.0, 0.05),
        "run_migration" => (3.0, 0.05),
        "request_biometric" => (5.0, 0.5),
        "keychain_set" => (10.0, 0.5),
        "keychain_get" => (30.0, 1.5),
        "keychain_delete" => (10.0, 0.5),
        "save_workspace" => (30.0, 2.0),
        "open_window" => (10.0, 0.5),
        "apply_update" => (3.0, 0.1),
        // High-volume utility commands — generous but bounded.
        "write_log_entry" => (200.0, 50.0),
        "notify" => (60.0, 5.0),
        // Default for anything else.
        _ => (60.0, 10.0),
    }
}

/// Try to consume a single token for `cmd`. Returns `Err` if the caller is
/// over budget so the command handler can short-circuit with a clear
/// error message.
pub fn check(cmd: &'static str) -> Result<(), String> {
    let (cap, refill) = limits_for(cmd);
    let mut reg = registry().lock();
    let bucket = reg.entry(cmd).or_insert_with(|| Bucket::new(cap, refill));
    if bucket.try_take() {
        Ok(())
    } else {
        Err(format!("rate limit exceeded for {cmd}"))
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn fresh(cmd: &'static str) {
        // Drain anything left over from a previous test by re-inserting.
        registry().lock().remove(cmd);
    }

    #[test]
    fn allows_first_burst() {
        fresh("write_log_entry");
        for _ in 0..50 {
            assert!(check("write_log_entry").is_ok());
        }
    }

    #[test]
    fn rejects_after_capacity_exceeded() {
        fresh("install_to_applications");
        // capacity=3 for install_to_applications
        assert!(check("install_to_applications").is_ok());
        assert!(check("install_to_applications").is_ok());
        assert!(check("install_to_applications").is_ok());
        assert!(check("install_to_applications").is_err());
    }

    #[test]
    fn refills_over_time() {
        fresh("request_biometric");
        // capacity=5, refill 0.5/s
        for _ in 0..5 {
            assert!(check("request_biometric").is_ok());
        }
        assert!(check("request_biometric").is_err());
        // We can't sleep an entire second in a unit test reliably; instead
        // poke the bucket directly to simulate elapsed time.
        let mut reg = registry().lock();
        if let Some(b) = reg.get_mut("request_biometric") {
            b.last_refill = Instant::now() - std::time::Duration::from_secs(60);
        }
        drop(reg);
        assert!(check("request_biometric").is_ok());
    }
}
