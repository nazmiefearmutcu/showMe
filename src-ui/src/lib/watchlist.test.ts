import { afterEach, beforeEach, describe, expect, it } from "vitest";
import {
  addSymbol,
  clearWatchlist,
  loadWatchlist,
  removeSymbol,
  saveWatchlist,
} from "./watchlist";

describe("watchlist (browser-mode)", () => {
  beforeEach(() => clearWatchlist());
  afterEach(() => clearWatchlist());

  it("starts empty", async () => {
    expect(await loadWatchlist()).toEqual([]);
  });

  it("addSymbol uppercases and dedupes", async () => {
    await addSymbol("aapl");
    await addSymbol("AAPL");
    const rows = await loadWatchlist();
    expect(rows).toHaveLength(1);
    expect(rows[0].symbol).toBe("AAPL");
  });

  it("removeSymbol drops by symbol", async () => {
    await addSymbol("AAPL");
    await addSymbol("MSFT");
    const rows = await removeSymbol("AAPL");
    expect(rows.map((r) => r.symbol)).toEqual(["MSFT"]);
  });

  it("saveWatchlist replaces the bundle wholesale", async () => {
    await addSymbol("X");
    await saveWatchlist([{ symbol: "Y" }, { symbol: "Z" }]);
    const rows = await loadWatchlist();
    expect(rows.map((r) => r.symbol)).toEqual(["Y", "Z"]);
  });

  it("ignores blank input", async () => {
    await addSymbol("   ");
    expect(await loadWatchlist()).toEqual([]);
  });
});
