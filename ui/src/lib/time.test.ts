import { describe, expect, it } from "vitest";
import { newsTimestampMs, relativeTimeLabel, sortNewsNewestFirst } from "./time";

const NOW = Date.parse("2026-05-02T16:30:00Z");

describe("relativeTimeLabel", () => {
  it("formats ISO dates as relative Turkish labels", () => {
    expect(relativeTimeLabel("2026-05-02T13:30:00Z", NOW)).toBe("3 saat önce");
    expect(relativeTimeLabel("2026-05-01", NOW)).toBe("1 gün önce");
  });

  it("normalizes existing compact relative labels", () => {
    expect(relativeTimeLabel("23m", NOW)).toBe("23 dakika önce");
    expect(relativeTimeLabel("3h", NOW)).toBe("3 saat önce");
    expect(relativeTimeLabel("2 days ago", NOW)).toBe("2 gün önce");
  });

  it("keeps unparsable labels visible", () => {
    expect(relativeTimeLabel("unknown", NOW)).toBe("unknown");
  });

  it("sorts mixed absolute and relative news timestamps newest first", () => {
    const rows = [
      { title: "date only", ts: "2026-05-01" },
      { title: "three hours", ts: "3h" },
      { title: "minutes", ts: "23 dakika önce" },
      { title: "unknown", ts: "unknown" },
    ];
    expect(sortNewsNewestFirst(rows, (row) => row.ts).map((row) => row.title)).toEqual([
      "minutes",
      "three hours",
      "date only",
      "unknown",
    ]);
  });

  it("converts relative inputs into comparable timestamps", () => {
    expect(newsTimestampMs("3 saat önce", NOW)).toBe(NOW - 3 * 60 * 60 * 1000);
  });
});
