/**
 * LocalStorage-backed "recently opened" stack for the command palette
 * and the sidebar Recent group. Capped at 5 entries; survives reload but
 * not import/export.
 *
 *   v1 — initial palette-only stack (UI-INT-04).
 *   v2 — QA-2026-05-23: sidebar Recent group switched from a hard-coded
 *        5-item seed (GEX, BTMM, WEI, OMON, EQS) to this stack. v1
 *        contents are migrated forward losslessly; legacy v1 keys are
 *        purged so we never resurrect stale seeds.
 */
import { safeReadLocal } from "./safe-storage";

const KEY = "showme.palette.recents.v2";
const LEGACY_KEYS = ["showme.palette.recents.v1"];
const MAX = 5;

function migrateLegacyIfNeeded(): void {
  if (typeof window === "undefined") return;
  try {
    if (window.localStorage.getItem(KEY)) return;
    for (const legacyKey of LEGACY_KEYS) {
      const raw = window.localStorage.getItem(legacyKey);
      if (!raw) continue;
      window.localStorage.removeItem(legacyKey);
      // Forward legacy content into v2 — preserves real user history
      // (anything the palette had recorded) while shedding the old key.
      try {
        const parsed = JSON.parse(raw);
        if (Array.isArray(parsed)) {
          const cleaned = parsed
            .filter((s) => typeof s === "string")
            .slice(0, MAX);
          if (cleaned.length > 0) {
            window.localStorage.setItem(KEY, JSON.stringify(cleaned));
          }
        }
      } catch {
        // Corrupt JSON in legacy slot — just drop it.
      }
    }
  } catch {
    // Ignore quota / sandbox errors.
  }
}

function safeRead(): string[] {
  if (typeof window === "undefined") return [];
  migrateLegacyIfNeeded();
  const arr = safeReadLocal<string[]>(KEY, [], {
    label: "Recent commands",
    validate: (v): v is string[] => Array.isArray(v),
  });
  return arr.filter((s) => typeof s === "string").slice(0, MAX);
}

function safeWrite(stack: string[]): void {
  if (typeof window === "undefined") return;
  try {
    window.localStorage.setItem(KEY, JSON.stringify(stack));
  } catch {
    // Ignore quota / private-mode errors.
  }
}

export function listRecentCodes(): string[] {
  return safeRead();
}

export function recordRecentCode(code: string): void {
  const upper = code.toUpperCase();
  const current = safeRead().filter((c) => c.toUpperCase() !== upper);
  current.unshift(upper);
  safeWrite(current.slice(0, MAX));
}

export function __resetForTests(): void {
  if (typeof window === "undefined") return;
  window.localStorage.removeItem(KEY);
  for (const legacyKey of LEGACY_KEYS) {
    window.localStorage.removeItem(legacyKey);
  }
}
