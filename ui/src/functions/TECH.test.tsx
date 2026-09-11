/**
 * TECH pane — load-state + render-contract tests.
 *
 * `useFunction` is mocked via a mutable shared state (same pattern as
 * GEX.test.tsx) so each test drives the pane into a specific branch
 * without the real sidecar transport. Pins:
 *
 *  - loading / error / empty / ok states render;
 *  - latest-value cards derive from the payload (RSI, MACD line+hist,
 *    BB upper, SMA fast) with honest captions/tones;
 *  - a family chip toggle hides that family's cards AND persists the
 *    hidden id under `showme.tech.families`;
 *  - hiding every family renders an explicit all-hidden note;
 *  - the close-price sparkline renders an SVG path + accessible label;
 *  - degraded payloads (envelope warnings) surface a visible pill.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { act, cleanup, fireEvent, render, screen, within } from "@testing-library/react";
import { TECHPane } from "./TECH";

/* ── useFunction mock ──────────────────────────────────────────────── */

interface MockFnState {
  state: "idle" | "loading" | "ok" | "error" | "refreshing";
  data?:
    | {
        data?: unknown;
        data_state?: string;
        sources?: string[];
        elapsed_ms?: number;
        warnings?: string[];
      }
    | undefined;
  error?: Error | null;
}

const mockFn: MockFnState = { state: "idle", data: undefined, error: null };

function setMockFn(next: MockFnState) {
  mockFn.state = next.state;
  mockFn.data = next.data;
  mockFn.error = next.error ?? null;
}

// Visibility poll controls + useFunction arg recorder (live adoption tests).
const mockTick = { current: 0 };
const refetchMock = vi.fn();
let lastFnArgs: Record<string, unknown> | undefined;

vi.mock("@/lib/useFunction", () => ({
  useFunction: (args: Record<string, unknown>) => {
    lastFnArgs = args;
    return {
      state: mockFn.state,
      data: mockFn.data,
      error: mockFn.error,
      refetch: refetchMock,
    };
  },
}));

vi.mock("@/lib/useVisibilityTick", () => ({
  useVisibilityTick: () => mockTick.current,
}));

vi.mock("@/shell/SymbolBar", () => ({
  SymbolBar: () => null,
}));

/* ── fixture (small: 3 bars, condensed indicator set) ──────────────── */

const bar = (close: number, extra: Record<string, number> = {}) => ({
  date: "2026-09-01T13:30:00+00:00",
  open: close - 1,
  high: close + 1,
  low: close - 2,
  close,
  volume: 1000,
  ...extra,
});

const rows = [
  bar(100, {
    sma_fast: 99,
    sma_slow: 95,
    ema: 99.5,
    rsi: 55,
    macd: 1.1,
    macd_signal: 0.9,
    macd_hist: 0.2,
    atr: 1.5,
    adx: 30,
    stoch_k: 65,
    stoch_d: 60,
    obv: 1000,
  }),
  bar(101, { obv: 1500 }),
  bar(102, {
    sma_fast: 99,
    sma_slow: 95,
    ema: 99.5,
    rsi: 53.91,
    macd: 2.5557,
    macd_signal: 0.9801,
    macd_hist: -0.4188,
    atr: 1.8,
    adx: 15.4,
    stoch_k: 56.76,
    stoch_d: 77.97,
    obv: 2000,
  }),
];

function okPayload(warnings: string[] = [], lastPrice = 102) {
  return {
    data: {
      data: {
        status: "ok",
        model: "builtin",
        rows,
        summary: {
          last_price: lastPrice,
          rsi: 53.91,
          atr: 1.8,
          adx: 15.4,
          macd: 2.5557,
          macd_signal: 0.9801,
          stoch_k: 56.76,
          stoch_d: 77.97,
          obv: 2000,
        },
        indicators: {
          bb_upper: [{ time: "2026-09-01T13:30:00+00:00", value: 110 }],
          bb_mid: [{ time: "2026-09-01T13:30:00+00:00", value: 100 }],
          bb_lower: [{ time: "2026-09-01T13:30:00+00:00", value: 90 }],
        },
        bar_count: 3,
        resolution: "1d",
        indicator_params: {
          rsi_period: 14,
          sma_fast: 20,
          sma_slow: 50,
          ema_period: 20,
          bb_period: 20,
          bb_std: 2,
          macd_fast: 12,
          macd_slow: 26,
          macd_signal: 9,
          atr_period: 14,
          adx_period: 14,
          stoch_k: 14,
          stoch_d: 3,
        },
      },
      data_state: "live",
      sources: ["yfinance"],
      elapsed_ms: 12.3,
      warnings,
    },
  };
}

/* ── tests ─────────────────────────────────────────────────────────── */

