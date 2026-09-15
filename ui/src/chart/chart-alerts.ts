/**
 * showMe chart engine — indicator alerts (milestone 3).
 *
 * Pure rule evaluation + a tiny per-symbol localStorage store. The React
 * shell owns the lifecycle: it recomputes the open indicators, feeds each
 * rule's plot into `evaluateAlertRule`, and turns a `fired: true` result
 * into a toast + an in-pane alert-list entry.
 *
 * Dedupe semantics (honest, no spam):
 *   - A crossing fires ONCE per crossing bar (`lastFiredBarT` memo).
 *   - Re-arming is implicit: when the series recrosses the value in the
 *     opposite direction and later crosses back, the most recent crossing
 *     bar changes and the rule fires again.
 *   - An optional cooldown (ms) is a second gate for noisy marks.
 *
 * All storage access is defensive: a missing/corrupt store reads as empty
 * and writes silently no-op when localStorage is unavailable.
 */
import type { Bar } from "./types";

export type AlertOp = "crossesAbove" | "crossesBelow";

export interface AlertRule {
  id: string;
  /** IndicatorInstance.id this rule belongs to. */
  instanceId: string;
  /** IndicatorDef.id (label only — evaluation uses plotKey). */
  indicator: string;
  /** Plot key inside the computed IndicatorResult. */
  plotKey: string;
  /** Plot label for humans. */
  plotLabel: string;
  op: AlertOp;
  value: number;
}

export interface AlertFireState {
  /** Bar time (or index when no times are supplied) of the fired crossing. */
  lastFiredBarT: number | null;
  /** Wall clock of the fire (cooldown gate). */
  lastFiredAtMs: number | null;
}

export interface AlertEvalResult {
  fired: boolean;
  /** Most recent crossing candidate (present even when suppressed). */
  crossingBarT: number | null;
  crossingValue: number | null;
  state: AlertFireState;
}

export const ALERT_STORE_KEY = "showme.chart.alerts.v1";

/** Cooldown used by the shell: a second gate below the crossing memo. */
export const ALERT_COOLDOWN_MS = 60_000;

export interface AlertStore {
  rules: AlertRule[];
  fired: Record<string, AlertFireState>;
}

let _ruleSeq = 0;
export function alertRuleId(): string {
  _ruleSeq += 1;
  return `al-${Date.now().toString(36)}-${_ruleSeq}`;
}

/**
 * Most recent index where `series` crossed `value` in the rule's direction.
 * Scans from the end; both sides of the crossing must be finite (a null
 * between the values means "not defined", not a crossing).
 */
export function findLastCrossing(
  series: (number | null)[],
  op: AlertOp,
  value: number,
): { index: number; value: number } | null {
  if (!Array.isArray(series) || !Number.isFinite(value)) return null;
  for (let i = series.length - 1; i >= 1; i--) {
    const prev = series[i - 1];
    const cur = series[i];
    if (prev == null || cur == null) continue;
    if (!Number.isFinite(prev) || !Number.isFinite(cur)) continue;
    const crossed =
      op === "crossesAbove" ? prev <= value && cur > value : prev >= value && cur < value;
    if (crossed) return { index: i, value: cur };
  }
  return null;
}

/**
 * Evaluate one rule against one plot series. Returns the fire decision plus
 * the next dedupe state (callers persist it). Only a NEW crossing bar can
 * fire; a repeated evaluation of the same bar is suppressed.
 */
