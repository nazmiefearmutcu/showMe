/**
 * fly-alerts — pure rule-evaluation contract.
 *
 * Pins the three rules the FLY pane ships (erratic / crash / stale), the
 * honesty rule that missing fields never fire, the per-callsign+rule
 * cooldown, and the persistence round-trip for `showme.fly.alerts`.
 */
import { beforeEach, describe, expect, it } from "vitest";
import {
  DEFAULT_FLY_ALERT_CONFIG,
  FLY_ALERT_COOLDOWN_MS,
  FLY_ALERT_STORAGE_KEY,
  emptyFlyAlertMemory,
  evaluateFlyAlerts,
  headingDeltaDeg,
  loadFlyAlertConfig,
  normalizeFlyAlertConfig,
  saveFlyAlertConfig,
  type FlyAlertConfig,
  type FlyAlertMemory,
  type FlyContactRow,
} from "./fly-alerts";

const T0 = Date.parse("2026-09-16T12:00:00+00:00");

function row(now: number, overrides: Partial<FlyContactRow> = {}): FlyContactRow {
  return {
    callsign: "THY1",
    icao24: "abc123",
    heading: 90,
    altitude_ft: 35000,
    speed_kt: 450,
    vertical_rate_mps: 0,
    last_contact_utc: new Date(now - 5_000).toISOString(),
    lat: 41,
    lon: 29,
    on_ground: false,
    ...overrides,
  };
}

function config(overrides: Record<string, unknown> = {}): FlyAlertConfig {
  return normalizeFlyAlertConfig(overrides);
}

function memoryWith(key: string, snapshots: FlyContactRow[]): FlyAlertMemory {
  return { rows: new Map([[key, snapshots]]), firedAt: {} };
}

beforeEach(() => {
  window.localStorage.clear();
});

describe("headingDeltaDeg", () => {
  it("returns the shortest signed turn across the 0° seam", () => {
    expect(headingDeltaDeg(10, 90)).toBe(80);
    expect(headingDeltaDeg(350, 10)).toBe(20);
    expect(headingDeltaDeg(10, 350)).toBe(-20);
    expect(headingDeltaDeg(0, 180)).toBe(-180);
  });
});

describe("erratic rule", () => {
  it("fires on a heading change >= the threshold between consecutive polls", () => {
    const prev = memoryWith("THY1", [row(T0, { heading: 10 })]);
    const { alerts, memory } = evaluateFlyAlerts(prev, [row(T0, { heading: 90 })], config(), T0);
    const hit = alerts.find((a) => a.rule === "erratic");
    expect(hit).toBeDefined();
    expect(hit?.label).toBe("FLY rule: erratic — heading step");
    expect(hit?.detail).toContain("80°");
    expect(hit?.detail).toContain("threshold 60°");
    expect(memory.firedAt["THY1|erratic"]).toBe(T0);
  });

  it("does not fire on a small heading change", () => {
    const prev = memoryWith("THY1", [row(T0, { heading: 10 })]);
    const { alerts } = evaluateFlyAlerts(prev, [row(T0, { heading: 40 })], config(), T0);
    expect(alerts).toEqual([]);
  });

  it("fires on a two-step zig-zag of half-threshold swings in opposite directions", () => {
    const prev = memoryWith("THY1", [
      row(T0, { heading: 0 }),
      row(T0, { heading: 35 }),
    ]);
    const { alerts } = evaluateFlyAlerts(prev, [row(T0, { heading: 0 })], config(), T0);
    const hit = alerts.find((a) => a.rule === "erratic");
    expect(hit).toBeDefined();
    expect(hit?.label).toBe("FLY rule: erratic — heading oscillation");
  });

  it("never fires when the previous heading is missing (null ≠ zero)", () => {
    const prev = memoryWith("THY1", [row(T0, { heading: null })]);
    const { alerts } = evaluateFlyAlerts(prev, [row(T0, { heading: 90 })], config(), T0);
    expect(alerts.find((a) => a.rule === "erratic")).toBeUndefined();
  });

  it("does not fire on the first poll (no previous snapshot exists)", () => {
    const { alerts } = evaluateFlyAlerts(emptyFlyAlertMemory(), [row(T0, { heading: 90 })], config(), T0);
    expect(alerts.find((a) => a.rule === "erratic")).toBeUndefined();
  });

  it("is skipped entirely when disabled in the config", () => {
    const prev = memoryWith("THY1", [row(T0, { heading: 10 })]);
    const { alerts } = evaluateFlyAlerts(
      prev,
      [row(T0, { heading: 90 })],
      config({ erratic: { enabled: false } }),
      T0,
    );
    expect(alerts).toEqual([]);
  });
});

