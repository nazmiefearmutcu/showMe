/**
 * Timezone preference (UX-TZ-01).
 *
 * Single source of truth for how showMe formats clocks, dates, and news
 * timestamps. Defaults to Europe/Istanbul because that's where the operator
 * lives — but the value is user-tunable from Preferences → Appearance.
 *
 * The picked timezone is mirrored to a tiny event-emitter so React components
 * can subscribe via `useTimezone()` and re-render the moment the user flips
 * the dropdown; no full page reload required.
 */
import { useSyncExternalStore } from "react";

/**
 * Persisted shape: `{"mode": "auto" | "manual", "manualTz": "Europe/Istanbul"}`.
 *
 * On a virgin install `mode = "auto"` — the app reads the OS tz via
 * `Intl.DateTimeFormat().resolvedOptions().timeZone` and follows it every
 * launch. Once the user explicitly picks a city, mode flips to `"manual"`
 * and the manual pick is honored verbatim regardless of where the laptop
 * is plugged in.
 *
 * Legacy v1 callers that stored a bare tz string still decode correctly —
 * `safeParse` accepts both.
 */
const STORAGE_KEY = "showme.timezone.v1";
const FALLBACK_TZ = "Europe/Istanbul";

export type TimezoneMode = "auto" | "manual";

interface TimezoneState {
  mode: TimezoneMode;
  manualTz: string;
}

const DEFAULT_STATE: TimezoneState = { mode: "auto", manualTz: FALLBACK_TZ };

type Listener = (tz: string) => void;
const listeners = new Set<Listener>();

function isValidTimeZone(tz: unknown): tz is string {
  if (typeof tz !== "string" || tz.length === 0) return false;
  try {
    new Intl.DateTimeFormat(undefined, { timeZone: tz });
    return true;
  } catch {
    return false;
  }
}

export function getSystemTimezone(): string {
  try {
    const tz = Intl.DateTimeFormat().resolvedOptions().timeZone;
    if (isValidTimeZone(tz)) return tz;
  } catch {
    /* ignore */
  }
  return FALLBACK_TZ;
}

function safeParse(raw: string | null): TimezoneState {
  if (!raw) return { ...DEFAULT_STATE };
  // Legacy v1: bare tz string (no JSON wrapper).
  if (isValidTimeZone(raw)) {
    return { mode: "manual", manualTz: raw };
  }
  try {
    const obj = JSON.parse(raw);
    const mode: TimezoneMode = obj?.mode === "manual" ? "manual" : "auto";
    const manualTz = isValidTimeZone(obj?.manualTz) ? obj.manualTz : FALLBACK_TZ;
    return { mode, manualTz };
  } catch {
    return { ...DEFAULT_STATE };
  }
}

function readState(): TimezoneState {
  if (typeof localStorage === "undefined") return { ...DEFAULT_STATE };
  try {
    return safeParse(localStorage.getItem(STORAGE_KEY));
  } catch {
    return { ...DEFAULT_STATE };
  }
}

function writeState(state: TimezoneState): void {
  if (typeof localStorage === "undefined") return;
  try {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(state));
  } catch {
    /* ignore quota */
  }
}

function notify(): void {
  const tz = readTimezone();
  listeners.forEach((fn) => {
    try {
      fn(tz);
    } catch {
      /* never let one subscriber break peers */
    }
  });
}

export function readTimezone(): string {
  const state = readState();
  if (state.mode === "auto") return getSystemTimezone();
  return state.manualTz;
}

export function readTimezoneMode(): TimezoneMode {
  return readState().mode;
}

export function readManualTimezone(): string {
  return readState().manualTz;
}

export function setTimezoneMode(mode: TimezoneMode): string {
  const state = readState();
  state.mode = mode;
  writeState(state);
  notify();
  return readTimezone();
}

/**
 * User explicitly picked a city — flip to manual and remember it.
 * `writeTimezone` keeps its v1 signature for existing callers.
 */
export function writeTimezone(tz: string): string {
  const next = isValidTimeZone(tz) ? tz : FALLBACK_TZ;
  writeState({ mode: "manual", manualTz: next });
  notify();
  return next;
}

