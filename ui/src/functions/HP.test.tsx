/**
 * HP / Historical price regressions — in-house chart engine migration.
 *
 * What we lock down:
 *   1. The pane mounts the in-house chart engine (`@/chart/Chart`) with the
 *      pane symbol and the mapped initial timeframe/style, and no longer
 *      imports or instantiates lightweight-charts.
 *   2. The redundant chip rows (TIMEFRAME / STYLE / BARS / INDICATORS) and
 *      the chart-instance-bound Compare / PNG-export controls are gone — the
 *      engine owns those controls now. The RANGE row (which drives the
 *      function payload behind the header stats and key-level rail) and the
 *      CSV export (real data) stay.
 *   3. Fabricated content guards: no `buildMockNews`, no canned fake
 *      headlines, honest "News feed not wired" empty state.
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

function hpPayload() {
  return {
    data: {
      ohlcv: [
        { date: "2026-05-18", open: 100, high: 102, low: 99, close: 101, volume: 100_000 },
        { date: "2026-05-19", open: 101, high: 104, low: 100, close: 103, volume: 120_000 },
        { date: "2026-05-20", open: 103, high: 105, low: 102, close: 104.25, volume: 90_000 },
      ],
    },
    sources: ["yfinance"],
  };
}

beforeEach(() => {
  engineProbe.lastProps = null;
  mockState.payload = hpPayload();
  if (typeof localStorage !== "undefined") localStorage.clear();
});

afterEach(() => {
  cleanup();
});

/* ── tests ──────────────────────────────────────────────────────────── */

describe("HP — in-house chart engine mount", () => {
  it("mounts the engine with the pane symbol and mapped timeframe/style", () => {
    render(<HPPane code="HP" symbol="AAPL" />);
    expect(screen.getByTestId("chart-engine")).toBeInTheDocument();
    expect(engineProbe.lastProps?.symbol).toBe("AAPL");
    expect(engineProbe.lastProps?.fill).toBe(true);
    // HP's default interval "1d" + style "candle" map onto engine vocabulary.
    expect(engineProbe.lastProps?.initialInterval).toBe("1D");
    expect(engineProbe.lastProps?.initialType).toBe("candles");
  });

  it("maps a persisted lowercase interval onto the engine catalog", () => {
    localStorage.setItem("showme.hp-interval", "1h");
    render(<HPPane code="HP" symbol="AAPL" />);
    expect(engineProbe.lastProps?.initialInterval).toBe("1h");
  });

  it("uses the pane's default symbol when the route carries none", () => {
    render(<HPPane code="HP" symbol={undefined} />);
    expect(screen.getByTestId("chart-engine")).toBeInTheDocument();
    expect(engineProbe.lastProps?.symbol).toBeTruthy();
  });

  it("keeps the RANGE row and CSV export while the engine owns the rest", () => {
    const { container } = render(<HPPane code="HP" symbol="AAPL" />);
    expect(screen.getByText("RANGE")).toBeInTheDocument();
    for (const chipRow of ["TIMEFRAME", "STYLE", "BARS"]) {
      expect(container.textContent).not.toContain(chipRow);
    }
    expect(screen.queryByRole("button", { name: /Indicators/ })).toBeNull();
    expect(screen.queryByRole("button", { name: "Export chart as PNG" })).toBeNull();
    expect(container.querySelector('[data-testid="hp-compare-toggle"]')).toBeNull();
    expect(screen.queryByText(/Compare/)).toBeNull();
    expect(screen.getByRole("button", { name: "CSV" })).toBeInTheDocument();
  });
});

describe("HP source — fabricated content guards", () => {
  it("does not export or define buildMockNews", () => {
    expect(hpSourceRaw).not.toMatch(/function\s+buildMockNews/);
    expect(hpSourceRaw).not.toMatch(/buildMockNews\s*\(/);
  });

  it("does not contain the canned fake headline strings", () => {
    // These three sentences were the entire output of the removed
    // `buildMockNews` helper. Any reintroduction must fail this test.
    expect(hpSourceRaw).not.toContain("prints fresh session high on volume spike");
    expect(hpSourceRaw).not.toContain("Sector rotation lifts");
    expect(hpSourceRaw).not.toContain("options skew turns bullish into expiry");
  });

  it("renders an honest 'News feed not wired' empty state", () => {
    expect(hpSourceRaw).toContain("News feed not wired");
    expect(hpSourceRaw).toMatch(/data-testid="hp-news-empty"/);
  });
});

describe("HP source — chart engine migration cleanup", () => {
  it("no longer imports or ships lightweight-charts / PriceChart", () => {
    expect(hpSourceRaw).not.toMatch(/lightweight-charts/);
    expect(hpSourceRaw).not.toMatch(/PriceChart/);
    expect(hpSourceRaw).not.toMatch(/createChart/);
  });

  it("mounts the in-house chart engine", () => {
    expect(hpSourceRaw).toMatch(/from\s+"@\/chart\/Chart"/);
    expect(hpSourceRaw).toMatch(/<Chart[\s\S]{0,300}initialInterval=\{mapInterval\(interval\)\}/);
    expect(hpSourceRaw).toMatch(/initialType=\{mapStyle\(HP_CHART_STYLE\)\}/);
  });

  it("no longer ships the chart-bound Compare / PNG-export controls", () => {
    expect(hpSourceRaw).not.toMatch(/ComparePopup/);
    expect(hpSourceRaw).not.toMatch(/hp-compare-toggle/);
    expect(hpSourceRaw).not.toMatch(/takeScreenshot/);
    expect(hpSourceRaw).not.toMatch(/\.png/);
  });

  it("keeps the real CSV export path (downloadCsv → buildCsv)", () => {
    expect(hpSourceRaw).toMatch(/function\s+downloadCsv\s*\(/);
    expect(hpSourceRaw).toMatch(/downloadCsv\(/);
    expect(hpSourceRaw).toMatch(/from\s+"\.\/HP\.csv"/);
  });
});