beforeEach(() => {
  localStorage.clear();
  setMockFn({ state: "idle", data: undefined });
  mockTick.current = 0;
  refetchMock.mockClear();
  lastFnArgs = undefined;
});
afterEach(() => {
  cleanup();
});

describe("TECH pane — load states", () => {
  it("renders a skeleton while loading", () => {
    setMockFn({ state: "loading", data: undefined });
    const { container } = render(<TECHPane code="TECH" symbol="AAPL" />);
    expect(container.querySelector('[aria-busy="true"]')).not.toBeNull();
  });

  it("renders the error state when the fetch errors", () => {
    setMockFn({
      state: "error",
      data: undefined,
      error: new Error("sidecar exploded"),
    });
    render(<TECHPane code="TECH" symbol="AAPL" />);
    expect(screen.getByText(/sidecar exploded/i)).toBeInTheDocument();
  });

  it("renders the empty state when no bars come back", () => {
    setMockFn({
      state: "ok",
      data: { data: { status: "empty", rows: [], summary: {} } },
    });
    render(<TECHPane code="TECH" symbol="AAPL" />);
    expect(screen.getByText(/No indicator bars returned/i)).toBeInTheDocument();
  });

  it("renders latest indicator cards when ok", () => {
    setMockFn({ state: "ok", ...okPayload() });
    render(<TECHPane code="TECH" symbol="AAPL" />);
    // RSI from summary, formatted to 2 decimals.
    expect(screen.getByText("53.91")).toBeInTheDocument();
    // MACD line + histogram (histogram from the last bar).
    expect(screen.getByText("2.56")).toBeInTheDocument();
    expect(screen.getByText("-0.42")).toBeInTheDocument();
    expect(screen.getByText(/BEARISH MOMENTUM/i)).toBeInTheDocument();
    // BB upper from the indicators series + %B caption.
    expect(screen.getByText("110.00")).toBeInTheDocument();
    expect(screen.getByText("%B 0.60")).toBeInTheDocument();
    // SMA fast with price-above caption (SMA50 + EMA share it => getAllByText).
    expect(screen.getByText("99.00")).toBeInTheDocument();
    expect(screen.getAllByText(/PRICE ABOVE/i).length).toBeGreaterThanOrEqual(1);
    // ADX below 25 => ranging caption.
    expect(screen.getByText(/RANGING < 25/i)).toBeInTheDocument();
  });
});

describe("TECH pane — family toggles", () => {
  it("hides a family's cards when its chip is toggled off and persists it", () => {
    setMockFn({ state: "ok", ...okPayload() });
    render(<TECHPane code="TECH" symbol="AAPL" />);
    expect(screen.getByText("53.91")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "RSI" }));
    expect(screen.queryByText("53.91")).toBeNull();
    expect(localStorage.getItem("showme.tech.families")).toContain("rsi");
    // Toggle back on restores the card.
    fireEvent.click(screen.getByRole("button", { name: "RSI" }));
    expect(screen.getByText("53.91")).toBeInTheDocument();
  });

  it("renders an explicit note when every family is hidden", () => {
    setMockFn({ state: "ok", ...okPayload() });
    render(<TECHPane code="TECH" symbol="AAPL" />);
    for (const id of ["MA", "RSI", "MACD", "BB", "STOCH", "ADX", "OBV"]) {
      fireEvent.click(screen.getByRole("button", { name: id }));
    }
    expect(screen.getByText(/All indicator families hidden/i)).toBeInTheDocument();
  });
});

describe("TECH pane — sparkline + honesty", () => {
  it("renders the close-price sparkline as an SVG path with an accessible label", () => {
    setMockFn({ state: "ok", ...okPayload() });
    const { container } = render(<TECHPane code="TECH" symbol="AAPL" />);
    const spark = screen.getByRole("img", { name: /Close price/i });
    expect(spark).toBeInTheDocument();
    const path = spark.querySelector("path");
    expect(path).not.toBeNull();
    expect(path?.getAttribute("d")).toBeTruthy();
    // Params strip is derived from indicator_params.
    expect(container.textContent).toContain("MACD 12/26/9");
  });

  it("surfaces degraded payloads via a visible warning pill", () => {
    setMockFn({
      state: "ok",
      ...okPayload(["yfinance returned partial history"]),
    });
    render(<TECHPane code="TECH" symbol="AAPL" />);
    expect(screen.getByText(/Degraded:/i)).toBeInTheDocument();
    expect(screen.getByText(/partial history/i)).toBeInTheDocument();
  });
});

