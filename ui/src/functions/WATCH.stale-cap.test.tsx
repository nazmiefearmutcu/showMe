/**
 * QA-2026-05-23 regressions for WATCH:
 *   - "Stale" duration must cap at 5 minutes and surface a STALE badge +
 *     Refresh button per row, not an ever-growing "Xm · stale" string.
 *   - The MEDIAN Δ% card must NOT compute a median until every row's first
 *     fetch has settled — otherwise the user sees "(1 SAMPLED)" briefly even
 *     though six other symbols are still mid-flight.
 */
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { WATCHPane } from "./WATCH";
import * as marketData from "@/lib/market-data";
import * as watchlist from "@/lib/watchlist";
import * as store from "@/lib/store";
import type { QuoteView } from "@/lib/market-data";

vi.mock("@/lib/sidecar", () => ({
  sidecarFetch: vi.fn(async () => ({ data: { ohlcv: [] } })),
}));

vi.mock("@/lib/tauri", () => ({
  isInTauri: () => false,
  invoke: vi.fn(),
}));

function makeView(overrides: Partial<QuoteView> = {}): QuoteView {
  return {
    symbol: "AAPL",
    snapshot: {
      symbol: "AAPL",
      asset_class: "EQUITY",
      last: 200,
      price: 200,
      previous_close: 198,
      change_pct: 1.0,
      volume: 1000,
      bid: null,
      ask: null,
      source: "yahoo",
      provider_symbol: "AAPL",
      currency: "USD",
      fetched_at: new Date().toISOString(),
    } as never,
    lastTick: null,
    price: 200,
    changePct: 1.2,
    source: "yahoo",
    sourceKind: "snapshot",
    fetchedAt: Date.now() - 60_000,
    freshnessMs: 60_000,
    stale: false,
    loading: false,
    refreshing: false,
    error: null,
    transportState: "live",
    lastTickAt: null,
    refetch: vi.fn(),
    ...overrides,
  };
}

beforeEach(() => {
  vi.spyOn(watchlist, "loadWatchlist").mockResolvedValue([
    { symbol: "AAPL" },
    { symbol: "MSFT" },
  ]);
  vi.spyOn(store, "useAppStore").mockImplementation(((selector: (s: { sidecarStatus: string; functionIndex: unknown[] }) => unknown) =>
    selector({ sidecarStatus: "healthy", functionIndex: [] })) as never);
});

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

describe("WATCH stale-cap", () => {
  it("renders STALE pill + per-row refresh button when freshness ≥ 5min", async () => {
    const refetch = vi.fn();
    vi.spyOn(marketData, "useLiveQuotes").mockReturnValue({
      AAPL: makeView({
        symbol: "AAPL",
        freshnessMs: 6 * 60_000,
        stale: true,
        refetch,
      }),
      MSFT: makeView({
        symbol: "MSFT",
        freshnessMs: 30_000,
        stale: false,
        refetch: vi.fn(),
      }),
    });
    render(<WATCHPane code="WATCH" symbol={undefined} />);
    // Wait for the watchlist load to settle.
    await screen.findByText("AAPL");
    const stale = screen.getByTestId("watch-row-stale-AAPL");
    expect(stale).toBeInTheDocument();
    const refreshBtn = screen.getByTestId("watch-row-refresh-AAPL");
    expect(refreshBtn).toBeInTheDocument();
    fireEvent.click(refreshBtn);
    expect(refetch).toHaveBeenCalled();
  });

  it("normal freshness < 5min does NOT show the STALE chip / refresh button", async () => {
    vi.spyOn(marketData, "useLiveQuotes").mockReturnValue({
      AAPL: makeView({
        symbol: "AAPL",
        freshnessMs: 90_000,
        stale: false,
      }),
      MSFT: makeView({
        symbol: "MSFT",
        freshnessMs: 60_000,
        stale: false,
      }),
    });
    render(<WATCHPane code="WATCH" symbol={undefined} />);
    await screen.findByText("AAPL");
    expect(screen.queryByTestId("watch-row-stale-AAPL")).toBeNull();
    expect(screen.queryByTestId("watch-row-refresh-AAPL")).toBeNull();
  });
});

describe("WATCH median Δ% sampling gate", () => {
  it("shows 'computing · n/total' while some rows still loading", async () => {
    vi.spyOn(marketData, "useLiveQuotes").mockReturnValue({
      AAPL: makeView({
        symbol: "AAPL",
        changePct: 1.2,
        loading: false,
        snapshot: { symbol: "AAPL" } as never,
      }),
      MSFT: makeView({
        symbol: "MSFT",
        changePct: null,
        loading: true,
        snapshot: null,
      }),
    });
    render(<WATCHPane code="WATCH" symbol={undefined} />);
    await screen.findByText("AAPL");
    // The median card caption should reveal in-flight progress.
    expect(screen.getByText(/computing/i)).toBeInTheDocument();
  });

  it("shows actual median once all rows settled", async () => {
    vi.spyOn(marketData, "useLiveQuotes").mockReturnValue({
      AAPL: makeView({
        symbol: "AAPL",
        changePct: 1.0,
        loading: false,
        snapshot: { symbol: "AAPL" } as never,
      }),
      MSFT: makeView({
        symbol: "MSFT",
        changePct: -2.0,
        loading: false,
        snapshot: { symbol: "MSFT" } as never,
      }),
    });
    render(<WATCHPane code="WATCH" symbol={undefined} />);
    await screen.findByText("AAPL");
    expect(screen.queryByText(/computing/i)).toBeNull();
    expect(screen.getByText(/sampled/i)).toBeInTheDocument();
  });
});