/**
 * Re-poll the OS tz and re-notify if we're in auto mode. Cheap; safe to
 * call on every focus / visibilitychange event so the app follows a
 * traveling laptop without needing a restart.
 */
export function refreshAutoTimezone(): void {
  if (readState().mode === "auto") notify();
}

export function subscribeTimezone(fn: Listener): () => void {
  listeners.add(fn);
  return () => {
    listeners.delete(fn);
  };
}

/**
 * Bundle D / MULTITAB-01. Cross-tab sync: when another browser tab writes a
 * new timezone, the `storage` event fires here and we rebroadcast through
 * the in-process listener set so every `useTimezone()`/`useTimezoneMode()`
 * subscriber repaints. Same-tab writes still go through `notify()` directly
 * — `storage` only fires for cross-tab changes.
 */
if (typeof window !== "undefined" && typeof window.addEventListener === "function") {
  window.addEventListener("storage", (event) => {
    if (event.key !== STORAGE_KEY) return;
    notify();
  });
}

export function useTimezone(): string {
  return useSyncExternalStore(
    (n) => subscribeTimezone(() => n()),
    readTimezone,
    () => FALLBACK_TZ,
  );
}

export function useTimezoneMode(): TimezoneMode {
  return useSyncExternalStore(
    (n) => subscribeTimezone(() => n()),
    readTimezoneMode,
    () => "auto",
  );
}

// ── Formatters ──────────────────────────────────────────────────────────

/**
 * Treat naive ISO-ish timestamps as UTC so a news row published "2026-05-15
 * 12:48:00" (no offset, no Z) doesn't get re-interpreted as local wall time
 * and drift several hours when converted into the user's display tz. RSS
 * adapters in the engine sometimes hand us naive strings; this is the
 * single chokepoint for hardening them.
 */
function safeDate(value: Date | string | number | null | undefined): Date | null {
  if (value == null) return null;
  if (value instanceof Date) {
    return Number.isNaN(value.getTime()) ? null : value;
  }
  if (typeof value === "number") {
    const d = new Date(value);
    return Number.isNaN(d.getTime()) ? null : d;
  }
  if (typeof value !== "string") return null;
  const trimmed = value.trim();
  if (!trimmed) return null;
  // Already has an explicit zone marker → trust it.
  const naive = /^\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}(:\d{2}(\.\d+)?)?$/.test(trimmed);
  const hasOffset = /(Z|[+-]\d{2}:?\d{2})$/.test(trimmed);
  const normalized = naive && !hasOffset
    ? trimmed.replace(" ", "T") + "Z"
    : trimmed;
  const d = new Date(normalized);
  return Number.isNaN(d.getTime()) ? null : d;
}

export function formatTime(
  value: Date | string | number | null | undefined,
  opts: { tz?: string; seconds?: boolean; hour12?: boolean } = {},
): string {
  const d = safeDate(value);
  if (!d) return "-";
  const tz = opts.tz ?? readTimezone();
  try {
    return new Intl.DateTimeFormat("en-GB", {
      hour: "2-digit",
      minute: "2-digit",
      second: opts.seconds ? "2-digit" : undefined,
      hour12: opts.hour12 ?? false,
      timeZone: tz,
    }).format(d);
  } catch {
    return d.toISOString().slice(11, opts.seconds ? 19 : 16);
  }
}

export function formatDate(
  value: Date | string | number | null | undefined,
  opts: { tz?: string; weekday?: boolean } = {},
): string {
  const d = safeDate(value);
  if (!d) return "-";
  const tz = opts.tz ?? readTimezone();
  try {
    return new Intl.DateTimeFormat("en-GB", {
      year: "numeric",
      month: "short",
      day: "2-digit",
      weekday: opts.weekday ? "short" : undefined,
      timeZone: tz,
    }).format(d);
  } catch {
    return d.toISOString().slice(0, 10);
  }
}

/**
 * Mirrors Welcome.tsx's old `formatDateStamp` shape — "MON MAY 15" — but
 * routed through the user-picked tz so the masthead matches the statusbar.
 */
