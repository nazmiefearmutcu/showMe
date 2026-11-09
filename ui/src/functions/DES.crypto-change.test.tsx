/**
 * ASOF-9 follow-up: the backend publishes crypto's 24h change as change_24h
 * (price minus the 24h-ago price) and sets previousClose to null, because a
 * crypto asset has no prior session close. The quote header must still render
 * the absolute change from that declared 24h figure.
 */
import { cleanup, render } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { DESPane } from "./DES";

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

const BTC_24H = {
  symbol: "BTC",
  name: "Bitcoin",
  longName: "Bitcoin",
  asset_class: "CRYPTO",
  exchange: "CRYPTO",
  currency: "USD",
  regularMarketPrice: 75000,
  currentPrice: 75000,
  previousClose: null,
  price_24h_ago: 76500,
  change_24h: -1500,
  change_basis: "24h_rolling",
  regularMarketChangePercent: -1.9607843137254901,
  source: "coingecko",
};

function payload(profile: Record<string, unknown>) {
  return {
    state: "ok",
    data: {
      status: "ok",
      data: { status: "ok", ...profile },
      sources: ["coingecko"],
      elapsed_ms: 12,
    },
    error: null,
    refetch: vi.fn(),
  };
}

beforeEach(() => {
  useFunctionMock.mockReturnValue(payload(BTC_24H));
});
afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

describe("DES crypto absolute change", () => {
  it("renders the absolute 24h change from change_24h when previousClose is null", () => {
    const { container } = render(<DESPane code="DES" symbol="BTC" />);
    const change = container.querySelector('[data-testid="des-change-abs"]');
    expect(change).not.toBeNull();
    expect(change?.textContent).toContain("−");
    expect(change?.textContent).toContain("1,500");
  });

  it("does not invent an absolute change when neither previousClose nor change_24h is declared", () => {
    useFunctionMock.mockReturnValue(
      payload({ ...BTC_24H, change_24h: null, price_24h_ago: null }),
    );
    const { container } = render(<DESPane code="DES" symbol="BTC" />);
    expect(container.querySelector('[data-testid="des-change-abs"]')).toBeNull();
  });
});
