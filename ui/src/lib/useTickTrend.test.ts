import { act, renderHook } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import type { QuoteView } from "@/lib/market-data";
import {
  appendTickPoint,
  TICK_TREND_MAX_POINTS,
  useTickTrend,
} from "@/lib/useTickTrend";

const q = (price: number | null) => ({ price }) as unknown as QuoteView;

describe("appendTickPoint", () => {
  it("appends the first price", () => {
    expect(appendTickPoint([], 100)).toEqual([100]);
  });

  it("ignores missing and non-finite prices (same reference, no render)", () => {
    const hist = [100];
    expect(appendTickPoint(hist, null)).toBe(hist);
    expect(appendTickPoint(hist, undefined)).toBe(hist);
    expect(appendTickPoint(hist, NaN)).toBe(hist);
    expect(appendTickPoint(hist, Infinity)).toBe(hist);
  });

  it("dedupes a price equal to the last point", () => {
    const hist = [100, 101];
    expect(appendTickPoint(hist, 101)).toBe(hist);
  });

  it("caps the series at maxPoints, dropping the oldest", () => {
    const hist = [1, 2, 3];
    expect(appendTickPoint(hist, 4, 3)).toEqual([2, 3, 4]);
    expect(TICK_TREND_MAX_POINTS).toBe(30);
  });
});

describe("useTickTrend", () => {
  it("accumulates per-symbol series upper-cased, in arrival order", () => {
    const { result, rerender } = renderHook(
      ({ quotes }: { quotes: Record<string, QuoteView> }) => useTickTrend(quotes),
      { initialProps: { quotes: { btcusdt: q(100) } as Record<string, QuoteView> } },
    );
    expect(result.current).toEqual({ BTCUSDT: [100] });
    rerender({ quotes: { btcusdt: q(100), ETHUSDT: q(50) } });
    expect(result.current).toEqual({ BTCUSDT: [100], ETHUSDT: [50] });
    rerender({ quotes: { btcusdt: q(101), ETHUSDT: q(50) } });
    expect(result.current).toEqual({ BTCUSDT: [100, 101], ETHUSDT: [50] });
  });

  it("ignores null prices and prunes removed symbols", () => {
    const { result, rerender } = renderHook(
      ({ quotes }: { quotes: Record<string, QuoteView> }) => useTickTrend(quotes),
      { initialProps: { quotes: { AAPL: q(10), MSFT: q(20) } as Record<string, QuoteView> } },
    );
    expect(result.current).toEqual({ AAPL: [10], MSFT: [20] });
    rerender({ quotes: { AAPL: q(null) } });
    // MSFT pruned (gone from quotes); AAPL keeps history (null adds nothing).
    expect(result.current).toEqual({ AAPL: [10] });
  });

  it("does not grow on identical re-renders", () => {
    const quotes: Record<string, QuoteView> = { AAPL: q(10) };
    const { result, rerender } = renderHook(
      ({ qs }: { qs: Record<string, QuoteView> }) => useTickTrend(qs),
      { initialProps: { qs: quotes } },
    );
    const first = result.current;
    act(() => {
      rerender({ qs: quotes });
    });
    expect(result.current).toBe(first);
  });
});
