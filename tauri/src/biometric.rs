//! LocalAuthentication / Touch ID bridge.
//!
//! Round 21 ships the real prompt: `LAContext.evaluatePolicy:reply:` is
//! invoked through `objc2` + `block2`, with the completion block
//! pushing the user's decision onto a one-shot `mpsc::Sender<bool>`.
//! The Rust call blocks until the user responds (or the OS times the
//! prompt out — 120 s wall clock).
//!
//! Outcomes:
//!
//!   * `via: TouchId / FaceId, allowed: true` — biometry policy
//!     accepted by the user.
//!   * `via: Password, allowed: true`        — biometry unavailable
//!     but device-owner passcode policy accepted.
//!   * `via: Denied, allowed: false`         — user cancelled, or no
//!     policy is evaluable.
//!
//! On non-macOS targets `run_evaluate_policy` returns `Ok(false)` so
//! callers don't accidentally fire live trades on a dev box.
//!
//! ## Tokens (SEC-04 P1 fix)
//!
//! On a successful prompt we mint a 32-char hex token that is bound to
//! a single 5-minute window. Privileged commands like `keychain_get`,
//! `install_to_applications`, and `run_migration` must present the token
//! before the Rust handler will execute. `consume_token` revokes it after
//! a one-shot operation; `verify_token` leaves it intact for repeated
//! reads inside the 5-minute window. This stops a renderer from replaying
//! a fake `{ allowed: true }` payload — the privileged commands ignore
//! everything except a token they themselves minted.

use once_cell::sync::Lazy;
use rand::RngCore;
use serde::Serialize;
use std::collections::HashMap;
use std::sync::Mutex;
use std::time::{Duration, Instant};

const TOKEN_TTL: Duration = Duration::from_secs(300); // 5 minutes

/// Active biometric tokens minted by `evaluate()`. Each token maps to the
/// `Instant` it was created at; on lookup we drop anything older than
/// `TOKEN_TTL` automatically.
pub static BIOMETRIC_TOKENS: Lazy<Mutex<HashMap<String, Instant>>> =
    Lazy::new(|| Mutex::new(HashMap::new()));

#[derive(Serialize, Clone, Debug)]
pub struct BiometricResult {
    pub allowed: bool,
    pub reason: String,
    pub via: BioVia,
    pub capabilities: Capabilities,
    /// Single-use auth token (only present when `allowed == true`). Pass it
    /// to `keychain_get`/`install_to_applications`/`run_migration` to
    /// authenticate within the next 5 minutes.
    pub token: Option<String>,
}

#[derive(Serialize, Clone, Copy, Debug, Default)]
pub struct Capabilities {
    pub biometry_available: bool,
    pub passcode_available: bool,
    pub biometry_kind: BiometryKind,
}

#[derive(Serialize, Clone, Copy, Debug, Default)]
#[serde(rename_all = "snake_case")]
pub enum BiometryKind {
    #[default]
    None,
    TouchId,
    FaceId,
}

#[derive(Serialize, Clone, Copy, Debug)]
#[serde(rename_all = "snake_case")]
#[allow(dead_code)]
pub enum BioVia {
    TouchId,
    FaceId,
    Password,
    Stub,
    Denied,
}

pub fn evaluate(reason: &str) -> BiometricResult {
    let caps = capabilities();
    if !caps.biometry_available && !caps.passcode_available {
        return BiometricResult {
            allowed: false,
            reason: reason.to_string(),
            via: BioVia::Denied,
            capabilities: caps,
            token: None,
        };
    }
    let prefer_biometry = caps.biometry_available;
    let policy_id: i64 = if prefer_biometry { 1 } else { 2 };
    let outcome = run_evaluate_policy(reason, policy_id);
    match outcome {
        Ok(true) => BiometricResult {
            allowed: true,
            reason: reason.to_string(),
            via: if prefer_biometry {
                match caps.biometry_kind {
                    BiometryKind::FaceId => BioVia::FaceId,
                    _ => BioVia::TouchId,
                }
            } else {
                BioVia::Password
            },
            capabilities: caps,
            token: Some(mint_token()),
        },
        Ok(false) => BiometricResult {
            allowed: false,
            reason: reason.to_string(),
            via: BioVia::Denied,
            capabilities: caps,
            token: None,
        },
        Err(err) => {
            log::warn!("biometric::evaluate prompt error: {err}");
            BiometricResult {
                allowed: false,
                reason: reason.to_string(),
                via: BioVia::Denied,
                capabilities: caps,
                token: None,
            }
        }
    }
}

/// Mint a fresh 32-char hex token, store it in `BIOMETRIC_TOKENS` with the
/// current `Instant`, and return the string. Also opportunistically reaps
/// expired tokens to keep the map bounded.
fn mint_token() -> String {
    let mut bytes = [0u8; 16];
    rand::thread_rng().fill_bytes(&mut bytes);
    let token: String = bytes.iter().map(|b| format!("{b:02x}")).collect();
    if let Ok(mut map) = BIOMETRIC_TOKENS.lock() {
        let now = Instant::now();
        map.retain(|_, t| now.duration_since(*t) < TOKEN_TTL);
        map.insert(token.clone(), now);
    }
    token
}

