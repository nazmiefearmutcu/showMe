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

fn safe_name(name: &str) -> Option<String> {
    let trimmed = name.trim();
    if trimmed.is_empty() {
        return None;
    }
    if trimmed.contains(|c: char| {
        c == '/' || c == '\\' || c.is_control() || c == ':' || c == '\0'
    }) {
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
    std::fs::write(&path, text).map_err(|e| e.to_string())
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

pub fn root_path<R: Runtime>(app: &AppHandle<R>) -> Option<PathBuf> {
    root(app)
}
