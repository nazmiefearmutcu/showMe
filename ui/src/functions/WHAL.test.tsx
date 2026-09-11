/**
 * WHAL — cross-market whale monitor tests.
 *
 * Pins two contracts:
 *  1. Tab/symbol consistency — a bound crypto symbol (BTCUSDT) must never be
 *     queried under the Equity/ETF/FX tab; the tab falls back to its sample
 *     (AAPL/SPY/EURUSD) until a new security is picked.
 *  2. The canonical refresh pattern (UA-HIGH-16) — `tick` stays OUT of
 *     `params` and drives `refetch()` from an effect.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { WHALPane } from "./WHAL";

interface MockFnState {
  state: "idle" | "loading" | "ok" | "error" | "refreshing";
  data?: { data?: unknown; sources?: string[] } | undefined;
  error?: Error | null;
  refetch: ReturnType<typeof vi.fn>;
}

const mockFn: MockFnState = {
  state: "idle",
  data: undefined,
  error: null,
  refetch: vi.fn(),
};

function setMockFn(next: Partial<MockFnState>) {
  mockFn.state = next.state ?? "idle";
  mockFn.data = next.data;
  mockFn.error = next.error ?? null;
  if (next.refetch) mockFn.refetch = next.refetch;
}

const mockTick = { current: 0 };
let lastFnArgs: Record<string, unknown> | undefined;

vi.mock("@/lib/useFunction", () => ({
  useFunction: (args: Record<string, unknown>) => {
    lastFnArgs = args;
    return {
      state: mockFn.state,
      data: mockFn.data,
      error: mockFn.error,
      refetch: mockFn.refetch,
    };
  },
}));

vi.mock("@/lib/useVisibilityTick", () => ({
  useVisibilityTick: () => mockTick.current,
}));

function okPayload() {
  return {
    data: {
      data: {
        status: "ok",
        provider: "binance_agg_trades",
        market: "CRYPTO",
        rows: [
          {
            timestamp: "2026-09-11T00:00:00Z",
            alert_type: "large_trade",
            symbol: "BTCUSDT",
            usd_value: 2_500_000,
            threshold_crossed: true,
            direction: "buy_initiated",
            severity: "high",
          },
        ],
        cards: [{ label: "Threshold hits", value: 1 }],
        summary: "1 public alert",
      },
      sources: ["binance"],
    },
  };
}

function paramsNow(): Record<string, unknown> {
  return (lastFnArgs?.params ?? {}) as Record<string, unknown>;
}

beforeEach(() => {
  localStorage.clear();
  mockTick.current = 0;
  lastFnArgs = undefined;
  setMockFn({ state: "ok", ...okPayload(), refetch: vi.fn() });
});
afterEach(() => {
  cleanup();
});

describe("WHAL pane — market tab / symbol consistency", () => {
  it("keeps the bound crypto symbol on the Crypto tab", () => {
    render(<WHALPane code="WHAL" symbol="BTCUSDT" />);
    expect(paramsNow().symbol).toBe("BTCUSDT");
    expect(paramsNow().market).toBe("CRYPTO");
  });

  it("falls back to the market sample when switching to Equity with a crypto symbol bound", () => {
    render(<WHALPane code="WHAL" symbol="BTCUSDT" />);
    fireEvent.click(screen.getByRole("tab", { name: "Equity" }));
    expect(paramsNow().market).toBe("EQUITY");
    expect(paramsNow().symbol).toBe("AAPL");
    expect(paramsNow().symbol).not.toBe("BTCUSDT");
  });

  it("falls back to the ETF/FX samples too", () => {
    render(<WHALPane code="WHAL" symbol="BTCUSDT" />);
    fireEvent.click(screen.getByRole("tab", { name: "ETF" }));
    expect(paramsNow().symbol).toBe("SPY");
    fireEvent.click(screen.getByRole("tab", { name: "FX" }));
    expect(paramsNow().symbol).toBe("EURUSD");
  });

  it("restores the bound symbol when returning to its own market tab", () => {
    render(<WHALPane code="WHAL" symbol="BTCUSDT" />);
    fireEvent.click(screen.getByRole("tab", { name: "Equity" }));
    expect(paramsNow().symbol).toBe("AAPL");
    fireEvent.click(screen.getByRole("tab", { name: "Crypto" }));
    expect(paramsNow().symbol).toBe("BTCUSDT");
  });
});

describe("WHAL pane — visibility poll (live adoption)", () => {
  it("refetches on a visibility tick but not on mount", () => {
    const refetch = vi.fn();
    setMockFn({ state: "ok", ...okPayload(), refetch });
    const { rerender } = render(<WHALPane code="WHAL" symbol="BTCUSDT" />);
    expect(refetch).not.toHaveBeenCalled();

    mockTick.current = 1;
    rerender(<WHALPane code="WHAL" symbol="BTCUSDT" />);
    expect(refetch).toHaveBeenCalledTimes(1);
  });

  it("keeps the request params stable across ticks (no tick key)", () => {
    const { rerender } = render(<WHALPane code="WHAL" symbol="BTCUSDT" />);
    const before = JSON.stringify(lastFnArgs?.params ?? null);
    expect(before).not.toContain("tick");

    mockTick.current = 5;
    rerender(<WHALPane code="WHAL" symbol="BTCUSDT" />);
    expect(JSON.stringify(lastFnArgs?.params ?? null)).toBe(before);
  });
});
