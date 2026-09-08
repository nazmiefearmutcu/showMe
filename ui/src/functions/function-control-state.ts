import { useEffect, useState } from "react";

export type PrimitiveControlValue = string | number;
export type LoadState = "idle" | "loading" | "ok" | "error" | "refreshing" | "timeout";

export const NEWS_LIMITS = [10, 25, 50, 100] as const;
export const ROW_LIMITS = [25, 50, 100, 200] as const;
export const TOP_N_LIMITS = [10, 20, 50, 100] as const;

export type NewsLimit = (typeof NEWS_LIMITS)[number];
export type RowLimit = (typeof ROW_LIMITS)[number];
export type TopNLimit = (typeof TOP_N_LIMITS)[number];

export function usePersistentOption<T extends PrimitiveControlValue>(
  key: string,
  options: readonly T[],
  fallback: T,
) {
  const [value, setValue] = useState<T>(() => readStoredOption(key, options, fallback));
  useEffect(() => {
    if (typeof localStorage !== "undefined") {
      localStorage.setItem(key, String(value));
    }
  }, [key, value]);
  return [value, setValue] as const;
}

export function usePersistentNumber(key: string, fallback: number) {
  const [value, setValue] = useState<number>(() => readStoredNumber(key, fallback));
  useEffect(() => {
    if (typeof localStorage !== "undefined") {
      localStorage.setItem(key, String(value));
    }
  }, [key, value]);
  return [value, setValue] as const;
}

/**
 * Persistence rule for pane controls (survey F3):
 *
 * - Whitelisted string/number options  -> `usePersistentOption`
 * - Free numeric values                -> `usePersistentNumber`
 * - Free single-string values          -> `usePersistentString`
 * - Raw localStorage is ONLY allowed for structured values the hooks cannot
 *   hold: JSON arrays/objects (HP/ISIN/HFS/OSA legs), comma-set semantics
 *   (TECH, TRDH), and async-validated values whose option list is only known
 *   after load (OMON/IVOL expiry vs the loaded expiry list). Keep the
 *   `showme.<code>.<param>` key format in those cases too.
 *
 * All hooks store `String(value)` under the same key, so existing persisted
 * values stay backward-compatible.
 */
export function usePersistentString(key: string, fallback: string) {
  const [value, setValue] = useState<string>(() => readStoredString(key, fallback));
  useEffect(() => {
    if (typeof localStorage !== "undefined") {
      localStorage.setItem(key, value);
    }
  }, [key, value]);
  return [value, setValue] as const;
}

function readStoredString(key: string, fallback: string): string {
  if (typeof localStorage === "undefined") return fallback;
  const raw = localStorage.getItem(key);
  return raw ?? fallback;
}

export function clampToOptions<T extends number>(
  value: number,
  options: readonly T[],
  fallback: T,
): T {
  return options.includes(value as T) ? (value as T) : fallback;
}

function readStoredOption<T extends PrimitiveControlValue>(
  key: string,
  options: readonly T[],
  fallback: T,
): T {
  if (typeof localStorage === "undefined") return fallback;
  const raw = localStorage.getItem(key);
  if (raw == null) return fallback;
  const value = typeof fallback === "number" ? Number(raw) : raw;
  return options.includes(value as T) ? (value as T) : fallback;
}

function readStoredNumber(key: string, fallback: number): number {
  if (typeof localStorage === "undefined") return fallback;
  // GUARD: Number(null) === 0, so an absent key must be checked BEFORE the
  // numeric coercion or every fresh session reads 0 instead of `fallback`
  // (and then persists the 0 on mount, wedging the control permanently).
  const raw = localStorage.getItem(key);
  if (raw == null || raw.trim() === "") return fallback;
  const value = Number(raw);
  return Number.isFinite(value) ? value : fallback;
}