describe("crash-risk rule", () => {
  it("fires on a steep descent (vertical rate below −threshold)", () => {
    const { alerts } = evaluateFlyAlerts(
      emptyFlyAlertMemory(),
      [row(T0, { vertical_rate_mps: -20, altitude_ft: 40000 })],
      config(),
      T0,
    );
    const hit = alerts.find((a) => a.rule === "crash");
    expect(hit).toBeDefined();
    expect(hit?.label).toBe("FLY rule: crash risk — steep descent");
    expect(hit?.detail).toContain("-3,937 ft/min");
    expect(hit?.detail).toContain("−2,500");
  });

  it("fires on low altitude while descending", () => {
    const { alerts } = evaluateFlyAlerts(
      emptyFlyAlertMemory(),
      [row(T0, { vertical_rate_mps: -2, altitude_ft: 1200 })],
      config(),
      T0,
    );
    const hit = alerts.find((a) => a.rule === "crash");
    expect(hit?.label).toBe("FLY rule: crash risk — low altitude + descending");
  });

  it("never fires on a low altitude without a descent rate", () => {
    const { alerts } = evaluateFlyAlerts(
      emptyFlyAlertMemory(),
      [row(T0, { vertical_rate_mps: null, altitude_ft: 1200 })],
      config(),
      T0,
    );
    expect(alerts).toEqual([]);
  });

  it("still catches a steep descent when altitude is missing (rate is enough)", () => {
    const { alerts } = evaluateFlyAlerts(
      emptyFlyAlertMemory(),
      [row(T0, { vertical_rate_mps: -20, altitude_ft: null })],
      config(),
      T0,
    );
    expect(alerts.find((a) => a.rule === "crash")).toBeDefined();
  });

  it("excludes aircraft flagged on_ground", () => {
    const { alerts } = evaluateFlyAlerts(
      emptyFlyAlertMemory(),
      [row(T0, { on_ground: true, vertical_rate_mps: -20, altitude_ft: 0 })],
      config(),
      T0,
    );
    expect(alerts).toEqual([]);
  });
});

describe("stale-contact rule", () => {
  it("fires on an old last-contact for an aircraft seen in an earlier poll", () => {
    const first = evaluateFlyAlerts(emptyFlyAlertMemory(), [row(T0)], config(), T0);
    expect(first.alerts).toEqual([]);
    // Same snapshot 20 minutes later — the contact is 20 min old now.
    const now = T0 + 20 * 60_000;
    const second = evaluateFlyAlerts(first.memory, [row(T0)], config(), now);
    const hit = second.alerts.find((a) => a.rule === "stale");
    expect(hit).toBeDefined();
    expect(hit?.label).toBe("FLY rule: stale contact");
    expect(hit?.detail).toContain("data staleness, not a flight-schedule delay");
  });

  it("never fires on the first sighting, however old the contact is", () => {
    const { alerts } = evaluateFlyAlerts(
      emptyFlyAlertMemory(),
      [row(T0, { last_contact_utc: new Date(T0 - 60 * 60_000).toISOString() })],
      config(),
      T0,
    );
    expect(alerts).toEqual([]);
  });

  it("never fires on an unparsable or missing last_contact_utc", () => {
    const first = evaluateFlyAlerts(emptyFlyAlertMemory(), [row(T0, { last_contact_utc: null })], config(), T0);
    const second = evaluateFlyAlerts(
      first.memory,
      [row(T0, { last_contact_utc: "not-a-date" })],
      config(),
      T0 + 60 * 60_000,
    );
    expect(second.alerts).toEqual([]);
  });

  it("is skipped for on-ground aircraft", () => {
    const first = evaluateFlyAlerts(emptyFlyAlertMemory(), [row(T0)], config(), T0);
    const second = evaluateFlyAlerts(
      first.memory,
      [row(T0, { on_ground: true })],
      config(),
      T0 + 20 * 60_000,
    );
    expect(second.alerts).toEqual([]);
  });
});

