/**
 * GP#5: the header, subtitle, payload request and rail must follow the
 * timeframe the chart shows, not a separate persisted GP interval.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, render } from "@testing-library/react";
import type { TransportState } from "@/lib/market-data";
import { GPPane } from "./GP";

// The mocked chart reports a timeframe the user picked, as the real Chart does.
vi.mock("@/chart/Chart", async () => {
  const { useEffect } = await import("react");
  return {
    Chart: (props: { onIntervalChange?: (interval: string) => void }) => {
      useEffect(() => {
        props.onIntervalChange?.("1h");
      }, [props]);
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

const calls = vi.hoisted(() => ({ params: [] as Array<Record<string, unknown>> }));

vi.mock("@/lib/useFunction", () => ({
  useFunction: (opts: { params?: Record<string, unknown> }) => {
    calls.params.push(opts.params ?? {});
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
    return {
      state: "ok",
      data: { data: { ohlcv }, sources: ["yfinance"] },
      error: null,
      refetch: vi.fn(),
    };
  },
}));

beforeEach(() => {
  calls.params = [];
  if (typeof localStorage !== "undefined") localStorage.clear();
});

afterEach(() => {
  cleanup();
});

describe("GP timeframe follows the chart (GP#5)", () => {
  it("requests and labels the chart's timeframe, not the persisted GP default", () => {
    const { container } = render(<GPPane code="GP" symbol="AAPL" />);
    // The payload asks the engine for the chart's 1h bars.
    expect(calls.params.at(-1)?.interval).toBe("1h");
    // The subtitle (and so the header and rail) states the same timeframe.
    expect(container.textContent).toMatch(/1Y · 1h · 60 candles/);
    expect(container.textContent).not.toMatch(/1Y · 1d ·/);
  });
});
