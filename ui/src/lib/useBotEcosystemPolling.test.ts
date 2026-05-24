/**
 * Single-source polling test (BUG #10).
 *
 * Verifies that one hook mount fans out to both `useBotsSupervisionStore.
 * loadAll` AND `usePerformanceStore.loadLeaderboard` on the same interval,
 * fires once immediately on mount, and clears the interval on unmount.
 */
import { act, renderHook } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { useBotEcosystemPolling, BOT_ECOSYSTEM_POLL_MS } from "./useBotEcosystemPolling";
import { useBotsSupervisionStore } from "./bots-supervision-store";
import { usePerformanceStore } from "./performance-store";

beforeEach(() => {
  vi.useFakeTimers();
  useBotsSupervisionStore.setState({
    loadAll: vi.fn(async () => {}),
  } as never);
  usePerformanceStore.setState({
    loadLeaderboard: vi.fn(async () => {}),
  } as never);
});

afterEach(() => {
  vi.useRealTimers();
  vi.restoreAllMocks();
});

describe("useBotEcosystemPolling", () => {
  it("fires both store actions once on mount (no waiting required)", () => {
    const supSpy = useBotsSupervisionStore.getState().loadAll as ReturnType<typeof vi.fn>;
    const perfSpy = usePerformanceStore.getState().loadLeaderboard as ReturnType<typeof vi.fn>;

    renderHook(() => useBotEcosystemPolling(1_000));

    expect(supSpy).toHaveBeenCalledTimes(1);
    expect(perfSpy).toHaveBeenCalledTimes(1);
  });

  it("re-fires both at every interval tick (single source)", () => {
    const supSpy = useBotsSupervisionStore.getState().loadAll as ReturnType<typeof vi.fn>;
    const perfSpy = usePerformanceStore.getState().loadLeaderboard as ReturnType<typeof vi.fn>;

    renderHook(() => useBotEcosystemPolling(5_000));
    // initial tick
    expect(supSpy).toHaveBeenCalledTimes(1);
    expect(perfSpy).toHaveBeenCalledTimes(1);

    // S4 fix: polling now goes through useVisibilityTick which uses
    // setState; we need `act` to flush React's re-render → effect chain.
    act(() => {
      vi.advanceTimersByTime(5_000);
    });
    expect(supSpy).toHaveBeenCalledTimes(2);
    expect(perfSpy).toHaveBeenCalledTimes(2);

    act(() => {
      vi.advanceTimersByTime(5_000);
    });
    expect(supSpy).toHaveBeenCalledTimes(3);
    expect(perfSpy).toHaveBeenCalledTimes(3);
  });

  it("stops polling after unmount (clearInterval is wired)", () => {
    const supSpy = useBotsSupervisionStore.getState().loadAll as ReturnType<typeof vi.fn>;

    const { unmount } = renderHook(() => useBotEcosystemPolling(1_000));
    expect(supSpy).toHaveBeenCalledTimes(1);

    unmount();
    vi.advanceTimersByTime(10_000);
    // No further calls after unmount.
    expect(supSpy).toHaveBeenCalledTimes(1);
  });

  it("default interval is 10s (BUG #10 contract — matches between BOTS+PERF)", () => {
    expect(BOT_ECOSYSTEM_POLL_MS).toBe(10_000);
    const supSpy = useBotsSupervisionStore.getState().loadAll as ReturnType<typeof vi.fn>;
    renderHook(() => useBotEcosystemPolling());
    // 1× on mount, advance by default interval → exactly 2× total.
    expect(supSpy).toHaveBeenCalledTimes(1);
    act(() => {
      vi.advanceTimersByTime(BOT_ECOSYSTEM_POLL_MS);
    });
    expect(supSpy).toHaveBeenCalledTimes(2);
  });
});
