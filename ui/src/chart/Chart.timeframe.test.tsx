/**
 * Timeframe/provider-capability contract.
 *
 * A routed default or a restored per-symbol layout can land on a timeframe
 * the instrument's provider does not serve (the reported case: a stale "1s"
 * restored on an AAPL Yahoo chart -> "No bars / 1s bars are not available
 * for yahoo instruments"). The shell must auto-correct ONCE to the closest
 * supported horizon, and the picker must disable options the current
 * provider cannot serve. The refusal message only stays when the user
 * deliberately picks an unsupported pair after the one-shot correction.
 */
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const fetchMock = vi.fn();

vi.mock("@/lib/sidecar", () => ({
  sidecarFetch: (...args: unknown[]) => fetchMock(...args),
}));

import { Chart } from "./Chart";

class FakeResizeObserver {
  observe(): void {}
  unobserve(): void {}
  disconnect(): void {}
}

const originalGetContext = HTMLCanvasElement.prototype.getContext;

beforeEach(() => {
  fetchMock.mockReset();
  (globalThis as { ResizeObserver?: unknown }).ResizeObserver = FakeResizeObserver;
  /* jsdom's canvas has no 2D context - return null so draw() bails early. */
  HTMLCanvasElement.prototype.getContext = (() =>
    null) as typeof HTMLCanvasElement.prototype.getContext;
  localStorage.clear();
});

afterEach(() => {
  cleanup();
  HTMLCanvasElement.prototype.getContext = originalGetContext;
});

const yahooBars = (symbol: string, interval: string) => ({
  symbol,
  interval,
  source: "yahoo",
  asOf: "2026-09-16T00:00:00Z",
  bars: [{ t: 1757894400000, o: 330, h: 335, l: 328, c: 331.34, v: 1_000 }],
});

describe("Chart timeframe capability (jsdom)", () => {
  it("auto-corrects an unsupported restored interval (1s on a Yahoo symbol) to 1D", async () => {
    fetchMock.mockImplementation(async (url: string) => {
      if (url.includes("interval=1s")) {
        return {
          symbol: "AAPL",
          interval: "1s",
          source: "yahoo",
          bars: [],
          reason: "1s bars are not available for yahoo instruments",
        };
      }
      return yahooBars("AAPL", "1D");
    });

    render(<Chart symbol="AAPL" initialInterval="1s" />);

    await waitFor(() => {
      expect(fetchMock).toHaveBeenCalledWith(expect.stringContaining("interval=1D"));
    });
    /* The refusal message does not survive the corrected fetch. */
    await waitFor(() => {
      expect(screen.queryByText(/not available for yahoo instruments/)).toBeNull();
    });
    expect(screen.getByTestId("sm-chart-tf-toggle")).toHaveTextContent("1D");
  });

  it("disables provider-unsupported options in the picker once the source is known", async () => {
    fetchMock.mockImplementation(async (url: string) => {
      const match = /interval=([^&]+)/.exec(url);
      const interval = decodeURIComponent(match?.[1] ?? "15m");
      return yahooBars("AAPL", interval);
    });

    render(<Chart symbol="AAPL" />);
    await waitFor(() => {
      expect(fetchMock).toHaveBeenCalled();
    });
    await waitFor(() => {
      expect(screen.getByTestId("sm-chart-tf-toggle")).toHaveTextContent("15m");
    });

    fireEvent.click(screen.getByTestId("sm-chart-tf-toggle"));
    const oneSecond = await screen.findByRole("option", { name: "1s" });
    expect(oneSecond).toBeDisabled();
    const oneDay = screen.getByRole("option", { name: "1D" });
    expect(oneDay).not.toBeDisabled();
  });
});
