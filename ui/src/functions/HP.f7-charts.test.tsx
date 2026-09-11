/**
 * F7 — HP chart fixes (audit A1 / HP subsection).
 *
 * Pins the fixes shipped in the charts fix lane:
 *   1. The name/exchange pills render from the alias payload
 *      (`long_name` / `short_name` / `exchange`) instead of the never-emitted
 *      camelCase keys.
 *   2. "52w high/low" only claims 52 weeks when the provider meta supplied
 *      real 52-week levels; otherwise the rail labels show honest
 *      "Range high/low".
 *   3. "ATR(14)" is TRUE ATR — Wilder-smoothed max(H−L, |H−prevC|,
 *      |L−prevC|) — not the old mean |Δclose| (with flat closes and big
 *      ranges the old code showed 0.00; the fix shows the true range).
 *   4. Indicator toggles that used to be silent no-ops now draw:
 *      BB(20,2) → 3 band overlays on the price pane, RSI(14) → sub-pane 1,
 *      MACD → line+signal+histogram in a stacked study pane.
 *   5. The fake `cache · live` footer pill (field never existed) is replaced
 *      by an honest deep/windowed history chip.
 *   6. The crosshair readout prefers the main price series even when study
 *      series are listed first in `param.seriesData`.
 */
import { readFileSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import {
  act,
  cleanup,
  fireEvent,
  render,
  screen,
  within,
} from "@testing-library/react";
import type { TransportState } from "@/lib/market-data";
import { HPPane } from "./HP";

const __dirname = dirname(fileURLToPath(import.meta.url));
const hpSourceRaw = readFileSync(resolve(__dirname, "HP.tsx"), "utf-8");

/* ── lightweight-charts spy ─────────────────────────────────────────── */

interface SeriesStub {
  setData: ReturnType<typeof vi.fn>;
  update: ReturnType<typeof vi.fn>;
  applyOptions: ReturnType<typeof vi.fn>;
  moveToPane: ReturnType<typeof vi.fn>;
  getPane: () => { paneIndex: () => number };
  __pane: number;
  __label?: string;
}
interface AddedEntry {
  constructor: unknown;
  options: Record<string, unknown>;
  series: SeriesStub;
  pane: number;
}
interface PaneStub {
  setStretchFactor: ReturnType<typeof vi.fn>;
  paneIndex: () => number;
}
interface ChartStub {
  addSeries: ReturnType<typeof vi.fn>;
  removeSeries: ReturnType<typeof vi.fn>;
  subscribeCrosshairMove: ReturnType<typeof vi.fn>;
  priceScale: ReturnType<typeof vi.fn>;
  timeScale: ReturnType<typeof vi.fn>;
  remove: ReturnType<typeof vi.fn>;
  applyOptions: ReturnType<typeof vi.fn>;
  resize: ReturnType<typeof vi.fn>;
  takeScreenshot: ReturnType<typeof vi.fn>;
  panes: ReturnType<typeof vi.fn>;
  __series: SeriesStub[];
  __added: AddedEntry[];
}

const chartInstances: ChartStub[] = [];

vi.mock("lightweight-charts", () => {
  class LineSeries {}
  class CandlestickSeries {}
  class HistogramSeries {}
  class AreaSeries {}
  const createChart = vi.fn(() => {
    const series: SeriesStub[] = [];
    const added: AddedEntry[] = [];
    const makeSeries = (pane: number): SeriesStub => {
      const stub: SeriesStub = {
        setData: vi.fn(),
        update: vi.fn(),
        applyOptions: vi.fn(),
        moveToPane: vi.fn((next: number) => {
          stub.__pane = next;
        }),
        getPane: () => ({ paneIndex: () => stub.__pane }),
        __pane: pane,
      };
      return stub;
    };
    const panes: PaneStub[] = [0, 1, 2].map((index) => ({
      setStretchFactor: vi.fn(),
      paneIndex: () => index,
    }));
    const instance: ChartStub = {
      addSeries: vi.fn(
        (
          constructor: unknown,
          options: Record<string, unknown>,
          paneIndex?: number,
        ) => {
          const pane = typeof paneIndex === "number" ? paneIndex : 0;
          const stub = makeSeries(pane);
          series.push(stub);
          added.push({ constructor, options, series: stub, pane });
          return stub;
        },
      ),
      removeSeries: vi.fn(),
      subscribeCrosshairMove: vi.fn(),
      priceScale: vi.fn(() => ({ applyOptions: vi.fn() })),
      timeScale: vi.fn(() => ({
        fitContent: vi.fn(),
        setVisibleLogicalRange: vi.fn(),
      })),
      remove: vi.fn(),
      applyOptions: vi.fn(),
      resize: vi.fn(),
      takeScreenshot: vi.fn(() => document.createElement("canvas")),
      panes: vi.fn(() => panes),
      __series: series,
      __added: added,
    };
    chartInstances.push(instance);
    return instance;
  });
  return { createChart, LineSeries, CandlestickSeries, HistogramSeries, AreaSeries };
});

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

function openIndicatorMenu() {
  fireEvent.click(screen.getByRole("button", { name: /Indicators/ }));
  return within(screen.getByTestId("hp-indicators-menu"));
}

beforeEach(() => {
  chartInstances.length = 0;
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

describe("F7 HP — indicator toggles actually draw", () => {
  it("BB(20,2) adds upper/mid/lower overlays on the price pane", () => {
    render(<HPPane code="HP" symbol="AAPL" />);
    const menu = openIndicatorMenu();
    fireEvent.click(menu.getByText("BB(20,2)"));
    const chart = chartInstances[0];
    const bands = chart.__added.filter((entry) =>
      String(entry.options.title).startsWith("BB(20,2)"),
    );
    expect(bands.map((entry) => entry.options.title).sort()).toEqual([
      "BB(20,2):lower",
      "BB(20,2):mid",
      "BB(20,2):upper",
    ]);
    expect(bands.every((entry) => entry.pane === 0)).toBe(true);
    expect(
      bands.every((entry) => entry.series.setData.mock.calls.length > 0),
    ).toBe(true);
  });

  it("RSI(14) adds a Wilder-RSI study series in sub-pane 1", () => {
    render(<HPPane code="HP" symbol="AAPL" />);
    const menu = openIndicatorMenu();
    fireEvent.click(menu.getByText("RSI(14)"));
    const chart = chartInstances[0];
    const rsi = chart.__added.find((entry) => entry.options.title === "RSI(14)");
    expect(rsi).toBeDefined();
    expect(rsi?.pane).toBe(1);
    expect(rsi?.series.setData).toHaveBeenCalled();
  });

  it("MACD adds line+signal+histogram and re-homes when RSI toggles off", () => {
    render(<HPPane code="HP" symbol="AAPL" />);
    const menu = openIndicatorMenu();
    fireEvent.click(menu.getByText("RSI(14)"));
    fireEvent.click(menu.getByText("MACD"));

    const chart = chartInstances[0];
    const macdEntries = chart.__added.filter((entry) =>
      String(entry.options.title).startsWith("MACD"),
    );
    expect(macdEntries.map((entry) => entry.options.title)).toEqual(
      expect.arrayContaining(["MACD", "MACD:signal", "MACD:hist"]),
    );
    expect(macdEntries.every((entry) => entry.pane === 2)).toBe(true);
    const hist = macdEntries.find((entry) => entry.options.title === "MACD:hist");
    expect((hist?.constructor as { name?: string })?.name).toBe("HistogramSeries");

    // RSI off → the MACD study pane moves up to index 1 (no empty pane gap).
    fireEvent.click(menu.getByText("RSI(14)"));
    const macdLine = chart.__added.find((entry) => entry.options.title === "MACD");
    expect(macdLine?.series.moveToPane).toHaveBeenCalledWith(1);
  });

  it("does not rebuild the chart when a study is toggled", () => {
    render(<HPPane code="HP" symbol="AAPL" />);
    const menu = openIndicatorMenu();
    fireEvent.click(menu.getByText("RSI(14)"));
    fireEvent.click(menu.getByText("MACD"));
    expect(chartInstances).toHaveLength(1);
    expect(chartInstances[0].remove).not.toHaveBeenCalled();
  });

  it("re-applies active studies after a chart-style rebuild", () => {
    render(<HPPane code="HP" symbol="AAPL" />);
    expect(chartInstances).toHaveLength(1);
    // Candle → Line is the legitimate rebuild path (different series type).
    fireEvent.click(screen.getByRole("button", { name: "Line" }));
    expect(chartInstances).toHaveLength(2);
    const rebuilt = chartInstances[1];
    const sma = rebuilt.__added.find((entry) => entry.options.title === "SMA(20)");
    expect(sma).toBeDefined();
    expect(sma?.series.setData).toHaveBeenCalled();
  });
});

describe("F7 HP — crosshair readout with study panes", () => {
  it("prefers the main price series over an oscillator listed first", () => {
    render(<HPPane code="HP" symbol="AAPL" />);
    const chart = chartInstances[0];
    const handler = chart.subscribeCrosshairMove.mock.calls[0]?.[0] as
      | ((param: unknown) => void)
      | undefined;
    expect(handler).toBeDefined();
    const mainSeries = chart.__series[0];
    const oscillator = { __osc: true };
    act(() => {
      handler?.({
        time: 123,
        seriesData: new Map<unknown, unknown>([
          [oscillator, { value: 55.5 }],
          [mainSeries, { close: 123.45 }],
        ]),
      });
    });
    expect(screen.getByText("123.45")).toBeInTheDocument();
    expect(screen.queryByText("55.50")).toBeNull();
  });
});
