/**
 * Welcome dashboard — live data wiring + grid semantics.
 *
 * Covers the eight QA-report fixes:
 *   1. KPI strip uses live quotes where available + per-tile DEMO badges.
 *   2. Watchlist uses saved symbols / portfolio; empty state has a CTA.
 *   3. Movers wires to MOST when registered; per-row DEMO when not.
 *   4. BRIEF demo banner elevated (warn tone, top of card).
 *   5. No synthetic `makeTrend()` sparkline — empty rows show placeholder.
 *   6. bid/ask come from live quote, never fabricated.
 *   7. Sentiment error path renders Retry button instead of forever-Loading.
 *   8. Watchlist uses `role="grid"` + `role="rowgroup"` + `role="gridcell"`.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { act, cleanup, fireEvent, render, waitFor } from "@testing-library/react";
import {
  Welcome,
  buildMarketTiles,
  buildMovers,
  buildPortfolioWatchRows,
  buildSavedWatchRows,
} from "./Welcome";
import { useAppStore } from "@/lib/store";
import { useSentimentStore } from "@/lib/sentiment-store";

// Default-no-op useFunction prevents jsdom from chasing the sidecar.
vi.mock("@/lib/useFunction", () => ({
  useFunction: () => ({ state: "idle", data: null, error: null, refetch: () => {} }),
}));

// Default-empty market-data stub. Individual tests override the mock to
// inject live quotes via `vi.doMock` + `vi.resetModules`.
vi.mock("@/lib/market-data", () => ({
  useLiveQuotes: () => ({}),
}));

// In jsdom watchlist load resolves immediately to whatever localStorage holds.
vi.mock("@/lib/watchlist", async () => {
  const actual = await vi.importActual<typeof import("@/lib/watchlist")>(
    "@/lib/watchlist",
  );
  return actual;
});

beforeEach(() => {
  localStorage.clear();
  useAppStore.setState({
    sidecarStatus: "booting",
    sidecarPort: null,
    engineRoot: null,
    functionIndex: [],
  });
  useSentimentStore.setState({
    score: 0,
    label: "Neutral",
    mentions: 0,
    loading: false,
    error: null,
    lastUpdated: null,
    _inflight: null,
  });
});

afterEach(() => {
  cleanup();
});

describe("Welcome KPI strip — live quotes + per-tile DEMO", () => {
  it("renders DEMO badge on every tile when no live data is wired", async () => {
    const { findByTestId, queryByTestId } = render(<Welcome />);
    await findByTestId("kpi-tile-BTC");
    // BTC has a quoteSymbol but no mocked data → still demo.
    expect(queryByTestId("kpi-tile-BTC-demo")).not.toBeNull();
    expect(queryByTestId("kpi-tile-SPX-demo")).not.toBeNull();
    expect(queryByTestId("kpi-tile-EURUSD-demo")).not.toBeNull();
  });

  it("kpi-tile data-demo='0' once a live quote replaces a seed", () => {
    const seed = [
      {
        symbol: "BTC",
        quoteSymbol: "BTC/USDT",
        label: "Bitcoin",
        value: "—",
        change: 0,
        detail: "crypto",
        demo: true,
      },
      {
        symbol: "GOLD",
        label: "Gold",
        value: "—",
        change: 0,
        detail: "metal",
        demo: true,
      },
    ];
    const overlaid = buildMarketTiles(seed, {
      "BTC/USDT": {
        symbol: "BTC/USDT",
        price: 78421,
        changePct: 1.42,
      } as any,
    });
    expect(overlaid[0]!.demo).toBe(false);
    expect(overlaid[0]!.value).toBe("78421.00");
    expect(overlaid[0]!.change).toBe(1.42);
    // No quote = stays demo.
    expect(overlaid[1]!.demo).toBe(true);
  });
});

describe("Welcome watchlist — empty state + CTA", () => {
  it("renders the empty-state CTA when no saved symbols and no portfolio", async () => {
    const { findByTestId } = render(<Welcome />);
    const cta = await findByTestId("watchlist-empty-cta");
    expect(cta.textContent).toMatch(/add symbols/i);
    // No fake DOGE / AAPL rows.
    expect(document.querySelector(".terminal-watchlist__row")).toBeNull();
  });

  it("buildPortfolioWatchRows uses live bid/ask/last and computes notional", () => {
    const rows = buildPortfolioWatchRows(
      [
        {
          symbol: "AAPL",
          asset_class: "EQUITY",
          market_value: 30000,
          unrealized_pnl: 1500,
          weight_pct: 12.5,
        },
      ],
      {
        AAPL: {
          symbol: "AAPL",
          price: 308.82,
          changePct: 1.42,
          lastTick: { bid: 308.8, ask: 308.84 } as any,
          snapshot: null,
        } as any,
      },
    );
    expect(rows).toHaveLength(1);
    const row = rows[0]!;
    // Bid/ask come from the live tick, NOT market_value.
    expect(row.bid).toBe("308.80");
    expect(row.ask).toBe("308.84");
    expect(row.last).toBe("308.82");
    // 1D notional = (1.42 / 100) * 308.82 ≈ 4.39, sign-correct.
    expect(row.notional).toMatch(/^\+\$4(\.|$)/);
    // Trend is empty so the UI shows the dashed placeholder.
    expect(row.trend).toEqual([]);
  });

  it("buildSavedWatchRows: no live quote → all live fields render as '—', notional too", () => {
    const rows = buildSavedWatchRows(
      [{ symbol: "TSLA" }, { symbol: "MSFT", label: "Microsoft" }],
      {},
    );
    expect(rows[0]!.symbol).toBe("TSLA");
    expect(rows[0]!.bid).toBe("—");
    expect(rows[0]!.ask).toBe("—");
    expect(rows[0]!.last).toBe("—");
    expect(rows[0]!.notional).toBe("—");
    expect(rows[1]!.name).toBe("Microsoft");
  });

  it("buildSavedWatchRows surfaces live bid/ask and a sign-correct notional", () => {
    const rows = buildSavedWatchRows(
      [{ symbol: "NVDA" }],
      {
        NVDA: {
          symbol: "NVDA",
          price: 1100,
          changePct: -1.5,
          lastTick: { bid: 1099.95, ask: 1100.05 } as any,
          snapshot: { volume: 3500000, asset_class: "EQUITY" } as any,
        } as any,
      },
    );
    expect(rows[0]!.bid).toBe("1099.95");
    expect(rows[0]!.ask).toBe("1100.05");
    expect(rows[0]!.last).toBe("1100.00");
    // (-1.5/100) * 1100 = -16.5, rounded by money() to -$17 (no fractional digits).
    expect(rows[0]!.notional).toMatch(/^-\$1[67]$/);
    // Volume compacted, not raw 3500000.
    expect(rows[0]!.volume).toBe("3.50M");
    expect(rows[0]!.sector).toBe("EQUITY");
  });
});

describe("Welcome movers — buildMovers contract", () => {
  it("returns [] when payload is missing / malformed", () => {
    expect(buildMovers(undefined)).toEqual([]);
    expect(buildMovers(null)).toEqual([]);
    expect(buildMovers({})).toEqual([]);
    expect(buildMovers({ rows: undefined })).toEqual([]);
  });

  it("filters out rows missing symbol / price / change", () => {
    const out = buildMovers({
      rows: [
        { symbol: "AAA", last: 10, change_pct: 1.2 },
        { symbol: "BBB", last: null as any, change_pct: 0.5 },
        { symbol: "", last: 5, change_pct: -1 },
        { symbol: "CCC", last: 50 },
        { symbol: "DDD", last: 50, change_pct: NaN },
      ],
    });
    expect(out).toEqual([
      { symbol: "AAA", price: "10.00", change: 1.2 },
    ]);
  });

  it("returns up to 4 gainers + 4 losers sorted by magnitude", () => {
    const rows = Array.from({ length: 12 }, (_, i) => ({
      symbol: `S${i}`,
      last: 100,
      change_pct: i - 6, // -6..5
    }));
    const out = buildMovers({ rows });
    // First four are gainers descending (5,4,3,2). Negatives follow.
    expect(out.slice(0, 4).map((r) => r.change)).toEqual([5, 4, 3, 2]);
    // Losers ascending (most negative first).
    const losers = out.filter((r) => r.change < 0).map((r) => r.change);
    expect(losers).toEqual([-6, -5, -4, -3]);
  });
});

describe("Welcome movers — DOM", () => {
  it("renders 'Demo data' badge plus per-row DEMO pill when MOST is not registered", async () => {
    const { findByTestId } = render(<Welcome />);
    const banner = await findByTestId("movers-demo-banner");
    expect(banner.textContent).toMatch(/Demo data/i);
    // At least one demo pill should be visible (depends on top-4 split).
    const anyDemoPill = document.querySelector(
      "[data-testid^='mover-demo-']",
    );
    expect(anyDemoPill).not.toBeNull();
  });
});

describe("Welcome BRIEF panel — elevated demo banner", () => {
  it("brief-demo-banner is now a status block with the Demo Data pill and prominent copy", async () => {
    const { findByTestId } = render(<Welcome />);
    const banner = await findByTestId("brief-demo-banner");
    expect(banner.getAttribute("role")).toBe("status");
    expect(banner.textContent).toMatch(/Demo data/i);
    expect(banner.textContent).toMatch(/not yet wired|illustrative/i);
  });
});

describe("Welcome sentiment — error path renders Retry", () => {
  it("error+no-lastUpdated state shows the Retry button (no infinite Loading…)", async () => {
    useSentimentStore.setState({
      loading: false,
      error: "503 Service Unavailable",
      lastUpdated: null,
    });
    const { findByTestId } = render(<Welcome />);
    const retry = await findByTestId("sentiment-retry");
    expect(retry.textContent).toMatch(/retry/i);
    expect((await findByTestId("sentiment-label")).textContent).toMatch(
      /unavailable/i,
    );
    expect((await findByTestId("sentiment-gauge")).getAttribute("aria-label"))
      .toBe("Sentiment unavailable");
  });

  it("Retry button calls refreshSentiment with the symbol list", async () => {
    const refreshSpy = vi.fn();
    useSentimentStore.setState({
      loading: false,
      error: "timeout",
      lastUpdated: null,
      refresh: refreshSpy,
    });
    const { findByTestId } = render(<Welcome />);
    const retry = await findByTestId("sentiment-retry");
    act(() => {
      fireEvent.click(retry);
    });
    expect(refreshSpy).toHaveBeenCalled();
    const calledSymbols = refreshSpy.mock.calls[0]![0] as string[];
    expect(Array.isArray(calledSymbols)).toBe(true);
    expect(calledSymbols.length).toBeGreaterThan(0);
  });

  it("sentiment timeout: after SENTIMENT_LOAD_TIMEOUT_MS of loading without lastUpdated, store flips to error", async () => {
    vi.useFakeTimers();
    try {
      useAppStore.setState({ sidecarStatus: "healthy" });
      useSentimentStore.setState({
        loading: true,
        error: null,
        lastUpdated: null,
        refresh: vi.fn(),
      });
      const { unmount } = render(<Welcome />);
      // Run past the 30-second watchdog.
      act(() => {
        vi.advanceTimersByTime(35_000);
      });
      const snap = useSentimentStore.getState();
      expect(snap.loading).toBe(false);
      expect(snap.error).toMatch(/timeout|unavailable/i);
      unmount();
    } finally {
      vi.useRealTimers();
    }
  });
});

describe("Welcome watchlist — ARIA grid semantics", () => {
  it("portfolio path renders role='grid' wrapper with row/columnheader/rowgroup children", async () => {
    // Inject a portfolio via the PORT mock — easier: install a saved symbol so
    // we render the live-row layout, then assert ARIA roles.
    localStorage.setItem(
      "showme.watchlist",
      JSON.stringify({ rows: [{ symbol: "AAPL" }] }),
    );
    const { container, queryByTestId } = render(<Welcome />);
    await waitFor(() => {
      expect(container.querySelector("[role='grid']")).not.toBeNull();
    });
    // No empty-state CTA when symbols exist.
    expect(queryByTestId("watchlist-empty-cta")).toBeNull();
    // Two rowgroups (header + body) — standard ARIA pattern.
    expect(container.querySelectorAll("[role='rowgroup']").length).toBe(2);
    // columnheaders, no orphan role="row" without grid parent.
    const grid = container.querySelector("[role='grid']")!;
    expect(grid.getAttribute("aria-rowcount")).toBe("2");
    expect(grid.querySelectorAll("[role='columnheader']").length).toBe(9);
    // gridcell instead of cell now.
    expect(grid.querySelectorAll("[role='gridcell']").length).toBeGreaterThan(0);
    expect(grid.querySelectorAll("[role='cell']").length).toBe(0);
  });

  it("the Mkt Cap column is replaced by '1D Notional'", async () => {
    localStorage.setItem(
      "showme.watchlist",
      JSON.stringify({ rows: [{ symbol: "AAPL" }] }),
    );
    const { container } = render(<Welcome />);
    await waitFor(() => {
      expect(container.querySelector("[role='grid']")).not.toBeNull();
    });
    const headers = Array.from(
      container.querySelectorAll("[role='columnheader']"),
    ).map((n) => n.textContent);
    expect(headers).toContain("1D Notional");
    // The old misleading "Mkt cap" column is gone.
    expect(headers).not.toContain("Mkt cap");
  });
});

describe("Welcome sparkline — no synthetic trend", () => {
  it("WatchRow with empty trend renders the dashed placeholder with aria-label", async () => {
    localStorage.setItem(
      "showme.watchlist",
      JSON.stringify({ rows: [{ symbol: "AAPL" }] }),
    );
    const { findByTestId } = render(<Welcome />);
    const placeholder = await findByTestId("spark-empty-AAPL");
    expect(placeholder.getAttribute("aria-label")).toBe("Trend data unavailable");
  });
});
