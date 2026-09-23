/**
 * DES missing-data density — owner report (2026-09-17): "boş gözükmek yerine
 * ya veri girilsin ya da silinsin" — the pane rendered a seven-cell
 * fundamentals strip and a snapshot card full of "—" placeholders plus a
 * dead-end "Provider did not return a business summary." card.
 *
 * Contract pinned here:
 *  1. metric cells with no provider value are NOT rendered (all-missing ->
 *     the strip disappears entirely);
 *  2. snapshot rows with no value are dropped;
 *  3. the business-summary card is omitted when there is no summary (or
 *     website/repo/categories content) — no dead-end note;
 *  4. payloads that DO carry values are untouched (no over-hiding), and the
 *     crypto "∞" max-supply sentinel survives (it means "unlimited", not
 *     "missing").
 */
import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { DESPane } from "./DES";

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
    useLiveQuotes: () => ({ snapshots: {}, ticks: {} }),
  };
});

const useFunctionMock = vi.fn();
vi.mock("@/lib/useFunction", () => ({
  useFunction: () => useFunctionMock(),
}));

function payload(profile: Record<string, unknown>) {
  return {
    state: "ok",
    data: {
      status: "ok",
      data: { status: "ok", ...profile },
      sources: ["yfinance"],
      elapsed_ms: 23,
    },
    error: null,
    refetch: vi.fn(),
  };
}

/** Sparse instrument (the owner's XAU/YHD run): 52w + exchange/IPO only. */
const SPARSE_EQUITY = {
  symbol: "XAU",
  longName: "XAU",
  exchange_name: "YHD",
  ipoDate: "2013-02-26",
  fiftyTwoWeekHigh: 1.68,
  fiftyTwoWeekLow: 1.64,
};

const FULL_EQUITY = {
  symbol: "AAPL",
  longName: "Apple Inc.",
  sector: "Technology",
  industry: "Consumer Electronics",
  country: "United States",
  city: "Cupertino",
  fullTimeEmployees: 164000,
  marketCap: 1_800_000_000_000,
  trailingPE: 28.5,
  forwardPE: 26.1,
  beta: 1.24,
  dividendYield: 0.0044,
  fiftyTwoWeekHigh: 320.1,
  fiftyTwoWeekLow: 164.08,
  exchange_name: "NASDAQ",
  currency: "USD",
  ipoDate: "1980-12-12",
  longBusinessSummary: "Apple designs and sells consumer electronics.",
};

const SPARSE_CRYPTO = {
  symbol: "BTC",
  longName: "Bitcoin",
  asset_class: "CRYPTO",
  marketCap: 1_200_000_000_000,
  regularMarketPrice: 64000,
  circulating_supply: 19_700_000,
  total_supply: 19_700_000,
  max_supply: null,
  categories: ["Layer 1"],
};

beforeEach(() => {
  useFunctionMock.mockReturnValue(payload(SPARSE_EQUITY));
});
afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

describe("DES missing-data density — empty cells are removed", () => {
  it("drops metric cells and snapshot rows the provider left empty", () => {
    render(<DESPane code="DES" symbol="XAU" />);
    // Kept: values that exist.
    expect(screen.getAllByText("52w high").length).toBeGreaterThanOrEqual(1);
    expect(screen.getAllByText("52w low").length).toBeGreaterThanOrEqual(1);
    expect(screen.getByText("IPO")).toBeInTheDocument();
    // Removed: empty placeholder cells/rows.
    for (const label of [
      "Market cap",
      "P/E (TTM)",
      "Forward P/E",
      "Beta",
      "Dividend yield",
      "Sector",
      "Industry",
      "HQ",
      "Employees",
      "Currency",
    ]) {
      expect(screen.queryByText(label)).toBeNull();
    }
  });

  it("omits the business-summary card instead of the dead-end note", () => {
    render(<DESPane code="DES" symbol="XAU" />);
    expect(screen.queryByText(/Business summary/i)).toBeNull();
    expect(screen.queryByText(/Provider did not return/i)).toBeNull();
    // No em-dash placeholder rows anywhere in the pane body.
    expect(screen.queryByText("—")).toBeNull();
  });

  it("keeps every cell when the payload carries the values (no over-hiding)", () => {
    useFunctionMock.mockReturnValue(payload(FULL_EQUITY));
    render(<DESPane code="DES" symbol="AAPL" />);
    for (const label of [
      "Market cap",
      "P/E (TTM)",
      "Forward P/E",
      "Beta",
      "Dividend yield",
      "Sector",
      "Industry",
      "HQ",
      "Employees",
      "Currency",
      "IPO",
    ]) {
      expect(screen.getByText(label)).toBeInTheDocument();
    }
    expect(screen.getByText(/Business summary/i)).toBeInTheDocument();
  });

  it("crypto: keeps the ∞ max-supply sentinel while dropping empty terms", () => {
    useFunctionMock.mockReturnValue(payload(SPARSE_CRYPTO));
    render(<DESPane code="DES" symbol="BTC" />);
    // "∞" appears twice by design (metric strip + snapshot term).
    expect(screen.getAllByText("∞").length).toBeGreaterThanOrEqual(1);
    expect(screen.queryByText("Algorithm")).toBeNull();
    expect(screen.queryByText("Block time")).toBeNull();
    expect(screen.queryByText(/CoinGecko did not return/i)).toBeNull();
  });
});
