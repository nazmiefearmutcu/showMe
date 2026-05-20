//! Layout-preset filesystem store.
//!
//! Each preset is a JSON file under
//! `~/Library/Application Support/showMe/state/layout-presets/<name>.json`.
//! Round-15's frontend already serialized presets to the same JSON shape;
//! Round-16 swaps the storage backend without touching call sites.

use crate::AppState;
use serde::{Deserialize, Serialize};
use std::path::{Path, PathBuf};
use tauri::{AppHandle, Manager, Runtime};

const SUBDIR: &str = "state/layout-presets";

#[derive(Serialize, Deserialize, Clone, Debug)]
pub struct PresetSummary {
    pub name: String,
    pub saved_at: String,
}

fn root<R: Runtime>(app: &AppHandle<R>) -> Option<PathBuf> {
    app.state::<AppState>()
        .data_root
        .read()
        .clone()
        .map(|p| p.join(SUBDIR))
}

fn ensure_dir(p: &Path) -> std::io::Result<()> {
    if !p.exists() {
        std::fs::create_dir_all(p)?;
    }
    Ok(())
}

/// Strict allow-list sanitizer for preset names.
///
/// SEC-04 P2 / SEC-07 P1: the previous implementation allowed `..`, leading
/// dots, and Unicode whitespace, all of which let a renderer write outside
/// `state/layout-presets/` (e.g. by naming a preset `../../state/secrets.index`)
/// or create dotfiles. We now match `^[A-Za-z0-9 _-]{1,64}$` exactly and
/// reject anything else, including names that begin with `.` or contain `..`.
fn safe_name(name: &str) -> Option<String> {
    let trimmed = name.trim();
    if trimmed.is_empty() {
        return None;
    }
    if trimmed.len() > 64 {
        return None;
    }
    if trimmed.starts_with('.') {
        return None;
    }
    if trimmed.contains("..") {
        return None;
    }
    if !trimmed
        .chars()
        .all(|c| c.is_ascii_alphanumeric() || c == ' ' || c == '_' || c == '-')
    {
        return None;
    }
    Some(trimmed.to_string())
}

#[derive(Deserialize)]
struct StoredPreset {
    saved_at: String,
}

pub fn list<R: Runtime>(app: &AppHandle<R>) -> Result<Vec<PresetSummary>, String> {
    let Some(dir) = root(app) else {
        return Err("data root not initialized".into());
    };
    if !dir.exists() {
        return Ok(vec![]);
    }
    let mut out = vec![];
    for entry in std::fs::read_dir(&dir).map_err(|e| e.to_string())? {
        let entry = entry.map_err(|e| e.to_string())?;
        let path = entry.path();
        if !path.is_file() {
            continue;
        }
        let Some(name) = path
            .file_stem()
            .and_then(|s| s.to_str())
            .map(|s| s.to_string())
        else {
            continue;
        };
        let saved_at = std::fs::read_to_string(&path)
            .ok()
            .and_then(|t| serde_json::from_str::<StoredPreset>(&t).ok())
            .map(|p| p.saved_at)
            .unwrap_or_default();
        out.push(PresetSummary { name, saved_at });
    }
    out.sort_by(|a, b| a.name.cmp(&b.name));
    Ok(out)
}

pub fn read<R: Runtime>(app: &AppHandle<R>, name: &str) -> Result<serde_json::Value, String> {
    let safe = safe_name(name).ok_or("invalid name")?;
    let Some(dir) = root(app) else {
        return Err("data root not initialized".into());
    };
    let path = dir.join(format!("{safe}.json"));
    let text = std::fs::read_to_string(&path).map_err(|e| e.to_string())?;
    serde_json::from_str(&text).map_err(|e| e.to_string())
}

pub fn write<R: Runtime>(
    app: &AppHandle<R>,
    name: &str,
    content: &serde_json::Value,
) -> Result<(), String> {
    let safe = safe_name(name).ok_or("invalid name")?;
    let Some(dir) = root(app) else {
        return Err("data root not initialized".into());
    };
    ensure_dir(&dir).map_err(|e| e.to_string())?;
    let path = dir.join(format!("{safe}.json"));
    let text = serde_json::to_string_pretty(content).map_err(|e| e.to_string())?;
    crate::filesystem::atomic_write(&path, text.as_bytes()).map_err(|e| e.to_string())
}

pub fn delete<R: Runtime>(app: &AppHandle<R>, name: &str) -> Result<bool, String> {
    let safe = safe_name(name).ok_or("invalid name")?;
    let Some(dir) = root(app) else {
        return Err("data root not initialized".into());
    };
    let path = dir.join(format!("{safe}.json"));
    if !path.exists() {
        return Ok(false);
    }
    std::fs::remove_file(&path).map_err(|e| e.to_string())?;
    Ok(true)
}

#[allow(dead_code)]
pub fn root_path<R: Runtime>(app: &AppHandle<R>) -> Option<PathBuf> {
    root(app)
}

#[cfg(test)]
mod tests {
    use super::safe_name;

    #[test]
    fn rejects_empty_and_whitespace() {
        assert_eq!(safe_name(""), None);
        assert_eq!(safe_name("   "), None);
    }

    #[test]
    fn rejects_double_dot() {
        assert_eq!(safe_name(".."), None);
        assert_eq!(safe_name("../../etc/passwd"), None);
        assert_eq!(safe_name("foo..bar"), None);
    }

    #[test]
    fn rejects_leading_dot() {
        assert_eq!(safe_name(".hidden"), None);
        assert_eq!(safe_name(".gitignore"), None);
    }

    #[test]
    fn rejects_path_separators() {
        assert_eq!(safe_name("a/b"), None);
        assert_eq!(safe_name("a\\b"), None);
        assert_eq!(safe_name("a:b"), None);
    }

    #[test]
    fn rejects_quotes_and_punctuation() {
        // `Q4 ' 26` contains an apostrophe which is not in the allow-list,
        // so it must be rejected per the new SEC-07 policy.
        assert_eq!(safe_name("Q4 ' 26"), None);
    }

    #[test]
    fn allows_typical_names() {
        assert_eq!(safe_name("Layout 1"), Some("Layout 1".to_string()));
        assert_eq!(safe_name("my-preset"), Some("my-preset".to_string()));
        assert_eq!(safe_name("Q4_26"), Some("Q4_26".to_string()));
        assert_eq!(safe_name("Default"), Some("Default".to_string()));
    }

    #[test]
    fn rejects_names_over_64_chars() {
        let long = "a".repeat(65);
        assert_eq!(safe_name(&long), None);
        let limit = "a".repeat(64);
        assert_eq!(safe_name(&limit), Some(limit));
    }

    #[test]
    fn trims_surrounding_whitespace() {
        assert_eq!(safe_name("  Layout 1  "), Some("Layout 1".to_string()));
    }
}