describe("dedupe + cooldown", () => {
  it("cooldown suppresses a repeat fire inside the window and allows it after", () => {
    const first = evaluateFlyAlerts(
      emptyFlyAlertMemory(),
      [row(T0, { vertical_rate_mps: -20 })],
      config(),
      T0,
    );
    expect(first.alerts).toHaveLength(1);

    const within = evaluateFlyAlerts(first.memory, [row(T0 + 60_000, { vertical_rate_mps: -20 })], config(), T0 + 60_000);
    expect(within.alerts).toEqual([]);

    const after = evaluateFlyAlerts(
      within.memory,
      [row(T0 + FLY_ALERT_COOLDOWN_MS + 1, { vertical_rate_mps: -20 })],
      config(),
      T0 + FLY_ALERT_COOLDOWN_MS + 1,
    );
    expect(after.alerts.find((a) => a.rule === "crash")).toBeDefined();
  });

  it("a duplicated callsign row fires once per poll", () => {
    const dup = row(T0, { vertical_rate_mps: -20 });
    const { alerts } = evaluateFlyAlerts(emptyFlyAlertMemory(), [dup, dup], config(), T0);
    expect(alerts.filter((a) => a.rule === "crash")).toHaveLength(1);
  });

  it("keys memory per callsign so two aircraft fire independently", () => {
    const { alerts } = evaluateFlyAlerts(
      emptyFlyAlertMemory(),
      [
        row(T0, { callsign: "THY1", vertical_rate_mps: -20 }),
        row(T0, { callsign: "PGT2", vertical_rate_mps: -25 }),
      ],
      config(),
      T0,
    );
    expect(alerts).toHaveLength(2);
    expect(new Set(alerts.map((a) => a.callsign))).toEqual(new Set(["THY1", "PGT2"]));
  });

  it("keeps the two most recent snapshots per callsign", () => {
    const first = evaluateFlyAlerts(emptyFlyAlertMemory(), [row(T0, { heading: 0 })], config(), T0);
    const second = evaluateFlyAlerts(first.memory, [row(T0 + 1, { heading: 5 })], config(), T0 + 1);
    const third = evaluateFlyAlerts(second.memory, [row(T0 + 2, { heading: 10 })], config(), T0 + 2);
    const history = third.memory.rows.get("THY1") ?? [];
    expect(history).toHaveLength(2);
    expect(history[0].heading).toBe(5);
    expect(history[1].heading).toBe(10);
  });
});

describe("config normalization + persistence", () => {
  it("exposes honest defaults", () => {
    expect(DEFAULT_FLY_ALERT_CONFIG).toEqual({
      erratic: { enabled: true, headingDeg: 60 },
      crash: { enabled: true, verticalFpm: 2500, lowAltFt: 2000 },
      stale: { enabled: true, minutes: 10 },
    });
  });

  it("merges partial stored configs onto the defaults", () => {
    const normalized = normalizeFlyAlertConfig({ crash: { verticalFpm: 3000 } });
    expect(normalized.crash.verticalFpm).toBe(3000);
    expect(normalized.crash.lowAltFt).toBe(2000);
    expect(normalized.crash.enabled).toBe(true);
    expect(normalized.stale.minutes).toBe(10);
  });

  it("clamps out-of-range thresholds and rejects non-numeric ones", () => {
    const normalized = normalizeFlyAlertConfig({
      erratic: { headingDeg: 999 },
      crash: { verticalFpm: "fast" },
      stale: { minutes: 0 },
    });
    expect(normalized.erratic.headingDeg).toBe(180);
    expect(normalized.crash.verticalFpm).toBe(2500);
    expect(normalized.stale.minutes).toBe(1);
  });

  it("round-trips a saved config through localStorage", () => {
    const custom = normalizeFlyAlertConfig({
      erratic: { enabled: false, headingDeg: 75 },
      crash: { lowAltFt: 1500 },
    });
    saveFlyAlertConfig(custom);
    expect(loadFlyAlertConfig()).toEqual(custom);
  });

  it("falls back to defaults on malformed stored JSON", () => {
    window.localStorage.setItem(FLY_ALERT_STORAGE_KEY, "{not json");
    expect(loadFlyAlertConfig()).toEqual(DEFAULT_FLY_ALERT_CONFIG);
    window.localStorage.setItem(FLY_ALERT_STORAGE_KEY, JSON.stringify({ stale: { enabled: false } }));
    expect(loadFlyAlertConfig().stale.enabled).toBe(false);
    expect(loadFlyAlertConfig().erratic).toEqual(DEFAULT_FLY_ALERT_CONFIG.erratic);
  });
});
