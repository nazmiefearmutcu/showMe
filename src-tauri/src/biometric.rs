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

use serde::Serialize;

#[derive(Serialize, Clone, Debug)]
pub struct BiometricResult {
    pub allowed: bool,
    pub reason: String,
    pub via: BioVia,
    pub capabilities: Capabilities,
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
        },
        Ok(false) => BiometricResult {
            allowed: false,
            reason: reason.to_string(),
            via: BioVia::Denied,
            capabilities: caps,
        },
        Err(err) => {
            log::warn!("biometric::evaluate prompt error: {err}");
            BiometricResult {
                allowed: false,
                reason: reason.to_string(),
                via: BioVia::Denied,
                capabilities: caps,
            }
        }
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
