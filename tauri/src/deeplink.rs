//! `showme://` URL scheme.
//!
//! Examples:
//!   showme://function/AAPL/FA            → load function FA for AAPL
//!   showme://scan/<scan_id>              → open scanner result
//!   showme://alert/<alert_id>            → focus alert detail
//!
//! Tauri receives the URL via `tauri-plugin-deep-link`, we parse it into a
//! small typed envelope (so the renderer never has to re-implement the
//! grammar, and we can reject malformed input at the trust boundary), then
//! forward to the frontend through a `deeplink:received` event.
//!
//! ## Hardening (SEC-04 P1)
//!
//! - Reject schemes other than `showme://`.
//! - Reject paths longer than 1 KiB.
//! - Reject control characters anywhere in the URL.
//! - Reject unknown verbs (`function`, `scan`, `alert`, `nav`).
//! - Reject argument segments with `..` (path traversal style abuse — the
//!   target is the React router, not the filesystem, but normalising here
//!   removes a foot-gun for the in-app navigator).
//! - In **release** builds, reject the developer-only `dev/*` verbs that
//!   exist for ad-hoc debugging (SEC-01/02/03 P3 — strip developer
//!   helpers in shipped builds).

use serde::Serialize;
use tauri::{App, Manager};
use tauri_plugin_deep_link::DeepLinkExt;

const MAX_DEEPLINK_BYTES: usize = 1024;

#[derive(Debug, Serialize, Clone, PartialEq, Eq)]
pub struct DeepLinkEnvelope {
    pub raw: String,
    pub verb: String,
    pub args: Vec<String>,
}

#[derive(Debug, PartialEq, Eq)]
pub enum DeepLinkError {
    Empty,
    TooLong,
    InvalidScheme,
    ControlChar,
    UnknownVerb,
    PathTraversal,
    /// Reserved for `cfg(not(debug_assertions))` rejection of `dev/*` verbs.
    #[allow(dead_code)]
    DevDisabled,
}

/// Parse a `showme://...` URL into a typed envelope.
///
/// Returns `Err` on any rejection so callers can log + drop without
/// emitting an event.
pub fn parse(url: &str) -> Result<DeepLinkEnvelope, DeepLinkError> {
    if url.is_empty() {
        return Err(DeepLinkError::Empty);
    }
    if url.len() > MAX_DEEPLINK_BYTES {
        return Err(DeepLinkError::TooLong);
    }
    if url.chars().any(|c| c.is_control()) {
        return Err(DeepLinkError::ControlChar);
    }
    let body = url
        .strip_prefix("showme://")
        .ok_or(DeepLinkError::InvalidScheme)?;
    // Drop trailing '?...' / '#...' fragments — we don't honour them today
    // and they widen the attack surface.
    let body = body.split(['?', '#']).next().unwrap_or("");
    let mut parts = body.split('/').filter(|s| !s.is_empty());
    let verb = parts.next().unwrap_or("").to_string();
    if verb.is_empty() {
        return Err(DeepLinkError::Empty);
    }
    let args: Vec<String> = parts.map(|s| s.to_string()).collect();
    if args.iter().any(|a| a == ".." || a.contains("..")) {
        return Err(DeepLinkError::PathTraversal);
    }

    let known: &[&str] = &["function", "scan", "alert", "nav"];
    let dev: &[&str] = &["dev"];
    if !known.iter().any(|k| *k == verb) {
        if dev.iter().any(|k| *k == verb) {
            #[cfg(not(debug_assertions))]
            {
                return Err(DeepLinkError::DevDisabled);
            }
        } else {
            return Err(DeepLinkError::UnknownVerb);
        }
    }

    Ok(DeepLinkEnvelope { raw: url.to_string(), verb, args })
}

pub fn register(app: &App) {
    let handle = app.handle().clone();
    let deep_link = app.deep_link();
    deep_link.on_open_url(move |event| {
        for url in event.urls() {
            let url_str = url.to_string();
            log::info!("deeplink: {url_str}");
            match parse(&url_str) {
                Ok(envelope) => {
                    if let Some(w) = handle.get_webview_window("main") {
                        let _ = w.show();
                        let _ = w.set_focus();
                    }
                    let _ = tauri::Emitter::emit(&handle, "deeplink:received", envelope);
                }
                Err(err) => {
                    log::warn!("deeplink rejected ({err:?}): {url_str}");
                }
            }
        }
    });
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn parses_known_verb() {
        let env = parse("showme://function/AAPL/FA").unwrap();
        assert_eq!(env.verb, "function");
        assert_eq!(env.args, vec!["AAPL", "FA"]);
    }

    #[test]
    fn rejects_unknown_verb() {
        assert_eq!(parse("showme://exec/rm-rf"), Err(DeepLinkError::UnknownVerb));
    }

    #[test]
    fn rejects_invalid_scheme() {
        assert_eq!(parse("https://attacker.example/"), Err(DeepLinkError::InvalidScheme));
        assert_eq!(parse("javascript:alert(1)"), Err(DeepLinkError::InvalidScheme));
    }

    #[test]
    fn rejects_path_traversal() {
        assert_eq!(parse("showme://function/../etc/passwd"), Err(DeepLinkError::PathTraversal));
    }

    #[test]
    fn rejects_control_chars() {
        assert_eq!(parse("showme://function/AAPL\nFA"), Err(DeepLinkError::ControlChar));
    }

    #[test]
    fn rejects_overlong() {
        let url = format!("showme://function/{}", "A".repeat(2000));
        assert_eq!(parse(&url), Err(DeepLinkError::TooLong));
    }

    #[test]
    fn drops_query_and_fragment() {
        let env = parse("showme://nav/preferences?ref=abc#x").unwrap();
        assert_eq!(env.verb, "nav");
        assert_eq!(env.args, vec!["preferences"]);
    }

    #[cfg(debug_assertions)]
    #[test]
    fn dev_verbs_allowed_in_debug() {
        assert!(parse("showme://dev/probe").is_ok());
    }

    #[cfg(not(debug_assertions))]
    #[test]
    fn dev_verbs_blocked_in_release() {
        assert_eq!(parse("showme://dev/probe"), Err(DeepLinkError::DevDisabled));
    }
}
