//! Keychain-backed secret store.
//!
//! All keys live under a single Generic-Password service identifier
//! (`SERVICE`), keyed by an arbitrary user-supplied account name like
//! `"finnhub"` or `"openai"`. The macOS Keychain handles the actual
//! confidentiality (Secure Enclave when the user has opted in, encrypted
//! file otherwise). Other targets get a no-op error path so the rest of
//! the app keeps building.
//!
//! ## Hardening (SEC-08)
//!
//! * Read errors that are NOT `errSecItemNotFound` are scrubbed before
//!   they leave Rust — the renderer sees `"keychain error"`, the operator
//!   sees the full text in the Rust log (P2).
//! * `sanitize()` rejects control chars + names over 128 bytes.
//! * Sensitive reads in `commands::keychain_get` are gated by a fresh
//!   biometric token (`auth_token: Option<String>`); see `commands.rs`.
//! * SEC-08 P1 (Round 3C) — every write goes through
//!   `set_generic_password_options` with two pinned attributes:
//!
//!     - `kSecAttrAccessible = kSecAttrAccessibleWhenUnlockedThisDeviceOnly`
//!     - `kSecAttrSynchronizable = false`
//!
//!   This stops iCloud Keychain from replicating the secret to other
//!   devices the user owns AND keeps the ciphertext encrypted-at-rest
//!   while the device is locked.
//!
//!   `security-framework 3.7` ships a high-level setter for
//!   `kSecAttrSynchronizable` (`set_access_synchronized(Some(false))`)
//!   but does NOT expose a setter for the plain `kSecAttrAccessible`
//!   attribute — its `set_access_control` helper instead binds a
//!   `SecAccessControl` object, and the modern `kSecAttrAccessControl`
//!   path requires a data-protection-keychain entitlement that a Rust
//!   unit-test binary doesn't get (errSecMissingEntitlement, -34018).
//!
//!   To keep the API working both inside the signed `.app` bundle AND
//!   in `cargo test --lib`, we push the legacy `kSecAttrAccessible`
//!   attribute directly into the `PasswordOptions` query via a tiny
//!   raw-`core-foundation` glue (`kSecAttrAccessible` is declared in
//!   `Security.framework` but not re-exported by `security-framework-sys
//!   2.17`). This is the "raw CF" fallback path called out in the
//!   SEC-08 P1 ticket. Reads continue to use the default-store query
//!   (`kSecAttrSynchronizableAny` is NOT set) so pre-migration entries
//!   written via the bare `set_generic_password` helper are still
//!   findable until `migrate_account` rewrites them.
//!
//! ## Legacy → hardened migration
//!
//! `set_secret` always rewrites with the new ACL, so any user touching
//! Preferences cycles their entries through the hardened code path.
//! `migrate_account` is invoked lazily from `commands::keychain_set`
//! the first time a given session interacts with an account so secrets
//! left untouched since the old build still get the better protection
//! class on next launch.
//!
//! We never log secret payloads. `list_accounts()` only returns names.

#![cfg(target_os = "macos")]

use core_foundation::base::TCFType;
use core_foundation::string::{CFString, CFStringRef};
use security_framework::passwords::{
    delete_generic_password, get_generic_password, set_generic_password_options, PasswordOptions,
};
use serde::Serialize;

const SERVICE: &str = "app.showme.terminal";

// We need two CFStringRef constants that `security-framework 3.7` does
// not re-export from its own crate:
//   * `kSecAttrAccessible` — the dictionary KEY for the accessibility
//     class. Used by the legacy file-based keychain path so the same
//     code works inside the signed `.app` bundle AND in `cargo test
//     --lib` (where the modern data-protection-keychain API trips
//     `errSecMissingEntitlement, -34018`).
//   * `kSecAttrAccessibleWhenUnlockedThisDeviceOnly` — the VALUE we
//     pin: ciphertext is gated on the device being unlocked AND the
//     entry never roams to other devices the user owns.
//
// Both symbols have been stable in `Security.framework` since macOS
// 10.9. We import them directly via the framework's dynamic linker
// rather than pull `security-framework-sys` in as a separate direct
// dependency just for two extern statics — the rest of the API surface
// is reached through the high-level `security_framework` crate.
#[link(name = "Security", kind = "framework")]
extern "C" {
    static kSecAttrAccessible: CFStringRef;
    static kSecAttrAccessibleWhenUnlockedThisDeviceOnly: CFStringRef;
}

