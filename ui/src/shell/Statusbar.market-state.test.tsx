/**
 * QA-2026-05-23: the MARKET pill used the heuristic UTC-hours rule and lit
 * "open" on Saturday 14:00 UTC. This regression test pins the new behaviour
 * by stubbing the time and confirming the data-attribute lands on the
 * expected NyseMarketState discriminator.
 */
import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { Statusbar } from "./Statusbar";
import * as store from "@/lib/store";

vi.mock("@/lib/timezone", () => ({
  useTimezone: () => "UTC",
  formatTime: () => "00:00:00",
  timezoneOffsetLabel: () => "UTC",
  readTimezone: () => "UTC",
}));

vi.mock("@/lib/theme", () => ({
  PRESET_LABELS: { matrix: "Matrix" },
  readState: () => ({ preset: "matrix" }),
  THEME_CHANGE_EVENT: "theme-change",
}));

afterEach(() => {
  cleanup();
  vi.useRealTimers();
  vi.restoreAllMocks();
});

beforeEach(() => {
  vi.spyOn(store, "useAppStore").mockImplementation(((selector: (s: {
    sidecarStatus: string;
    sidecarPort: number | null;
    engineRoot: string | null;
    functionIndex: unknown[];
  }) => unknown) =>
    selector({
      sidecarStatus: "healthy",
      sidecarPort: 58744,
      engineRoot: "/tmp/showme",
      functionIndex: [],
    })) as never);
});

describe("Statusbar — NYSE market state", () => {
  it("Saturday 14:00 UTC (10:00 ET) → closed-weekend", () => {
    vi.useFakeTimers();
    // 2026-05-23 is a Saturday.
    vi.setSystemTime(new Date("2026-05-23T14:00:00Z"));
    render(<Statusbar />);
    const pill = screen.getByTestId("market-state");
    expect(pill.getAttribute("data-market-state")).toBe("closed-weekend");
  });

  it("Friday 09:35 ET → open", () => {
    vi.useFakeTimers();
    // 2026-05-22 = Friday; 13:35 UTC = 09:35 ET (EDT).
    vi.setSystemTime(new Date("2026-05-22T13:35:00Z"));
    render(<Statusbar />);
    const pill = screen.getByTestId("market-state");
    expect(pill.getAttribute("data-market-state")).toBe("open");
  });

  it("Christmas Day 2026 (Friday) → closed-holiday, never 'open'", () => {
    vi.useFakeTimers();
    vi.setSystemTime(new Date("2026-12-25T19:00:00Z"));
    render(<Statusbar />);
    const pill = screen.getByTestId("market-state");
    expect(pill.getAttribute("data-market-state")).toBe("closed-holiday");
  });
});
