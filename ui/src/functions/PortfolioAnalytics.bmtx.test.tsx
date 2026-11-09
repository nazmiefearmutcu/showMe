/**
 * BMTX#7 regression: the Backtest Matrix pane is titled after its function,
 * not the old "Behavior Matrix" diagnostic label.
 */
import { cleanup, render, screen } from "@testing-library/react";
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

describe("BMTX pane identity (wc1-g08 BMTX#7)", () => {
  it("is titled after the Backtest Matrix function, not a behavior diagnostic", () => {
    mockOk({ status: "needs_input", cells: [] });
    render(<PortfolioAnalyticsPane code="BMTX" symbol="" />);
    expect(screen.getAllByText("Backtest Matrix").length).toBeGreaterThan(0);
    expect(screen.queryByText("Behavior Matrix")).toBeNull();
  });
});
