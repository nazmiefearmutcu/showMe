/**
 * Bundle D / PERF-04 — useVisibilityTick contract.
 *
 *  - Increments on the interval while the tab is visible.
 *  - Pauses while `document.visibilityState === "hidden"`.
 *  - Resumes when the tab is shown again.
 *  - Clears the interval on unmount.
 */
import { renderHook, act } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { useVisibilityTick } from "./useVisibilityTick";

function setVisibility(state: "visible" | "hidden") {
  Object.defineProperty(document, "visibilityState", {
    configurable: true,
    get: () => state,
  });
  document.dispatchEvent(new Event("visibilitychange"));
}

describe("useVisibilityTick", () => {
  beforeEach(() => {
    vi.useFakeTimers();
    setVisibility("visible");
  });
  afterEach(() => {
    vi.useRealTimers();
    setVisibility("visible");
  });

  it("increments on each interval while visible", () => {
    const { result } = renderHook(() => useVisibilityTick(1000));
    expect(result.current).toBe(0);
    act(() => {
      vi.advanceTimersByTime(1000);
    });
    expect(result.current).toBe(1);
    act(() => {
      vi.advanceTimersByTime(3000);
    });
    expect(result.current).toBe(4);
  });

  it("pauses while the tab is hidden", () => {
    const { result } = renderHook(() => useVisibilityTick(1000));
    act(() => {
      vi.advanceTimersByTime(1000);
    });
    expect(result.current).toBe(1);
    act(() => {
      setVisibility("hidden");
      vi.advanceTimersByTime(5000);
    });
    // Hidden — counter does not advance even after 5s of fake time.
    expect(result.current).toBe(1);
  });

  it("resumes when the tab becomes visible again", () => {
    const { result } = renderHook(() => useVisibilityTick(1000));
    act(() => {
      setVisibility("hidden");
      vi.advanceTimersByTime(5000);
    });
    expect(result.current).toBe(0);
    act(() => {
      setVisibility("visible");
      vi.advanceTimersByTime(2000);
    });
    expect(result.current).toBe(2);
  });

  it("clears its interval on unmount", () => {
    const clearSpy = vi.spyOn(window, "clearInterval");
    const { unmount } = renderHook(() => useVisibilityTick(1000));
    unmount();
    expect(clearSpy).toHaveBeenCalled();
  });
});
