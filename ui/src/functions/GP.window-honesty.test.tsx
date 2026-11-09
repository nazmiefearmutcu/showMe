/**
 * GP window honesty (GP#2), Fibonacci labelling (GP#6) and the EMA seed (GP#7).
 *
 *   - The request asks the engine for enough bars to cover the window.
 *   - The subtitle states the real span when the returned history is shorter.
 *   - The two ratio levels are labelled as Fibonacci retracements.
 *   - EMA is seeded on the first observation, as the backend TECH function.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, render, screen } from "@testing-library/react";
import type { TransportState } from "@/lib/market-data";
import { GPPane, barsForWindow, ema } from "./GP";

vi.mock("@/chart/Chart", () => ({
  Chart: () => <div data-testid="chart-engine" />,
  default: () => <div data-testid="chart-engine" />,
}));

class FakeResizeObserver {
  observe() {}
  disconnect() {}
  unobserve() {}
}
(globalThis as { ResizeObserver?: unknown }).ResizeObserver = FakeResizeObserver;

const mockQuoteState = {
  transportState: "idle" as TransportState,
  lastTick: null as { price: number; ts: number } | null,
  lastTickAt: null as number | null,
  snapshot: null as { price: number } | null,
  freshnessMs: null as number | null,
  stale: false,
  refreshing: false,
};

vi.mock("@/lib/market-data", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/lib/market-data")>();
  return {
    ...actual,
    useLiveQuote: () => mockQuoteState,
    useLiveQuotes: () => ({ snapshots: {}, ticks: {} }),
  };
});

const mockState = vi.hoisted(() => ({ payload: {} as unknown }));

vi.mock("@/lib/useFunction", () => ({
  useFunction: () => ({
    state: "ok",
    data: mockState.payload,
    error: null,
    refetch: vi.fn(),
  }),
}));

/** Candles `stepSeconds` apart, ending now, with close rising by 0.1 per bar. */
function candles(stepSeconds: number, count: number) {
  const end = Math.floor(Date.now() / 1000);
  return Array.from({ length: count }, (_, i) => {
    const time = end - (count - 1 - i) * stepSeconds;
    const close = 100 + i * 0.1;
    return { time, open: close - 0.2, high: close + 0.5, low: close - 0.5, close, volume: 1000 };
  });
}

beforeEach(() => {
  mockState.payload = {};
  if (typeof localStorage !== "undefined") localStorage.clear();
});

afterEach(() => {
  cleanup();
});

describe("GP request depth", () => {
  it("asks for enough bars to cover a 5-year daily window", () => {
    // 1825 calendar days, 5 trading days in 7, plus a margin.
    expect(barsForWindow(365 * 5, "1d")).toBe(1314);
  });

  it("keeps the 1000-bar floor for short daily windows", () => {
    expect(barsForWindow(30, "1d")).toBe(1000);
  });

  it("caps the request at the engine limit for minute bars over a year", () => {
    expect(barsForWindow(365, "1m")).toBe(20_000);
  });
});

describe("GP EMA seed (GP#7)", () => {
  it("seeds on the first observation, matching the TECH convention", () => {
    // alpha = 2/(3+1) = 0.5: the first value is the seed, not an SMA of 3 values.
    expect(ema([10, 11, 12], 3)).toEqual([10, 10.5, 11.25]);
  });
});

describe("GP window span (GP#2)", () => {
  it("states the real span when a 1Y request returns about a day of minute bars", () => {
    mockState.payload = { data: { ohlcv: candles(60, 1000) }, sources: ["yahoo_chart"] };
    const { container } = render(<GPPane code="GP" symbol="AAPL" />);
    expect(container.textContent).toMatch(/1000 candles · shows 0\.7 days of 1Y/);
  });

  it("does not state a span when the window is covered", () => {
    mockState.payload = { data: { ohlcv: candles(86_400, 400) }, sources: ["yahoo_chart"] };
    const { container } = render(<GPPane code="GP" symbol="AAPL" />);
    expect(container.textContent).not.toMatch(/shows .* days of/);
  });
});

describe("GP key levels (GP#6)", () => {
  it("labels the two ratio levels as Fibonacci retracements, not support and resistance", () => {
    mockState.payload = { data: { ohlcv: candles(86_400, 60) }, sources: ["yfinance"] };
    render(<GPPane code="GP" symbol="AAPL" />);
    expect(screen.getByText("Fib 23.6%")).toBeInTheDocument();
    expect(screen.getByText("Fib 78.6%")).toBeInTheDocument();
    expect(screen.queryByText("Support")).toBeNull();
    expect(screen.queryByText("Resistance")).toBeNull();
  });
});
