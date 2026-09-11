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
  describeSessionState,
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

// ---------- L3 (campaign 2026-09-11): multi-venue session awareness ----------

describe("describeSessionState — crypto", () => {
  it("is always open, any day/time, labeled 24/7", () => {
    const saturday = new Date("2026-05-23T15:00:00Z");
    expect(describeSessionState("crypto", saturday)).toEqual({
      label: "24/7",
      state: "24h",
      venue: "Crypto",
    });
    const mondayNight = new Date("2026-05-25T03:00:00Z");
    expect(describeSessionState("crypto", mondayNight).state).toBe("24h");
  });
});

describe("describeSessionState — equity reuses the NYSE calendar", () => {
  it("Friday RTH → open / NYSE", () => {
    const fri = new Date("2026-05-22T13:35:00Z"); // 09:35 ET
    expect(describeSessionState("equity", fri)).toEqual({
      label: "open",
      state: "open",
      venue: "NYSE",
    });
  });
  it("weekend → closed with the honest weekend label", () => {
    const sat = new Date("2026-05-23T19:00:00Z");
    const out = describeSessionState("equity", sat);
    expect(out.state).toBe("closed");
    expect(out.label).toContain("weekend");
  });
  it("pre-open and after-hours map to pre/post buckets", () => {
    expect(describeSessionState("equity", new Date("2026-05-22T13:29:00Z")).state).toBe("pre");
    expect(describeSessionState("equity", new Date("2026-05-22T20:00:00Z")).state).toBe("post");
  });
  it("holiday stays closed and says so", () => {
    const xmas = new Date("2026-12-25T19:00:00Z");
    const out = describeSessionState("equity", xmas);
    expect(out.state).toBe("closed");
    expect(out.label).toContain("holiday");
  });
});

describe("describeSessionState — FX 24/5 week boundaries (UTC)", () => {
  it("closed on Saturday", () => {
    expect(describeSessionState("fx", new Date("2026-05-23T12:00:00Z"))).toMatchObject({
      state: "closed",
      venue: "FX",
    });
  });
  it("closed Sunday 20:59 UTC, open Sunday 21:00 UTC exactly", () => {
    expect(describeSessionState("fx", new Date("2026-05-24T20:59:00Z")).state).toBe("closed");
    expect(describeSessionState("fx", new Date("2026-05-24T21:00:00Z")).state).toBe("open");
  });
  it("open Friday 20:59 UTC, closed Friday 21:00 UTC exactly", () => {
    expect(describeSessionState("fx", new Date("2026-05-22T20:59:00Z")).state).toBe("open");
    expect(describeSessionState("fx", new Date("2026-05-22T21:00:00Z")).state).toBe("closed");
  });
  it("winter (EST): the week opens at 22:00 UTC — Sunday 21:30 UTC stays closed", () => {
    expect(describeSessionState("fx", new Date("2026-01-11T21:30:00Z")).state).toBe("closed");
    expect(describeSessionState("fx", new Date("2026-01-11T22:30:00Z")).state).toBe("open");
  });
  it("winter (EST): the week closes at 22:00 UTC — Friday 21:30 UTC stays open", () => {
    expect(describeSessionState("fx", new Date("2026-01-09T21:30:00Z")).state).toBe("open");
    expect(describeSessionState("fx", new Date("2026-01-09T22:30:00Z")).state).toBe("closed");
  });
  it("open midweek", () => {
    expect(describeSessionState("fx", new Date("2026-05-20T03:00:00Z")).state).toBe("open");
  });
  it("label says 24/5 in both states — never a bare 'open'", () => {
    expect(describeSessionState("fx", new Date("2026-05-20T03:00:00Z")).label).toBe("open · 24/5");
    expect(describeSessionState("fx", new Date("2026-05-23T12:00:00Z")).label).toBe("closed · 24/5");
  });
});

describe("describeSessionState — futures honest 24/5 approximation", () => {
  it("closed Saturday and Sunday before 22:00 UTC", () => {
    expect(describeSessionState("futures", new Date("2026-05-23T12:00:00Z")).state).toBe("closed");
    expect(describeSessionState("futures", new Date("2026-05-24T21:59:00Z")).state).toBe("closed");
  });
  it("open Sunday at 22:00 UTC exactly", () => {
    expect(describeSessionState("futures", new Date("2026-05-24T22:00:00Z")).state).toBe("open");
  });
  it("closed Friday at 21:00 UTC exactly", () => {
    expect(describeSessionState("futures", new Date("2026-05-22T21:00:00Z")).state).toBe("closed");
  });
  it("venue discloses the approximation instead of claiming CME certainty", () => {
    const out = describeSessionState("futures", new Date("2026-05-20T12:00:00Z"));
    expect(out.venue).toContain("approx");
    expect(out.label).toBe("open · 24/5");
  });
});
