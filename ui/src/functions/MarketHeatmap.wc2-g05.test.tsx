/**
 * WC2-G05: SECT backend warnings must render even when the delivered period
 * matches the requested window (a window with missing base closes shows null
 * changes, and the warning explains why).
 */
import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";

const mockReturn: { current: unknown } = { current: null };
vi.mock("@/lib/useFunction", () => ({
  useFunction: () => mockReturn.current,
}));
vi.mock("@/lib/useVisibilityTick", () => ({
  useVisibilityTick: () => 0,
}));
vi.mock("@/lib/router", () => ({ navigate: vi.fn() }));
vi.mock("@/lib/workspace", () => ({
  useWorkspace: (sel: (s: unknown) => unknown) =>
    sel({ setFocusedTarget: vi.fn() }),
}));

import { MarketHeatmapPane } from "./MarketHeatmap";

afterEach(() => {
  cleanup();
});

describe("MarketHeatmap — SECT warnings without a period mismatch (WC2-G05)", () => {
  it("renders the backend warning when the delivered period equals the requested one", () => {
    mockReturn.current = {
      state: "ok",
      data: {
        data: {
          status: "ok",
          period: "YTD",
          change_pct_period: "YTD",
          rows: [
            {
              sector: "Technology",
              etf: "XLK",
              last: 210.5,
              change_pct: null,
              change_pct_period: null,
              period: "YTD",
              quote_type: "live",
            },
          ],
        },
        metadata: { live: true, requested_period: "YTD", live_period: "YTD" },
        sources: ["yfinance"],
        warnings: [
          "1 sector ETF(s) have no YTD base close in their daily history (XLK); their change is null, not zero",
        ],
        fetched_at: "2026-06-08T10:11:28.250007+00:00",
        elapsed_ms: 120,
      },
      error: undefined,
      refetch: vi.fn(),
    };
    render(<MarketHeatmapPane code="SECT" />);
    // The pane opens on 1D; select YTD so the requested window matches the payload.
    fireEvent.click(screen.getByRole("button", { name: "YTD", pressed: false }));

    expect(screen.queryByTestId("map-period-notice")).toBeNull();
    const notice = screen.getByTestId("map-warnings-notice");
    expect(notice.getAttribute("role")).toBe("status");
    expect(notice.textContent).toMatch(/no YTD base close/);
    expect(notice.textContent).toMatch(/not zero/);
  });
});
