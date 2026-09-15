/**
 * F7 — HP chart fixes (audit A1 / HP subsection).
 *
 * Pins the fixes shipped in the charts fix lane that still hold after the
 * pane migrated to the in-house chart engine:
 *   1. The name/exchange pills render from the alias payload
 *      (`long_name` / `short_name` / `exchange`) instead of the never-emitted
 *      camelCase keys.
 *   2. "52w high/low" only claims 52 weeks when the provider meta supplied
 *      real 52-week levels; otherwise the rail labels show honest
 *      "Range high/low".
 *   3. "ATR(14)" is TRUE ATR — Wilder-smoothed max(H−L, |H−prevC|,
 *      |L−prevC|) — not the old mean |Δclose| (with flat closes and big
 *      ranges the old code showed 0.00; the fix shows the true range).
 *   4. The fake `cache · live` footer pill (field never existed) is replaced
 *      by an honest deep/windowed history chip.
 *
 * The retired chart-series indicator toggles (BB/RSI/MACD overlays) are now
 * owned by the engine; the pane mounts `@/chart/Chart` and no longer exposes
 * the removed chip menu.
 */
import { readFileSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, render, screen } from "@testing-library/react";
import type { TransportState } from "@/lib/market-data";
import { HPPane } from "./HP";

const __dirname = dirname(fileURLToPath(import.meta.url));
const hpSourceRaw = readFileSync(resolve(__dirname, "HP.tsx"), "utf-8");

/* ── chart-engine stub ──────────────────────────────────────────────── */
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

/* ── hook mocks ─────────────────────────────────────────────────────── */

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

/** Flat closes with wide high/low: |Δclose| ATR = 0, true ATR = 20. */
function flatRangeRows(count: number) {
  return Array.from({ length: count }, (_, i) => ({
    date: new Date(Date.UTC(2026, 0, 1 + i)).toISOString(),
    open: 100,
    high: 110,
    low: 90,
    close: 100,
    volume: 10,
  }));
}

function payloadWith(data: Record<string, unknown>) {
  return { data: { ohlcv: makeRows(30), ...data }, sources: ["yahoo_chart"] };
}

beforeEach(() => {
  mockQuoteState.transportState = "idle";
  mockState.payload = payloadWith({});
});

afterEach(() => {
  cleanup();
});

/* ── tests ──────────────────────────────────────────────────────────── */

describe("F7 HP — wire-truth payload reads", () => {
  it("renders the long name + exchange pills from the alias payload", () => {
    mockState.payload = payloadWith({
      long_name: "Apple Inc.",
      short_name: "Apple",
      exchange: "NMS",
    });
    const { container } = render(<HPPane code="HP" symbol="AAPL" />);
    expect(container.textContent).toContain("Apple Inc.");
    expect(container.textContent).toContain("NMS");
  });

  it("claims '52w high/low' only when provider meta supplied real 52w levels", () => {
    mockState.payload = payloadWith({
      fifty_two_week_high: 260.1,
      fifty_two_week_low: 164.08,
    });
    const first = render(<HPPane code="HP" symbol="AAPL" />);
    expect(first.container.textContent).toContain("52w high");
    expect(first.container.textContent).toContain("52w low");
    expect(first.container.textContent).toContain("260.10");
    expect(first.container.textContent).not.toContain("Range high");
    cleanup();

    mockState.payload = payloadWith({});
    const second = render(<HPPane code="HP" symbol="AAPL" />);
    expect(second.container.textContent).not.toContain("52w high");
    expect(second.container.textContent).toContain("Range high");
    expect(second.container.textContent).toContain("Range low");
  });

  it("reports deep vs windowed history instead of the fake cache pill", () => {
    mockState.payload = payloadWith({ deep_history: true });
    const first = render(<HPPane code="HP" symbol="AAPL" />);
    expect(first.container.textContent).toContain("deep");
    expect(first.container.textContent).not.toContain("cache");
    cleanup();

    mockState.payload = payloadWith({});
    const second = render(<HPPane code="HP" symbol="AAPL" />);
    expect(second.container.textContent).toContain("windowed");
  });

  it("HP source no longer reads the never-emitted camelCase identity keys", () => {
    expect(hpSourceRaw).not.toMatch(/longName\?:/);
    expect(hpSourceRaw).not.toMatch(/\)\?\.longName/);
  });
});

describe("F7 HP — true ATR(14)", () => {
  it("uses high/low true range, not mean |Δclose|", () => {
    mockState.payload = { data: { ohlcv: flatRangeRows(16) }, sources: ["yahoo_chart"] };
    render(<HPPane code="HP" symbol="AAPL" />);
    const label = screen.getByText("ATR(14)");
    // TR = max(110−90, |110−100|, |90−100|) = 20 on every bar → ATR = 20.00.
    // The pre-fix mean |Δclose| implementation rendered 0.00 here.
    expect(label.parentElement?.textContent).toContain("20.00");
  });
});

describe("F7 HP — chart surface after the engine migration", () => {
  it("mounts the engine; the removed chart-series chip menu does not resurface", () => {
    render(<HPPane code="HP" symbol="AAPL" />);
    expect(screen.getByTestId("chart-engine")).toBeInTheDocument();
    expect(screen.queryByTestId("hp-indicators-menu")).toBeNull();
    expect(screen.queryByRole("button", { name: /Indicators/ })).toBeNull();
    // The payload's indicator toggles fed the retired lightweight-charts
    // series; no indicator preset chip list may come back with the engine
    // in place (the engine owns the searchable indicator picker now).
    expect(hpSourceRaw).not.toMatch(/INDICATOR_PRESETS/);
  });
});
