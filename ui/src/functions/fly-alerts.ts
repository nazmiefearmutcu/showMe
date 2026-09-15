/**
 * FLY alert rules — pure evaluation over consecutive OpenSky polls.
 *
 * FLY has no flight-plan provider: positions are ADS-B state vectors from
 * OpenSky /states/all refreshed by the pane. Every rule below is defined
 * strictly on fields the payload carries, and a rule NEVER fires when a
 * field it requires is missing (null ≠ zero — no fabricated matches):
 *
 *  - ERRATIC  "sapıtma": heading change between consecutive polls ≥ X°,
 *             a two-step zig-zag of ≥ X/2° in opposite directions, or a
 *             vertical-rate sign reversal while the heading still swings.
 *             Needs: heading on the previous AND current poll (the zig-zag
 *             and vertical forms additionally need the poll before last).
 *  - CRASH    "düşme olasılığı": vertical rate ≤ −Y ft/min, or altitude
 *             below Z ft while descending. Needs vertical_rate (converted
 *             from m/s); the low-altitude form additionally needs
 *             altitude. Aircraft flagged on_ground are excluded.
 *  - STALE    "gecikme": last ADS-B contact older than N minutes for an
 *             airborne aircraft already seen in an earlier poll. This is
 *             DATA staleness — FLY has no flight-schedule provider, so the
 *             label never claims a schedule delay. Needs a parsable
 *             last_contact_utc and a prior snapshot of the same callsign.
 *
 * Dedupe/cooldown: at most one fire per callsign+rule per cooldown window
 * (default 5 min) so a single flopping aircraft cannot spam toasts/history.
 */
export type FlyAlertRuleId = "erratic" | "crash" | "stale";

/** Subset of the backend FLY row the rules consume. */
export interface FlyContactRow {
  callsign?: string | null;
  icao24?: string | null;
  heading?: number | null;
  altitude_ft?: number | null;
  speed_kt?: number | null;
  vertical_rate_mps?: number | null;
  last_contact_utc?: string | null;
  lat?: number | null;
  lon?: number | null;
  on_ground?: boolean | null;
}

export interface FlyAlertConfig {
  erratic: { enabled: boolean; headingDeg: number };
  crash: { enabled: boolean; verticalFpm: number; lowAltFt: number };
  stale: { enabled: boolean; minutes: number };
}

export const DEFAULT_FLY_ALERT_CONFIG: FlyAlertConfig = {
  erratic: { enabled: true, headingDeg: 60 },
  crash: { enabled: true, verticalFpm: 2500, lowAltFt: 2000 },
  stale: { enabled: true, minutes: 10 },
};

/** One fire per callsign+rule per window (ms). */
export const FLY_ALERT_COOLDOWN_MS = 5 * 60 * 1000;

export const FLY_ALERT_STORAGE_KEY = "showme.fly.alerts";

export interface FlyAlert {
  /** Unique per fire — safe as a React key / toast id. */
  id: string;
  callsign: string;
  rule: FlyAlertRuleId;
  /** Honest rule label, e.g. "FLY rule: crash risk — steep descent". */
  label: string;
  /** Threshold + measured value, e.g. "vertical rate −3,937 ft/min (…)". */
  detail: string;
  ts: number;
}

/** Cross-poll state: last snapshots per callsign + cooldown stamps. */
export interface FlyAlertMemory {
  /** Up to two most recent snapshots per callsign (oldest first). */
  rows: Map<string, FlyContactRow[]>;
  /** `${key}|${rule}` → last fire timestamp (ms). */
  firedAt: Record<string, number>;
}

export function emptyFlyAlertMemory(): FlyAlertMemory {
  return { rows: new Map(), firedAt: {} };
}

const MPS_TO_FPM = 196.850394;
const MEMORY_MAX_KEYS = 256;
/** Vertical rates below ±0.5 m/s (~98 ft/min) do not count as a direction. */
const VERTICAL_SIGN_DEADBAND_MPS = 0.5;