export function formatDateStamp(
  value: Date | string | number | null | undefined,
  tz: string = readTimezone(),
): string {
  const d = safeDate(value);
  if (!d) return "-";
  try {
    return new Intl.DateTimeFormat("en-US", {
      weekday: "short",
      month: "short",
      day: "2-digit",
      timeZone: tz,
    })
      .format(d)
      .replace(/,/g, "")
      .replace(/\s+/g, " ")
      .trim()
      .toUpperCase();
  } catch {
    return d.toISOString().slice(0, 10).toUpperCase();
  }
}

/**
 * Compact relative label for news rows: "12:48" if today, "May 14" otherwise.
 * Honours the user's tz so the "is this today?" check matches the wall clock
 * the user actually sees.
 */
export function formatNewsTimestamp(
  value: Date | string | number | null | undefined,
  tz: string = readTimezone(),
): string {
  const d = safeDate(value);
  if (!d) return "";
  const now = new Date();
  try {
    const fmt = new Intl.DateTimeFormat("en-CA", {
      year: "numeric",
      month: "2-digit",
      day: "2-digit",
      timeZone: tz,
    });
    if (fmt.format(d) === fmt.format(now)) {
      return formatTime(d, { tz });
    }
    return new Intl.DateTimeFormat("en-US", {
      month: "short",
      day: "2-digit",
      timeZone: tz,
    }).format(d);
  } catch {
    return formatTime(d, { tz });
  }
}

// ── Timezone catalog (for the picker) ───────────────────────────────────

export interface TimezoneOption {
  id: string;
  label: string;
  group: "popular" | "europe" | "americas" | "asia" | "other";
}

export const POPULAR_TIMEZONES: TimezoneOption[] = [
  { id: "Europe/Istanbul", label: "Istanbul (TRT, UTC+3)", group: "popular" },
  { id: "UTC", label: "UTC", group: "popular" },
  { id: "Europe/London", label: "London (GMT/BST)", group: "europe" },
  { id: "Europe/Berlin", label: "Berlin (CET/CEST)", group: "europe" },
  { id: "Europe/Paris", label: "Paris (CET/CEST)", group: "europe" },
  { id: "Europe/Moscow", label: "Moscow (MSK, UTC+3)", group: "europe" },
  { id: "America/New_York", label: "New York (ET)", group: "americas" },
  { id: "America/Chicago", label: "Chicago (CT)", group: "americas" },
  { id: "America/Los_Angeles", label: "Los Angeles (PT)", group: "americas" },
  { id: "America/Sao_Paulo", label: "São Paulo (BRT)", group: "americas" },
  { id: "Asia/Dubai", label: "Dubai (GST, UTC+4)", group: "asia" },
  { id: "Asia/Tokyo", label: "Tokyo (JST, UTC+9)", group: "asia" },
  { id: "Asia/Hong_Kong", label: "Hong Kong (HKT)", group: "asia" },
  { id: "Asia/Shanghai", label: "Shanghai (CST, UTC+8)", group: "asia" },
  { id: "Asia/Singapore", label: "Singapore (SGT)", group: "asia" },
  { id: "Asia/Kolkata", label: "Mumbai (IST, UTC+5:30)", group: "asia" },
  { id: "Australia/Sydney", label: "Sydney (AEDT/AEST)", group: "other" },
];

export function listAllTimezones(): string[] {
  try {
    // Intl.supportedValuesOf is widely available in modern WebKit/Chromium.
    const intlAny = Intl as unknown as {
      supportedValuesOf?: (key: string) => string[];
    };
    if (typeof intlAny.supportedValuesOf === "function") {
      return intlAny.supportedValuesOf("timeZone");
    }
  } catch {
    /* ignore */
  }
  return POPULAR_TIMEZONES.map((opt) => opt.id);
}

export function timezoneOffsetLabel(tz: string, at: Date = new Date()): string {
  try {
    const parts = new Intl.DateTimeFormat("en-GB", {
      timeZone: tz,
      timeZoneName: "shortOffset",
    }).formatToParts(at);
    const off = parts.find((p) => p.type === "timeZoneName")?.value ?? "";
    return off || tz;
  } catch {
    return tz;
  }
}
