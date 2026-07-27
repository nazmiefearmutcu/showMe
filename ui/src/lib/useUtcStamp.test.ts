/**
 * useUtcStamp contract — the stamp tracks the freshness signal, not renders.
 *
 *  - Stable across re-renders that do not advance the signal.
 *  - Re-reads the clock when the signal advances.
 *  - Works with an object signal (payload identity), not just a counter.
 */
import { renderHook } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { useUtcStamp } from "./useUtcStamp";

describe("useUtcStamp", () => {
  beforeEach(() => {
    vi.useFakeTimers();
    vi.setSystemTime(new Date("2026-07-27T09:15:00Z"));
  });
  afterEach(() => {
    vi.useRealTimers();
  });

  it("formats the clock as HH:MM", () => {
    const { result } = renderHook(() => useUtcStamp(0));
    expect(result.current).toBe("09:15");
  });

  it("does not re-stamp on a re-render that leaves the signal alone", () => {
    const { result, rerender } = renderHook(({ s }) => useUtcStamp(s), {
      initialProps: { s: 0 },
    });
    expect(result.current).toBe("09:15");

    // Clock moves, but nothing polled — the label must not drift.
    vi.setSystemTime(new Date("2026-07-27T11:42:00Z"));
    rerender({ s: 0 });
    expect(result.current).toBe("09:15");
  });

  it("re-stamps when the signal advances", () => {
    const { result, rerender } = renderHook(({ s }) => useUtcStamp(s), {
      initialProps: { s: 0 },
    });
    expect(result.current).toBe("09:15");

    vi.setSystemTime(new Date("2026-07-27T11:42:00Z"));
    rerender({ s: 1 });
    expect(result.current).toBe("11:42");
  });

  it("accepts an object signal and keys on its identity", () => {
    const first = { rows: [] };
    const { result, rerender } = renderHook(({ s }) => useUtcStamp(s), {
      initialProps: { s: first as unknown },
    });
    expect(result.current).toBe("09:15");

    vi.setSystemTime(new Date("2026-07-27T11:42:00Z"));
    rerender({ s: first as unknown });
    expect(result.current).toBe("09:15");

    // New payload object -> new poll -> new stamp.
    rerender({ s: { rows: [] } as unknown });
    expect(result.current).toBe("11:42");
  });
});
