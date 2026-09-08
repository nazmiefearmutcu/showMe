/**
 * Lane D — U9 first-run desk setup: flag contract + pristine-tree check +
 * starter-watchlist seeding through the real (localStorage-backed)
 * watchlist queue.
 */
import { afterEach, beforeEach, describe, expect, it } from "vitest";
import {
  FIRST_RUN_DONE_KEY,
  STARTER_WATCHLIST_SYMBOLS,
  isFirstRunDone,
  isPristineHomeWorkspace,
  markFirstRunDone,
  seedStarterWatchlist,
} from "./first-run";
import { leaf, split } from "./workspace";
import { loadWatchlist } from "./watchlist";

beforeEach(() => {
  localStorage.clear();
});

afterEach(() => {
  localStorage.clear();
});

describe("first-run flag", () => {
  it("is unanswered on a clean store", () => {
    expect(isFirstRunDone()).toBe(false);
  });

  it("records the answer and never un-answers", () => {
    markFirstRunDone();
    expect(isFirstRunDone()).toBe(true);
    markFirstRunDone();
    expect(isFirstRunDone()).toBe(true);
    expect(localStorage.getItem(FIRST_RUN_DONE_KEY)).toBe("1");
  });
});

describe("isPristineHomeWorkspace", () => {
  it("matches only the untouched single-HOME default", () => {
    expect(isPristineHomeWorkspace(leaf("HOME"))).toBe(true);
  });

  it("rejects split trees and non-HOME single leaves", () => {
    expect(isPristineHomeWorkspace(split("h", [leaf("HOME"), leaf("GP")]))).toBe(false);
    expect(isPristineHomeWorkspace(leaf("DES", "AAPL"))).toBe(false);
  });
});

describe("seedStarterWatchlist", () => {
  it("seeds every starter symbol once and is idempotent", async () => {
    const rows = await seedStarterWatchlist();
    expect(rows.map((r) => r.symbol)).toEqual([...STARTER_WATCHLIST_SYMBOLS]);

    // Second run (e.g. user re-triggers before flag lands) must not duplicate.
    await seedStarterWatchlist();
    const stored = await loadWatchlist();
    expect(stored).toHaveLength(STARTER_WATCHLIST_SYMBOLS.length);
    const symbols = new Set(stored.map((r) => r.symbol));
    expect(symbols.size).toBe(STARTER_WATCHLIST_SYMBOLS.length);
  });

  it("keeps user rows that already existed", async () => {
    localStorage.setItem(
      "showme.watchlist",
      JSON.stringify({ rows: [{ symbol: "TSLA" }] }),
    );
    await seedStarterWatchlist();
    const stored = await loadWatchlist();
    expect(stored.some((r) => r.symbol === "TSLA")).toBe(true);
    expect(stored).toHaveLength(STARTER_WATCHLIST_SYMBOLS.length + 1);
  });
});
