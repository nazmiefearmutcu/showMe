/**
 * UA-CRITICAL-06 — Welcome.tsx liveQuoteSymbols cascade.
 *
 * `positions` identity rotates on every snapshot poll (~5s). The previous
 * `useMemo([positions, savedWatchSymbols])` returned a NEW array on every
 * one of those polls, which invalidated the `useLiveQuotes(...)` argument,
 * which tore down + reopened every WS channel — a reconnect storm.
 *
 * The fix derives a stable string key (sorted unique symbols joined), then
 * memoizes the actual array on that key alone. This test pins the contract.
 */
import { describe, expect, it } from "vitest";

// Mirror of the derivation logic in Welcome.tsx so we can unit-test the
// stability invariant without mounting the entire shell.
function deriveLiveQuoteKey(
  positions: Array<{ symbol: string }>,
  savedWatchSymbols: string[],
  marketStrip: string[],
): string {
  const baseSymbols = positions.length
    ? positions.slice(0, 12).map((p) => p.symbol).filter(Boolean)
    : savedWatchSymbols;
  const merged = [...baseSymbols, ...marketStrip];
  return Array.from(new Set(merged)).sort().join(",");
}

function deriveLiveQuoteSymbols(key: string): string[] {
  return key ? key.split(",") : [];
}

const MARKET_STRIP = ["SPY", "QQQ", "BTC-USD"];

describe("UA-CRITICAL-06: Welcome liveQuoteSymbols stability", () => {
  it("key is identical when positions identity changes but symbols don't", () => {
    const pos1 = [{ symbol: "AAPL" }, { symbol: "MSFT" }];
    const pos2 = [{ symbol: "AAPL" }, { symbol: "MSFT" }]; // new identity
    expect(pos1).not.toBe(pos2);
    expect(deriveLiveQuoteKey(pos1, [], MARKET_STRIP)).toBe(
      deriveLiveQuoteKey(pos2, [], MARKET_STRIP),
    );
  });

  it("key changes when an actual symbol is added or removed", () => {
    const pos1 = [{ symbol: "AAPL" }, { symbol: "MSFT" }];
    const pos2 = [{ symbol: "AAPL" }, { symbol: "MSFT" }, { symbol: "GOOG" }];
    expect(deriveLiveQuoteKey(pos1, [], MARKET_STRIP)).not.toBe(
      deriveLiveQuoteKey(pos2, [], MARKET_STRIP),
    );
  });

  it("key is order-independent (sorts before joining)", () => {
    const pos1 = [{ symbol: "MSFT" }, { symbol: "AAPL" }];
    const pos2 = [{ symbol: "AAPL" }, { symbol: "MSFT" }];
    expect(deriveLiveQuoteKey(pos1, [], MARKET_STRIP)).toBe(
      deriveLiveQuoteKey(pos2, [], MARKET_STRIP),
    );
  });

  it("falls back to saved watchlist when no positions exist", () => {
    const k = deriveLiveQuoteKey([], ["TSLA", "NVDA"], MARKET_STRIP);
    expect(k).toContain("TSLA");
    expect(k).toContain("NVDA");
  });

  it("dedupes when a portfolio symbol also appears in the market strip", () => {
    const k = deriveLiveQuoteKey([{ symbol: "SPY" }], [], MARKET_STRIP);
    expect(k.split(",").filter((s) => s === "SPY")).toHaveLength(1);
  });

  it("deriveLiveQuoteSymbols returns empty array for empty key", () => {
    expect(deriveLiveQuoteSymbols("")).toEqual([]);
  });

  it("deriveLiveQuoteSymbols splits the joined key back into the symbol list", () => {
    expect(deriveLiveQuoteSymbols("AAPL,MSFT,SPY")).toEqual(["AAPL", "MSFT", "SPY"]);
  });
});