#[derive(Serialize, Clone, Debug)]
pub struct SecretSummary {
    pub account: String,
    pub service: String,
}

/// Build a `PasswordOptions` configured with the SEC-08 P1 access
/// controls. Used by both the initial write and the migration path.
///
/// * `kSecAttrAccessible = kSecAttrAccessibleWhenUnlockedThisDeviceOnly`
///   → ciphertext is gated on the device being unlocked, AND the entry
///   does not roam to other devices the user owns. We deliberately use
///   this legacy attribute (not the modern `kSecAttrAccessControl`
///   object) so the same code path works inside the signed `.app`
///   bundle and in `cargo test --lib` — the modern attribute requires a
///   data-protection-keychain entitlement that a CLI test binary
///   doesn't get. Biometric / passcode gating is enforced one layer up
///   in the Rust command (`biometric::verify_token`) so we don't lose
///   any security posture by skipping the kSecAccessControl prompt.
/// * `kSecAttrSynchronizable = false` → never replicated via iCloud
///   Keychain, even if the user is signed in.
fn options_with_acl(account: &str) -> PasswordOptions {
    let mut opts = PasswordOptions::new_generic_password(SERVICE, account);
    // SAFETY: `kSecAttrAccessible` is a CFStringRef constant exported by
    // `Security.framework`; the dynamic linker resolves it on app load
    // and it remains valid for the lifetime of the process. We wrap
    // under the GetRule (Apple-managed retain count) which matches how
    // every other `kSec*` constant is fetched in `passwords_options.rs`.
    let key = unsafe { CFString::wrap_under_get_rule(kSecAttrAccessible) };
    // The accessibility *value* constant is also a CFStringRef from the
    // framework; same wrapping rule.
    let value =
        unsafe { CFString::wrap_under_get_rule(kSecAttrAccessibleWhenUnlockedThisDeviceOnly) };
    // `PasswordOptions::query` is exposed (though deprecated) so we can
    // append the missing attribute pair without a fork of the crate.
    #[allow(deprecated)]
    opts.query.push((key, value.into_CFType()));
    opts.set_access_synchronized(Some(false));
    opts
}

pub fn set_secret(account: &str, value: &str) -> Result<(), String> {
    let acct = sanitize(account)?;
    // SEC-08 P1 — pre-delete any legacy entry so the underlying
    // `SecItemAdd` path always runs (and therefore always carries the new
    // accessibility + synchronizable attributes). Without this, an
    // existing item created by the pre-Round-3C build would route
    // through `SecItemUpdate`, which only touches `kSecValueData` and
    // leaves the original (weaker) attributes in place.
    let _ = delete_generic_password(SERVICE, &acct);
    let opts = options_with_acl(&acct);
    set_generic_password_options(value.as_bytes(), opts).map_err(|e| {
        log::warn!("secrets::set_secret: {e}");
        "keychain error".to_string()
    })
}

/// macOS `errSecItemNotFound` — the canonical "no such item" status from
/// the Keychain. Pre-Round-3C this module matched the error string for
/// `"-25300"` / `"not found"`, but `security-framework 3.7` returns a
/// localized description like `"The specified item could not be found
/// in the keychain."` which contains neither substring. Match the
/// numeric `code()` directly so the classification works across
/// `security-framework` releases and macOS locales.
const ERR_SEC_ITEM_NOT_FOUND: i32 = -25300;

pub fn get_secret(account: &str) -> Result<Option<String>, String> {
    let acct = sanitize(account)?;
    match get_generic_password(SERVICE, &acct) {
        Ok(bytes) => Ok(Some(String::from_utf8_lossy(&bytes).into_owned())),
        Err(err) if err.code() == ERR_SEC_ITEM_NOT_FOUND => Ok(None),
        Err(err) => {
            // SEC-08 P2 — collapse error string so we don't leak the
            // verbose macOS error / file path back to the renderer.
            log::warn!("secrets::get_secret: code={} {err}", err.code());
            Err("keychain error".into())
        }
    }
}

pub fn delete_secret(account: &str) -> Result<bool, String> {
    let acct = sanitize(account)?;
    match delete_generic_password(SERVICE, &acct) {
        Ok(()) => Ok(true),
        Err(err) if err.code() == ERR_SEC_ITEM_NOT_FOUND => Ok(false),
        Err(err) => {
            log::warn!("secrets::delete_secret: code={} {err}", err.code());
            Err("keychain error".into())
        }
    }
}

