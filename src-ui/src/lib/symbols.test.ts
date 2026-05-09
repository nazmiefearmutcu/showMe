import { beforeEach, describe, expect, it } from "vitest";
import {
  assetClassForFunctionSymbol,
  clearRecentSymbols,
  defaultSymbolForFunction,
  inferAssetClassName,
  listRecentSymbols,
  normalizeSymbolInput,
  pushRecentSymbol,
  quickSymbolsForFunction,
  removeRecentSymbol,
} from "./symbols";

beforeEach(() => clearRecentSymbols());

describe("recent symbols", () => {
  it("starts empty", () => {
    expect(listRecentSymbols()).toEqual([]);
  });

  it("uppercases + dedupes + most-recent first", () => {
    pushRecentSymbol("aapl");
    pushRecentSymbol("MSFT");
    pushRecentSymbol("AAPL"); // duplicate (case-insensitive)
    expect(listRecentSymbols()).toEqual(["AAPL", "MSFT"]);
  });

  it("normalizes the common APPL typo to AAPL", () => {
    pushRecentSymbol("APPL");
    expect(listRecentSymbols()).toEqual(["AAPL"]);
  });

  it("normalizes crypto coin names to Binance-style pairs", () => {
    expect(normalizeSymbolInput("ethereum")).toBe("ETHUSDT");
    expect(normalizeSymbolInput("Pepe")).toBe("PEPEUSDT");
    expect(normalizeSymbolInput("flock")).toBe("FLOCKUSDT");
    expect(inferAssetClassName("dogwifhat")).toBe("CRYPTO");
  });

  it("dedupes legacy stored variants while preserving recency order", () => {
    localStorage.setItem(
      "showme.recent-symbols",
      JSON.stringify([
        { sym: "aapl", ts: 3 },
        { sym: "APPL", ts: 2 },
        { sym: "BTCUSDT", ts: 1 },
        { sym: "AAPL", ts: 0 },
      ]),
    );
    expect(listRecentSymbols()).toEqual(["AAPL", "BTCUSDT"]);
    pushRecentSymbol("APPL");
    expect(listRecentSymbols()).toEqual(["AAPL", "BTCUSDT"]);
  });

  it("caps at 12 entries", () => {
    for (let i = 0; i < 20; i++) pushRecentSymbol(`SYM${i}`);
    expect(listRecentSymbols()).toHaveLength(12);
    expect(listRecentSymbols()[0]).toBe("SYM19");
  });

  it("ignores empty input", () => {
    pushRecentSymbol("   ");
    expect(listRecentSymbols()).toEqual([]);
  });

  it("removes one recent symbol without touching the rest", () => {
    pushRecentSymbol("BTCUSDT");
    pushRecentSymbol("ETHUSDT");
    pushRecentSymbol("SOLUSDT");
    removeRecentSymbol("ethusdt");
    expect(listRecentSymbols()).toEqual(["SOLUSDT", "BTCUSDT"]);
  });

  it("infers broad asset classes from common market symbols", () => {
    expect(inferAssetClassName("BTCUSDT")).toBe("CRYPTO");
    expect(inferAssetClassName("SUSDT")).toBe("CRYPTO");
    expect(inferAssetClassName("4USDT")).toBe("CRYPTO");
    expect(inferAssetClassName("EURUSD")).toBe("FX");
    expect(inferAssetClassName("GC=F")).toBe("COMMODITY");
    expect(inferAssetClassName("^GSPC")).toBe("INDEX");
    expect(inferAssetClassName("AAPL")).toBe("EQUITY");
  });

  it("chooses a compatible default symbol for function asset classes", () => {
    pushRecentSymbol("AAPL");
    expect(defaultSymbolForFunction("news", ["CRYPTO"])).toBe("BTCUSDT");
    expect(defaultSymbolForFunction("equity", ["EQUITY", "ETF"])).toBe("AAPL");
    expect(quickSymbolsForFunction("fx", ["FX"])).toContain("EURUSD");
  });

  it("filters incompatible recent symbols from function quick picks", () => {
    pushRecentSymbol("BTCUSDT");
    const picks = quickSymbolsForFunction("equity", ["EQUITY"]);
    expect(picks).not.toContain("BTCUSDT");
    expect(picks).toContain("AAPL");
  });

  it("does not let recent crypto leak into equity functions without asset metadata", () => {
    pushRecentSymbol("BTCUSDT");
    expect(defaultSymbolForFunction("equity", [])).toBe("AAPL");
    expect(quickSymbolsForFunction("equity", [])).not.toContain("BTCUSDT");
  });

  it("keeps market microstructure on crypto defaults even after equity recents", () => {
    pushRecentSymbol("AAPL");
    expect(defaultSymbolForFunction("MICRO", ["CRYPTO", "EQUITY"])).toBe("BTCUSDT");
    expect(quickSymbolsForFunction("MICRO", ["CRYPTO", "EQUITY"])).toEqual(
      expect.arrayContaining(["BTCUSDT", "ETHUSDT", "SOLUSDT"]),
    );
    expect(quickSymbolsForFunction("MICRO", ["CRYPTO", "EQUITY"])).not.toContain("AAPL");
  });

  it("keeps yield analytics on bond symbols even without asset metadata", () => {
    pushRecentSymbol("AAPL");
    expect(defaultSymbolForFunction("YAS", [])).toBe("US10Y");
    expect(quickSymbolsForFunction("YAS", [])).toEqual(
      expect.arrayContaining(["US10Y", "US2Y", "US30Y"]),
    );
    expect(quickSymbolsForFunction("YAS", [])).not.toContain("AAPL");
  });

  it("sends a supported asset class with symbol-first function calls", () => {
    expect(assetClassForFunctionSymbol("AAPL", ["DERIVATIVE"])).toBe("DERIVATIVE");
    expect(assetClassForFunctionSymbol("BTCUSDT", ["EQUITY", "CRYPTO"])).toBe("CRYPTO");
  });
});
