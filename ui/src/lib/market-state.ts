/**
 * NYSE market state machine.
 *
 * Replaces the heuristic "UTC hours 13-21 ≈ open" rule that lit MARKET / open
 * on Saturday. This module computes the actual NYSE session by extracting
 * America/New_York wall-clock from any `Date` and consulting:
 *   - weekday vs weekend,
 *   - a hand-maintained US federal market-holiday list,
 *   - regular-session hours 09:30–16:00 ET, pre-open 04:00–09:30 ET,
 *     after-hours 16:00–20:00 ET.
 *
 * The Statusbar consumes `getNyseMarketState(now)` and renders a Pill from the
 * returned discriminator. Tests pin Saturday → closed-weekend, Friday 09:35 ET
 * → open, Christmas Day → closed-holiday so the bar can never lie again.
 */
export type NyseMarketState =
  | "closed-weekend"
  | "closed-holiday"
  | "pre-open"
  | "open"
  | "after-hours"
  | "closed";

const PRE_OPEN_START_MIN = 4 * 60; // 04:00 ET
const REGULAR_OPEN_MIN = 9 * 60 + 30; // 09:30 ET
const REGULAR_CLOSE_MIN = 16 * 60; // 16:00 ET
const AFTER_HOURS_END_MIN = 20 * 60; // 20:00 ET

/**
 * US market holidays (NYSE / NASDAQ closures). Format: ISO date string in ET
 * (YYYY-MM-DD). Extend by appending — order is irrelevant, Set membership
 * check is O(1). Sources: NYSE & NASDAQ published calendars for the relevant
 * years. Early-close days (Black Friday, Christmas Eve) are deliberately NOT
 * marked closed here — the helper would mis-classify the morning session as
 * "open" then. A future enhancement can layer those on as `early-close`.
 */
export const NYSE_HOLIDAYS_2026 = [
  "2026-01-01", // New Year's Day
  "2026-01-19", // MLK Day (3rd Mon Jan)
  "2026-02-16", // Presidents' Day (3rd Mon Feb)
  "2026-04-03", // Good Friday
  "2026-05-25", // Memorial Day (last Mon May)
  "2026-06-19", // Juneteenth
  "2026-07-03", // July 4 observed (July 4 falls Saturday in 2026)
  "2026-09-07", // Labor Day (1st Mon Sep)
  "2026-11-26", // Thanksgiving (4th Thu Nov)
  // 2026-11-27 is an early-close day, NOT a full close.
  "2026-12-25", // Christmas Day
] as const;

export const NYSE_HOLIDAYS_2025 = [
  "2025-01-01",
  "2025-01-09", // Carter mourning closure
  "2025-01-20",
  "2025-02-17",
  "2025-04-18",
  "2025-05-26",
  "2025-06-19",
  "2025-07-04",
  "2025-09-01",
  "2025-11-27",
  "2025-12-25",
] as const;

export const NYSE_HOLIDAYS_2027 = [
  "2027-01-01",
  "2027-01-18",
  "2027-02-15",
  "2027-03-26", // Good Friday
  "2027-05-31",
  "2027-06-18", // Juneteenth observed (June 19 is Saturday)
  "2027-07-05", // July 4 observed (July 4 is Sunday)
  "2027-09-06",
  "2027-11-25",
  "2027-12-24", // Christmas observed
] as const;

const DEFAULT_HOLIDAYS = new Set<string>([
  ...NYSE_HOLIDAYS_2025,
  ...NYSE_HOLIDAYS_2026,
  ...NYSE_HOLIDAYS_2027,
]);

let holidayOverride: Set<string> | null = null;

/**
 * Test seam — replace the holiday list for the duration of a unit test. Pass
 * `null` to restore the bundled NYSE calendar.
 */
export function __setHolidaysForTests(list: Iterable<string> | null): void {
  holidayOverride = list ? new Set(list) : null;
}

