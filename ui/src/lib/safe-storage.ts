/**
 * `safeReadLocal` — JSON.parse with corrupt-on-read cleanup.
 *
 * QA found multiple lib/* read sites silently swallowing JSON.parse failures
 * (catch → return defaults), so a single bad blob in localStorage produces
 * persistent, invisible misbehaviour. This helper:
 *
 *   1. Tries `localStorage.getItem(key)` + `JSON.parse`.
 *   2. Optionally validates the parsed value via a guard function.
 *   3. On failure: logs to console, removes the bad key, and pushes a single
 *      warning toast so the user knows their preferences were reset.
 *   4. Toasts are throttled per-key so a hot loop can't spam the host.
 *
 * Wrapper-only by design — call sites keep their existing keys/shapes; only
 * the failure path changes from "silent fallback" to "loud-but-recoverable".
 */
import { toast } from "./toast";

const TOAST_THROTTLE_MS = 5_000;
const recentlyToasted = new Map<string, number>();

export interface SafeReadOptions<T> {
  /** Optional shape guard. Returning false treats the blob as corrupt. */
  validate?: (value: unknown) => value is T;
  /** Pretty-name used in the toast title, e.g. "Watchlist". */
  label?: string;
  /** Suppress side effects (toast + remove) for diagnostic tests. */
  silent?: boolean;
}

function emitCorruptionToast(key: string, label?: string): void {
  const now = Date.now();
  const previous = recentlyToasted.get(key) ?? 0;
  if (now - previous < TOAST_THROTTLE_MS) return;
  recentlyToasted.set(key, now);
  const pretty = label ?? prettifyKey(key);
  toast.warn(
    `${pretty} reset due to corrupted data`,
    `Cleared localStorage entry "${key}" to recover.`,
  );
}

function prettifyKey(key: string): string {
  return key
    .replace(/^showme\./i, "")
    .replace(/\.v\d+$/i, "")
    .split(/[-._]/)
    .filter(Boolean)
    .map((part) => part.charAt(0).toUpperCase() + part.slice(1).toLowerCase())
    .join(" ");
}

/**
 * Safely parse a JSON blob persisted under `key`. Returns `fallback` when the
 * key is missing, the blob is unparseable, or the validator rejects it. On
 * corruption: logs the original error, removes the bad blob, and toasts.
 */
export function safeReadLocal<T>(
  key: string,
  fallback: T,
  options: SafeReadOptions<T> = {},
): T {
  if (typeof localStorage === "undefined") return fallback;
  let raw: string | null = null;
  try {
    raw = localStorage.getItem(key);
  } catch (err) {
    // Private-mode iOS Safari can throw on getItem when the bucket is full.
    if (!options.silent) {
      console.warn(`[safe-storage] failed to read ${key}`, err);
    }
    return fallback;
  }
  if (raw == null) return fallback;
  let parsed: unknown;
  try {
    parsed = JSON.parse(raw);
  } catch (err) {
    if (!options.silent) {
      console.warn(`[safe-storage] corrupt JSON for ${key}`, err);
      try {
        localStorage.removeItem(key);
      } catch {
        /* nothing to do */
      }
      emitCorruptionToast(key, options.label);
    }
    return fallback;
  }
  if (options.validate && !options.validate(parsed)) {
    if (!options.silent) {
      console.warn(`[safe-storage] schema mismatch for ${key}`, parsed);
      try {
        localStorage.removeItem(key);
      } catch {
        /* nothing to do */
      }
      emitCorruptionToast(key, options.label);
    }
    return fallback;
  }
  return parsed as T;
}

// ---------- safeWriteLocal ----------

const QUOTA_TOAST_THROTTLE_MS = 30_000;
const recentlyQuotaToasted = new Map<string, number>();

export interface SafeWriteResult {
  ok: boolean;
  /** Set when the write failed; "quota" | "unavailable" | "serialize" | "unknown". */
  reason?: "quota" | "unavailable" | "serialize" | "unknown";
  error?: unknown;
}

export interface SafeWriteOptions {
  /** Pretty-name used in the toast title, e.g. "Watchlist". */
  label?: string;
  /** Suppress side effects (toast) for diagnostic tests. */
  silent?: boolean;
}

/**
 * Quota-safe localStorage.setItem wrapper.
 *
 * Audit HIGH (S14): watchlist.ts / alerts.ts / symbols.ts each had their own
 * `try { localStorage.setItem(...) } catch {}` block that swallowed
 * QuotaExceededError silently — a user with a packed browser profile would
 * see "pin saved" toasts that, on next reload, had nothing in storage.
 * Centralising the write here lets every caller render a single, accurate
 * "Storage full" toast so the user knows their preference lives in memory
 * only until they free space.
 *
 * Accepts either a pre-serialized string OR any value (will JSON.stringify).
 * Returns a result envelope; callers can branch on `ok`/`reason`.
 */
export function safeWriteLocal(
  key: string,
  value: unknown,
  options: SafeWriteOptions = {},
): SafeWriteResult {
  if (typeof localStorage === "undefined") {
    return { ok: false, reason: "unavailable" };
  }
  let serialized: string;
  try {
    serialized = typeof value === "string" ? value : JSON.stringify(value);
  } catch (err) {
    if (!options.silent) {
      console.warn(`[safe-storage] serialize failed for ${key}`, err);
    }
    return { ok: false, reason: "serialize", error: err };
  }
  try {
    localStorage.setItem(key, serialized);
    return { ok: true };
  } catch (err) {
    // QuotaExceededError varies across browsers: Chromium throws DOMException
    // with name "QuotaExceededError" (code 22 / 1014). Firefox uses
    // NS_ERROR_DOM_QUOTA_REACHED. Be liberal — anything named *Quota* is a
    // bucket-full signal; everything else is reported as "unknown".
    const isQuota = _isQuotaError(err);
    if (!options.silent) {
      console.warn(`[safe-storage] write failed for ${key}`, err);
      if (isQuota) {
        _emitQuotaToast(key, options.label);
      }
    }
    return {
      ok: false,
      reason: isQuota ? "quota" : "unknown",
      error: err,
    };
  }
}

function _isQuotaError(err: unknown): boolean {
  if (!err) return false;
  if (err instanceof Error) {
    if (err.name === "QuotaExceededError") return true;
    if (err.name === "NS_ERROR_DOM_QUOTA_REACHED") return true;
    if (/quota/i.test(err.message)) return true;
  }
  // DOMException has numeric `code`
  if (typeof err === "object" && err !== null && "code" in err) {
    const code = (err as { code: unknown }).code;
    if (code === 22 || code === 1014) return true;
  }
  return false;
}

function _emitQuotaToast(key: string, label?: string): void {
  const now = Date.now();
  const previous = recentlyQuotaToasted.get(key) ?? 0;
  if (now - previous < QUOTA_TOAST_THROTTLE_MS) return;
  recentlyQuotaToasted.set(key, now);
  const pretty = label ?? prettifyKey(key);
  toast.error(
    "Storage full",
    `${pretty} was saved in memory only — free browser storage to persist.`,
  );
}

/**
 * Test helper — clears the per-key toast throttle so successive unit tests
 * don't see a previous test's last-emit timestamp.
 */
export function __resetSafeStorageThrottleForTests(): void {
  recentlyToasted.clear();
  recentlyQuotaToasted.clear();
}
