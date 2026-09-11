/**
 * Regression — F14 [M] (audit A10 WATCH): the shared snapshot poll was not
 * visibility-paused.
 *
 * `useLiveQuotesInternal` ran a bare setInterval, so a backgrounded WATCH
 * (and every other quote pane) kept firing 30s snapshot fetches forever.
 * The canonical kit pattern is pause-on-hidden + one refresh on resume.
 * These tests drive the REAL hook with fake timers and a mutable
 * `document.visibilityState`, asserting:
 *   - visible cadence still ticks,
 *   - hidden ticks issue no fetches,
 *   - the return transition fires exactly one immediate refresh and the
 *     cadence resumes.
 */
import { act, renderHook } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { useLiveQuotes } from "./market-data";
import type { QuoteSnapshot } from "./quotes";

function makeSnapshot(overrides: Partial<QuoteSnapshot> = {}): QuoteSnapshot {
  return {
    symbol: "AAPL",
    asset_class: "EQUITY",
    last: 200,
    price: 200,
    previous_close: 195,
    change_pct: 2.56,
    volume: 10_000_000,
    bid: null,
    ask: null,
    source: "yahoo_chart",
    provider_symbol: "AAPL",
    currency: "USD",
    fetched_at: "2026-05-20T12:00:00Z",
    ...overrides,
  };
}

function setVisibility(value: "visible" | "hidden"): void {
  Object.defineProperty(document, "visibilityState", {
    configurable: true,
    get: () => value,
  });
  act(() => {
    document.dispatchEvent(new Event("visibilitychange"));
  });
}

beforeEach(() => {
  vi.useFakeTimers();
  Object.defineProperty(document, "visibilityState", {
    configurable: true,
    get: () => "visible",
  });
});

afterEach(() => {
  vi.useRealTimers();
});

describe("useLiveQuotes visibility pause (F14 M)", () => {
  it("skips poll ticks while hidden and resumes with one immediate refresh", async () => {
    let calls = 0;
    const fetcher = vi.fn(async (sym: string) => {
      calls += 1;
      return makeSnapshot({ symbol: sym, last: 100 + calls });
    });
    const subscriber = vi.fn(() => ({ close: () => undefined }));

    renderHook(() =>
      useLiveQuotes(["AAPL"], { pollMs: 1_000, fetcher, subscriber }),
    );

    await act(async () => {
      await Promise.resolve();
      await Promise.resolve();
    });
    const afterMount = fetcher.mock.calls.length;
    expect(afterMount).toBe(1);

    // A visible cadence still refreshes.
    await act(async () => {
      await vi.advanceTimersByTimeAsync(1_100);
    });
    const afterVisibleTick = fetcher.mock.calls.length;
    expect(afterVisibleTick).toBeGreaterThan(afterMount);

    // Hidden: five cadences must not issue a single request.
    setVisibility("hidden");
    await act(async () => {
      await vi.advanceTimersByTimeAsync(5_000);
    });
    expect(fetcher.mock.calls.length).toBe(afterVisibleTick);

    // Returning to foreground fires exactly one immediate refresh…
    setVisibility("visible");
    await act(async () => {
      await Promise.resolve();
      await Promise.resolve();
    });
    expect(fetcher.mock.calls.length).toBe(afterVisibleTick + 1);

    // …and the cadence resumes.
    await act(async () => {
      await vi.advanceTimersByTimeAsync(1_100);
    });
    expect(fetcher.mock.calls.length).toBe(afterVisibleTick + 2);
  });
});
