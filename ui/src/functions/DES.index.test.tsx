/**
 * DES index branch — honest index presentation (2026-09-16).
 *
 * Indices (^GSPC, ^STOXX50E, XU100.IS…) carry no company fundamentals, and
 * the reference providers return nothing for them — the pane used to render
 * an all-"—" fundamentals grid plus "Provider did not return a business
 * summary". This file pins the replacement contract:
 *
 *  1. `computeIndexSnapshot` derives Last / day range / 52w range and
 *     1M-3M-6M-YTD returns from real daily bars, nulls when bars are absent;
 *  2. the pane renders that snapshot labelled "computed from daily bars";
 *  3. the business-summary fallback is replaced by a curated factual index
 *     profile line (fallback: "Index instrument — fundamentals not applicable");
 *  4. equities keep the existing Business-summary path untouched.
 */
import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { Bar } from "@/chart/types";
import { DESPane, computeIndexSnapshot } from "./DES";

const DAY = 86_400_000;
const BASE = Date.UTC(2026, 0, 1);

/** 288 daily bars (30 before Jan 1 2026, through 2026-09-15). */
function makeBars(): Bar[] {
  const bars: Bar[] = [];
  for (let i = -30; i <= 257; i++) {
    const c = 4000 + i;
    bars.push({ t: BASE + i * DAY, o: c, h: c + 1, l: c - 1, c, v: 0 });
  }
  return bars;
}

const sidecarFetchMock = vi.fn();
vi.mock("@/lib/sidecar", () => ({
  sidecarFetch: (...args: unknown[]) => sidecarFetchMock(...args),
}));

// The engine fetches /api/bars and paints a canvas — stub it out.
vi.mock("@/chart/Chart", () => ({
  Chart: () => <div data-testid="chart-engine" />,
}));

vi.mock("@/lib/market-data", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/lib/market-data")>();
  return {
    ...actual,
    useLiveQuote: () => ({
      transportState: "idle",
      lastTick: null,
      lastTickAt: null,
      snapshot: null,
      freshnessMs: null,
      stale: false,
      refreshing: false,
    }),
  };
});

const useFunctionMock = vi.fn();
vi.mock("@/lib/useFunction", () => ({
  useFunction: () => useFunctionMock(),
}));

function indexPayload(symbol = "^GSPC") {
  return {
    state: "ok",
    data: {
      status: "unsupported_asset",
      sources: ["showme_compatibility_guard"],
      elapsed_ms: 3,
      data: {
        symbol,
        status: "unsupported_asset",
        reason: "DES does not support INDEX",
      },
    },
    error: null,
    refetch: vi.fn(),
  };
}

function equityPayload() {
  return {
    state: "ok",
    data: {
      status: "ok",
      sources: ["yfinance"],
      elapsed_ms: 42,
      data: {
        status: "ok",
        longName: "Apple Inc.",
        shortName: "Apple",
        regularMarketPrice: 302.5,
        previousClose: 300.0,
        sector: "Technology",
        exchange_name: "NASDAQ",
        longBusinessSummary: "Apple designs and sells consumer electronics.",
      },
    },
    error: null,
    refetch: vi.fn(),
  };
}

beforeEach(() => {
  sidecarFetchMock.mockReset();
  sidecarFetchMock.mockResolvedValue({
    symbol: "^GSPC",
    interval: "1d",
    source: "yahoo",
    asOf: "2026-09-15T20:00:00+00:00",
    bars: makeBars(),
  });
  useFunctionMock.mockReturnValue(indexPayload());
});

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

describe("computeIndexSnapshot — daily bars only, nulls when absent", () => {
  it("computes last/range/returns from real bars", () => {
    const snap = computeIndexSnapshot(makeBars());
    expect(snap.last).toBeCloseTo(4257, 5);
    expect(snap.dayLow).toBeCloseTo(4256, 5);
    expect(snap.dayHigh).toBeCloseTo(4258, 5);
    expect(snap.low52).toBeCloseTo(3969, 5);
    expect(snap.high52).toBeCloseTo(4258, 5);
    expect(snap.r1m).toBeCloseTo((4257 / 4227 - 1) * 100, 4);
    expect(snap.r3m).toBeCloseTo((4257 / 4166 - 1) * 100, 4);
    expect(snap.r6m).toBeCloseTo((4257 / 4075 - 1) * 100, 4);
    // YTD reference is the last close before Jan 1 2026 (3999).
    expect(snap.ytd).toBeCloseTo((4257 / 3999 - 1) * 100, 4);
  });

  it("returns nulls for empty or malformed input", () => {
    for (const snap of [
      computeIndexSnapshot([]),
      computeIndexSnapshot([{ t: NaN, o: 0, h: 0, l: 0, c: NaN, v: 0 }]),
    ]) {
      expect(snap.last).toBeNull();
      expect(snap.high52).toBeNull();
      expect(snap.r1m).toBeNull();
      expect(snap.ytd).toBeNull();
    }
  });
});

describe("DES index branch — rendered snapshot", () => {
  it("renders the computed snapshot instead of an empty fundamentals grid", async () => {
    render(<DESPane code="DES" symbol="^GSPC" />);
    expect(await screen.findByText(/computed from daily bars/i)).toBeInTheDocument();
    expect(screen.getByTestId("des-index-snapshot")).toBeInTheDocument();
    expect(screen.getByTestId("des-index-pill").textContent).toMatch(/INDEX SNAPSHOT/);
    expect(screen.getByText("$4,257.00")).toBeInTheDocument();
    expect(screen.getByText(/52w range/i)).toBeInTheDocument();
    // The broken-looking legacy fallbacks are gone.
    expect(
      screen.queryByText(/Provider did not return a business summary/i),
    ).toBeNull();
    expect(screen.queryByText(/Business summary/i)).toBeNull();
    expect(screen.queryByText(/^Market cap$/)).toBeNull();
  });

  it("shows the curated factual profile line for a known index", async () => {
    render(<DESPane code="DES" symbol="^GSPC" />);
    expect(
      await screen.findByText(/S&P 500 — large-cap U\.S\. equity benchmark/i),
    ).toBeInTheDocument();
    expect(screen.getByTestId("des-index-profile")).toBeInTheDocument();
    // Never a fake business description.
    expect(
      screen.queryByText(/Provider did not return a business summary/i),
    ).toBeNull();
  });

  it("falls back to the factual not-applicable line for unknown indices", async () => {
    useFunctionMock.mockReturnValue(indexPayload("^ZZZ"));
    sidecarFetchMock.mockResolvedValue({ bars: [] });
    render(<DESPane code="DES" symbol="^ZZZ" />);
    expect(
      await screen.findByText(/Index instrument — fundamentals not applicable/),
    ).toBeInTheDocument();
    expect(screen.getByText(/Index snapshot unavailable/i)).toBeInTheDocument();
  });
});

describe("DES equity branch — unchanged", () => {
  it("keeps equities on the business-summary path", async () => {
    useFunctionMock.mockReturnValue(equityPayload());
    render(<DESPane code="DES" symbol="AAPL" />);
    expect(await screen.findByText(/Business summary/i)).toBeInTheDocument();
    expect(
      screen.getByText(/Apple designs and sells consumer electronics/i),
    ).toBeInTheDocument();
    expect(screen.queryByTestId("des-index-snapshot")).toBeNull();
    // The index bars fetch must not fire for equities (other panes' chips
    // may still call the sidecar — only /api/bars is the boundary here).
    expect(
      sidecarFetchMock.mock.calls.some(([path]) =>
        String(path).startsWith("/api/bars"),
      ),
    ).toBe(false);
  });
});