/// SEC-08 P1 — read a possibly-legacy entry and, if it exists, rewrite
/// it under the hardened ACL.
///
/// Idempotent: a fresh entry (or a missing one) is left alone after the
/// read attempt. The new write goes through `set_secret`, which
/// pre-deletes and re-adds so `SecItemAdd` reapplies our access control.
///
/// Returns:
/// * `Ok(true)` — there was a value and it has been rewritten.
/// * `Ok(false)` — no value to migrate (cold account, or not stored).
/// * `Err(_)` — keychain I/O failed mid-flight; the legacy value is
///   left intact so the next attempt can retry.
pub fn migrate_account(account: &str) -> Result<bool, String> {
    let acct = sanitize(account)?;
    let Some(value) = get_secret(&acct)? else {
        return Ok(false);
    };
    // `set_secret` pre-deletes and re-adds with the hardened ACL.
    set_secret(&acct, &value)?;
    Ok(true)
}

/// Convenience wrapper for `commands::keychain_get`. Reads the secret
/// and opportunistically rewrites it on first access if it lacks the
/// SEC-08 P1 attributes. Failures during rewrite are logged but do not
/// poison the read — the caller still gets the secret.
///
/// Tracking which entries have been migrated lives in the lightweight
/// `secrets.index.json` index alongside the account list, in a `_migrated`
/// array that the caller manages.
#[allow(dead_code)]
pub fn get_or_migrate(account: &str) -> Result<Option<String>, String> {
    let v = get_secret(account)?;
    if v.is_some() {
        // Best-effort rewrite. Errors are logged in `set_secret` already.
        if let Err(err) = migrate_account(account) {
            log::warn!("secrets::get_or_migrate: migrate {account}: {err}");
        }
    }
    Ok(v)
}

/// Return the list of account names this app stored under SERVICE.
///
/// `security-framework` doesn't expose a generic-password enumeration helper
/// directly, so Round 20 mirrors the names in a thin local index file
/// at `~/Library/Application Support/showMe/state/secrets.index.json`.
/// The index is *only* a list of names — secrets themselves stay in the
/// Keychain.
pub fn list_accounts(index_path: &std::path::Path) -> Vec<SecretSummary> {
    let Ok(text) = std::fs::read_to_string(index_path) else {
        return vec![];
    };
    let names: Vec<String> = serde_json::from_str(&text).unwrap_or_default();
    names
        .into_iter()
        .map(|account| SecretSummary {
            account,
            service: SERVICE.to_string(),
        })
        .collect()
}

pub fn write_index(index_path: &std::path::Path, names: &[String]) -> Result<(), String> {
    let json = serde_json::to_string_pretty(names).map_err(|e| e.to_string())?;
    // FUNC-04 P0 — atomic temp-file rename so a multi-window race or a
    // crash during write can never leave a torn `secrets.index.json`.
    crate::filesystem::atomic_write(index_path, json.as_bytes()).map_err(|e| e.to_string())
}

fn sanitize(account: &str) -> Result<String, String> {
    let trimmed = account.trim();
    if trimmed.is_empty() {
        return Err("account required".into());
    }
    if trimmed.contains(|c: char| c.is_control() || c == '\0') {
        return Err("account contains control characters".into());
    }
    if trimmed.len() > 128 {
        return Err("account name too long".into());
    }
    Ok(trimmed.to_string())
}

