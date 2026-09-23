/**
 * Chart shell — symbol prop swap WITHOUT remount (HNT-01) and load race
 * (HNT-02), jsdom.
 *
 * The workspace keeps a leaf's id when its symbol changes (link groups,
 * SymbolBar), so `<Chart symbol={x}>` re-renders instead of remounting.
 * The shell must re-read the new symbol's alert/layout stores, never
 * persist the previous symbol's state under the new key, and drop a stale
 * fetch response that resolves after a newer request. Canvas context is
 * stubbed to null (jsdom has no 2D backend) — assertions are DOM/store
 * observable.
 */
import { act, cleanup, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { BarsResponse } from "./types";

function makeBars(n: number, base: number, t0: number) {
  const bars = [];
  for (let i = 0; i < n; i++) {
    const c = base + i * 0.5;
    bars.push({ t: t0 + i * 60_000, o: c - 0.05, h: c + 0.1, l: c - 0.1, c, v: 10 + i });
  }
  return bars;
}

const fetchMock = vi.fn();

vi.mock("@/lib/sidecar", () => ({
  sidecarFetch: (...args: unknown[]) => fetchMock(...args),
}));

import { Chart } from "./Chart";
import { ALERT_STORE_KEY } from "./chart-alerts";
import { LAYOUT_STORE_KEY, loadLayout } from "./chart-layout";

class FakeResizeObserver {
  observe(): void {}
  unobserve(): void {}
  disconnect(): void {}
}

const originalGetContext = HTMLCanvasElement.prototype.getContext;

vi.spyOn(HTMLElement.prototype, "clientWidth", "get").mockReturnValue(800);
vi.spyOn(HTMLElement.prototype, "clientHeight", "get").mockReturnValue(600);

beforeEach(() => {
  fetchMock.mockReset();
  fetchMock.mockImplementation(async () => ({
    symbol: "TEST",
    interval: "15m",
    bars: makeBars(30, 100, 1_700_000_000_000),
    source: "test",
    asOf: "2026-09-15T00:00:00Z",
  }));
  (globalThis as { ResizeObserver?: unknown }).ResizeObserver = FakeResizeObserver;
  HTMLCanvasElement.prototype.getContext = (() =>
    null) as typeof HTMLCanvasElement.prototype.getContext;
  localStorage.clear();
});

afterEach(() => {
  cleanup();
  HTMLCanvasElement.prototype.getContext = originalGetContext;
});

describe("Chart symbol swap without remount (HNT-01)", () => {
  it("restores the new symbol's saved layout instead of keeping the old symbol's", async () => {
    localStorage.setItem(
      LAYOUT_STORE_KEY,
      JSON.stringify({
        AAPL: { priceMode: "log" },
        MSFT: { priceMode: "percent" },
      }),
    );
    const { rerender } = render(<Chart symbol="AAPL" refreshMs={0} />);
    expect(await screen.findByTestId("sm-chart-scale-log")).toHaveAttribute(
      "aria-pressed",
      "true",
    );

    rerender(<Chart symbol="MSFT" refreshMs={0} />);
    /* MSFT's own saved layout (percent) is restored — not AAPL's log. */
    await waitFor(() => {
      expect(screen.getByTestId("sm-chart-scale-percent")).toHaveAttribute(
        "aria-pressed",
        "true",
      );
    });
    expect(screen.getByTestId("sm-chart-scale-log")).toHaveAttribute("aria-pressed", "false");
  });

  it("never persists the old symbol's layout or alert rules under the new symbol's key", async () => {
    localStorage.setItem(
      LAYOUT_STORE_KEY,
      JSON.stringify({ AAPL: { priceMode: "log" }, MSFT: { priceMode: "percent" } }),
    );
    localStorage.setItem(
      ALERT_STORE_KEY,
      JSON.stringify({
        AAPL: {
          rules: [
            {
              id: "rule-a1",
              instanceId: "ind-1",
              indicator: "RSI",
              plotKey: "rsi",
              plotLabel: "RSI",
              op: "crossesAbove",
              value: 70,
            },
          ],
          fired: {},
        },
      }),
    );
    const { rerender } = render(<Chart symbol="AAPL" refreshMs={0} />);
    expect(await screen.findByTestId("sm-chart-scale-log")).toHaveAttribute(
      "aria-pressed",
      "true",
    );

    rerender(<Chart symbol="MSFT" refreshMs={0} />);
    await waitFor(() => {
      expect(screen.getByTestId("sm-chart-scale-percent")).toHaveAttribute(
        "aria-pressed",
        "true",
      );
    });

    /* The old symbol's entries are untouched… */
    expect(loadLayout("AAPL")?.priceMode).toBe("log");
    const alertMap = JSON.parse(localStorage.getItem(ALERT_STORE_KEY) ?? "{}") as {
      AAPL?: { rules?: unknown[] };
      MSFT?: { rules?: unknown[] };
    };
    expect(alertMap.AAPL?.rules).toHaveLength(1);
    /* …and the new symbol's key never received the old symbol's state. */
    expect(loadLayout("MSFT")?.priceMode).toBe("percent");
    expect(alertMap.MSFT?.rules ?? []).toEqual([]);
  });

  it("re-reads the new symbol's alert rules (old rules stop evaluating)", async () => {
    localStorage.setItem(
      ALERT_STORE_KEY,
      JSON.stringify({
        AAPL: {
          rules: [
            {
              id: "rule-a1",
              instanceId: "ind-1",
              indicator: "RSI",
              plotKey: "rsi",
              plotLabel: "RSI",
              op: "crossesAbove",
              value: 70,
            },
          ],
          fired: {},
        },
      }),
    );
    const { rerender } = render(<Chart symbol="AAPL" refreshMs={0} />);
    await screen.findByTestId("sm-chart-scale-linear");

    rerender(<Chart symbol="MSFT" refreshMs={0} />);
    /* MSFT has no rules — the alert list must stay empty (no re-fired
       crossings from AAPL's rules against stale bars, no spurious toast). */
    await waitFor(() => {
      expect(screen.queryByTestId("sm-chart-alert-list")).toBeNull();
    });
  });
});

describe("Chart load race (HNT-02)", () => {
  it("drops a stale response for the previous symbol when a newer one landed first", async () => {
    let resolveFirst: ((v: BarsResponse) => void) | null = null;
    fetchMock.mockImplementation(async (path: string) => {
      const url = new URL(path, "http://localhost");
      const symbol = url.searchParams.get("symbol") ?? "";
      if (symbol === "AAPL") {
        return new Promise<BarsResponse>((resolve) => {
          resolveFirst = resolve;
        });
      }
      return {
        symbol: "MSFT",
        interval: "15m",
        bars: makeBars(30, 300, 1_700_000_000_000),
        source: "msft-src",
        asOf: "2026-09-15T00:00:00Z",
      };
    });

    const { rerender } = render(<Chart symbol="AAPL" refreshMs={0} />);
    rerender(<Chart symbol="MSFT" refreshMs={0} />);
    /* MSFT lands first… */
    expect(await screen.findByText("msft-src")).toBeInTheDocument();

    /* …then the slow AAPL response arrives and must be dropped. */
    await act(async () => {
      resolveFirst?.({
        symbol: "AAPL",
        interval: "15m",
        bars: makeBars(30, 100, 1_700_000_000_000),
        source: "aapl-src",
        asOf: "2026-09-15T00:00:00Z",
      });
    });
    await waitFor(() => {
      expect(screen.queryByText("aapl-src")).toBeNull();
    });
    expect(screen.getByText("msft-src")).toBeInTheDocument();
  });
});
