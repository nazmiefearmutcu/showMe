/**
 * Chart engine — gesture contract pins (user report: "chart yatay eksende
 * inverted hareket ediyor").
 *
 * Content must FOLLOW the pointer like TradingView's grab behavior:
 * dragging right shows EARLIER bars (the visible index window moves back),
 * dragging left moves the window forward. The regression was a stray `-dx`
 * in the drag handler against a content-follow `panBy`; these tests pin the
 * direction via the canvas' observable view window (data-view-from/to).
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, waitFor } from "@testing-library/react";
import type { BarsResponse } from "./types";

const bar = (i: number) => ({
  t: 1_700_000_000_000 + i * 60_000,
  o: 100 + i * 0.1,
  h: 100.5 + i * 0.1,
  l: 99.5 + i * 0.1,
  c: 100.2 + i * 0.1,
  v: 10 + i,
});

const payload: BarsResponse = {
  symbol: "BTCUSDT",
  interval: "1m",
  bars: Array.from({ length: 300 }, (_, i) => bar(i)),
  source: "binance",
  asOf: "2026-09-15T00:00:00Z",
};

vi.mock("@/lib/sidecar", () => ({
  sidecarFetch: vi.fn(async () => payload),
}));

// jsdom has no canvas backend: draw() writes the observable view state
// before hitting the null-context guard.
vi.spyOn(HTMLCanvasElement.prototype, "getContext").mockReturnValue(null);

const widthSpy = vi
  .spyOn(HTMLElement.prototype, "clientWidth", "get")
  .mockReturnValue(800);
const heightSpy = vi
  .spyOn(HTMLElement.prototype, "clientHeight", "get")
  .mockReturnValue(600);

import { Chart } from "./Chart";

beforeEach(() => {
  cleanup();
  localStorage.clear();
});
afterEach(() => {
  cleanup();
});

async function mountChart() {
  const { container } = render(<Chart symbol="BTCUSDT" height={400} />);
  const canvas = container.querySelector("canvas.sm-chart__canvas") as HTMLCanvasElement;
  await waitFor(() => expect(canvas.dataset.viewFrom).toBeTruthy());
  return canvas;
}

const viewFrom = (canvas: HTMLCanvasElement) => Number(canvas.dataset.viewFrom);

describe("Chart engine — grab-drag direction", () => {
  it("dragging RIGHT moves the window back (content follows the pointer)", async () => {
    const canvas = await mountChart();
    const before = viewFrom(canvas);
    fireEvent.pointerDown(canvas, { clientX: 300, clientY: 150, pointerId: 1 });
    fireEvent.pointerMove(canvas, { clientX: 460, clientY: 150, pointerId: 1 });
    fireEvent.pointerUp(canvas, { clientX: 460, clientY: 150, pointerId: 1 });
    await waitFor(() => expect(viewFrom(canvas)).not.toBe(before));
    expect(viewFrom(canvas)).toBeLessThan(before);
  });

  it("dragging LEFT moves the window forward", async () => {
    const canvas = await mountChart();
    const before = viewFrom(canvas);
    fireEvent.pointerDown(canvas, { clientX: 460, clientY: 150, pointerId: 2 });
    fireEvent.pointerMove(canvas, { clientX: 300, clientY: 150, pointerId: 2 });
    fireEvent.pointerUp(canvas, { clientX: 300, clientY: 150, pointerId: 2 });
    await waitFor(() => expect(viewFrom(canvas)).not.toBe(before));
    expect(viewFrom(canvas)).toBeGreaterThan(before);
  });

  it("vertical drag pans the price window in the same (content-follow) direction", async () => {
    const canvas = await mountChart();
    const before = Number(canvas.dataset.priceMin);
    fireEvent.pointerDown(canvas, { clientX: 300, clientY: 150, pointerId: 3 });
    fireEvent.pointerMove(canvas, { clientX: 300, clientY: 250, pointerId: 3 });
    fireEvent.pointerUp(canvas, { clientX: 300, clientY: 250, pointerId: 3 });
    await waitFor(() => expect(Number(canvas.dataset.priceMin)).not.toBe(before));
    // Pointer down (content down) reveals HIGHER prices? No — content moves
    // down, so the window shifts UP: min/max increase.
    expect(Number(canvas.dataset.priceMin)).toBeGreaterThan(before);
  });
});

// Keep the spies from leaking into other suites in the same worker.
export function _restoreSpies() {
  widthSpy.mockRestore();
  heightSpy.mockRestore();
}
