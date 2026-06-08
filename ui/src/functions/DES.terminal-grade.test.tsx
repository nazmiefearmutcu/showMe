/**
 * DES terminal-grade polish — display quality + a11y close-out.
 *
 * Pins the P1/P2 contracts added in the page-by-page pass:
 *   1. Quote-header absolute change is sign-coloured (positive/negative)
 *      and carries `terminal-grid-numeric` (monospace tabular) so the
 *      price + change don't jitter on live updates.
 *   2. The last price also carries `terminal-grid-numeric`.
 *   3. Formatter output is sourced from `@/lib/format` (compact market cap
 *      renders as e.g. "$1.8T", not a rolled-own "1.80T").
 *   4. Long business summaries clamp with a "Show more" affordance.
 *   5. External links (website / github) carry descriptive aria-labels and
 *      open in a new tab safely.
 */
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { TransportState } from "@/lib/market-data";
import { DESPane } from "./DES";

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

const useFunctionMock = vi.fn();
vi.mock("@/lib/useFunction", () => ({
  useFunction: () => useFunctionMock(),
}));

const LONG_SUMMARY = "Apple designs and sells consumer electronics. ".repeat(60);

function equityPayload(extra: Record<string, unknown> = {}) {
  return {
    state: "ok",
    data: {
      status: "ok",
      data: {
        longName: "Apple Inc.",
        shortName: "Apple",
        regularMarketPrice: 302.5,
        previousClose: 300.0,
        regularMarketChangePercent: 0.83,
        exchange_name: "NASDAQ",
        sector: "Technology",
        marketCap: 1_800_000_000_000,
        website: "https://apple.com",
        longBusinessSummary: LONG_SUMMARY,
        status: "ok",
        ...extra,
      },
      sources: ["yfinance"],
      elapsed_ms: 42,
    },
    error: null,
    refetch: vi.fn(),
  };
}

beforeEach(() => {
  mockQuoteState.transportState = "live";
  mockQuoteState.lastTick = { price: 302.5, ts: Date.now() };
  useFunctionMock.mockReturnValue(equityPayload());
});
afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

describe("DES quote header — terminal-grade numerics", () => {
  it("colours the absolute change green when positive", () => {
    const { container } = render(<DESPane code="DES" symbol="AAPL" />);
    const change = container.querySelector('[data-testid="des-change-abs"]');
    expect(change).not.toBeNull();
    expect(change?.textContent).toMatch(/\+2\.50/);
    // sign-coloured via the positive token, not a flat secondary grey.
    expect((change as HTMLElement).style.color).toContain("--positive");
  });

  it("colours the absolute change red when negative", () => {
    useFunctionMock.mockReturnValue(
      equityPayload({ regularMarketPrice: 298, previousClose: 300, regularMarketChangePercent: -0.67 }),
    );
    const { container } = render(<DESPane code="DES" symbol="AAPL" />);
    const change = container.querySelector('[data-testid="des-change-abs"]');
    expect(change?.textContent).toMatch(/-2\.00/);
    expect((change as HTMLElement).style.color).toContain("--negative");
  });

  it("gives price and change the terminal-grid-numeric class", () => {
    const { container } = render(<DESPane code="DES" symbol="AAPL" />);
    const price = container.querySelector('[data-testid="des-last-price"]');
    const change = container.querySelector('[data-testid="des-change-abs"]');
    expect(price?.className).toContain("terminal-grid-numeric");
    expect(change?.className).toContain("terminal-grid-numeric");
  });
});

describe("DES market cap — format.ts source of truth", () => {
  it("renders compact currency from formatCurrency (e.g. $1.8T)", () => {
    render(<DESPane code="DES" symbol="AAPL" />);
    // 1.8e12 → "$1.8T" via formatCurrency({compact:true}).
    expect(screen.getByText("$1.8T")).toBeTruthy();
  });
});

describe("DES business summary — readability clamp", () => {
  it("clamps a very long summary behind a Show more toggle", () => {
    const { container } = render(<DESPane code="DES" symbol="AAPL" />);
    const summary = container.querySelector('[data-testid="des-summary"]');
    expect(summary).not.toBeNull();
    // Collapsed by default → a Show more control is present.
    const toggle = screen.getByRole("button", { name: /show more/i });
    expect(toggle).toBeTruthy();
    expect((summary as HTMLElement).getAttribute("data-expanded")).toBe("false");
    fireEvent.click(toggle);
    expect((summary as HTMLElement).getAttribute("data-expanded")).toBe("true");
    expect(screen.getByRole("button", { name: /show less/i })).toBeTruthy();
  });

  it("does not show the toggle for a short summary", () => {
    useFunctionMock.mockReturnValue(equityPayload({ longBusinessSummary: "Short blurb." }));
    render(<DESPane code="DES" symbol="AAPL" />);
    expect(screen.queryByRole("button", { name: /show more/i })).toBeNull();
  });
});

describe("DES external links — a11y", () => {
  it("gives the website link a descriptive aria-label and safe target", () => {
    const { container } = render(<DESPane code="DES" symbol="AAPL" />);
    const link = container.querySelector('a[href="https://apple.com"]');
    expect(link).not.toBeNull();
    expect(link?.getAttribute("aria-label")).toMatch(/website.*new tab/i);
    expect(link?.getAttribute("target")).toBe("_blank");
    expect(link?.getAttribute("rel")).toMatch(/noopener/);
  });

  it("gives the github repo link a descriptive aria-label", () => {
    useFunctionMock.mockReturnValue(
      equityPayload({
        asset_class: "CRYPTO",
        github_repo: "https://github.com/bitcoin/bitcoin",
        symbol: "BTC",
        longName: "Bitcoin",
      }),
    );
    const { container } = render(<DESPane code="DES" symbol="BTC" />);
    const repo = container.querySelector('a[href="https://github.com/bitcoin/bitcoin"]');
    expect(repo).not.toBeNull();
    expect(repo?.getAttribute("aria-label")).toMatch(/github.*new tab/i);
  });
});