/**
 * Extract America/New_York wall-clock fields from a Date, regardless of the
 * host's TZ. Uses `Intl.DateTimeFormat` so DST transitions are handled by the
 * platform tz database (no hand-rolled offset math).
 */
export function getEasternParts(now: Date, tz = "America/New_York"): {
  year: number;
  month: number; // 1-12
  day: number; // 1-31
  weekday: number; // 0 (Sun) .. 6 (Sat) matching Date.getDay()
  hour: number; // 0-23
  minute: number; // 0-59
  isoDate: string; // YYYY-MM-DD
} {
  const fmt = new Intl.DateTimeFormat("en-US", {
    timeZone: tz,
    hour12: false,
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
    weekday: "short",
    hour: "2-digit",
    minute: "2-digit",
  });
  const parts = fmt.formatToParts(now);
  const lookup = (type: Intl.DateTimeFormatPartTypes) =>
    parts.find((p) => p.type === type)?.value ?? "";
  const year = Number(lookup("year"));
  const month = Number(lookup("month"));
  const day = Number(lookup("day"));
  // `Intl` returns 24-hour values with hour12:false, but some engines emit "24"
  // for midnight — normalize defensively.
  const rawHour = Number(lookup("hour"));
  const hour = rawHour === 24 ? 0 : rawHour;
  const minute = Number(lookup("minute"));
  const weekdayStr = lookup("weekday");
  const weekday = WEEKDAY_INDEX[weekdayStr] ?? 0;
  const isoDate =
    `${year.toString().padStart(4, "0")}-` +
    `${month.toString().padStart(2, "0")}-` +
    `${day.toString().padStart(2, "0")}`;
  return { year, month, day, weekday, hour, minute, isoDate };
}

const WEEKDAY_INDEX: Record<string, number> = {
  Sun: 0,
  Mon: 1,
  Tue: 2,
  Wed: 3,
  Thu: 4,
  Fri: 5,
  Sat: 6,
};

/**
 * Resolve the current NYSE session state for the supplied wall-clock instant.
 * Defaults to the New York timezone; tests can pin a different zone to verify
 * the helper isn't accidentally dependent on the host clock.
 */
export function getNyseMarketState(
  now: Date,
  tz = "America/New_York",
): NyseMarketState {
  const parts = getEasternParts(now, tz);
  // Saturday = 6, Sunday = 0.
  if (parts.weekday === 0 || parts.weekday === 6) return "closed-weekend";
  const holidays = holidayOverride ?? DEFAULT_HOLIDAYS;
  if (holidays.has(parts.isoDate)) return "closed-holiday";
  const minutesOfDay = parts.hour * 60 + parts.minute;
  if (minutesOfDay < PRE_OPEN_START_MIN) return "closed";
  if (minutesOfDay < REGULAR_OPEN_MIN) return "pre-open";
  if (minutesOfDay < REGULAR_CLOSE_MIN) return "open";
  if (minutesOfDay < AFTER_HOURS_END_MIN) return "after-hours";
  return "closed";
}

/**
 * Display copy + pill tone for each NYSE state. The shell consumes this so
 * the status bar reads the same labels every test pins.
 */
export interface NyseMarketStateDisplay {
  label: string;
  tone: "positive" | "warn" | "muted" | "negative";
  withDot: boolean;
}

export function describeNyseMarketState(state: NyseMarketState): NyseMarketStateDisplay {
  switch (state) {
    case "open":
      return { label: "open", tone: "positive", withDot: true };
    case "pre-open":
      return { label: "pre-open", tone: "warn", withDot: false };
    case "after-hours":
      return { label: "after-hours", tone: "warn", withDot: false };
    case "closed-weekend":
      return { label: "closed · weekend", tone: "muted", withDot: false };
    case "closed-holiday":
      return { label: "closed · holiday", tone: "muted", withDot: false };
    case "closed":
    default:
      return { label: "closed", tone: "muted", withDot: false };
  }
}
