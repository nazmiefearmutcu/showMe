/**
 * Theme persistence.
 *
 * Stored at `localStorage["showme.theme"]`; the choice is mirrored to
 * `[data-theme]` on `<html>` so tokens.css picks the right palette.
 *
 * In Tauri-mode we'll later sync with the OS appearance via
 * `tauri-plugin-os` (Round 16+).
 */
export type Theme = "dark" | "light";
export type Accent = "cyan" | "amber" | "violet" | "lime";
export type Density = "compact" | "comfortable";

const THEME_KEY = "showme.theme";
const ACCENT_KEY = "showme.accent";
const DENSITY_KEY = "showme.density";

export function readTheme(): Theme {
  if (typeof localStorage === "undefined") return "dark";
  const v = localStorage.getItem(THEME_KEY);
  return v === "light" ? "light" : "dark";
}

export function applyTheme(theme: Theme) {
  if (typeof document === "undefined") return;
  document.documentElement.setAttribute("data-theme", theme);
  if (typeof localStorage !== "undefined") localStorage.setItem(THEME_KEY, theme);
}

export function toggleTheme(): Theme {
  const next: Theme = readTheme() === "dark" ? "light" : "dark";
  applyTheme(next);
  return next;
}

export function readAccent(): Accent {
  if (typeof localStorage === "undefined") return "cyan";
  const v = localStorage.getItem(ACCENT_KEY);
  return v === "amber" || v === "violet" || v === "lime" ? v : "cyan";
}

export function applyAccent(accent: Accent) {
  if (typeof document === "undefined") return;
  document.documentElement.setAttribute("data-accent", accent);
  if (typeof localStorage !== "undefined") localStorage.setItem(ACCENT_KEY, accent);
}

export function readDensity(): Density {
  if (typeof localStorage === "undefined") return "compact";
  return localStorage.getItem(DENSITY_KEY) === "comfortable" ? "comfortable" : "compact";
}

export function applyDensity(density: Density) {
  if (typeof document === "undefined") return;
  document.documentElement.setAttribute("data-density", density);
  if (typeof localStorage !== "undefined") localStorage.setItem(DENSITY_KEY, density);
}

export function applyAppearancePrefs() {
  applyTheme(readTheme());
  applyAccent(readAccent());
  applyDensity(readDensity());
}