export function evaluateAlertRule(
  series: (number | null)[],
  rule: { op: AlertOp; value: number },
  state: AlertFireState | null,
  opts: {
    barTimes?: (number | null)[] | null;
    nowMs?: number;
    cooldownMs?: number;
  } = {},
): AlertEvalResult {
  const prevState: AlertFireState = {
    lastFiredBarT: state?.lastFiredBarT ?? null,
    lastFiredAtMs: state?.lastFiredAtMs ?? null,
  };
  const crossing = findLastCrossing(series, rule.op, rule.value);
  if (!crossing) {
    return { fired: false, crossingBarT: null, crossingValue: null, state: prevState };
  }
  const times = opts.barTimes ?? null;
  const rawT = times ? times[crossing.index] : crossing.index;
  const barT = typeof rawT === "number" && Number.isFinite(rawT) ? rawT : crossing.index;
  const nowMs = opts.nowMs ?? Date.now();
  const cooldownMs = opts.cooldownMs ?? 0;
  const sameCrossing = prevState.lastFiredBarT === barT;
  const cooling =
    !sameCrossing &&
    cooldownMs > 0 &&
    prevState.lastFiredAtMs != null &&
    nowMs - prevState.lastFiredAtMs < cooldownMs;
  if (sameCrossing || cooling) {
    return { fired: false, crossingBarT: barT, crossingValue: crossing.value, state: prevState };
  }
  const state2: AlertFireState = { lastFiredBarT: barT, lastFiredAtMs: nowMs };
  return { fired: true, crossingBarT: barT, crossingValue: crossing.value, state: state2 };
}

/* ── storage ─────────────────────────────────────────────────────────── */

function safeStorage(storage?: Storage | null): Storage | null {
  if (storage !== undefined) return storage;
  try {
    return typeof window !== "undefined" ? window.localStorage : null;
  } catch {
    return null;
  }
}

function readMap(storage: Storage | null): Record<string, unknown> {
  if (!storage) return {};
  try {
    const raw = storage.getItem(ALERT_STORE_KEY);
    if (!raw) return {};
    const parsed: unknown = JSON.parse(raw);
    if (typeof parsed !== "object" || parsed === null || Array.isArray(parsed)) return {};
    return parsed as Record<string, unknown>;
  } catch {
    return {};
  }
}

function isRule(v: unknown): v is AlertRule {
  if (typeof v !== "object" || v === null) return false;
  const r = v as Record<string, unknown>;
  return (
    typeof r.id === "string" &&
    typeof r.instanceId === "string" &&
    typeof r.indicator === "string" &&
    typeof r.plotKey === "string" &&
    (r.op === "crossesAbove" || r.op === "crossesBelow") &&
    typeof r.value === "number" &&
    Number.isFinite(r.value)
  );
}

function sanitizeRule(v: unknown): AlertRule | null {
  if (!isRule(v)) return null;
  return {
    id: v.id,
    instanceId: v.instanceId,
    indicator: v.indicator,
    plotKey: v.plotKey,
    plotLabel: typeof v.plotLabel === "string" ? v.plotLabel : v.plotKey,
    op: v.op,
    value: v.value,
  };
}

function isFired(v: unknown): v is AlertFireState {
  if (typeof v !== "object" || v === null) return false;
  const f = v as Record<string, unknown>;
  return (
    (f.lastFiredBarT === null || typeof f.lastFiredBarT === "number") &&
    (f.lastFiredAtMs === null || typeof f.lastFiredAtMs === "number")
  );
}

/** Read the alert store for one symbol; corrupt/missing data reads as empty. */
export function loadAlertStore(symbol: string, storage?: Storage | null): AlertStore {
  const store = readMap(safeStorage(storage));
  const entry = store[symbol];
  if (typeof entry !== "object" || entry === null) return { rules: [], fired: {} };
  const raw = entry as Record<string, unknown>;
  const rules = Array.isArray(raw.rules)
    ? (raw.rules.map(sanitizeRule).filter(Boolean) as AlertRule[])
    : [];
  const fired: Record<string, AlertFireState> = {};
  if (typeof raw.fired === "object" && raw.fired !== null && !Array.isArray(raw.fired)) {
    for (const [key, value] of Object.entries(raw.fired as Record<string, unknown>)) {
      if (isFired(value)) fired[key] = value;
    }
  }
  return { rules, fired };
}

/** Persist the alert store for one symbol; storage failures are ignored. */
export function saveAlertStore(
  symbol: string,
  store: AlertStore,
  storage?: Storage | null,
): void {
  const s = safeStorage(storage);
  if (!s) return;
  try {
    const map = readMap(s);
    map[symbol] = store;
    s.setItem(ALERT_STORE_KEY, JSON.stringify(map));
  } catch {
    /* private mode / quota — alerts stay session-local, silently */
  }
}

/** Injectable seam for tests that need bar times without a full Bar[]. */
export type AlertBarTimes = Pick<Bar, "t">[];
