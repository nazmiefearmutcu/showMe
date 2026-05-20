import { beforeEach, describe, expect, it } from "vitest";
import {
  isPinned,
  listPinnedItems,
  parsePinnedItemPayload,
  makePinnedItemForPane,
  makePinnedItemForFunctionEntry,
  resetPinnedItemsForTests,
  serializePinnedItem,
  togglePinnedItem,
  unpinItem,
} from "./pins";

beforeEach(() => {
  localStorage.clear();
  resetPinnedItemsForTests();
});

describe("pins", () => {
  it("loads the default pinned market shortcuts when no user state exists", () => {
    expect(listPinnedItems().map((item) => item.path)).toEqual([
      "/symbol/AAPL/DES",
      "/symbol/NVDA/DES",
      "/symbol/BTC/DES",
      "/symbol/SPX/DES",
    ]);
  });

  it("toggles a function pin and persists the user list", () => {
    const item = makePinnedItemForPane("GEX", undefined, [
      {
        code: "GEX",
        name: "Gamma Exposure",
        category: "derivative",
        description: "Gamma profile",
      },
    ]);

    expect(togglePinnedItem(item)).toBe(true);
    expect(isPinned("function:GEX")).toBe(true);
    expect(listPinnedItems()[0]).toMatchObject({
      id: "function:GEX",
      label: "Gamma Exposure",
      path: "/fn/GEX",
    });

    resetPinnedItemsForTests();
    expect(listPinnedItems()[0].id).toBe("function:GEX");

    expect(togglePinnedItem(item)).toBe(false);
    expect(isPinned("function:GEX")).toBe(false);
  });

  it("unpinning defaults records an explicit user list instead of restoring defaults", () => {
    unpinItem("symbol:AAPL:DES");

    expect(listPinnedItems().map((item) => item.id)).not.toContain("symbol:AAPL:DES");

    resetPinnedItemsForTests();
    expect(listPinnedItems().map((item) => item.id)).not.toContain("symbol:AAPL:DES");
  });

  it("creates symbol-bound pins for the active pane", () => {
    const item = makePinnedItemForPane("DES", "btc", []);

    expect(item).toMatchObject({
      id: "symbol:BTCUSDT:DES",
      code: "BTCUSDT",
      label: "BTCUSDT",
      meta: "DES",
      path: "/symbol/BTCUSDT/DES",
      href: "#/symbol/BTCUSDT/DES",
    });
  });

  it("round-trips drag payloads through the same normalized pin shape", () => {
    const item = makePinnedItemForFunctionEntry({
      code: "GEX",
      name: "Gamma Exposure",
      category: "derivative",
      description: "Gamma profile",
    });

    expect(parsePinnedItemPayload(serializePinnedItem(item))).toEqual({
      id: "function:GEX",
      kind: "function",
      code: "GEX",
      label: "Gamma Exposure",
      meta: "GEX",
      path: "/fn/GEX",
      href: "#/fn/GEX",
    });
  });
});