function finiteNumber(value: unknown): number | null {
  return typeof value === "number" && Number.isFinite(value) ? value : null;
}

/** Shortest signed turn from `from` to `to`, in (−180, 180]. */
export function headingDeltaDeg(from: number, to: number): number {
  return ((to - from + 540) % 360) - 180;
}

function verticalSign(value: number | null): -1 | 0 | 1 {
  if (value == null || Math.abs(value) < VERTICAL_SIGN_DEADBAND_MPS) return 0;
  return value > 0 ? 1 : -1;
}

function rowKey(row: FlyContactRow): string {
  const callsign = (row.callsign ?? "").trim().toUpperCase();
  if (callsign) return callsign;
  return (row.icao24 ?? "").trim().toUpperCase();
}

function displayCallsign(row: FlyContactRow): string {
  return (row.callsign ?? "").trim().toUpperCase() || (row.icao24 ?? "").trim().toUpperCase();
}

function fmtInt(v: number): string {
  return Math.round(v).toLocaleString("en-US");
}

/**
 * Evaluate every enabled rule against the current poll.
 *
 * @param prev   Cross-poll memory from the previous evaluation (cooldown
 *               stamps + last snapshots); use `emptyFlyAlertMemory()` first.
 * @param curr   Rows from the current poll (the backend's FLY row shape).
 * @param config Rule toggles + thresholds (`normalizeFlyAlertConfig`).
 * @param now    Clock in ms (Date.now()) — injected for tests.
 */
export function evaluateFlyAlerts(
  prev: FlyAlertMemory,
  curr: readonly FlyContactRow[],
  config: FlyAlertConfig,
  now: number,
): { alerts: FlyAlert[]; memory: FlyAlertMemory } {
  const alerts: FlyAlert[] = [];
  const firedAt: Record<string, number> = { ...prev.firedAt };

  const fire = (
    key: string,
    row: FlyContactRow,
    rule: FlyAlertRuleId,
    label: string,
    detail: string,
  ): void => {
    const cooldownKey = `${key}|${rule}`;
    const last = finiteNumber(firedAt[cooldownKey]);
    if (last != null && now - last < FLY_ALERT_COOLDOWN_MS) return;
    firedAt[cooldownKey] = now;
    alerts.push({
      id: `${cooldownKey}|${now}`,
      callsign: displayCallsign(row) || key,
      rule,
      label,
      detail,
      ts: now,
    });
  };

  for (const row of curr) {
    const key = rowKey(row);
    if (!key) continue;
    const history = prev.rows.get(key) ?? [];
    const last = history[history.length - 1];
    const beforeLast = history[history.length - 2];

    if (config.erratic.enabled) {
      const hit = evaluateErratic(config, row, last, beforeLast);
      if (hit) fire(key, row, "erratic", hit.label, hit.detail);
    }
    if (config.crash.enabled) {
      const hit = evaluateCrash(config, row);
      if (hit) fire(key, row, "crash", hit.label, hit.detail);
    }
    if (config.stale.enabled) {
      const hit = evaluateStale(config, row, prev.rows.has(key), now);
      if (hit) fire(key, row, "stale", hit.label, hit.detail);
    }
  }

  return { alerts, memory: { rows: nextMemoryRows(prev.rows, curr), firedAt: pruneFiredAt(firedAt, now) } };
}

