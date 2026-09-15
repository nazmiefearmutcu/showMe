/**
 * S12 GP truth — header/footer must reflect the live tick when the
 * transport is actually live, not stay frozen on the candle-derived
 * historical close.
 *
 * Pre-S12 the price/change in the GP header strip rendered straight
 * from `lastClose` (the close of the most recent historical candle),
 * which meant the chart series ticked via `series.update()` while the
 * displayed number stayed stale until the next history refetch. This
 * test pins the new contract:
 *
 *  1. When `useLiveQuote.transportState === "live"` and a tick is
 *     present, the header price element exposes
 *     `data-testid="gp-display-price"` with `data-live="1"` and the
 *     formatted live price.
 *  2. When transport is idle / no tick has landed, the header falls
 *     back to the historical `lastClose` and reports `data-live="0"`.
 *  3. A live tick re-renders the header without remounting the chart
 *     engine (the engine owns its own canvas + live refresh).
 */
import { readFileSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { act, cleanup, render, screen } from "@testing-library/react";
import type { TransportState } from "@/lib/market-data";
import { GPPane } from "./GP";

const __dirname = dirname(fileURLToPath(import.meta.url));
const gpSourceRaw = readFileSync(resolve(__dirname, "GP.tsx"), "utf-8");

/* ── chart-engine stub ─────────────────────────────────────────────── */
// The engine fetches /api/bars and paints a canvas — stub it out.
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

/* ── hook mocks ────────────────────────────────────────────────────── */

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

function resetMockQuoteState() {
  mockQuoteState.transportState = "idle";
  mockQuoteState.lastTick = null;
  mockQuoteState.lastTickAt = null;
  mockQuoteState.snapshot = null;
  mockQuoteState.freshnessMs = null;
  mockQuoteState.stale = false;
  mockQuoteState.refreshing = false;
}

vi.mock("@/lib/market-data", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/lib/market-data")>();
  return {
    ...actual,
    useLiveQuote: () => mockQuoteState,
    useLiveQuotes: () => ({ snapshots: {}, ticks: {} }),
  };
});

const baseGpData = {
  data: {
    ohlcv: [
      { time: "2026-05-18", open: 100, high: 102, low: 99, close: 101, volume: 100_000 },
      { time: "2026-05-19", open: 101, high: 104, low: 100, close: 103, volume: 120_000 },
      { time: "2026-05-20", open: 103, high: 105, low: 102, close: 104.25, volume: 90_000 },
    ],
  },
  sources: ["yfinance"],
};

vi.mock("@/lib/useFunction", () => ({
  useFunction: () => ({
    state: "ok",
    data: baseGpData,
    error: null,
    refetch: vi.fn(),
  }),
}));

/* ── tests ─────────────────────────────────────────────────────────── */

beforeEach(() => {
  resetMockQuoteState();
});
afterEach(() => {
  cleanup();
});

describe("S12 GP truth — header reflects live tick", () => {
  it("falls back to historical lastClose when transport is idle (data-live=0)", () => {
    mockQuoteState.transportState = "idle";
    const { container } = render(<GPPane code="GP" symbol="AAPL" />);
    const priceEl = container.querySelector('[data-testid="gp-display-price"]');
    expect(priceEl).not.toBeNull();
    expect(priceEl?.getAttribute("data-live")).toBe("0");
    // historical lastClose from baseGpData = 104.25 → "104.25"
    expect(priceEl?.textContent).toMatch(/104\.25/);
  });

  it("renders the live tick when transport is 'live' (data-live=1)", () => {
    mockQuoteState.transportState = "live";
    mockQuoteState.lastTick = { price: 108.6, ts: Date.now() };
    mockQuoteState.lastTickAt = Date.now();
    const { container } = render(<GPPane code="GP" symbol="AAPL" />);
    const priceEl = container.querySelector('[data-testid="gp-display-price"]');
    expect(priceEl?.getAttribute("data-live")).toBe("1");
    expect(priceEl?.textContent).toMatch(/108\.6/);
  });

  it("does NOT promote a stale snapshot price to live tick (data-live=0 when transport != live)", () => {
    // Snapshot present but transport hasn't reached "live" — header
    // must show the historical lastClose, not the snapshot price.
    mockQuoteState.transportState = "connecting";
    mockQuoteState.snapshot = { price: 999.99 };
    const { container } = render(<GPPane code="GP" symbol="AAPL" />);
    const priceEl = container.querySelector('[data-testid="gp-display-price"]');
    expect(priceEl?.getAttribute("data-live")).toBe("0");
    expect(priceEl?.textContent).toMatch(/104\.25/);
  });

  it("source guards a minimum chart height (>= 240px) so the chart remains dominant", () => {
    const minHeightMatches = Array.from(
      gpSourceRaw.matchAll(/minHeight\s*=\s*\{(\d+)\}/g),
    ).map((m) => Number(m[1]));
    expect(minHeightMatches.length).toBeGreaterThan(0);
    expect(minHeightMatches[0]).toBeGreaterThanOrEqual(240);
    expect(gpSourceRaw).toMatch(/defaultHeight=\{\{[^}]*min:\s*(2[4-9]\d|[3-9]\d{2,})/);
  });

  it("keeps the engine mounted when a live tick lands (no remount)", () => {
    const { rerender } = render(<GPPane code="GP" symbol="AAPL" />);
    const engineNode = screen.getByTestId("chart-engine");

    const tickTs = Date.now();
    act(() => {
      mockQuoteState.transportState = "live";
      mockQuoteState.lastTick = { price: 109.5, ts: tickTs };
      mockQuoteState.lastTickAt = tickTs;
    });
    rerender(<GPPane code="GP" symbol="AAPL" />);

    // Same DOM node ⇒ the engine was re-rendered in place, not remounted
    // (the engine owns its own canvas and live refresh).
    expect(screen.getByTestId("chart-engine")).toBe(engineNode);
  });
});