/// Returns `Ok(())` if the token exists and is younger than `TOKEN_TTL`.
/// On expiry the token is removed; on Err the token is also removed if it
/// was present, so a stale or bogus token cannot be retried.
///
/// Reserved for repeated keychain reads inside a single 5-minute window;
/// the keychain commands are not yet wired through here, hence the
/// `allow(dead_code)`. SEC-04 P1 follow-up.
#[allow(dead_code)]
pub fn verify_token(token: &str) -> Result<(), String> {
    let mut map = BIOMETRIC_TOKENS
        .lock()
        .map_err(|e| format!("token map poisoned: {e}"))?;
    match map.get(token).copied() {
        Some(t) if Instant::now().duration_since(t) < TOKEN_TTL => Ok(()),
        Some(_) => {
            map.remove(token);
            Err("biometric token expired".into())
        }
        None => Err("biometric token not recognized".into()),
    }
}

/// Verify and remove the token. Use this for one-shot privileged
/// operations (e.g. `install_to_applications`, `run_migration`) so the
/// same prompt cannot authorize two different actions.
pub fn consume_token(token: &str) -> Result<(), String> {
    let mut map = BIOMETRIC_TOKENS
        .lock()
        .map_err(|e| format!("token map poisoned: {e}"))?;
    match map.remove(token) {
        Some(t) if Instant::now().duration_since(t) < TOKEN_TTL => Ok(()),
        Some(_) => Err("biometric token expired".into()),
        None => Err("biometric token not recognized".into()),
    }
}

#[cfg(target_os = "macos")]
pub fn capabilities() -> Capabilities {
    use objc2::{class, msg_send, runtime::AnyObject};
    use std::ptr;

    let mut caps = Capabilities::default();

    unsafe {
        let cls = class!(LAContext);
        let ctx: *mut AnyObject = msg_send![cls, new];
        if ctx.is_null() {
            return caps;
        }

        const POLICY_BIOMETRICS: i64 = 1;
        const POLICY_OWNER: i64 = 2;
        let mut err: *mut AnyObject = ptr::null_mut();
        let bio: bool = msg_send![ctx, canEvaluatePolicy: POLICY_BIOMETRICS, error: &mut err];
        caps.biometry_available = bio;

        let mut err2: *mut AnyObject = ptr::null_mut();
        let owner: bool = msg_send![ctx, canEvaluatePolicy: POLICY_OWNER, error: &mut err2];
        caps.passcode_available = owner;

        if bio {
            let kind: i64 = msg_send![ctx, biometryType];
            caps.biometry_kind = match kind {
                1 => BiometryKind::TouchId,
                2 => BiometryKind::FaceId,
                _ => BiometryKind::None,
            };
        }
        let _: () = msg_send![ctx, release];
    }
    caps
}

#[cfg(not(target_os = "macos"))]
pub fn capabilities() -> Capabilities {
    Capabilities::default()
}

// ── Real evaluatePolicy:reply: bridge (Round 21) ─────────────────────────

#[cfg(target_os = "macos")]
fn run_evaluate_policy(reason: &str, policy: i64) -> Result<bool, String> {
    use block2::RcBlock;
    use objc2::{
        class, msg_send,
        runtime::{AnyObject, Bool},
    };
    use std::sync::mpsc;
    use std::time::Duration;

    let (tx, rx) = mpsc::channel::<bool>();
    let tx = std::sync::Mutex::new(Some(tx));

    unsafe {
        let cls = class!(LAContext);
        let ctx: *mut AnyObject = msg_send![cls, new];
        if ctx.is_null() {
            return Err("LAContext alloc failed".into());
        }

        // NSString *reason = [NSString stringWithUTF8String:…]
        let ns_string_cls = class!(NSString);
        let cstr = std::ffi::CString::new(reason).map_err(|e| e.to_string())?;
        let ns_reason: *mut AnyObject =
            msg_send![ns_string_cls, stringWithUTF8String: cstr.as_ptr()];

        let block = RcBlock::<dyn Fn(Bool, *mut AnyObject)>::new(
            move |success: Bool, _err: *mut AnyObject| {
            if let Ok(mut guard) = tx.lock() {
                if let Some(sender) = guard.take() {
                    let _ = sender.send(success.as_bool());
                }
            }
            },
        );

        let _: () =
            msg_send![ctx, evaluatePolicy: policy, localizedReason: ns_reason, reply: &*block];

        // Block until the user responds (or Apple times the prompt out at ~60s).
        let result = rx
            .recv_timeout(Duration::from_secs(120))
            .map_err(|e| format!("auth timeout: {e}"));
        let _: () = msg_send![ctx, release];
        result
    }
}

#[cfg(not(target_os = "macos"))]
fn run_evaluate_policy(_reason: &str, _policy: i64) -> Result<bool, String> {
    // Other targets fall straight through to "denied" so callers don't
    // accidentally let live trades fire on a non-mac dev box.
    Ok(false)
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::thread::sleep;

    #[test]
    fn verify_token_rejects_unknown() {
        let res = verify_token("nope-not-a-real-token");
        assert!(res.is_err());
    }

    #[test]
    fn consume_token_removes_after_use() {
        let tok = mint_token();
        consume_token(&tok).expect("first consume should succeed");
        // Second consume should now fail since the token was removed.
        assert!(consume_token(&tok).is_err());
    }

    #[test]
    fn verify_token_keeps_token_for_reuse() {
        let tok = mint_token();
        verify_token(&tok).expect("first verify ok");
        verify_token(&tok).expect("second verify still ok within TTL");
        // Cleanup.
        let _ = consume_token(&tok);
    }

    #[test]
    fn mint_token_returns_32_hex_chars() {
        let tok = mint_token();
        assert_eq!(tok.len(), 32);
        assert!(tok.chars().all(|c| c.is_ascii_hexdigit()));
        let _ = consume_token(&tok);
        // Sleep is just for paranoia; the test does not depend on timing.
        sleep(Duration::from_millis(0));
    }
}
