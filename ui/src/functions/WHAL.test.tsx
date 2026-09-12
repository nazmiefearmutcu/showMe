/**
 * WHAL — cross-market whale monitor tests.
 *
 * Pins three contracts:
 *  1. Tab/symbol consistency — a bound crypto symbol (BTCUSDT) must never be
 *     queried under the Equity/ETF/FX tab; the tab falls back to its sample
 *     (AAPL/SPY/EURUSD) until a new security is picked.
 *  2. The canonical refresh pattern (UA-HIGH-16) — `tick` stays OUT of
 *     `params` and drives `refetch()` from an effect.
 *  3. P0/X-02 — the symbol-less route (`#/fn/WHAL`) must NOT re-arm a
 *     render-phase rebind every render ("Too many re-renders" → error
 *     boundary); the rebind converges and only fires on a genuine prop change.
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

describe("WHAL pane — 24h volume unit (OPP wave)", () => {
  it("renders the quote-currency unit from the backend on the volume card", () => {
    setMockFn({
      state: "ok",
      data: {
        data: {
          status: "ok",
          provider: "binance_spot",
          market: "CRYPTO",
          rows: [],
          cards: [
            { label: "24h quote volume", value: 2_500_000_000, unit: "USDT" },
          ],
          summary: "no alerts",
        },
      },
    });
    render(<WHALPane code="WHAL" symbol="BTCUSDT" />);
    expect(screen.getByText("24h quote volume")).toBeInTheDocument();
    expect(screen.getByText("2.50B USDT")).toBeInTheDocument();
  });

  it("renders the bare number when the backend cannot prove the quote asset", () => {
    setMockFn({
      state: "ok",
      data: {
        data: {
          status: "ok",
          provider: "binance_spot",
          market: "CRYPTO",
          rows: [],
          cards: [{ label: "24h quote volume", value: 1234 }],
          summary: "no alerts",
        },
      },
    });
    render(<WHALPane code="WHAL" symbol="BTCUSDT" />);
    expect(screen.getByText("1.2k")).toBeInTheDocument();
    expect(screen.queryByText(/1\.2k USDT/)).toBeNull();
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

describe("WHAL pane — symbol-less route convergence (P0 / X-02)", () => {
  // Crash shape from C5 S1/S3 (+ C8 S1): `#/fn/WHAL` mounts with NO symbol
  // prop and a live payload; the old render-phase rebind compared
  // `bound?.symbol ?? ""` against `undefined` (always true) and looped into
  // React's "Too many re-renders". This suite must fail on that code (the
  // per-render setState throws during mount) and pass once the rebind
  // converges on a genuine prop change.
  it("mounts without a symbol prop and paints the crypto sample rows (no rebind loop)", () => {
    render(<WHALPane code="WHAL" />);
    expect(paramsNow().symbol).toBe("BTCUSDT");
    expect(paramsNow().market).toBe("CRYPTO");
    // Live-shape row actually painted — not an error boundary.
    expect(screen.getByText("large trade")).toBeInTheDocument();
    expect(screen.getByText("$2.50M")).toBeInTheDocument();
    expect(screen.queryByText(/pane render failed/i)).toBeNull();
    expect(screen.queryByText(/too many re-renders/i)).toBeNull();
  });

  it("falls back to each market sample when no symbol prop is present", () => {
    render(<WHALPane code="WHAL" />);
    expect(paramsNow().symbol).toBe("BTCUSDT");
    fireEvent.click(screen.getByRole("tab", { name: "Equity" }));
    expect(paramsNow().symbol).toBe("AAPL");
    fireEvent.click(screen.getByRole("tab", { name: "ETF" }));
    expect(paramsNow().symbol).toBe("SPY");
    fireEvent.click(screen.getByRole("tab", { name: "FX" }));
    expect(paramsNow().symbol).toBe("EURUSD");
  });

  it("rebinds when the prop symbol genuinely changes", () => {
    const { rerender } = render(<WHALPane code="WHAL" symbol="BTCUSDT" />);
    expect(paramsNow().symbol).toBe("BTCUSDT");
    rerender(<WHALPane code="WHAL" symbol="ETHUSDT" />);
    expect(paramsNow().symbol).toBe("ETHUSDT");
  });

  it("keeps the bound record when the prop disappears and still resolves samples", () => {
    const { rerender } = render(<WHALPane code="WHAL" symbol="BTCUSDT" />);
    rerender(<WHALPane code="WHAL" />);
    // Prop absent → market sample wins (CRYPTO sample is BTCUSDT here), and
    // crucially the pane does not crash or loop on the transition.
    expect(paramsNow().symbol).toBe("BTCUSDT");
    fireEvent.click(screen.getByRole("tab", { name: "Equity" }));
    expect(paramsNow().symbol).toBe("AAPL");
    fireEvent.click(screen.getByRole("tab", { name: "Crypto" }));
    expect(paramsNow().symbol).toBe("BTCUSDT");
    expect(screen.queryByText(/too many re-renders/i)).toBeNull();
  });

  it("rebinds when the prop returns after being absent", () => {
    const { rerender } = render(<WHALPane code="WHAL" />);
    expect(paramsNow().symbol).toBe("BTCUSDT");
    rerender(<WHALPane code="WHAL" symbol="SOLUSDT" />);
    expect(paramsNow().symbol).toBe("SOLUSDT");
  });
});