function evaluateErratic(
  config: FlyAlertConfig,
  row: FlyContactRow,
  last: FlyContactRow | undefined,
  beforeLast: FlyContactRow | undefined,
): { label: string; detail: string } | null {
  const headingNow = finiteNumber(row.heading);
  const headingPrev = last ? finiteNumber(last.heading) : null;
  // Without a previous heading there is no step to measure — never guess.
  if (headingNow == null || headingPrev == null) return null;

  const delta = headingDeltaDeg(headingPrev, headingNow);
  const mag = Math.abs(delta);
  const threshold = config.erratic.headingDeg;
  if (mag >= threshold) {
    return {
      label: "FLY rule: erratic — heading step",
      detail: `heading jumped ${fmtInt(mag)}° between consecutive polls (threshold ${fmtInt(threshold)}°)`,
    };
  }

  const half = threshold / 2;
  const headingBefore = beforeLast ? finiteNumber(beforeLast.heading) : null;
  if (headingBefore != null) {
    const firstSwing = headingDeltaDeg(headingBefore, headingPrev);
    if (
      Math.abs(firstSwing) >= half &&
      mag >= half &&
      Math.sign(firstSwing) !== Math.sign(delta) &&
      firstSwing !== 0 &&
      delta !== 0
    ) {
      return {
        label: "FLY rule: erratic — heading oscillation",
        detail: `two consecutive heading swings ${fmtInt(firstSwing)}° / ${fmtInt(delta)}° in opposite directions (threshold ${fmtInt(half)}° each)`,
      };
    }
  }

  if (beforeLast) {
    const v0 = verticalSign(finiteNumber(beforeLast.vertical_rate_mps));
    const v1 = verticalSign(last ? finiteNumber(last.vertical_rate_mps) : null);
    const v2 = verticalSign(finiteNumber(row.vertical_rate_mps));
    const flipped =
      (v0 !== 0 && v1 !== 0 && v0 !== v1) || (v1 !== 0 && v2 !== 0 && v1 !== v2);
    if (flipped && mag >= half) {
      return {
        label: "FLY rule: erratic — vertical+heading oscillation",
        detail: `vertical rate reversed sign while the heading still swung ${fmtInt(mag)}° (threshold ${fmtInt(half)}°)`,
      };
    }
  }
  return null;
}

function evaluateCrash(
  config: FlyAlertConfig,
  row: FlyContactRow,
): { label: string; detail: string } | null {
  // A parked aircraft cannot be in a crash descent — skip only when the
  // feed explicitly says on_ground (a missing flag does not silence the rule).
  if (row.on_ground === true) return null;
  const verticalMps = finiteNumber(row.vertical_rate_mps);
  const fpm = verticalMps == null ? null : verticalMps * MPS_TO_FPM;
  const altitude = finiteNumber(row.altitude_ft);

  if (fpm != null && fpm <= -config.crash.verticalFpm) {
    return {
      label: "FLY rule: crash risk — steep descent",
      detail: `vertical rate ${fmtInt(fpm)} ft/min (threshold ≤ −${fmtInt(config.crash.verticalFpm)} ft/min)`,
    };
  }
  // "Descending" needs a real negative rate; altitude alone is never enough.
  if (fpm != null && fpm < 0 && altitude != null && altitude < config.crash.lowAltFt) {
    return {
      label: "FLY rule: crash risk — low altitude + descending",
      detail: `${fmtInt(altitude)} ft while descending ${fmtInt(fpm)} ft/min (threshold < ${fmtInt(config.crash.lowAltFt)} ft)`,
    };
  }
  return null;
}

function evaluateStale(
  config: FlyAlertConfig,
  row: FlyContactRow,
  seenBefore: boolean,
  now: number,
): { label: string; detail: string } | null {
  // "Previously looked active": the callsign must have appeared in an
  // earlier poll this session — a first sighting with an old timestamp is
  // data we cannot attribute to a lost contact.
  if (!seenBefore) return null;
  if (row.on_ground === true) return null;
  const iso = row.last_contact_utc;
  if (typeof iso !== "string" || iso.length === 0) return null;
  const contactMs = Date.parse(iso);
  if (!Number.isFinite(contactMs)) return null;
  const ageMs = now - contactMs;
  const thresholdMs = config.stale.minutes * 60_000;
  if (ageMs < thresholdMs) return null;
  return {
    label: "FLY rule: stale contact",
    detail: `last ADS-B contact ${fmtInt(ageMs / 60_000)} min ago (threshold ${fmtInt(config.stale.minutes)} min) — data staleness, not a flight-schedule delay`,
  };
}

