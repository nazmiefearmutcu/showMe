/**
 * Contract tests for the NYSE market-state helper.
 *
 * Pins the QA failure mode (Saturday → "open") plus the standard session
 * boundaries and a representative holiday. Inputs are constructed in UTC so
 * the helper's `Intl` extraction logic is what's actually under test rather
 * than the host clock.
 */
import { afterEach, describe, expect, it, vi } from "vitest";
import {
  __setHolidaysForTests,
  describeNyseMarketState,
  getEasternParts,
  getNyseMarketState,
} from "./market-state";

afterEach(() => {
  __setHolidaysForTests(null);
  vi.restoreAllMocks();
});

describe("getNyseMarketState — weekend rule", () => {
  it("Saturday 15:00 ET → closed-weekend (was the bogus 'open' bug)", () => {
    // Saturday 2026-05-23 15:00 ET = 19:00 UTC (EDT, UTC-4 in May).
    const sat = new Date("2026-05-23T19:00:00Z");
    expect(getNyseMarketState(sat)).toBe("closed-weekend");
  });
  it("Sunday 09:35 ET → closed-weekend even during what would be RTH", () => {
    const sun = new Date("2026-05-24T13:35:00Z");
    expect(getNyseMarketState(sun)).toBe("closed-weekend");
  });
});

describe("getNyseMarketState — session boundaries", () => {
  it("Friday 09:35 ET → open", () => {
    // Friday 2026-05-22 09:35 ET = 13:35 UTC (EDT).
    const fri = new Date("2026-05-22T13:35:00Z");
    expect(getNyseMarketState(fri)).toBe("open");
  });
  it("Friday 09:29 ET → pre-open", () => {
    const fri = new Date("2026-05-22T13:29:00Z");
    expect(getNyseMarketState(fri)).toBe("pre-open");
  });
  it("Friday 09:30 ET → open (boundary inclusive on the open side)", () => {
    const fri = new Date("2026-05-22T13:30:00Z");
    expect(getNyseMarketState(fri)).toBe("open");
  });
  it("Friday 16:00 ET → after-hours (boundary exclusive on the open side)", () => {
    const fri = new Date("2026-05-22T20:00:00Z");
    expect(getNyseMarketState(fri)).toBe("after-hours");
  });
  it("Friday 20:00 ET → closed", () => {
    const fri = new Date("2026-05-23T00:00:00Z"); // 20:00 ET Fri = 00:00 Z Sat
    expect(getNyseMarketState(fri)).toBe("closed");
  });
  it("Friday 04:00 ET → pre-open boundary", () => {
    const fri = new Date("2026-05-22T08:00:00Z"); // 04:00 ET Fri = 08:00 Z
    expect(getNyseMarketState(fri)).toBe("pre-open");
  });
  it("Friday 03:59 ET → closed (before pre-open opens)", () => {
    const fri = new Date("2026-05-22T07:59:00Z");
    expect(getNyseMarketState(fri)).toBe("closed");
  });
});

describe("getNyseMarketState — holidays", () => {
  it("Christmas Day 2026 (Friday) → closed-holiday, not 'open'", () => {
    // Christmas 2026 is a Friday; without the holiday list the helper would
    // return "open" at 14:00 ET. The list must beat the weekday rule.
    const xmas = new Date("2026-12-25T19:00:00Z");
    expect(getNyseMarketState(xmas)).toBe("closed-holiday");
  });
  it("MLK Day 2026 (Monday) → closed-holiday", () => {
    const mlk = new Date("2026-01-19T18:00:00Z");
    expect(getNyseMarketState(mlk)).toBe("closed-holiday");
  });
  it("Thanksgiving 2026 (Thursday) → closed-holiday", () => {
    const thx = new Date("2026-11-26T18:00:00Z");
    expect(getNyseMarketState(thx)).toBe("closed-holiday");
  });
  it("custom holiday list overrides the bundled calendar", () => {
    __setHolidaysForTests(["2026-05-22"]);
    const friAsHoliday = new Date("2026-05-22T18:00:00Z");
    expect(getNyseMarketState(friAsHoliday)).toBe("closed-holiday");
  });
});

