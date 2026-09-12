/**
 * B1 (campaign 2026-09-11 double) — reactive watchlist store.
 *
 * PaneChrome's "+ watch" toggle needs (a) a synchronous membership check
 * and (b) a subscription to publishes from any surface (WATCH pane,
 * Welcome seeding, first-run). These pin the new store layer on top of
 * the existing async persistence: isWatched / ensureWatchlistLoaded /
 * subscribeWatchlist.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import {
  addSymbol,
  clearWatchlist,
  ensureWatchlistLoaded,
  isWatched,
  removeSymbol,
  resetWatchlistStoreForTests,
  subscribeWatchlist,
} from "./watchlist";

describe("watchlist reactive store", () => {
  beforeEach(async () => {
    resetWatchlistStoreForTests();
    await clearWatchlist();
    resetWatchlistStoreForTests();
  });
  afterEach(async () => {
    await clearWatchlist();
    resetWatchlistStoreForTests();
  });

  it("isWatched is false before hydration, then normalized after add", async () => {
    expect(isWatched("AAPL")).toBe(false);
    await ensureWatchlistLoaded();
    expect(isWatched("AAPL")).toBe(false);
    await addSymbol("aapl");
    expect(isWatched("aapl")).toBe(true);
    expect(isWatched("AAPL")).toBe(true);
    expect(isWatched("  aapl  ")).toBe(true);
    await removeSymbol("AAPL");
    expect(isWatched("AAPL")).toBe(false);
  });

  it("ensureWatchlistLoaded hydrates from persistent storage", async () => {
    localStorage.setItem(
      "showme.watchlist",
      JSON.stringify({ rows: [{ symbol: "NVDA" }] }),
    );
    await ensureWatchlistLoaded();
    expect(isWatched("NVDA")).toBe(true);
    // Second call reuses the hydrated snapshot (no throw, still true).
    await ensureWatchlistLoaded();
    expect(isWatched("NVDA")).toBe(true);
  });

  it("subscribe fires on every publish; unsubscribe stops delivery", async () => {
    const seen = vi.fn();
    const unsubscribe = subscribeWatchlist(seen);
    await ensureWatchlistLoaded();
    seen.mockClear();

    await addSymbol("AAPL");
    expect(seen).toHaveBeenCalled();
    expect(isWatched("AAPL")).toBe(true);

    unsubscribe();
    seen.mockClear();
    await removeSymbol("AAPL");
    expect(seen).not.toHaveBeenCalled();
    expect(isWatched("AAPL")).toBe(false);
  });
});
