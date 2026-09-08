/**
 * Lane D — U10 tick-flash: pure direction math + the hook's one-shot pulse.
 *
 * The visual (450 ms background keyframes under
 * `prefers-reduced-motion: no-preference`) lives in
 * styles/workspace-ux.css; here we pin the observable contract: flash only
 * on a real numeric CHANGE, correct direction, auto-clear after 450 ms.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { act, cleanup, render } from "@testing-library/react";
import { tickDirection, useTickFlash, TICK_FLASH_MS } from "./tick-flash";

describe("tickDirection", () => {
  it("classifies up / down / flat", () => {
    expect(tickDirection(100, 101)).toBe("up");
    expect(tickDirection(100, 99.5)).toBe("down");
    expect(tickDirection(100, 100)).toBeNull();
  });

  it("never flashes from or to a missing price", () => {
    expect(tickDirection(null, 100)).toBeNull();
    expect(tickDirection(100, null)).toBeNull();
    expect(tickDirection(undefined, 100)).toBeNull();
  });

  it("rejects non-finite prices instead of flashing garbage", () => {
    expect(tickDirection(Number.NaN, 100)).toBeNull();
    expect(tickDirection(100, Number.POSITIVE_INFINITY)).toBeNull();
  });
});

describe("useTickFlash", () => {
  beforeEach(() => {
    vi.useFakeTimers();
  });
  afterEach(() => {
    vi.useRealTimers();
    cleanup();
  });

  function Probe({ price }: { price: number | null }) {
    const flash = useTickFlash(price);
    return <span data-testid="flash" data-flash={flash ?? ""} />;
  }

  it("does not flash on first render or on equal values", () => {
    const { getByTestId, rerender } = render(<Probe price={100} />);
    expect(getByTestId("flash").dataset.flash).toBe("");
    rerender(<Probe price={100} />);
    expect(getByTestId("flash").dataset.flash).toBe("");
  });

  it("flashes up on a rise and clears after the flash window", () => {
    const { getByTestId, rerender } = render(<Probe price={100} />);
    rerender(<Probe price={102} />);
    expect(getByTestId("flash").dataset.flash).toBe("up");
    act(() => {
      vi.advanceTimersByTime(TICK_FLASH_MS + 1);
    });
    expect(getByTestId("flash").dataset.flash).toBe("");
  });

  it("flashes down on a drop", () => {
    const { getByTestId, rerender } = render(<Probe price={100} />);
    rerender(<Probe price={99} />);
    expect(getByTestId("flash").dataset.flash).toBe("down");
  });

  it("does not flash when the price arrives for the first time (null → value)", () => {
    const { getByTestId, rerender } = render(<Probe price={null} />);
    rerender(<Probe price={123} />);
    expect(getByTestId("flash").dataset.flash).toBe("");
  });
});