describe("getEasternParts", () => {
  it("extracts ET wall-clock regardless of input UTC representation", () => {
    const ts = new Date("2026-05-22T13:35:00Z"); // EDT 09:35
    const parts = getEasternParts(ts);
    expect(parts.year).toBe(2026);
    expect(parts.month).toBe(5);
    expect(parts.day).toBe(22);
    expect(parts.hour).toBe(9);
    expect(parts.minute).toBe(35);
    expect(parts.weekday).toBe(5); // Friday
    expect(parts.isoDate).toBe("2026-05-22");
  });
});

describe("describeNyseMarketState", () => {
  it("maps each state to a label + tone", () => {
    expect(describeNyseMarketState("open").label).toBe("open");
    expect(describeNyseMarketState("open").tone).toBe("positive");
    expect(describeNyseMarketState("closed-weekend").label).toContain("weekend");
    expect(describeNyseMarketState("closed-weekend").tone).toBe("muted");
    expect(describeNyseMarketState("closed-holiday").label).toContain("holiday");
    expect(describeNyseMarketState("pre-open").tone).toBe("warn");
    expect(describeNyseMarketState("after-hours").tone).toBe("warn");
  });
  it("maps unknown-calendar to an honest warn label", () => {
    const display = describeNyseMarketState("unknown-calendar");
    expect(display.label).toContain("unknown");
    expect(display.tone).toBe("warn");
    expect(display.withDot).toBe(false);
  });
});

// ---------- UI-ROBUSTNESS F10: uncovered calendar years ----------

describe("getNyseMarketState — uncovered year flag (F10)", () => {
  it("2028 weekday in RTH → unknown-calendar, never a lying 'open'", () => {
    const warnSpy = vi.spyOn(console, "warn").mockImplementation(() => undefined);
    // Good Friday 2028-04-14 (Friday) 09:35 ET — the exact time bomb the old
    // table ended in 2027. Without coverage the helper must NOT say "open".
    const goodFriday = new Date("2028-04-14T13:35:00Z");
    expect(getNyseMarketState(goodFriday)).toBe("unknown-calendar");
    expect(warnSpy).toHaveBeenCalledTimes(1);
  });

  it("2028 weekends stay deterministic (no calendar needed)", () => {
    const saturday = new Date("2028-04-15T19:00:00Z"); // Sat 15:00 ET
    expect(getNyseMarketState(saturday)).toBe("closed-weekend");
  });

  it("warns once per uncovered year, not per call", () => {
    const warnSpy = vi.spyOn(console, "warn").mockImplementation(() => undefined);
    const a = new Date("2028-04-14T13:35:00Z");
    const b = new Date("2028-06-15T13:35:00Z"); // another 2028 weekday
    getNyseMarketState(a);
    getNyseMarketState(b);
    const coverageWarnings = warnSpy.mock.calls.filter((c) =>
      String(c[0]).includes("no coverage for 2028"),
    );
    expect(coverageWarnings).toHaveLength(1);
  });

  it("covered years keep full classification (no flag, no warning)", () => {
    const warnSpy = vi.spyOn(console, "warn").mockImplementation(() => undefined);
    const fri = new Date("2026-05-22T13:35:00Z");
    expect(getNyseMarketState(fri)).toBe("open");
    expect(warnSpy).not.toHaveBeenCalled();
  });

  it("an explicit test override is authoritative even for uncovered years", () => {
    __setHolidaysForTests(["2028-04-14"]);
    const goodFriday = new Date("2028-04-14T13:35:00Z");
    expect(getNyseMarketState(goodFriday)).toBe("closed-holiday");
    const regularFriday = new Date("2028-04-21T13:35:00Z");
    expect(getNyseMarketState(regularFriday)).toBe("open");
  });
});