function nextMemoryRows(
  prevRows: Map<string, FlyContactRow[]>,
  curr: readonly FlyContactRow[],
): Map<string, FlyContactRow[]> {
  const next = new Map<string, FlyContactRow[]>();
  for (const row of curr) {
    const key = rowKey(row);
    if (!key) continue;
    const prior = next.get(key) ?? prevRows.get(key) ?? [];
    next.set(key, [...prior, row].slice(-2));
  }
  // Keep callsigns that missed this poll (bounded) so a one-poll dropout
  // does not silently disarm the erratic/stale deltas on its return.
  for (const [key, history] of prevRows) {
    if (next.size >= MEMORY_MAX_KEYS) break;
    if (!next.has(key)) next.set(key, history);
  }
  return next;
}

function pruneFiredAt(firedAt: Record<string, number>, now: number): Record<string, number> {
  const out: Record<string, number> = {};
  for (const [key, ts] of Object.entries(firedAt)) {
    const stamp = finiteNumber(ts);
    if (stamp != null && now - stamp <= FLY_ALERT_COOLDOWN_MS * 2) out[key] = stamp;
  }
  return out;
}

/* ── config validation + persistence ───────────────────────────────── */

function coerceBool(value: unknown, fallback: boolean): boolean {
  return typeof value === "boolean" ? value : fallback;
}

function clampNumber(value: unknown, fallback: number, min: number, max: number): number {
  const n = finiteNumber(value);
  if (n == null) return fallback;
  return Math.min(max, Math.max(min, n));
}

/**
 * Merge an untrusted value (stored JSON / form draft) onto the defaults.
 * Missing or non-numeric thresholds keep the default; out-of-range values
 * are clamped to the documented range.
 */
export function normalizeFlyAlertConfig(raw: unknown): FlyAlertConfig {
  const root = (raw && typeof raw === "object" ? raw : {}) as Record<string, unknown>;
  const err = (root.erratic && typeof root.erratic === "object" ? root.erratic : {}) as Record<string, unknown>;
  const crash = (root.crash && typeof root.crash === "object" ? root.crash : {}) as Record<string, unknown>;
  const stale = (root.stale && typeof root.stale === "object" ? root.stale : {}) as Record<string, unknown>;
  const d = DEFAULT_FLY_ALERT_CONFIG;
  return {
    erratic: {
      enabled: coerceBool(err.enabled, d.erratic.enabled),
      headingDeg: clampNumber(err.headingDeg, d.erratic.headingDeg, 5, 180),
    },
    crash: {
      enabled: coerceBool(crash.enabled, d.crash.enabled),
      verticalFpm: clampNumber(crash.verticalFpm, d.crash.verticalFpm, 200, 10000),
      lowAltFt: clampNumber(crash.lowAltFt, d.crash.lowAltFt, 100, 30000),
    },
    stale: {
      enabled: coerceBool(stale.enabled, d.stale.enabled),
      minutes: clampNumber(stale.minutes, d.stale.minutes, 1, 720),
    },
  };
}

export function loadFlyAlertConfig(): FlyAlertConfig {
  if (typeof localStorage === "undefined") return normalizeFlyAlertConfig(undefined);
  try {
    return normalizeFlyAlertConfig(JSON.parse(localStorage.getItem(FLY_ALERT_STORAGE_KEY) ?? "null"));
  } catch {
    return normalizeFlyAlertConfig(undefined);
  }
}

export function saveFlyAlertConfig(config: FlyAlertConfig): void {
  if (typeof localStorage === "undefined") return;
  try {
    localStorage.setItem(FLY_ALERT_STORAGE_KEY, JSON.stringify(normalizeFlyAlertConfig(config)));
  } catch {
    /* quota / private mode — persistence is best-effort, rules still run */
  }
}
