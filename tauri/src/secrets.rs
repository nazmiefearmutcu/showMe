//! Keychain-backed secret store.
//!
//! All keys live under a single Generic-Password service identifier
//! (`SERVICE`), keyed by an arbitrary user-supplied account name like
//! `"finnhub"` or `"openai"`. The macOS Keychain handles the actual
//! confidentiality (Secure Enclave when the user has opted in, encrypted
//! file otherwise). Other targets get a no-op error path so the rest of
//! the app keeps building.
//!
//! We never log secret payloads. `list_accounts()` only returns names.

#![cfg(target_os = "macos")]

use security_framework::passwords::{
    delete_generic_password, get_generic_password, set_generic_password,
};
use serde::Serialize;

const SERVICE: &str = "app.showme.terminal";

#[derive(Serialize, Clone, Debug)]
pub struct SecretSummary {
    pub account: String,
    pub service: String,
}

pub fn set_secret(account: &str, value: &str) -> Result<(), String> {
    let acct = sanitize(account)?;
    set_generic_password(SERVICE, &acct, value.as_bytes()).map_err(|e| e.to_string())
}

pub fn get_secret(account: &str) -> Result<Option<String>, String> {
    let acct = sanitize(account)?;
    match get_generic_password(SERVICE, &acct) {
        Ok(bytes) => Ok(Some(String::from_utf8_lossy(&bytes).into_owned())),
        Err(err) => {
            // -25300 == errSecItemNotFound — caller should treat this as "no value".
            let msg = err.to_string();
            if msg.contains("-25300") || msg.to_ascii_lowercase().contains("not found") {
                Ok(None)
            } else {
                Err(msg)
            }
        }
    }
}

pub fn delete_secret(account: &str) -> Result<bool, String> {
    let acct = sanitize(account)?;
    match delete_generic_password(SERVICE, &acct) {
        Ok(()) => Ok(true),
        Err(err) => {
            let msg = err.to_string();
            if msg.contains("-25300") || msg.to_ascii_lowercase().contains("not found") {
                Ok(false)
            } else {
                Err(msg)
            }
        }
    }
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
    if let Some(parent) = index_path.parent() {
        std::fs::create_dir_all(parent).map_err(|e| e.to_string())?;
    }
    let json = serde_json::to_string_pretty(names).map_err(|e| e.to_string())?;
    std::fs::write(index_path, json).map_err(|e| e.to_string())
}

fn sanitize(account: &str) -> Result<String, String> {
    let trimmed = account.trim();
    if trimmed.is_empty() {
        return Err("account required".into());
    }
    if trimmed.contains(|c: char| c.is_control() || c == '\0') {
        return Err("account contains control characters".into());
    }
    Ok(trimmed.to_string())
}

#[allow(dead_code)]
pub const fn service_id() -> &'static str {
    SERVICE
}
