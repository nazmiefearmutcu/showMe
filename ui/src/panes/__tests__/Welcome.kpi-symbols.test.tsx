/**
 * QA-2026-05-24 fixes — Welcome KPI strip canonical quote symbols + NYSE
 * eyebrow session helper. Locks in five regressions:
 *
 *   - BTC tile must NOT use `BTC/USDT` (slash; `/api/quote/{sym}` regex
 *     `^[A-Za-z0-9._:=\-^]+$` rejects '/' and the route 404s).
 *   - Every advertised KPI tile must carry a backend-routable `quoteSymbol`
 *     so the DEMO chip can flip off once a live snapshot arrives. Prior
 *     to this fix, SPX/NDX/US10Y/DXY/VIX/WTI/XAU were declared without a
 *     `quoteSymbol` and would render `DEMO` forever.
 *   - The eyebrow MUST source its session label from the canonical NYSE
 *     state machine in `lib/market-state.ts`, not the heuristic UTC-hour
 *     rule that lit `OPEN` on Saturday.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, render } from "@testing-library/react";
import { Welcome } from "../Welcome";
import { useAppStore } from "@/lib/store";
import { useSentimentStore } from "@/lib/sentiment-store";

vi.mock("@/lib/useFunction", () => ({
  useFunction: () => ({ state: "idle", data: null, error: null, refetch: () => {} }),
}));

vi.mock("@/lib/market-data", () => ({
  useLiveQuotes: () => ({}),
}));

const ALLOWED_QUOTE_SYMBOL = /^[A-Za-z0-9._:=\-^]+$/;

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

describe("Welcome KPI strip — canonical quote symbols", () => {
  it("BTC tile uses BTCUSDT (no slash) so /api/quote/BTCUSDT does not 404", async () => {
    const { MARKET_STRIP_SEED } = await import("../Welcome");
    const btc = MARKET_STRIP_SEED.find((t) => t.symbol === "BTC");
    expect(btc, "BTC tile present in seed").toBeTruthy();
    expect(btc!.quoteSymbol).toBe("BTCUSDT");
    expect(btc!.quoteSymbol!).not.toContain("/");
    expect(btc!.quoteSymbol!).toMatch(ALLOWED_QUOTE_SYMBOL);
  });

  it("BTC quoteSymbol wires through buildMarketTiles overlay (flips DEMO off)", async () => {
    const { buildMarketTiles } = await import("../Welcome");
    const sample = [
      {
        symbol: "BTC",
        quoteSymbol: "BTCUSDT",
        label: "Bitcoin",
        value: "—",
        change: 0,
        detail: "crypto",
        demo: true,
      },
    ];
    const overlaid = buildMarketTiles(sample, {
      BTCUSDT: { symbol: "BTCUSDT", price: 78421, changePct: 1.42 } as never,
    });
    expect(overlaid[0]!.demo).toBe(false);
    expect(overlaid[0]!.value).toBe("78421.00");
    expect(overlaid[0]!.change).toBe(1.42);
  });

  it("every default KPI tile has a backend-routable quoteSymbol", async () => {
    const { MARKET_STRIP_SEED, buildMarketTiles } = await import("../Welcome");
    const expectedTiles: Array<[string, string]> = [
      ["SPX", "^GSPC"],
      ["NDX", "^NDX"],
      ["BTC", "BTCUSDT"],
      ["US10Y", "^TNX"],
      ["DXY", "DX-Y.NYB"],
      ["VIX", "^VIX"],
      ["WTI", "CL=F"],
      ["XAU", "GC=F"],
      ["EURUSD", "EURUSD=X"],
    ];
    for (const [sym, expectedQuote] of expectedTiles) {
      const tile = MARKET_STRIP_SEED.find((t) => t.symbol === sym);
      expect(tile, `KPI tile ${sym} present`).toBeTruthy();
      expect(tile!.quoteSymbol).toBe(expectedQuote);
      expect(tile!.quoteSymbol!).toMatch(ALLOWED_QUOTE_SYMBOL);
    }
    // And: every seed tile must be able to flip OFF its DEMO chip when a
    // live quote arrives keyed by its canonical sym (covers SPX/NDX/etc
    // which used to be permanently DEMO).
    const overlays = Object.fromEntries(
      MARKET_STRIP_SEED.filter((t) => t.quoteSymbol).map((t) => [
        (t.quoteSymbol as string).toUpperCase(),
        { symbol: t.quoteSymbol!, price: 100, changePct: 0.5 } as never,
      ]),
    );
    const overlaid = buildMarketTiles(MARKET_STRIP_SEED, overlays);
    for (const tile of overlaid) {
      expect(
        tile.demo,
        `${tile.symbol} must flip DEMO off when a live snapshot arrives`,
      ).toBe(false);
    }
  });

  it("BTC slash-form is explicitly forbidden in the seed", async () => {
    const { MARKET_STRIP_SEED } = await import("../Welcome");
    const offenders = MARKET_STRIP_SEED.filter((t) =>
      (t.quoteSymbol ?? "").includes("/"),
    );
    expect(offenders).toHaveLength(0);
  });
});

describe("Welcome eyebrow — NYSE session source", () => {
  // We assert against the synchronous first paint (no waitFor / no
  // findByText) because fake-timers stop the harness from advancing the
  // real-time-based waitFor poll, which used to hang the suite.
  afterEach(() => {
    vi.useRealTimers();
  });

  it("Saturday 14:00 UTC renders 'closed · weekend', never 'open'", () => {
    vi.useFakeTimers();
    // 2026-05-23 = Saturday.
    vi.setSystemTime(new Date("2026-05-23T14:00:00Z"));
    const { container } = render(<Welcome />);
    const eyebrow = container.querySelector(
      ".terminal-home__eyebrow",
    ) as HTMLElement | null;
    expect(eyebrow, "masthead eyebrow rendered").toBeTruthy();
    // Eyebrow upper-cases the session label; weekend state surfaces as
    // CLOSED · WEEKEND. Old heuristic emitted "OPEN" here.
    expect(eyebrow!.textContent?.toUpperCase()).toContain("CLOSED");
    expect(eyebrow!.textContent?.toUpperCase()).not.toMatch(/\/\s*OPEN(\s|$)/);
  });

  it("Christmas Day 2026 renders the canonical 'closed · holiday' label", () => {
    vi.useFakeTimers();
    vi.setSystemTime(new Date("2026-12-25T19:00:00Z"));
    const { container } = render(<Welcome />);
    const eyebrow = container.querySelector(
      ".terminal-home__eyebrow",
    ) as HTMLElement | null;
    expect(eyebrow!.textContent?.toUpperCase()).toContain("CLOSED");
    expect(eyebrow!.textContent?.toUpperCase()).toMatch(/HOLIDAY/);
    expect(eyebrow!.textContent?.toUpperCase()).not.toMatch(/\/\s*OPEN(\s|$)/);
  });

  it("Friday 09:35 ET prints 'open'", () => {
    vi.useFakeTimers();
    // 2026-05-22 = Friday; 13:35 UTC = 09:35 ET (EDT, NY DST observed).
    vi.setSystemTime(new Date("2026-05-22T13:35:00Z"));
    const { container } = render(<Welcome />);
    const eyebrow = container.querySelector(
      ".terminal-home__eyebrow",
    ) as HTMLElement | null;
    expect(eyebrow!.textContent?.toUpperCase()).toMatch(/\/\s*OPEN/);
  });
});
