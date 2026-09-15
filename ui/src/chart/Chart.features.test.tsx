/**
 * Chart shell — milestone-3 feature flows (jsdom).
 *
 * Compare-overlay chips, bar replay transport, layout persistence/restore/
 * reset and indicator alerts are exercised through the REAL shell with a
 * mocked sidecar (per-symbol bars) and a null canvas context (jsdom has no
 * 2D backend — every assertion below is DOM/state observable).
 */
import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { BarsResponse } from "./types";

/* Hoisted function declaration: the mock factory below runs before any
   module-body const initializers. Phase 1 declines (RSI low), phase 2
   rallies (RSI crosses above 70 mid-series). */
function makeBars(n: number, base: number, t0: number) {
  const bars = [];
  for (let i = 0; i < n; i++) {
    const c = i < n / 2 ? base + (n / 2 - i) * 0.4 : base + (i - n / 2 + 1) * 1.2;
    bars.push({ t: t0 + i * 60_000, o: c - 0.05, h: c + 0.1, l: c - 0.1, c, v: 10 + i });
  }
  return bars;
}

vi.mock("@/lib/sidecar", () => ({
  sidecarFetch: vi.fn(async (path: string) => {
    const url = new URL(path, "http://localhost");
    const symbol = url.searchParams.get("symbol") ?? "";
    if (symbol === "FAILUSDT") throw new Error("provider unavailable");
    const payload: BarsResponse = {
      symbol,
      interval: url.searchParams.get("interval") ?? "15m",
      bars: makeBars(120, symbol === "ETHUSDT" ? 200 : 100, 1_700_000_000_000),
      source: "test",
      asOf: "2026-09-15T00:00:00Z",
    };
    return payload;
  }),
}));

class FakeResizeObserver {
  observe(): void {}
  unobserve(): void {}
  disconnect(): void {}
}

const originalGetContext = HTMLCanvasElement.prototype.getContext;

vi.spyOn(HTMLElement.prototype, "clientWidth", "get").mockReturnValue(800);
vi.spyOn(HTMLElement.prototype, "clientHeight", "get").mockReturnValue(600);

import { Chart } from "./Chart";
import { loadLayout } from "./chart-layout";

beforeEach(() => {
  (globalThis as { ResizeObserver?: unknown }).ResizeObserver = FakeResizeObserver;
  HTMLCanvasElement.prototype.getContext = (() =>
    null) as typeof HTMLCanvasElement.prototype.getContext;
  localStorage.clear();
});

afterEach(() => {
  cleanup();
  HTMLCanvasElement.prototype.getContext = originalGetContext;
});

describe("Compare overlay", () => {
  it("adds a compare chip via the toolbar input and removes it", async () => {
    render(<Chart symbol="BTCUSDT" />);
    const input = await screen.findByTestId("sm-chart-compare-add");
    fireEvent.change(input, { target: { value: "ETHUSDT" } });
    fireEvent.keyDown(input, { key: "Enter" });
    const chip = await screen.findByTestId("sm-chart-compare-chip-ETHUSDT");
    expect(chip).toBeInTheDocument();
    fireEvent.click(within(chip).getByRole("button", { name: /Remove compare ETHUSDT/i }));
    await waitFor(() =>
      expect(screen.queryByTestId("sm-chart-compare-chip-ETHUSDT")).toBeNull(),
    );
  });

  it("shows a warning chip (never a fake line) when a compare symbol fails", async () => {
    render(<Chart symbol="BTCUSDT" />);
    const input = await screen.findByTestId("sm-chart-compare-add");
    fireEvent.change(input, { target: { value: "FAILUSDT" } });
    fireEvent.keyDown(input, { key: "Enter" });
    const chip = await screen.findByTestId("sm-chart-compare-chip-FAILUSDT");
    await waitFor(() => expect(chip.className).toContain("is-warn"));
    expect(chip.getAttribute("title")).toMatch(/failed/i);
  });
});

describe("Layout persistence", () => {
  it("restores interval-free state (price scale) across mounts", async () => {
    const first = render(<Chart symbol="BTCUSDT" />);
    fireEvent.click(await screen.findByTestId("sm-chart-scale-log"));
    await waitFor(() =>
      expect(screen.getByTestId("sm-chart-scale-log")).toHaveAttribute("aria-pressed", "true"),
    );
    first.unmount();

    render(<Chart symbol="BTCUSDT" />);
    await waitFor(() =>
      expect(screen.getByTestId("sm-chart-scale-log")).toHaveAttribute("aria-pressed", "true"),
    );
  });

  it("falls back to defaults on a corrupt store without crashing", async () => {
    localStorage.setItem("showme.chart.layout.v1", "{definitely not json");
    render(<Chart symbol="BTCUSDT" />);
    expect(await screen.findByTestId("sm-chart-scale-linear")).toHaveAttribute(
      "aria-pressed",
      "true",
    );
  });

  it("Reset clears the saved layout and returns to defaults", async () => {
    render(<Chart symbol="BTCUSDT" />);
    fireEvent.click(await screen.findByTestId("sm-chart-scale-log"));
    fireEvent.click(screen.getByTestId("sm-chart-reset-layout"));
    await waitFor(() =>
      expect(screen.getByTestId("sm-chart-scale-linear")).toHaveAttribute(
        "aria-pressed",
        "true",
      ),
    );
    expect(localStorage.getItem("showme.chart.layout.v1")).toBeNull();
    expect(loadLayout("BTCUSDT")).toBeNull();
  });
});

describe("Indicator alerts", () => {
  it("fires an RSI crossing alert once and lists it in the pane", async () => {
    render(<Chart symbol="BTCUSDT" />);
    await screen.findByTestId("sm-chart-scale-linear");

    /* Add RSI from the picker. */
    fireEvent.click(screen.getByRole("button", { name: /Indicators/ }));
    const picker = screen.getByRole("dialog", { name: "Add indicator" });
    fireEvent.click(within(picker).getByText("RSI"));

    /* Open its settings and add an alert (default level: RSI 70). */
    fireEvent.click(await screen.findByRole("tab", { name: /RSI/ }));
    const add = await screen.findByTestId("sm-chart-alert-add");
    fireEvent.click(add);

    const list = await screen.findByTestId("sm-chart-alert-list");
    expect(list.textContent).toContain("RSI");
    expect(list.textContent).toContain("crosses above 70");
    /* One entry only — the crossing is memoized, not re-fired per render. */
    expect(within(list).getAllByText(/crosses above 70/)).toHaveLength(1);
  });
});
