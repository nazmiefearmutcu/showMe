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

/* ── HP#3 — the 23.6% / 78.6% levels are labelled as Fibonacci ─────── */

describe("HP#3 — retracement levels are labelled with their method", () => {
  it("labels the 23.6% and 78.6% levels as Fibonacci retracements", () => {
    mockState.payload = payloadWith({});
    const { container } = render(<HPPane code="HP" symbol="AAPL" />);
    // The unlabelled "Support"/"Resistance" names implied a signal the
    // computation (a fixed fraction of the range) does not make.
    expect(screen.queryByText("Support")).toBeNull();
    expect(screen.queryByText("Resistance")).toBeNull();
    expect(screen.getByText("Fib 23.6%")).toBeInTheDocument();
    expect(screen.getByText("Fib 78.6%")).toBeInTheDocument();
    const fibLabel = screen.getByText("Fib 23.6%");
    expect(fibLabel.parentElement?.getAttribute("title") ?? "").toMatch(/retracement/i);
    expect(railValue(container, "Fib 78.6%")).not.toBeNull();
  });

  it("computes the levels as retracements down from the range high", () => {
    // Range high 115.50, range low 99.00, span 16.50. A standard retracement
    // of a low-to-high move is measured down from the high:
    //   23.6% -> 115.50 - 0.236 * 16.50 = 111.606 -> 111.61
    //   78.6% -> 115.50 - 0.786 * 16.50 = 102.531 -> 102.53
    // The previous formula (low + fraction * span) gave 102.89 and 111.97,
    // which are the 76.4% and 21.4% retracements, not the labelled levels.
    mockState.payload = payloadWith({});
    const { container } = render(<HPPane code="HP" symbol="AAPL" />);
    expect(railValue(container, "Fib 23.6%")).toBe("111.61");
    expect(railValue(container, "Fib 78.6%")).toBe("102.53");
    const title = screen.getByText("Fib 78.6%").parentElement?.getAttribute("title") ?? "";
    expect(title).toMatch(/from the range high/i);
  });
});

/* ── HP#2 — a bar-cap shortfall is disclosed, not silently shown ───── */

describe("HP#2 — the requested window is disclosed when the bar cap cuts it", () => {
  it("shows a shortfall notice when 1000 intraday bars cover far less than the range", () => {
    // 1000 one-minute bars span ~16.7 hours, against a 3M range.
    mockState.payload = payloadWith({}, makeMinuteRows(1000));
    render(<HPPane code="HP" symbol="AAPL" />);
    const notice = screen.getByTestId("hp-window-truncated");
    expect(notice.textContent).toMatch(/3M/);
    expect(notice.textContent).toMatch(/1000 bars/);
    expect(notice.textContent).toMatch(/hours/);
  });

  it("stays silent when the cap is full but the rows cover the requested window", () => {
    // 1000 daily bars span ~999 days, well past the 3M (~90 day) window, so
    // the 1000-row cap did not cut anything and no notice may appear. Using
    // fewer rows than the cap would make this silence trivially true.
    mockState.payload = payloadWith({}, makeRows(1000));
    render(<HPPane code="HP" symbol="AAPL" />);
    expect(screen.queryByTestId("hp-window-truncated")).toBeNull();
  });
});
