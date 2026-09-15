/**
 * Chart shell — jsdom smoke.
 *
 * Pins the milestone-2 toolbar contract without a real canvas: the sidecar
 * transport is mocked to return an empty bar set, `getContext` is stubbed to
 * null (jsdom has no 2D context) and ResizeObserver is polyfilled. The mount
 * must render the scale segmented control, the VOL toggle and the drawing
 * tools without crashing, and the scale buttons must reflect the active mode.
 */
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("@/lib/sidecar", () => ({
  sidecarFetch: vi.fn(async () => ({
    symbol: "BTCUSDT",
    interval: "15m",
    bars: [],
    source: "binance",
    asOf: "2026-09-15T00:00:00Z",
  })),
}));

import { Chart } from "./Chart";

/* jsdom ships no ResizeObserver (many suites polyfill their own). */
class FakeResizeObserver {
  observe(): void {}
  unobserve(): void {}
  disconnect(): void {}
}

const originalGetContext = HTMLCanvasElement.prototype.getContext;

beforeEach(() => {
  (globalThis as { ResizeObserver?: unknown }).ResizeObserver = FakeResizeObserver;
  /* jsdom's canvas has no 2D context — return null so draw() bails early. */
  HTMLCanvasElement.prototype.getContext = (() =>
    null) as typeof HTMLCanvasElement.prototype.getContext;
});

afterEach(() => {
  cleanup();
  HTMLCanvasElement.prototype.getContext = originalGetContext;
});

describe("Chart shell — toolbar smoke (jsdom)", () => {
  it("renders scale buttons + VOL toggle + drawing tools on an empty dataset", async () => {
    render(<Chart symbol="BTCUSDT" />);
    expect(await screen.findByTestId("sm-chart-scale-linear")).toBeInTheDocument();
    expect(screen.getByTestId("sm-chart-scale-log")).toBeInTheDocument();
    expect(screen.getByTestId("sm-chart-scale-percent")).toBeInTheDocument();
    const vol = screen.getByTestId("sm-chart-volume-toggle");
    expect(vol).toHaveAttribute("aria-pressed", "true");
    expect(screen.getByTestId("sm-chart-draw-hline")).toBeInTheDocument();
    expect(screen.getByTestId("sm-chart-draw-trend")).toBeInTheDocument();
    // Default mode is linear.
    expect(screen.getByTestId("sm-chart-scale-linear")).toHaveAttribute("aria-pressed", "true");
  });

  it("switches the active scale mode and toggles volume", async () => {
    render(<Chart symbol="BTCUSDT" />);
    const log = await screen.findByTestId("sm-chart-scale-log");
    fireEvent.click(log);
    expect(log).toHaveAttribute("aria-pressed", "true");
    expect(screen.getByTestId("sm-chart-scale-linear")).toHaveAttribute("aria-pressed", "false");

    const vol = screen.getByTestId("sm-chart-volume-toggle");
    fireEvent.click(vol);
    expect(vol).toHaveAttribute("aria-pressed", "false");
  });

  it("arms a drawing tool on click and disarms it on a second click", async () => {
    render(<Chart symbol="BTCUSDT" />);
    const trend = await screen.findByTestId("sm-chart-draw-trend");
    fireEvent.click(trend);
    expect(trend).toHaveAttribute("aria-pressed", "true");
    expect(screen.getByRole("img")).toHaveClass("is-drawing");
    fireEvent.click(trend);
    expect(trend).toHaveAttribute("aria-pressed", "false");
    expect(screen.getByRole("img")).not.toHaveClass("is-drawing");
  });
});
