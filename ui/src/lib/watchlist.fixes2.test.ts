/**
 * Bundle D / TOCTOU-01 — concurrent watchlist writes must serialize.
 *
 * Pre-fix, two parallel `addSymbol()` calls both `loadWatchlist()` against
 * the same baseline, both append independently, both `saveWatchlist()` —
 * second write wins, first symbol is lost. The module-level queue funnels
 * mutations so reads always see the latest publish.
 */
import { describe, expect, it, beforeEach, afterEach } from "vitest";
import { addSymbol, clearWatchlist, loadWatchlist, removeSymbol } from "./watchlist";

describe("watchlist concurrent writes (TOCTOU)", () => {
  beforeEach(async () => {
    await clearWatchlist();
  });
  afterEach(async () => {
    await clearWatchlist();
  });

  it("two concurrent addSymbol() calls both persist", async () => {
    const [a, b] = await Promise.all([
      addSymbol("AAPL"),
      addSymbol("MSFT"),
    ]);
    // Each return value is the row set *as of that write*, so the second
    // resolves with both rows; the first resolves with one.
    expect(a.map((r) => r.symbol)).toContain("AAPL");
    expect(b.map((r) => r.symbol).sort()).toEqual(["AAPL", "MSFT"]);
    const rows = await loadWatchlist();
    expect(rows.map((r) => r.symbol).sort()).toEqual(["AAPL", "MSFT"]);
  });

  it("five concurrent adds all land", async () => {
    const symbols = ["AAPL", "MSFT", "TSLA", "NVDA", "AMZN"];
    await Promise.all(symbols.map((s) => addSymbol(s)));
    const rows = await loadWatchlist();
    expect(rows.map((r) => r.symbol).sort()).toEqual([...symbols].sort());
  });

  it("interleaved add+remove preserves total ordering", async () => {
    await Promise.all([
      addSymbol("AAPL"),
      addSymbol("MSFT"),
      addSymbol("TSLA"),
      removeSymbol("MSFT"),
    ]);
    const rows = await loadWatchlist();
    const symbols = rows.map((r) => r.symbol).sort();
    expect(symbols).toEqual(["AAPL", "TSLA"]);
  });

  it("dedup still works under concurrent writes", async () => {
    await Promise.all([
      addSymbol("AAPL"),
      addSymbol("AAPL"),
      addSymbol("aapl"),
    ]);
    const rows = await loadWatchlist();
    expect(rows.filter((r) => r.symbol === "AAPL")).toHaveLength(1);
  });
});
