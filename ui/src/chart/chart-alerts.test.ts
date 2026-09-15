/**
 * Indicator alerts — pure crossing/cooldown math + the per-symbol store.
 *
 * The dedupe contract is the important half: a crossing fires once per
 * crossing bar, re-arms when the value recrosses back (a later crossing bar
 * is a new event), and an explicit cooldown can suppress rapid repeats.
 */
import { describe, expect, it } from "vitest";
import {
  ALERT_STORE_KEY,
  evaluateAlertRule,
  findLastCrossing,
  loadAlertStore,
  saveAlertStore,
  type AlertFireState,
  type AlertRule,
} from "./chart-alerts";

class MemoryStorage {
  private map = new Map<string, string>();
  getItem(key: string): string | null {
    return this.map.get(key) ?? null;
  }
  setItem(key: string, value: string): void {
    this.map.set(key, value);
  }
  removeItem(key: string): void {
    this.map.delete(key);
  }
  clear(): void {
    this.map.clear();
  }
}

const storage = () => new MemoryStorage() as unknown as Storage;

const rule = (over?: Partial<AlertRule>): AlertRule => ({
  id: "r1",
  instanceId: "ind-1",
  indicator: "RSI",
  plotKey: "rsi",
  plotLabel: "RSI",
  op: "crossesAbove",
  value: 70,
  ...over,
});

describe("findLastCrossing", () => {
  it("finds the most recent upward crossing", () => {
    const hit = findLastCrossing([null, 60, 69.9, 70.2, 72], "crossesAbove", 70);
    expect(hit).toEqual({ index: 3, value: 70.2 });
  });

  it("finds a downward crossing", () => {
    const hit = findLastCrossing([80, 70.5, 69, 68], "crossesBelow", 70);
    expect(hit).toEqual({ index: 2, value: 69 });
  });

  it("returns the LATEST crossing when the series crosses several times", () => {
    const hit = findLastCrossing([65, 75, 65, 75], "crossesAbove", 70);
    expect(hit?.index).toBe(3);
  });

  it("treats nulls as 'not defined' (no crossing through a gap)", () => {
    expect(findLastCrossing([60, null, 80], "crossesAbove", 70)).toBeNull();
  });

  it("requires an actual side change (touching the value is not a cross)", () => {
    expect(findLastCrossing([70, 70, 70], "crossesAbove", 70)).toBeNull();
    expect(findLastCrossing([70, 70, 70], "crossesBelow", 70)).toBeNull();
  });

  it("rejects malformed input", () => {
    expect(findLastCrossing([], "crossesAbove", 70)).toBeNull();
    expect(findLastCrossing([60, 80], "crossesAbove", Number.NaN)).toBeNull();
  });
});

describe("evaluateAlertRule", () => {
  it("fires once and memoizes the crossing bar index", () => {
    const series = [null, 60, 69.9, 70.2, 72];
    const first = evaluateAlertRule(series, rule(), null);
    expect(first.fired).toBe(true);
    expect(first.crossingBarT).toBe(3);
    /* Re-evaluating the same series/bar does not fire again. */
    const again = evaluateAlertRule(series, rule(), first.state);
    expect(again.fired).toBe(false);
    expect(again.state).toEqual(first.state);
  });

  it("uses bar times when supplied (dedupe key is the crossing bar time)", () => {
    const series = [69, 71];
    const times = [1_000, 2_000];
    const out = evaluateAlertRule(series, rule(), null, { barTimes: times, nowMs: 5_000 });
    expect(out.fired).toBe(true);
    expect(out.state.lastFiredBarT).toBe(2_000);
    expect(evaluateAlertRule(series, rule(), out.state, { barTimes: times }).fired).toBe(false);
  });

  it("re-arms after the value recrosses back and crosses again", () => {
    /* The first crossing fired on bar 2; the series then recrosses down and
       back up — bar 4 is a NEW crossing and must fire again. */
    const base: AlertFireState = { lastFiredBarT: 2, lastFiredAtMs: 0 };
    const series = [null, 69.9, 70.2, 68, 71];
    const out = evaluateAlertRule(series, rule(), base, { nowMs: 10_000 });
    expect(out.fired).toBe(true);
    expect(out.crossingBarT).toBe(4);
  });

  it("honours the cooldown gate for a different crossing bar", () => {
    /* Fired on bar 1; a new crossing arrives on bar 3. */
    const state: AlertFireState = { lastFiredBarT: 1, lastFiredAtMs: 1_000 };
    const series = [70.2, 68, 69, 72];
    const out = evaluateAlertRule(series, rule(), state, {
      cooldownMs: 60_000,
      nowMs: 30_000,
    });
    expect(out.fired).toBe(false);
    /* …and fires once the cooldown has elapsed. */
    const later = evaluateAlertRule(series, rule(), state, {
      cooldownMs: 60_000,
      nowMs: 62_000,
    });
    expect(later.fired).toBe(true);
  });

  it("does not fire without a crossing and never mutates the passed state", () => {
    const state: AlertFireState = { lastFiredBarT: null, lastFiredAtMs: null };
    const out = evaluateAlertRule([50, 55], rule(), state);
    expect(out.fired).toBe(false);
    expect(state).toEqual({ lastFiredBarT: null, lastFiredAtMs: null });
  });

  it("works for crossesBelow too", () => {
    const out = evaluateAlertRule([80, 65], rule({ op: "crossesBelow", value: 70 }), null);
    expect(out.fired).toBe(true);
    expect(out.crossingValue).toBe(65);
  });
});

describe("alert store", () => {
  it("round-trips rules + fired state per symbol", () => {
    const s = storage();
    const r = rule();
    const fired = { r1: { lastFiredBarT: 123, lastFiredAtMs: 456 } };
    saveAlertStore("BTCUSDT", { rules: [r], fired }, s);
    expect(loadAlertStore("BTCUSDT", s)).toEqual({ rules: [r], fired });
    expect(loadAlertStore("ETHUSDT", s)).toEqual({ rules: [], fired: {} });
  });

  it("falls back to empty on corrupt JSON", () => {
    const s = storage();
    s.setItem(ALERT_STORE_KEY, "{definitely not json");
    expect(loadAlertStore("BTCUSDT", s)).toEqual({ rules: [], fired: {} });
  });

  it("drops invalid rules and fired entries silently", () => {
    const s = storage();
    s.setItem(
      ALERT_STORE_KEY,
      JSON.stringify({
        BTCUSDT: {
          rules: [rule(), { id: "bad", op: "crossesAbove" }, 42],
          fired: { r1: { lastFiredBarT: 5, lastFiredAtMs: null }, bad: "nope" },
        },
      }),
    );
    const loaded = loadAlertStore("BTCUSDT", s);
    expect(loaded.rules).toHaveLength(1);
    expect(loaded.rules[0].id).toBe("r1");
    expect(loaded.fired).toEqual({ r1: { lastFiredBarT: 5, lastFiredAtMs: null } });
  });

  it("keeps symbols isolated in the shared store key", () => {
    const s = storage();
    saveAlertStore("BTCUSDT", { rules: [rule()], fired: {} }, s);
    saveAlertStore("ETHUSDT", { rules: [rule({ id: "r2" })], fired: {} }, s);
    expect(loadAlertStore("BTCUSDT", s).rules[0].id).toBe("r1");
    expect(loadAlertStore("ETHUSDT", s).rules[0].id).toBe("r2");
  });
});
