/**
 * GP#5 follow-up: a chart timeframe must reach the price engine as the engine's
 * own id, or not at all. "1M" (month) must not become "1m" (minute), and a
 * timeframe the engine does not serve (12h, 6h, 8h, seconds) must not be
 * silently replaced by daily bars.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, render } from "@testing-library/react";
import { GPPane } from "./GP";

// The mocked chart reports the timeframe the test selects, as the real Chart does.
const chart = vi.hoisted(() => ({ interval: "1h" }));
vi.mock("@/chart/Chart", async () => {
  const { useEffect } = await import("react");
  return {
    Chart: (props: { onIntervalChange?: (interval: string) => void }) => {
      useEffect(() => {
        props.onIntervalChange?.(chart.interval);
        // eslint-disable-next-line react-hooks/exhaustive-deps
      }, []);
      return <div data-testid="chart-engine" />;
    },
    default: () => <div data-testid="chart-engine" />,
  };
});

class FakeResizeObserver {
  observe() {}
  disconnect() {}
  unobserve() {}
}
(globalThis as { ResizeObserver?: unknown }).ResizeObserver = FakeResizeObserver;

vi.mock("@/lib/market-data", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/lib/market-data")>();
  return {
    ...actual,
    useLiveQuote: () => ({
      transportState: "idle",
      lastTick: null,
      lastTickAt: null,
      snapshot: null,
      freshnessMs: null,
      stale: false,
      refreshing: false,
    }),
    useLiveQuotes: () => ({ snapshots: {}, ticks: {} }),
  };
});

interface Call {
  enabled?: boolean;
  params?: Record<string, unknown>;
}
const calls = vi.hoisted(() => ({ opts: [] as Call[], reportedInterval: null as string | null }));

vi.mock("@/lib/useFunction", () => ({
  useFunction: (opts: Call) => {
    calls.opts.push(opts);
    if (opts.enabled === false) {
      return { state: "idle", data: undefined, error: null, refetch: vi.fn() };
    }
    const end = Math.floor(Date.now() / 1000);
    const ohlcv = Array.from({ length: 60 }, (_, i) => {
      const close = 100 + i * 0.1;
      return {
        time: end - (59 - i) * 86_400,
        open: close - 0.2,
        high: close + 0.5,
        low: close - 0.5,
        close,
        volume: 1000,
      };
    });
    const metadata =
      calls.reportedInterval == null ? {} : { interval: calls.reportedInterval };
    return {
      state: "ok",
      data: { data: { ohlcv }, sources: ["yfinance"], metadata },
      error: null,
      refetch: vi.fn(),
    };
  },
}));

beforeEach(() => {
  calls.opts = [];
  calls.reportedInterval = null;
  if (typeof localStorage !== "undefined") localStorage.clear();
});

afterEach(() => {
  cleanup();
});

describe("GP requests the chart timeframe's own engine id (GP#5)", () => {
  it("sends 1M as the engine's monthly id 1mo, never the minute id 1m", () => {
    chart.interval = "1M";
    const { container } = render(<GPPane code="GP" symbol="AAPL" />);
    const requested = calls.opts.map((o) => o.params?.interval);
    expect(requested.at(-1)).toBe("1mo");
    expect(requested).not.toContain("1m");
    expect(container.textContent).toMatch(/1Y · 1M · 60 candles/);
  });

  it("sends 1D and 1W as the engine's daily and weekly ids", () => {
    chart.interval = "1D";
    render(<GPPane code="GP" symbol="AAPL" />);
    expect(calls.opts.at(-1)?.params?.interval).toBe("1d");
  });

  it.each(["1s", "5s", "30s", "2h", "3m", "6h", "8h", "12h"])(
    "withholds the rail for %s instead of requesting daily bars",
    (id) => {
      chart.interval = id;
      const { container, queryByTestId } = render(<GPPane code="GP" symbol="AAPL" />);
      // The chart reports its timeframe after the first render (GP's own default
      // is 1D until then), so the settled request is the one that matters.
      expect(calls.opts.at(-1)?.enabled).toBe(false);
      expect(calls.opts.at(-1)?.params?.interval).not.toBe("1d");
      // The chart itself stays visible, and the gap is stated honestly.
      expect(queryByTestId("chart-engine")).not.toBeNull();
      expect(container.textContent).toMatch(/no .* history/i);
    },
  );

  it("withholds the rail when the engine reports a different interval than requested", () => {
    chart.interval = "4h";
    calls.reportedInterval = "1d";
    const { container } = render(<GPPane code="GP" symbol="AAPL" />);
    expect(calls.opts.at(-1)?.params?.interval).toBe("4h");
    expect(container.textContent).toMatch(/reported 1d/);
    expect(container.textContent).not.toMatch(/60 candles/);
  });
});
