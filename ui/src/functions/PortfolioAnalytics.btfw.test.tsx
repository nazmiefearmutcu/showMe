/**
 * PORTX — BTFW title and subtitle (BTFW#5).
 *
 * Kept separate from PortfolioAnalytics.test.tsx so the shared PORTX suite
 * stays untouched. BTFW is the historical walk-forward out-of-sample test; its
 * header must not describe a forward-looking template run, and its subtitle
 * must not promise a stitched OOS equity curve (only a live run produces one).
 */
import { cleanup, render } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

const mockReturn: { current: unknown } = { current: null };
vi.mock("@/lib/useFunction", () => ({
  useFunction: () => mockReturn.current,
}));
vi.mock("@/lib/router", () => ({ navigate: vi.fn() }));

import { PortfolioAnalyticsPane } from "./PortfolioAnalytics";

function mockOk(payload: Record<string, unknown>) {
  mockReturn.current = {
    state: "ok",
    data: {
      data: payload,
      metadata: { live: true },
      sources: ["showme engine"],
      warnings: [],
      elapsed_ms: 90,
    },
    error: undefined,
    refetch: vi.fn(),
  };
}

afterEach(() => {
  cleanup();
  mockReturn.current = null;
});

const LIVE_ROWS = [
  { symbol: "SPY", weight_pct: 0.4, total_pnl: 1200, return: 0.08 },
  { symbol: "QQQ", weight_pct: 0.6, total_pnl: -800, return: -0.03 },
];

describe("PORTX BTFW header (BTFW#5)", () => {
  it("titles BTFW as the historical walk-forward backtest it is", () => {
    mockOk({ status: "ok", rows: LIVE_ROWS });
    const { container } = render(<PortfolioAnalyticsPane code="BTFW" symbol="" />);
    expect(container.textContent).toContain("Walk-Forward Backtest");
    expect(container.textContent).not.toContain("Backtest Forward");
    expect(container.textContent).not.toContain("Forward-looking portfolio template run");
  });

  it("does not claim a stitched OOS curve in the subtitle", () => {
    mockOk({ status: "ok", rows: LIVE_ROWS });
    const { container } = render(<PortfolioAnalyticsPane code="BTFW" symbol="" />);
    expect(container.textContent).toContain("out-of-sample folds");
    expect(container.textContent).not.toContain("stitched");
  });
});
