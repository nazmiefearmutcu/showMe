/**
 * CHGS summary cards - a missing indicator is never labelled with a regime.
 *
 * ADX and RSI missing must read as "NO READING", not RANGE-BOUND (ADX
 * fallback 0) or NEUTRAL (RSI fallback 50): those labels assert a value the
 * payload never produced.
 */
import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, render } from "@testing-library/react";
import { CHGSPane } from "./CHGS";

const mockFn: { state: string; data: unknown; error: Error | null } = {
  state: "idle",
  data: undefined,
  error: null,
};

vi.mock("@/lib/useFunction", () => ({
  useFunction: () => ({
    state: mockFn.state,
    data: mockFn.data,
    error: mockFn.error,
    refetch: vi.fn(),
  }),
}));

vi.mock("@/chart/Chart", () => ({
  Chart: () => <div data-testid="chart-engine" />,
}));

function payloadWithoutIndicators(summary: Record<string, unknown>) {
  return {
    data: {
      data: {
        status: "ok",
        bar_count: 3,
        bars: [
          { date: "2026-09-01T13:30:00+00:00", close: 120 },
          { date: "2026-09-02T13:30:00+00:00", close: 121 },
          { date: "2026-09-03T13:30:00+00:00", close: 122 },
        ],
        indicators: {},
        indicator_rows: [],
        summary,
      },
      sources: ["yfinance"],
      metadata: { alias_of: "TECH", data_mode: "live_yfinance", interval: "1d" },
      elapsed_ms: 5,
    },
  };
}

afterEach(() => {
  cleanup();
});

describe("CHGS summary cards - missing indicators", () => {
  it("does not label a missing ADX as RANGE-BOUND", () => {
    mockFn.state = "ok";
    mockFn.data = payloadWithoutIndicators({ last_price: 122, rsi: 55, atr: 2 }).data;
    const { container } = render(<CHGSPane code="CHGS" symbol="AAPL" />);
    expect(container.textContent).not.toContain("RANGE-BOUND");
    expect(container.textContent).not.toContain("TRENDING");
    expect(container.textContent).toContain("NO READING");
  });

  it("does not label a missing RSI as NEUTRAL", () => {
    mockFn.state = "ok";
    mockFn.data = payloadWithoutIndicators({ last_price: 122, adx: 30, atr: 2 }).data;
    const { container } = render(<CHGSPane code="CHGS" symbol="AAPL" />);
    expect(container.textContent).not.toContain("NEUTRAL");
    expect(container.textContent).toContain("TRENDING");
  });
});
