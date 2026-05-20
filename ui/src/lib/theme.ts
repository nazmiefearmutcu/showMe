/**
 * Theme persistence — v2.
 *
 * Codex-style preset gallery + 3 user-tunable color slots (bg/surface/accent).
 * The picked values are mirrored to `[data-preset]` on `<html>` so tokens.css
 * picks the right palette; the "custom" preset additionally writes the three
 * inline CSS variables on `<html>` so the user's exact colors stick.
 *
 * Migration path: a v1 install that has `showme.theme` / `showme.accent` /
 * `showme.density` is read once on first boot and folded into v2.
 */

// ── Public types ────────────────────────────────────────────────────────

export type Preset =
  | "midnight"
  | "matrix"
  | "iced"
  | "amber"
  | "papyrus"
  | "neon"
  | "custom";

export type Density = "compact" | "comfortable";

export interface CustomColors {
  bg: string;
  surface: string;
  accent: string;
}

export interface ThemeState {
  preset: Preset;
  custom: CustomColors;
  density: Density;
}

// ── Legacy aliases (kept so old callers compile) ────────────────────────

export type Theme = "dark" | "light";
export type Accent = "cyan" | "amber" | "violet" | "lime";

// ── Transition (overlay during preset/density swap) ─────────────────────

import { runThemeTransition } from "@/lib/theme-transition";

// ── Constants ───────────────────────────────────────────────────────────

const KEY_V2 = "showme.theme.v2";
const KEY_V1_THEME = "showme.theme";
const KEY_V1_ACCENT = "showme.accent";
const KEY_V1_DENSITY = "showme.density";
const KEY_DEFAULT_PAPYRUS_MIGRATION = "showme.theme.defaultPapyrus.v1";
const DEFAULT_PRESET: Exclude<Preset, "custom"> = "papyrus";

const PRESET_DEFAULTS: Record<Exclude<Preset, "custom">, CustomColors> = {
  midnight: { bg: "#0b0907", surface: "#1b1813", accent: "#c96442" },
  matrix: { bg: "#000000", surface: "#040b06", accent: "#00ff41" },
  iced: { bg: "#04101c", surface: "#0c2238", accent: "#5bc0eb" },
  amber: { bg: "#0a0703", surface: "#1c1208", accent: "#ffb547" },
  papyrus: { bg: "#ece6d6", surface: "#faf5e3", accent: "#8a5a1f" },
  neon: { bg: "#05000b", surface: "#160426", accent: "#ff2bd6" },
};

const DEFAULT_STATE: ThemeState = {
  preset: DEFAULT_PRESET,
  custom: { ...PRESET_DEFAULTS[DEFAULT_PRESET] },
  density: "compact",
};

export const PRESETS: Preset[] = [
  "midnight",
  "matrix",
  "iced",
  "amber",
  "papyrus",
  "neon",
  "custom",
];

export const PRESET_LABELS: Record<Preset, string> = {
  midnight: "Midnight",
  matrix: "Matrix",
  iced: "Iced",
  amber: "Amber",
  papyrus: "Papyrus",
  neon: "Neon",
  custom: "Custom",
};

export const THEME_CHANGE_EVENT = "showme:theme-changed";

export function presetColors(p: Exclude<Preset, "custom">): CustomColors {
  return { ...PRESET_DEFAULTS[p] };
}

// ── Helpers ─────────────────────────────────────────────────────────────

function isHex(s: unknown): s is string {
  return typeof s === "string" && /^#([0-9a-f]{3}){1,2}$/i.test(s);
}