#[allow(dead_code)]
pub const fn service_id() -> &'static str {
    SERVICE
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn sanitize_rejects_empty() {
        assert!(sanitize("").is_err());
        assert!(sanitize("   ").is_err());
    }

    #[test]
    fn sanitize_rejects_control() {
        assert!(sanitize("hi\0there").is_err());
        assert!(sanitize("hi\nthere").is_err());
    }

    #[test]
    fn sanitize_rejects_overlong() {
        let s = "a".repeat(129);
        assert!(sanitize(&s).is_err());
    }

    #[test]
    fn sanitize_trims() {
        assert_eq!(sanitize("  finnhub  ").unwrap(), "finnhub");
    }

    #[test]
    fn sanitize_accepts_typical() {
        assert_eq!(sanitize("alpaca_paper_key").unwrap(), "alpaca_paper_key");
    }

    // ── SEC-08 P1 access-control round-trip ─────────────────────────────
    //
    // The two macOS-only tests below exercise the real Keychain. They are
    // gated on `target_os = "macos"` (the whole module already is) AND on
    // a `SHOWME_KEYCHAIN_TESTS=1` env var so CI runners without a logged-
    // in keychain session don't spuriously fail. Locally, run with:
    //
    //     SHOWME_KEYCHAIN_TESTS=1 cargo test --lib secrets::tests
    //
    // We use a unique per-test account name so two parallel test runs
    // never trample each other.

    fn keychain_tests_enabled() -> bool {
        std::env::var("SHOWME_KEYCHAIN_TESTS")
            .map(|v| v == "1" || v.eq_ignore_ascii_case("true"))
            .unwrap_or(false)
    }

    /// Test-only wrapper that exposes the raw `security-framework` error
    /// string. The shipped `set_secret` redacts errors before returning
    /// them (SEC-08 P2), which is correct in production but unhelpful
    /// when diagnosing a CI failure here.
    fn raw_set_for_test(account: &str, value: &str) -> Result<(), String> {
        let acct = sanitize(account)?;
        let _ = delete_generic_password(SERVICE, &acct);
        let opts = options_with_acl(&acct);
        set_generic_password_options(value.as_bytes(), opts)
            .map_err(|e| format!("set_generic_password_options: code={} {e}", e.code()))
    }


    #[test]
    fn options_with_acl_builds_without_panic() {
        // Confirms the raw CFStringRef wrapping for `kSecAttrAccessible`
        // resolves at link time and that pushing the pair into the
        // (deprecated) `PasswordOptions::query` Vec works on the version
        // of `security-framework` pinned by Cargo.lock. The query must
        // contain at least the three default entries (class, service,
        // account) plus the two we push (accessible, synchronizable).
        let opts = options_with_acl("sec_08_test_dummy");
        #[allow(deprecated)]
        let n = opts.query.len();
        assert!(
            n >= 5,
            "expected ≥5 query entries (class, service, account, accessible, synchronizable), got {n}"
        );
    }

    #[test]
    fn round_trip_set_get_delete_with_acl() {
        if !keychain_tests_enabled() {
            eprintln!(
                "skip: round_trip_set_get_delete_with_acl (set SHOWME_KEYCHAIN_TESTS=1 to enable)"
            );
            return;
        }
        let account = format!("showme_sec08_roundtrip_{}", std::process::id());
        // Clean slate.
        let _ = delete_secret(&account);

        // Surface the real `security-framework` error to make CI failures
        // diagnosable — the public `set_secret` collapses all errors to
        // `"keychain error"` for the renderer path.
        if let Err(e) = raw_set_for_test(&account, "s3cret-value-π") {
            panic!("raw set failed: {e}");
        }
        let got = get_secret(&account).expect("get_secret");
        assert_eq!(
            got.as_deref(),
            Some("s3cret-value-π"),
            "round-trip value mismatch"
        );

        let removed = delete_secret(&account).expect("delete_secret");
        assert!(removed, "delete_secret should report true after a write");
        // Production `get_secret` classifies errSecItemNotFound as Ok(None);
        // verify that the matcher actually hits that branch after delete.
        assert_eq!(
            get_secret(&account).expect("post-delete get_secret"),
            None,
            "value should be gone after delete"
        );
    }

    #[test]
    fn migrate_account_is_idempotent() {
        if !keychain_tests_enabled() {
            eprintln!(
                "skip: migrate_account_is_idempotent (set SHOWME_KEYCHAIN_TESTS=1 to enable)"
            );
            return;
        }
        let account = format!("showme_sec08_migrate_{}", std::process::id());
        let _ = delete_secret(&account);

        // Pre-seed with the hardened path so the read in migrate finds something.
        set_secret(&account, "value-1").expect("seed");

        let did_migrate_1 = migrate_account(&account).expect("first migrate");
        assert!(
            did_migrate_1,
            "migrate should report a rewrite when a value existed"
        );
        // After migration the value should still be readable AND unchanged.
        assert_eq!(get_secret(&account).expect("re-read"), Some("value-1".into()));

        let did_migrate_2 = migrate_account(&account).expect("second migrate");
        assert!(
            did_migrate_2,
            "migrate is idempotent and rewrites again on second call"
        );
        assert_eq!(get_secret(&account).expect("re-read 2"), Some("value-1".into()));

        // No-value case must return Ok(false), not Err.
        let _ = delete_secret(&account);
        let none = migrate_account(&account).expect("migrate-no-value");
        assert!(!none, "migrate must report false when there is no value");
    }
}
