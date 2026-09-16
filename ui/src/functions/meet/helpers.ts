/**
 * MEET (Meeting Briefings — World Events) — pure helpers.
 *
 * Kept separate from the pane so the countdown, grouping, spot-alert and
 * persistence rules are unit-testable without rendering:
 *
 *   - `formatCountdown` — adaptive-resolution countdown (>2d "3d 4h",
 *     >2h "1h 23m", >10m "23m 45s", else "45s");
 *   - `secondsUntil` — live seconds from a row's `when_utc`;
 *   - alert config load/save (`showme.meet.alerts`) + `dueAlert` — lead
 *     times fire once per (row, lead) pair (dedupe via the fired key set).
 */

export type MeetImpact = "high" | "medium" | "low" | "holiday";
export type MeetKind = "economic" | "world";
export type MeetCountryState = "live" | "imminent" | "soon" | "scheduled" | "quiet";

export interface MeetRowDetails {
  forecast?: unknown;
  previous?: unknown;
  unit?: string;
  matched_terms?: string[];
  impact_basis?: string;
  url?: string | null;
  provider_country?: string | null;
}

export interface MeetRow {
  id: string;
  kind: MeetKind;
  title: string;
  countries: string[];
  country_names: string[];
  when_utc: string;
  impact: MeetImpact;
  currencies?: string[];
  pairs: string[];
  source: string;
  spot: boolean;
  pinned: boolean;
  /** Terms that matched a followed symbol (only on symbol_rows). */
  symbol_matches?: string[];
  details?: MeetRowDetails;
  seconds_to_event?: number | null;
  age_minutes?: number | null;
  undated?: boolean;
}

export interface MeetNextEvent {
  id?: string;
  title?: string;
  when_utc?: string;
  impact?: string;
  seconds_to_event?: number;
  spot?: boolean;
  kind?: string;
  countries?: string[];
  country_names?: string[];
}

export interface MeetCountryEntry {
  iso: string;
  name: string;
  upcoming_count: number;
  past_count: number;
  next_event: MeetNextEvent | null;
  state: MeetCountryState;
}

export interface MeetAlertEntry {
  id: string;
  kind: MeetKind;
  title: string;
  when_utc: string;
  seconds_to_event: number;
  countries: string[];
  country_names: string[];
  pairs: string[];
  impact: MeetImpact;
  spot: boolean;
  pinned: boolean;
  source: string;
  lead_minutes: number[];
}

export interface MeetWindow {
  days_ahead?: number;
  days_back?: number;
  upcoming_count?: number;
  past_count?: number;
  earliest_upcoming_utc?: string | null;
  newest_past_utc?: string | null;
  next_high_impact?: MeetNextEvent | null;
  as_of?: string;
}

export interface MeetData {
  status?: string;
  reason?: string | null;
  as_of?: string;
  rows?: MeetRow[];
  upcoming?: MeetRow[];
  past?: MeetRow[];
  /** World headlines matched to the followed symbols (own section). */
  symbol_rows?: MeetRow[];
  /** The tickers the pane asked to track (already uppercased). */
  symbols_requested?: string[];
  row_count?: number;
  upcoming_count?: number;
  past_count?: number;
  window?: MeetWindow;
  country_index?: MeetCountryEntry[];
  country_catalog?: { iso: string; name: string }[];
  alerts?: MeetAlertEntry[];
  alert_default_lead_minutes?: number[];
  filtered_empty?: boolean;
  unfiltered_upcoming_count?: number;
  methodology?: string;
}

export interface MeetAlertHistoryItem {
  key: string;
  id: string;
  title: string;
  when_utc: string;
  lead: number;
  fired_at: string;
}

export interface MeetAlertConfig {
  enabled: boolean;
  leadMinutes: number[];
  /** Followed countries whose high-impact events are always spot-tracked. */
  spotCountries: string[];
  /** Followed instruments (crypto/equity symbols) shown in the follow strip. */
  symbols: string[];
  history: MeetAlertHistoryItem[];
}

export const MEET_ALERTS_KEY = "showme.meet.alerts";
export const MEET_ALERT_HISTORY_CAP = 50;

export const DEFAULT_MEET_ALERTS: MeetAlertConfig = {
  enabled: true,
  leadMinutes: [1440, 60, 5],
  spotCountries: [],
  symbols: [],
  history: [],
};

/**
 * Adaptive-resolution countdown. Rounds down so the display never claims
 * more remaining time than reality.
 *
 *   >= 2 days  → "3d 4h"
 *   >= 2 hours → "1h 23m"
 *   >= 10 min  → "23m 45s"
 *   <  10 min  → "45s"
 */
export function formatCountdown(seconds: number | null | undefined): string {
  if (seconds == null || !Number.isFinite(seconds)) return "—";
  const s = Math.floor(seconds);
  if (s <= 0) return "now";
  if (s >= 172800) {
    const d = Math.floor(s / 86400);
    const h = Math.floor((s % 86400) / 3600);
    return `${d}d ${h}h`;
  }
  if (s >= 7200) {
    const h = Math.floor(s / 3600);
    const m = Math.floor((s % 3600) / 60);
    return `${h}h ${m}m`;
  }
  if (s >= 600) {
    const m = Math.floor(s / 60);
    const sec = s % 60;
    return `${m}m ${sec}s`;
  }
  return `${s}s`;
}

/** Live seconds until a row's `when_utc` (falls back to the server value). */
export function secondsUntil(row: MeetRow, nowMs: number): number | null {
  const ts = Date.parse(row.when_utc);
  if (Number.isFinite(ts)) return (ts - nowMs) / 1000;
  return typeof row.seconds_to_event === "number" ? row.seconds_to_event : null;
}