function safeParse(raw: string | null): ThemeState | null {
  if (!raw) return null;
  try {
    const obj = JSON.parse(raw);
    if (!obj || typeof obj !== "object") return null;
    const preset = (PRESETS as string[]).includes(obj.preset)
      ? (obj.preset as Preset)
      : DEFAULT_PRESET;
    const density: Density = obj.density === "comfortable" ? "comfortable" : "compact";
    const cc = obj.custom ?? {};
    const custom: CustomColors = {
      bg: isHex(cc.bg) ? cc.bg : DEFAULT_STATE.custom.bg,
      surface: isHex(cc.surface) ? cc.surface : DEFAULT_STATE.custom.surface,
      accent: isHex(cc.accent) ? cc.accent : DEFAULT_STATE.custom.accent,
    };
    return { preset, custom, density };
  } catch {
    return null;
  }
}

function migrateFromV1(): ThemeState | null {
  if (typeof localStorage === "undefined") return null;
  const oldTheme = localStorage.getItem(KEY_V1_THEME);
  const oldAccent = localStorage.getItem(KEY_V1_ACCENT);
  const oldDensity = localStorage.getItem(KEY_V1_DENSITY);
  if (!oldTheme && !oldAccent && !oldDensity) return null;

  // Map v1 to nearest preset.
  let preset: Preset = DEFAULT_PRESET;
  if (oldTheme === "light") preset = "papyrus";
  else if (oldTheme === "dark") preset = "midnight";
  else if (oldAccent === "amber") preset = "amber";
  // (cyan/violet/lime fold into the new Papyrus default; user can re-pick.)

  const density: Density = oldDensity === "comfortable" ? "comfortable" : "compact";
  // `preset` here is always one of the non-custom variants by construction,
  // but TS narrows it; pull defaults defensively.
  const defaults = PRESET_DEFAULTS[preset as Exclude<Preset, "custom">] ?? PRESET_DEFAULTS.midnight;
  return {
    preset,
    custom: { ...defaults },
    density,
  };
}

// ── Read / write state ──────────────────────────────────────────────────

export function readState(): ThemeState {
  if (typeof localStorage === "undefined") return { ...DEFAULT_STATE };
  const v2 = safeParse(localStorage.getItem(KEY_V2));
  if (v2) return migrateStoredMidnightDefault(v2);
  const migrated = migrateFromV1();
  if (migrated) {
    try {
      localStorage.setItem(KEY_V2, JSON.stringify(migrated));
      localStorage.setItem(KEY_DEFAULT_PAPYRUS_MIGRATION, "1");
    } catch {
      // ignore
    }
    return migrated;
  }
  return { ...DEFAULT_STATE };
}

function writeState(state: ThemeState): void {
  if (typeof localStorage === "undefined") return;
  try {
    localStorage.setItem(KEY_V2, JSON.stringify(state));
    localStorage.setItem(KEY_DEFAULT_PAPYRUS_MIGRATION, "1");
  } catch {
    // ignore quota etc.
  }
}

function migrateStoredMidnightDefault(state: ThemeState): ThemeState {
  if (typeof localStorage === "undefined") return state;
  try {
    if (localStorage.getItem(KEY_DEFAULT_PAPYRUS_MIGRATION)) return state;
    if (state.preset !== "midnight") {
      localStorage.setItem(KEY_DEFAULT_PAPYRUS_MIGRATION, "1");
      return state;
    }
    const next: ThemeState = {
      ...state,
      preset: "papyrus",
      custom: { ...PRESET_DEFAULTS.papyrus },
    };
    writeState(next);
    return next;
  } catch {
    return state;
  }
}

// ── Apply (push to <html>) ──────────────────────────────────────────────

export function applyState(state: ThemeState): void {
  if (typeof document === "undefined") return;
  const root = document.documentElement;
  root.setAttribute("data-preset", state.preset);
  root.setAttribute("data-density", state.density);
  // Maintain legacy data-theme so any holdover CSS still resolves.
  root.setAttribute("data-theme", state.preset === "papyrus" ? "light" : "dark");

  if (state.preset === "custom") {
    root.style.setProperty("--bg", state.custom.bg);
    root.style.setProperty("--surface", state.custom.surface);
    root.style.setProperty("--accent", state.custom.accent);
  } else {
    root.style.removeProperty("--bg");
    root.style.removeProperty("--surface");
    root.style.removeProperty("--accent");
  }
  if (typeof window !== "undefined") {
    window.dispatchEvent(new CustomEvent(THEME_CHANGE_EVENT, { detail: state }));
  }
}

