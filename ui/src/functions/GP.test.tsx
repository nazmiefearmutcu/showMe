/**
 * GP / TECH regressions — in-house chart engine migration.
 *
 * What we lock down:
 *   1. The pane mounts the in-house chart engine (`@/chart/Chart`) with the
 *      pane symbol and mapped initial timeframe/style, and no longer imports
 *      or instantiates lightweight-charts.
 *   2. The redundant chip rows (TIMEFRAME / STYLE / BARS / INDICATORS) and
 *      the dead Compare/Export controls are gone — the engine owns those
 *      controls now. The RANGE row (which drives the function payload behind
 *      the header stats and key-level rail) stays.
 *   3. The source no longer ships the `buildMockNews` fabricator and none of
 *      the canned fake headlines leak into the file.
 */
import { readFileSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, render, screen } from "@testing-library/react";
import type { TransportState } from "@/lib/market-data";
import { GPPane } from "./GP";

const __dirname = dirname(fileURLToPath(import.meta.url));
const gpSourceRaw = readFileSync(resolve(__dirname, "GP.tsx"), "utf-8");

/* ── chart-engine probe ─────────────────────────────────────────────── */

const engineProbe = vi.hoisted(() => ({
  lastProps: null as Record<string, unknown> | null,
}));

vi.mock("@/chart/Chart", () => ({
  Chart: (props: Record<string, unknown>) => {
    engineProbe.lastProps = props;
    return <div data-testid="chart-engine" />;
  },
  default: () => <div data-testid="chart-engine" />,
}));

// jsdom ships no ResizeObserver — stub it for ResizableChartFrame.
class FakeResizeObserver {
  observe() {}
  disconnect() {}
  unobserve() {}
}
(globalThis as { ResizeObserver?: unknown }).ResizeObserver = FakeResizeObserver;

/* ── hook mocks ─────────────────────────────────────────────────────── */

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

/* ── fixtures ───────────────────────────────────────────────────────── */

function gpPayload() {
  return {
    data: {
      ohlcv: [
        { time: "2026-05-18", open: 100, high: 102, low: 99, close: 101, volume: 100_000 },
        { time: "2026-05-19", open: 101, high: 104, low: 100, close: 103, volume: 120_000 },
        { time: "2026-05-20", open: 103, high: 105, low: 102, close: 104.25, volume: 90_000 },
      ],
    },
    sources: ["yfinance"],
  };
}

beforeEach(() => {
  engineProbe.lastProps = null;
  mockState.payload = gpPayload();
  if (typeof localStorage !== "undefined") localStorage.clear();
});

afterEach(() => {
  cleanup();
});

/* ── tests ──────────────────────────────────────────────────────────── */

describe("GP — in-house chart engine mount", () => {
  it("mounts the engine with the pane symbol and mapped timeframe/style", () => {
    render(<GPPane code="GP" symbol="AAPL" />);
    expect(screen.getByTestId("chart-engine")).toBeInTheDocument();
    expect(engineProbe.lastProps?.symbol).toBe("AAPL");
    expect(engineProbe.lastProps?.fill).toBe(true);
    // GP's default interval "1d" + style "candle" map onto engine vocabulary.
    expect(engineProbe.lastProps?.initialInterval).toBe("1D");
    expect(engineProbe.lastProps?.initialType).toBe("candles");
  });

  it("maps a persisted lowercase interval onto the engine catalog", () => {
    localStorage.setItem("showme.gp-interval", "1h");
    render(<GPPane code="GP" symbol="AAPL" />);
    expect(engineProbe.lastProps?.initialInterval).toBe("1h");
  });

  it("uses the pane's default symbol when the route carries none", () => {
    render(<GPPane code="GP" symbol={undefined} />);
    expect(screen.getByTestId("chart-engine")).toBeInTheDocument();
    expect(engineProbe.lastProps?.symbol).toBeTruthy();
  });

  it("keeps the RANGE row (payload driver) while the engine owns the rest", () => {
    const { container } = render(<GPPane code="GP" symbol="AAPL" />);
    expect(screen.getByText("RANGE")).toBeInTheDocument();
    for (const chipRow of ["TIMEFRAME", "STYLE", "BARS", "INDICATORS"]) {
      expect(container.textContent).not.toContain(chipRow);
    }
    expect(screen.queryByTestId("gp-compare-button")).toBeNull();
    expect(screen.queryByTestId("gp-export-button")).toBeNull();
    expect(screen.queryByText("Compare +")).toBeNull();
  });
});

describe("GP source — fabricated content guards", () => {
  it("no longer imports or ships lightweight-charts / ChartView", () => {
    expect(gpSourceRaw).not.toMatch(/lightweight-charts/);
    expect(gpSourceRaw).not.toMatch(/ChartView/);
  });

  it("does not export or define buildMockNews", () => {
    expect(gpSourceRaw).not.toMatch(/function\s+buildMockNews/);
    expect(gpSourceRaw).not.toMatch(/buildMockNews\s*\(/);
  });

  it("does not contain the canned fake headline strings", () => {
    // These three sentences were the entire output of the removed
    // `buildMockNews` helper. Any reintroduction must fail this test.
    expect(gpSourceRaw).not.toContain("momentum builds as MA cross fires");
    expect(gpSourceRaw).not.toContain("Technical traders eye");
    expect(gpSourceRaw).not.toContain("closes in on key Fib retracement");
  });

  it("no longer ships the dead Compare/Export controls", () => {
    expect(gpSourceRaw).not.toMatch(/gp-compare-button/);
    expect(gpSourceRaw).not.toMatch(/gp-export-button/);
  });
});