describe("TECH pane — study sub-panes (OPP wave)", () => {
  it("renders the RSI(14) sub-pane from per-bar values and hides it with the RSI chip", () => {
    setMockFn({ state: "ok", ...okPayload() });
    render(<TECHPane code="TECH" symbol="AAPL" />);
    const study = screen.getByTestId("tech-study-rsi");
    expect(within(study).getByText("RSI(14)")).toBeInTheDocument();
    // Honest last-value + zone readout, derived from the last real bar (53.91).
    expect(within(study).getByText(/LAST 53\.91/)).toBeInTheDocument();
    expect(within(study).getByText(/NEUTRAL 30–70/)).toBeInTheDocument();
    expect(within(study).getByRole("img", { name: /RSI\(14\) study/i })).toBeInTheDocument();
    // The same family chip drives both the card and the study.
    fireEvent.click(screen.getByRole("button", { name: "RSI" }));
    expect(screen.queryByTestId("tech-study-rsi")).toBeNull();
  });

  it("renders the MACD study with line/signal/histogram and hides it with the MACD chip", () => {
    setMockFn({ state: "ok", ...okPayload() });
    render(<TECHPane code="TECH" symbol="AAPL" />);
    const study = screen.getByTestId("tech-study-macd");
    expect(within(study).getByText("MACD 12/26/9")).toBeInTheDocument();
    // Last per-bar readings: macd 2.56 / signal 0.98 / hist -0.42.
    expect(within(study).getByText(/MACD 2\.56 · SIGNAL 0\.98 · HIST -0\.42/)).toBeInTheDocument();
    const chart = within(study).getByRole("img", { name: /MACD\(12\/26\/9\) study/i });
    // Line + signal + at least one histogram rect.
    expect(chart.querySelectorAll("path").length).toBe(2);
    expect(chart.querySelectorAll("rect").length).toBeGreaterThanOrEqual(1);
    fireEvent.click(screen.getByRole("button", { name: "MACD" }));
    expect(screen.queryByTestId("tech-study-macd")).toBeNull();
  });

  it("does not fabricate a study pane when bars carry no per-bar study series", () => {
    const bare = [
      { date: "2026-09-01T13:30:00+00:00", open: 99, high: 101, low: 98, close: 100, volume: 1000 },
      { date: "2026-09-01T13:31:00+00:00", open: 100, high: 102, low: 99, close: 101, volume: 900 },
    ];
    setMockFn({
      state: "ok",
      data: {
        data: { status: "ok", rows: bare, summary: { last_price: 101, rsi: 55 } },
        data_state: "live",
      },
    });
    render(<TECHPane code="TECH" symbol="AAPL" />);
    // The RSI card still renders from summary — but no per-bar study series
    // exists, so no RSI/MACD sub-pane is offered (never a fabricated line).
    expect(screen.getByText("55.00")).toBeInTheDocument();
    expect(screen.queryByTestId("tech-study-rsi")).toBeNull();
    expect(screen.queryByTestId("tech-study-macd")).toBeNull();
  });
});

describe("TECH pane — visibility poll (live adoption)", () => {
  it("refetches on a visibility tick but not on mount", () => {
    setMockFn({ state: "ok", ...okPayload() });
    const { rerender } = render(<TECHPane code="TECH" symbol="AAPL" />);
    // Mount is useFunction's own initial load — the tick must not double-fetch.
    expect(refetchMock).not.toHaveBeenCalled();

    mockTick.current = 1;
    rerender(<TECHPane code="TECH" symbol="AAPL" />);
    expect(refetchMock).toHaveBeenCalledTimes(1);
  });

  it("keeps fetch args stable across ticks (never feeds tick into params)", () => {
    setMockFn({ state: "ok", ...okPayload() });
    const { rerender } = render(<TECHPane code="TECH" symbol="AAPL" />);
    const snapshot = () =>
      JSON.stringify({
        code: lastFnArgs?.code,
        symbol: lastFnArgs?.symbol,
        params: lastFnArgs?.params ?? null,
      });
    const before = snapshot();

    mockTick.current = 3;
    rerender(<TECHPane code="TECH" symbol="AAPL" />);
    expect(snapshot()).toBe(before);
    expect(snapshot()).not.toContain("tick");
  });

  it("flashes the last-price cell when the price moves (not on first render)", () => {
    vi.useFakeTimers();
    try {
      setMockFn({ state: "ok", ...okPayload([], 102) });
      const { rerender } = render(<TECHPane code="TECH" symbol="AAPL" />);
      const cell = screen.getByTestId("flash-value");
      expect(cell.className).not.toMatch(/flash/);

      setMockFn({ state: "ok", ...okPayload([], 103.5) });
      rerender(<TECHPane code="TECH" symbol="AAPL" />);
      expect(screen.getByTestId("flash-value").className).toContain("flash-pos");

      act(() => {
        vi.advanceTimersByTime(600);
      });
      expect(screen.getByTestId("flash-value").className).not.toMatch(/flash/);
    } finally {
      vi.useRealTimers();
    }
  });
});