export function setPreset(preset: Preset): ThemeState {
  const state = readState();
  state.preset = preset;
  if (preset !== "custom") {
    state.custom = { ...PRESET_DEFAULTS[preset] };
  }
  writeState(state);
  runThemeTransition(() => applyState(state));
  return state;
}

export function setCustom(custom: Partial<CustomColors>): ThemeState {
  const state = readState();
  state.preset = "custom";
  state.custom = {
    bg: custom.bg && isHex(custom.bg) ? custom.bg : state.custom.bg,
    surface:
      custom.surface && isHex(custom.surface) ? custom.surface : state.custom.surface,
    accent:
      custom.accent && isHex(custom.accent) ? custom.accent : state.custom.accent,
  };
  writeState(state);
  runThemeTransition(() => applyState(state));
  return state;
}

export function setDensity(density: Density): ThemeState {
  const state = readState();
  state.density = density;
  writeState(state);
  runThemeTransition(() => applyState(state));
  return state;
}

// ── Legacy API surface (kept compiling — call sites get progressively migrated) ─

export function readTheme(): Theme {
  return readState().preset === "papyrus" ? "light" : "dark";
}

export function applyTheme(t: Theme): void {
  setPreset(t === "light" ? "papyrus" : "midnight");
}

const LAST_DARK_KEY = "showme.theme.lastDark.v1";
const LAST_LIGHT_KEY = "showme.theme.lastLight.v1";

function readRememberedPreset(key: string, fallback: Preset): Preset {
  if (typeof localStorage === "undefined") return fallback;
  try {
    const stored = localStorage.getItem(key);
    if (stored && (PRESETS as string[]).includes(stored)) return stored as Preset;
  } catch {
    // ignore
  }
  return fallback;
}

function writeRememberedPreset(key: string, preset: Preset): void {
  if (typeof localStorage === "undefined") return;
  try {
    localStorage.setItem(key, preset);
  } catch {
    // ignore
  }
}

/**
 * Toggle between the user's last-used dark and light preset (UX-09 P2 +
 * UI-INT-06 P2). Replaces the legacy `applyTheme(light/dark)` which
 * always reset to midnight/papyrus regardless of the user's current pick.
 */
export function toggleTheme(): Theme {
  const state = readState();
  const isLight = state.preset === "papyrus";
  if (isLight) {
    writeRememberedPreset(LAST_LIGHT_KEY, state.preset);
    const next = readRememberedPreset(LAST_DARK_KEY, "midnight");
    setPreset(next);
    return "dark";
  }
  // Currently dark — remember it and flip to last-used light preset.
  if (state.preset !== "custom") {
    writeRememberedPreset(LAST_DARK_KEY, state.preset);
  }
  const next = readRememberedPreset(LAST_LIGHT_KEY, "papyrus");
  setPreset(next);
  return "light";
}

const ACCENT_TO_PRESET: Record<Accent, Preset> = {
  cyan: "midnight",
  amber: "amber",
  violet: "neon",
  lime: "matrix",
};

const PRESET_TO_ACCENT: Record<Preset, Accent> = {
  midnight: "amber",
  matrix: "lime",
  iced: "cyan",
  amber: "amber",
  papyrus: "amber",
  neon: "violet",
  custom: "violet",
};

export function readAccent(): Accent {
  return PRESET_TO_ACCENT[readState().preset];
}

export function applyAccent(a: Accent): void {
  setPreset(ACCENT_TO_PRESET[a]);
}

export function readDensity(): Density {
  return readState().density;
}

export function applyDensity(d: Density): void {
  setDensity(d);
}

export function applyAppearancePrefs(): void {
  applyState(readState());
}