/** Compact "how long ago" stamp for past rows ("3d", "4h", "12m"). */
export function formatAge(seconds: number | null | undefined): string {
  if (seconds == null || !Number.isFinite(seconds) || seconds >= 0) return "—";
  const s = Math.floor(-seconds);
  if (s >= 86400) return `${Math.floor(s / 86400)}d ago`;
  if (s >= 3600) return `${Math.floor(s / 3600)}h ago`;
  if (s >= 60) return `${Math.floor(s / 60)}m ago`;
  return `${s}s ago`;
}

/** A row belongs to the past group once its time has passed (undated = past). */
export function isPastRow(row: MeetRow, nowMs: number): boolean {
  if (row.undated) return true;
  const ts = Date.parse(row.when_utc);
  if (!Number.isFinite(ts)) return (row.seconds_to_event ?? 0) < 0;
  return ts <= nowMs;
}

/** Split the backend-ordered row list into [upcoming, past] live groups. */
export function groupRows(rows: MeetRow[], nowMs: number): { upcoming: MeetRow[]; past: MeetRow[] } {
  const upcoming: MeetRow[] = [];
  const past: MeetRow[] = [];
  for (const row of rows) {
    (isPastRow(row, nowMs) ? past : upcoming).push(row);
  }
  return { upcoming, past };
}

export function impactTone(impact: MeetImpact | string): "warn" | "accent" | "muted" | "neutral" {
  switch (impact) {
    case "high":
      return "warn";
    case "medium":
      return "accent";
    case "holiday":
      return "neutral";
    default:
      return "muted";
  }
}

/** Coerce anything persisted into a valid alert config (never throws). */
export function normalizeMeetAlerts(raw: unknown): MeetAlertConfig {
  const base = { ...DEFAULT_MEET_ALERTS, history: [] as MeetAlertHistoryItem[] };
  if (!raw || typeof raw !== "object") return base;
  const value = raw as Partial<MeetAlertConfig>;
  const leads = Array.isArray(value.leadMinutes)
    ? value.leadMinutes.filter((n) => Number.isFinite(n) && n > 0).map((n) => Math.round(n))
    : base.leadMinutes;
  const countries = Array.isArray(value.spotCountries)
    ? value.spotCountries.filter((c): c is string => typeof c === "string" && !!c.trim())
    : [];
  const symbols = Array.isArray(value.symbols)
    ? value.symbols.filter((s): s is string => typeof s === "string" && !!s.trim())
    : [];
  const history = Array.isArray(value.history)
    ? value.history.filter(
        (h): h is MeetAlertHistoryItem =>
          !!h && typeof h === "object" && typeof (h as MeetAlertHistoryItem).key === "string",
      )
    : [];
  return {
    enabled: value.enabled !== false,
    leadMinutes: leads.length ? leads : base.leadMinutes,
    spotCountries: Array.from(new Set(countries.map((c) => c.toUpperCase()))),
    symbols: Array.from(new Set(symbols.map((s) => s.toUpperCase()))),
    history: history.slice(0, MEET_ALERT_HISTORY_CAP),
  };
}

export function loadMeetAlerts(): MeetAlertConfig {
  if (typeof localStorage === "undefined") return normalizeMeetAlerts(null);
  try {
    const raw = localStorage.getItem(MEET_ALERTS_KEY);
    return normalizeMeetAlerts(raw ? JSON.parse(raw) : null);
  } catch {
    return normalizeMeetAlerts(null);
  }
}

export function saveMeetAlerts(config: MeetAlertConfig): void {
  if (typeof localStorage === "undefined") return;
  try {
    localStorage.setItem(MEET_ALERTS_KEY, JSON.stringify(normalizeMeetAlerts(config)));
  } catch {
    /* storage full — alerts still work in-memory for this session */
  }
}

/**
 * A row is spot-tracked when the provider flagged it (rate decision / war),
 * when it is a pinned high-impact print, or when it touches a followed
 * country (e.g. select Türkiye → the TCMB decision is always spotted).
 */
export function isSpotFor(row: MeetRow, config: Pick<MeetAlertConfig, "spotCountries">): boolean {
  if (row.spot) return true;
  const impact = String(row.impact || "").toLowerCase();
  const followed = row.countries.some((iso) => config.spotCountries.includes(iso.toUpperCase()));
  if (followed && impact === "high") return true;
  return Boolean(row.pinned) && impact === "high";
}

/**
 * The next lead-time crossing for a spot row, or null.
 *
 * Fires once per (row, lead): the smallest lead already crossed wins, so
 * an event 10 minutes out fires the 5-minute lead (not 5 alerts at once).
 * Once that lead fired the row does not back-fill larger leads — each
 * lead fires exactly once, in ascending order of imminence.
 */
export function dueAlert(
  row: MeetRow,
  config: MeetAlertConfig,
  nowMs: number,
  fired: ReadonlySet<string>,
): { key: string; lead: number } | null {
  if (!config.enabled) return null;
  if (!isSpotFor(row, config)) return null;
  const seconds = secondsUntil(row, nowMs);
  if (seconds == null || !Number.isFinite(seconds)) return null;
  if (seconds < -60) return null; // event has passed (1-min grace)
  const crossed = config.leadMinutes
    .filter((lead) => seconds <= lead * 60)
    .sort((a, b) => a - b);
  const lead = crossed[0];
  if (lead == null) return null;
  const key = `${row.id}:${lead}`;
  return fired.has(key) ? null : { key, lead };
}

export function leadLabel(minutes: number): string {
  if (minutes >= 1440 && minutes % 1440 === 0) return `${minutes / 1440}d`;
  if (minutes >= 60 && minutes % 60 === 0) return `${minutes / 60}h`;
  return `${minutes}m`;
}
