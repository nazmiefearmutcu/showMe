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
  const raw = Number(localStorage.getItem(key));
  return Number.isFinite(raw) ? raw : fallback;
}
