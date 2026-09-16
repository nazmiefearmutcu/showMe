/**
 * Layout persistence — round-trip, per-symbol isolation, corrupt fallback.
 *
 * The store is one localStorage map (`showme.chart.layout.v1`) keyed by
 * symbol. "Restore only what was saved": invalid fields are dropped on read
 * instead of being coerced into fake state.
 */
import { describe, expect, it } from "vitest";
import { LAYOUT_STORE_KEY, clearLayout, loadLayout, saveLayout, type ChartLayout } from "./chart-layout";

class MemoryStorage {
  private map = new Map<string, string>();
  getItem(key: string): string | null {
    return this.map.get(key) ?? null;
  }
  setItem(key: string, value: string): void {
    this.map.set(key, value);
  }
  removeItem(key: string): void {
    this.map.delete(key);
  }
  clear(): void {
    this.map.clear();
  }
}

const storage = () => new MemoryStorage() as unknown as Storage;

const fullLayout: ChartLayout = {
  interval: "1h",
  chartType: "line",
  priceMode: "log",
  showVolume: false,
  indicators: [
    {
      id: "ind-1",
      indicator: "rsi",
      params: { length: 14 },
      visible: true,
      pane: "separate",
    },
  ],
  drawings: [
    { id: "d1", kind: "hline", price: 123.4 },
    { id: "d2", kind: "trend", p1: { index: 1, price: 10 }, p2: { index: 5, price: 20 } },
    { id: "d3", kind: "fib", p1: { index: 2, price: 10 }, p2: { index: 8, price: 30 } },
  ],
  compareSymbols: ["ETHUSDT", "SPY"],
};

describe("chart layout store", () => {
  it("round-trips a full layout", () => {
    const s = storage();
    saveLayout("BTCUSDT", fullLayout, s);
    expect(loadLayout("BTCUSDT", s)).toEqual(fullLayout);
  });

  it("isolates symbols inside the single store key", () => {
    const s = storage();
    saveLayout("BTCUSDT", fullLayout, s);
    saveLayout("ETHUSDT", { ...fullLayout, interval: "5m" }, s);
    expect(loadLayout("BTCUSDT", s)?.interval).toBe("1h");
    expect(loadLayout("ETHUSDT", s)?.interval).toBe("5m");
    expect(loadLayout("NOPE", s)).toBeNull();
  });

  it("namespaces layouts per consuming scope (no cross-pane leakage)", () => {
    const s = storage();
    /* Reported: an intraday-pane entry (1s) leaked into the daily-studies
       pane for the same symbol and made its chart look dead. Scoped reads
       must not see entries saved under another scope — or under the legacy
       symbol-only key. */
    saveLayout("SOLUSDT", { ...fullLayout, interval: "1s" }, s, "GP");
    expect(loadLayout("SOLUSDT", s, "CHGS")).toBeNull();
    expect(loadLayout("SOLUSDT", s, "GP")?.interval).toBe("1s");
    expect(loadLayout("SOLUSDT", s)).toBeNull();

    /* Legacy symbol-only entries stay invisible to scoped panes. */
    saveLayout("AAPL", { ...fullLayout, interval: "1s" }, s);
    expect(loadLayout("AAPL", s, "CHGS")).toBeNull();
    expect(loadLayout("AAPL", s)?.interval).toBe("1s");

    /* Scoped clears only drop the scoped entry. */
    clearLayout("SOLUSDT", s, "GP");
    expect(loadLayout("SOLUSDT", s, "GP")).toBeNull();
    expect(loadLayout("AAPL", s)?.interval).toBe("1s");
  });

  it("returns null on corrupt JSON", () => {
    const s = storage();
    s.setItem(LAYOUT_STORE_KEY, "{oops");
    expect(loadLayout("BTCUSDT", s)).toBeNull();
  });

  it("returns null when the entry is not an object", () => {
    const s = storage();
    s.setItem(LAYOUT_STORE_KEY, JSON.stringify({ BTCUSDT: 42 }));
    expect(loadLayout("BTCUSDT", s)).toBeNull();
  });

  it("drops invalid fields and keeps the valid ones", () => {
    const s = storage();
    s.setItem(
      LAYOUT_STORE_KEY,
      JSON.stringify({
        BTCUSDT: {
          interval: "1h",
          chartType: "not-a-type",
          priceMode: "log",
          showVolume: "yes",
          indicators: [{ id: "i", indicator: "rsi" }, fullLayout.indicators[0]],
          drawings: [{ id: "bad", kind: "hline" }, fullLayout.drawings[0]],
          compareSymbols: ["ETHUSDT", "ETHUSDT", "", 7],
        },
      }),
    );
    const loaded = loadLayout("BTCUSDT", s);
    expect(loaded).toEqual({
      interval: "1h",
      priceMode: "log",
      indicators: [fullLayout.indicators[0]],
      drawings: [fullLayout.drawings[0]],
      compareSymbols: ["ETHUSDT"],
    });
  });

  it("returns null when nothing valid survives", () => {
    const s = storage();
    s.setItem(LAYOUT_STORE_KEY, JSON.stringify({ BTCUSDT: { interval: 7 } }));
    expect(loadLayout("BTCUSDT", s)).toBeNull();
  });

  it("clearLayout removes only the requested symbol", () => {
    const s = storage();
    saveLayout("BTCUSDT", fullLayout, s);
    saveLayout("ETHUSDT", fullLayout, s);
    clearLayout("BTCUSDT", s);
    expect(loadLayout("BTCUSDT", s)).toBeNull();
    expect(loadLayout("ETHUSDT", s)).not.toBeNull();
    clearLayout("ETHUSDT", s);
    expect(s.getItem(LAYOUT_STORE_KEY)).toBeNull();
  });
});
