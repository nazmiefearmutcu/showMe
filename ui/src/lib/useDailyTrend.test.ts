import { renderHook, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import {
  clearDailyTrendCache,
  closesFromGpPayload,
  useDailyTrends,
} from "@/lib/useDailyTrend";

vi.mock("@/lib/functions", () => ({
  runFunction: vi.fn(),
}));

import { runFunction } from "@/lib/functions";

const mockedRun = vi.mocked(runFunction);

const bars = (closes: number[]) =>
  closes.map((close, i) => ({
    time: 1_700_000_000 + i * 86_400,
    open: close,
    high: close + 1,
    low: close - 1,
    close,
    volume: 100,
  }));

beforeEach(() => {
  clearDailyTrendCache();
  mockedRun.mockReset();
});

describe("closesFromGpPayload", () => {
  it("reads ohlcv/bars/rows and returns finite closes time-ascending", () => {
    expect(closesFromGpPayload({ ohlcv: bars([3, 1, 2]) })).toEqual([3, 1, 2]);
    expect(closesFromGpPayload({ bars: bars([5]) })).toEqual([5]);
    expect(closesFromGpPayload({ rows: bars([7]) })).toEqual([7]);
    expect(closesFromGpPayload(null)).toEqual([]);
    expect(closesFromGpPayload({ ohlcv: [{ open: 1, high: 1, low: 1 }] })).toEqual([]);
  });
});

describe("useDailyTrends", () => {
  it("fetches daily closes per symbol, upper-cased keys", async () => {
    mockedRun.mockImplementation(async (_code: string, opts?: { symbol?: string }) => ({
      data: { ohlcv: bars([10, 11, 12]) },
      symbol: opts?.symbol,
    }) as never);
    const { result } = renderHook(() => useDailyTrends(["btcusdt"]));
    await waitFor(() => {
      expect(result.current).toEqual({ BTCUSDT: [10, 11, 12] });
    });
    expect(mockedRun).toHaveBeenCalledTimes(1);
    expect(mockedRun.mock.calls[0][1]).toMatchObject({
      symbol: "BTCUSDT",
      params: { interval: "1d", bars: 30 },
    });
  });

  it("serves the cache without refetching and skips failed symbols", async () => {
    mockedRun.mockImplementation(async (_code: string, opts?: { symbol?: string }) => {
      if (opts?.symbol === "BROKEN") throw new Error("down");
      return { data: { ohlcv: bars([1, 2]) } } as never;
    });
    const { result, rerender } = renderHook(
      ({ syms }: { syms: string[] }) => useDailyTrends(syms),
      { initialProps: { syms: ["AAPL", "BROKEN"] as string[] } },
    );
    await waitFor(() => {
      expect(result.current).toEqual({ AAPL: [1, 2] });
    });
    expect(mockedRun).toHaveBeenCalledTimes(2);
    // Remount with the same symbols: cache hit, no new fetch.
    rerender({ syms: ["AAPL"] });
    await waitFor(() => {
      expect(result.current).toEqual({ AAPL: [1, 2] });
    });
    expect(mockedRun).toHaveBeenCalledTimes(2);
  });

  it("does nothing when disabled", () => {
    const { result } = renderHook(() => useDailyTrends(["AAPL"], { enabled: false }));
    expect(result.current).toEqual({});
    expect(mockedRun).not.toHaveBeenCalled();
  });
});
