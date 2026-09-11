/**
 * Lane L4 — FlashValue primitive (campaign 2026-09-11).
 *
 * Pins the frozen update-pulse contract:
 *   - no flash on first render / equal values;
 *   - up → .flash-pos, down → .flash-neg;
 *   - class auto-clears after TICK_FLASH_MS;
 *   - null never flashes in either direction;
 *   - caller className is preserved; unmount mid-flash is safe.
 */
import { act, cleanup, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { FlashValue } from "./FlashValue";
import { TICK_FLASH_MS, tickFlashClass } from "@/lib/tick-flash";

function view(value: number | null, className?: string) {
  return (
    <FlashValue value={value} className={className}>
      <span>42.00</span>
    </FlashValue>
  );
}

function el(): HTMLElement {
  return screen.getByTestId("flash-value");
}

beforeEach(() => {
  vi.useFakeTimers();
});

afterEach(() => {
  cleanup();
  vi.useRealTimers();
});

describe("tickFlashClass", () => {
  it("maps directions to the shared flash classes", () => {
    expect(tickFlashClass("up")).toBe("flash-pos");
    expect(tickFlashClass("down")).toBe("flash-neg");
    expect(tickFlashClass(null)).toBeNull();
  });
});

describe("FlashValue", () => {
  it("renders children and does not flash on mount", () => {
    render(view(100));
    expect(el().textContent).toBe("42.00");
    expect(el().className).not.toMatch(/flash/);
    expect(el().dataset.flash).toBeUndefined();
  });

  it("flashes up when the value rises and clears after the window", () => {
    const { rerender } = render(view(100));
    rerender(view(101.5));
    expect(el().className).toContain("flash-pos");
    expect(el().dataset.flash).toBe("up");
    act(() => {
      vi.advanceTimersByTime(TICK_FLASH_MS + 1);
    });
    expect(el().className).not.toContain("flash-pos");
    expect(el().dataset.flash).toBeUndefined();
  });

  it("flashes down when the value drops", () => {
    const { rerender } = render(view(100));
    rerender(view(99));
    expect(el().className).toContain("flash-neg");
    expect(el().dataset.flash).toBe("down");
  });

  it("never flashes on equal values", () => {
    const { rerender } = render(view(100));
    rerender(view(100));
    expect(el().className).not.toMatch(/flash/);
  });

  it("never flashes from or to null (unknown is not a direction)", () => {
    const { rerender } = render(view(null));
    rerender(view(123));
    expect(el().className).not.toMatch(/flash/);
    rerender(view(null));
    expect(el().className).not.toMatch(/flash/);
  });

  it("preserves the caller className alongside the flash class", () => {
    const { rerender } = render(view(100, "watch-row__value"));
    rerender(view(101, "watch-row__value"));
    expect(el().className).toContain("watch-row__value");
    expect(el().className).toContain("flash-pos");
  });

  it("unmounting mid-flash does not leak a timer update", () => {
    const { rerender, unmount } = render(view(100));
    rerender(view(101));
    unmount();
    // No "update on unmounted component" / act warning must surface.
    expect(() => {
      act(() => {
        vi.advanceTimersByTime(TICK_FLASH_MS + 1);
      });
    }).not.toThrow();
  });
});
