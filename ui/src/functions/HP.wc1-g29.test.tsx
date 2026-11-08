/**
 * WC1-G29 — HP review fixes (HP#2 window truncation, HP#3 fib labels,
 * HP#4 range extremes from highs/lows).
 *
 * The chart engine is stubbed and useFunction / live quote are mocked the
 * same way as HP.f7-charts.test.tsx, so no network is involved.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, render, screen } from "@testing-library/react";
import type { TransportState } from "@/lib/market-data";
import { HPPane } from "./HP";

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

interface MockLiveQuoteState {
  transportState: TransportState;
  lastTick: { price: number; ts: number } | null;
  lastTickAt: number | null;
  snapshot: { price: number } | null;
  freshnessMs: number | null;
  stale: boolean;
  refreshing: boolean;
}

const mockQuoteState: MockLiveQuoteState = {
  transportState: "idle",
  lastTick: null,
  lastTickAt: null,
  snapshot: null,
  freshnessMs: null,
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

const mockState = vi.hoisted(() => ({
  payload: {} as unknown,
}));

vi.mock("@/lib/useFunction", () => ({
  useFunction: () => ({
    state: "ok",
    data: mockState.payload,
    error: null,
    refetch: vi.fn(),
  }),
}));

/* ── fixtures ───────────────────────────────────────────────────────── */

/** Daily rows: close 100..114.5, high = close + 1, low = close - 1. */
function makeRows(count: number) {
  return Array.from({ length: count }, (_, i) => {
    const close = 100 + i * 0.5;
    return {
      date: new Date(Date.UTC(2026, 0, 1 + i)).toISOString(),
      open: close - 0.25,
      high: close + 1,
      low: close - 1,
      close,
      volume: 1_000 + i,
    };
  });
}

/** Minute bars, one per minute, starting at a fixed instant. */
function makeMinuteRows(count: number) {
  const start = Date.UTC(2026, 0, 2, 14, 30);
  return Array.from({ length: count }, (_, i) => {
    const close = 100 + (i % 7) * 0.1;
    return {
      date: new Date(start + i * 60_000).toISOString(),
      open: close,
      high: close + 0.2,
      low: close - 0.2,
      close,
      volume: 10,
    };
  });
}

function payloadWith(data: Record<string, unknown>, ohlcv = makeRows(30)) {
  return { data: { ohlcv, ...data }, sources: ["yahoo_chart"] };
}

/** Value text of a key-level rail row, found by its label. */
function railValue(container: HTMLElement, label: string): string | null {
  const labelEl = Array.from(container.querySelectorAll("span")).find(
    (s) => s.textContent === label,
  );
  return labelEl?.nextElementSibling?.textContent ?? null;
}

beforeEach(() => {
  mockQuoteState.transportState = "idle";
  mockState.payload = payloadWith({});
});

afterEach(() => {
  cleanup();
});

/* ── HP#4 — range extremes come from highs and lows ─────────────────── */

describe("HP#4 — range high/low use the bar highs and lows", () => {
  it("reports the highest high and the lowest low, not the closes", () => {
    // Closes span 100..114.5 but highs reach 115.5 and lows drop to 99.
    mockState.payload = payloadWith({});
    const { container } = render(<HPPane code="HP" symbol="AAPL" />);
    expect(screen.getByText("Range high")).toBeInTheDocument();
    expect(railValue(container, "Range high")).toBe("115.50");
    expect(railValue(container, "Range low")).toBe("99.00");
  });
});
