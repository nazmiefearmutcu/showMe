/**
 * Pin the conversion behavior for the home Newsflow + Statusbar clock so
 * future refactors can't silently regress:
 *   • naive ISO strings (no Z, no offset) must be treated as UTC
 *   • the user's picked tz is the *display* tz; the underlying instant is preserved
 *   • mode=auto reads from `Intl.DateTimeFormat().resolvedOptions().timeZone`
 *   • flipping back to manual restores the user's previous city
 */
import { afterEach, beforeEach, describe, expect, it } from "vitest";
import {
  formatNewsTimestamp,
  formatTime,
  getSystemTimezone,
  readManualTimezone,
  readTimezone,
  readTimezoneMode,
  setTimezoneMode,
  writeTimezone,
} from "./timezone";

beforeEach(() => {
  localStorage.clear();
});

afterEach(() => {
  localStorage.clear();
});

describe("timezone module", () => {
  it("treats naive ISO strings as UTC, not local wall time", () => {
    const naive = "2026-05-15T14:00:00";
    const explicit = "2026-05-15T14:00:00Z";
    expect(formatTime(naive, { tz: "Europe/Istanbul", seconds: true })).toBe(
      formatTime(explicit, { tz: "Europe/Istanbul", seconds: true }),
    );
  });

  it("converts a UTC instant to the picked tz", () => {
    const ts = "2026-05-15T14:00:00Z";
    expect(formatTime(ts, { tz: "Europe/Istanbul" })).toBe("17:00");
    expect(formatTime(ts, { tz: "America/New_York" })).toBe("10:00");
    expect(formatTime(ts, { tz: "UTC" })).toBe("14:00");
  });

  it("formatNewsTimestamp shows time-of-day for today, MMM DD for older", () => {
    const today = new Date();
    today.setUTCHours(13, 0, 0, 0);
    const old = new Date(Date.now() - 7 * 24 * 60 * 60 * 1000);
    expect(formatNewsTimestamp(today.toISOString(), "Europe/Istanbul")).toMatch(
      /^\d{2}:\d{2}$/,
    );
    expect(formatNewsTimestamp(old.toISOString(), "Europe/Istanbul")).toMatch(
      /^[A-Za-z]{3} \d{2}$/,
    );
  });

  it("auto mode resolves to the system tz", () => {
    setTimezoneMode("auto");
    expect(readTimezoneMode()).toBe("auto");
    expect(readTimezone()).toBe(getSystemTimezone());
  });

  it("manual pick is preserved when flipping auto on/off", () => {
    writeTimezone("America/New_York");
    expect(readTimezone()).toBe("America/New_York");
    setTimezoneMode("auto");
    expect(readTimezone()).toBe(getSystemTimezone());
    setTimezoneMode("manual");
    expect(readTimezone()).toBe("America/New_York");
    expect(readManualTimezone()).toBe("America/New_York");
  });

  it("invalid tz falls back to the safe default", () => {
    writeTimezone("Not/A_Real/Zone");
    expect(readTimezone()).toBe("Europe/Istanbul");
  });
});
