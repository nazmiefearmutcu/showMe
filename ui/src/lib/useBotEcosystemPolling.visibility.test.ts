/**
 * Regression — audit S4.
 *
 * `useBotEcosystemPolling` ran a raw setInterval, ignoring document
 * visibility. Three open panes on a backgrounded tab × 2 calls each per
 * 10s = 18 req/10s for nothing. Fix: delegate to useVisibilityTick which
 * pauses while the tab is hidden.
 *
 * The test exercises the contract indirectly: when document.visibilityState
 * flips to "hidden", further interval ticks should NOT fire loadAll() /
 * loadLeaderboard(). When visibility returns, ticks resume.
 */
import { act, renderHook } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("./bots-supervision-store", () => ({
  useBotsSupervisionStore: {
    getState: vi.fn(() => ({
      loadAll: vi.fn(),
    })),
  },
}));
vi.mock("./performance-store", () => ({
  usePerformanceStore: {
    getState: vi.fn(() => ({
      loadLeaderboard: vi.fn(),
    })),
  },
}));

import { useBotEcosystemPolling } from "./useBotEcosystemPolling";
import { useBotsSupervisionStore } from "./bots-supervision-store";
import { usePerformanceStore } from "./performance-store";

const supState = useBotsSupervisionStore.getState as ReturnType<typeof vi.fn>;
const perfState = usePerformanceStore.getState as ReturnType<typeof vi.fn>;
let supCalls = 0;
let perfCalls = 0;

beforeEach(() => {
  supCalls = 0;
  perfCalls = 0;
  supState.mockReturnValue({
    loadAll: vi.fn(() => {
      supCalls += 1;
    }),
  });
  perfState.mockReturnValue({
    loadLeaderboard: vi.fn(() => {
      perfCalls += 1;
    }),
  });
  vi.useFakeTimers();
  // jsdom's default is "visible"
  Object.defineProperty(document, "visibilityState", {
    configurable: true,
    get: () => "visible",
  });
});

afterEach(() => {
  vi.useRealTimers();
});

function setVisibility(v: "visible" | "hidden"): void {
  Object.defineProperty(document, "visibilityState", {
    configurable: true,
    get: () => v,
  });
  act(() => {
    document.dispatchEvent(new Event("visibilitychange"));
  });
}

describe("useBotEcosystemPolling visibility pause (audit S4)", () => {
  it("fires loadAll + loadLeaderboard on each visible interval tick", () => {
    renderHook(() => useBotEcosystemPolling(1_000));
    // The initial tick fires once on mount.
    expect(supCalls).toBeGreaterThanOrEqual(1);
    const baseSup = supCalls;
    const basePerf = perfCalls;
    act(() => {
      vi.advanceTimersByTime(1_000);
    });
    expect(supCalls).toBe(baseSup + 1);
    expect(perfCalls).toBe(basePerf + 1);
  });

  it("pauses ticks when the tab is hidden", () => {
    renderHook(() => useBotEcosystemPolling(1_000));
    const baseSup = supCalls;
    setVisibility("hidden");
    act(() => {
      vi.advanceTimersByTime(5_000);
    });
    // No additional fan-out while hidden — the tick should not fire.
    expect(supCalls).toBe(baseSup);
  });

  it("resumes ticks when the tab returns to foreground", () => {
    renderHook(() => useBotEcosystemPolling(1_000));
    setVisibility("hidden");
    act(() => {
      vi.advanceTimersByTime(5_000);
    });
    const baseSup = supCalls;
    setVisibility("visible");
    act(() => {
      vi.advanceTimersByTime(1_000);
    });
    expect(supCalls).toBeGreaterThan(baseSup);
  });
});
