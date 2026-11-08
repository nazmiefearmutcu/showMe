/**
 * LOC-7: substring search must be locale-safe for Turkish text.
 * JS toLowerCase() maps U+0130 (İ) to "i" + U+0307, so "İstanbul" never
 * contains "istanbul"; dotless ı (U+0131) never matches "i". foldSearchText
 * folds both before lowercasing and keeps the string length (highlight offsets).
 */
import { describe, expect, it } from "vitest";
import { foldSearchText } from "./search-fold";
import { useIndicatorStore } from "./indicator-store";
import { useExchangeStore } from "./exchange-store";

describe("foldSearchText", () => {
  it("matches a dotted capital İ against a plain lowercase query", () => {
    expect(foldSearchText("İstanbul").includes(foldSearchText("istanbul"))).toBe(true);
  });

  it("folds dotless ı and capital I onto the same key", () => {
    expect(foldSearchText("ılık")).toBe(foldSearchText("Ilık"));
  });

  it("keeps the string length so highlight offsets stay valid", () => {
    const text = "İzmir Ilık Borsası";
    expect(foldSearchText(text).length).toBe(text.length);
  });
});

describe("catalog search with Turkish text", () => {
  it("indicator search finds a display name that starts with İ", () => {
    useIndicatorStore.setState({
      entries: [
        { id: "tr_band", display_name: "İstanbul Bant", family: "volatility", short_description: "" },
      ] as never,
    });
    const hits = useIndicatorStore.getState().search("istanbul", undefined);
    expect(hits.map((e) => e.id)).toEqual(["tr_band"]);
  });

  it("exchange catalog filter finds an alias that starts with İ", () => {
    useExchangeStore.setState({
      catalog: [
        { id: "ist", display_name: "Borsa", aliases: ["İstanbul Borsası"], asset_classes: [], regions: [] },
      ] as never,
    });
    const hits = useExchangeStore.getState().filterCatalog({ query: "istanbul", assetClasses: [], regions: [] } as never);
    expect(hits.map((e) => e.id)).toEqual(["ist"]);
  });
});
