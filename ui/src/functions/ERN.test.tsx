/**
 * ERN pane — awareness contract tests.
 *
 * Pins: provider_unavailable shows AwarenessUnavailable; an empty week says so
 * with relaxers; rows group by day then reporting time (BMO before AMC); the
 * watchlist toggle keeps only in_watchlist rows; Est vs LY is blank when the
 * last-year EPS is zero or missing (never a fabricated percent).
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { ERNPane, estVsLastYear, fmtCap } from "./ERN";

interface MockFnState {
  state: "idle" | "loading" | "ok" | "error" | "refreshing";
  data?: Record<string, unknown> | undefined;
  error?: Error | null;
}

const mockFn: MockFnState = { state: "idle", data: undefined, error: null };
const calls: unknown[] = [];

vi.mock("@/lib/useFunction", () => ({
  useFunction: (args: unknown) => {
    calls.push(args);
    return {
      state: mockFn.state,
      data: mockFn.data,
      error: mockFn.error,
      refetch: vi.fn(),
    };
  },
}));

function setMockFn(next: MockFnState) {
  mockFn.state = next.state;
  mockFn.data = next.data;
  mockFn.error = next.error ?? null;
}

const day = (offset: number) =>
  new Date(Date.now() + offset * 86_400_000).toISOString().slice(0, 10);

const ROWS = [
  {
    date: day(1),
    time_of_day: "amc",
    symbol: "NVDA",
    company: "NVIDIA",
    eps_estimate: 2.4,
    num_estimates: 40,
    fiscal_quarter: "Q3 FY26",
    market_cap: 3.1e12,
    last_year_eps: 1.8,
    in_watchlist: true,
    sources: [{ provider: "awareness" }],
  },
  {
    date: day(1),
    time_of_day: "bmo",
    symbol: "AAPL",
    company: "Apple",
    eps_estimate: 1.5,
    num_estimates: 30,
    fiscal_quarter: "Q4",
    market_cap: 2.9e12,
    last_year_eps: 0,
    in_watchlist: false,
    sources: [],
  },
  {
    date: day(2),
    time_of_day: "unknown",
    symbol: "ZZZ",
    company: "Small Co",
    eps_estimate: null,
    num_estimates: null,
    fiscal_quarter: null,
    market_cap: 4e9,
    last_year_eps: null,
    in_watchlist: false,
    sources: [],
  },
];

beforeEach(() => {
  calls.length = 0;
  setMockFn({ state: "idle" });
  window.localStorage.clear();
});
afterEach(() => cleanup());

describe("ERNPane states", () => {
  it("renders AwarenessUnavailable with the reason and no table", () => {
    setMockFn({
      state: "ok",
      data: {
        data: { status: "provider_unavailable", reason: "awareness down", rows: [] },
      },
    });
    render(<ERNPane code="ERN" />);
    expect(screen.getByRole("alert").textContent).toContain("awareness down");
    expect(screen.queryByRole("table", { name: "Earnings calendar" })).toBeNull();
  });

  it("says the week is empty and offers relaxers, with no sample rows", () => {
    setMockFn({ state: "ok", data: { data: { status: "empty", rows: [], by_day: {} } } });
    render(<ERNPane code="ERN" />);
    expect(screen.getByText("No earnings reports in this week")).toBeTruthy();
    expect(screen.getByRole("button", { name: "Remove market cap floor" })).toBeTruthy();
  });

  it("sends the window and the market cap floor as parameters", () => {
    setMockFn({ state: "loading" });
    render(<ERNPane code="ERN" />);
    const args = calls[0] as { params: Record<string, unknown> };
    expect(args.params.days).toBe(7);
    expect(args.params.min_market_cap).toBe(10e9);
    expect(typeof args.params.from).toBe("string");
  });
});

describe("ERNPane ok payload", () => {
  it("groups by day and reporting time with BMO before AMC", () => {
    setMockFn({ state: "ok", data: { data: { status: "ok", rows: ROWS, by_day: {} } } });
    render(<ERNPane code="ERN" />);
    const text = document.body.textContent ?? "";
    expect(text.indexOf("AAPL")).toBeLessThan(text.indexOf("NVDA"));
    expect(screen.getByText("BMO")).toBeTruthy();
    expect(screen.getByText("AMC")).toBeTruthy();
  });

  it("marks the watchlist star and keeps only watchlist rows when toggled", () => {
    setMockFn({ state: "ok", data: { data: { status: "ok", rows: ROWS, by_day: {} } } });
    render(<ERNPane code="ERN" />);
    expect(screen.getByRole("img", { name: "On watchlist" })).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Watchlist only" }));
    expect(screen.queryByRole("button", { name: "Open AAPL description" })).toBeNull();
    expect(screen.getByRole("button", { name: "Open NVDA description" })).toBeTruthy();
  });

  it("shows Est vs LY only when both inputs exist and last year is non-zero", () => {
    setMockFn({ state: "ok", data: { data: { status: "ok", rows: ROWS, by_day: {} } } });
    render(<ERNPane code="ERN" />);
    expect(screen.getByText("+33.3%")).toBeTruthy();
    expect(estVsLastYear(1.5, 0)).toBeNull();
    expect(estVsLastYear(null, 1.8)).toBeNull();
  });

  it("formats market caps in T, B or M", () => {
    expect(fmtCap(3.1e12)).toBe("$3.10T");
    expect(fmtCap(4e9)).toBe("$4.0B");
    expect(fmtCap(250e6)).toBe("$250M");
    expect(fmtCap(null)).toBe("—");
  });
});
