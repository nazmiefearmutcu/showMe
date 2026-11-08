/**
 * PORTX — Black-Litterman pane tests (BLAK#5 / BLAK#6 / BLAK#3-RQ).
 *
 * These cases used to sit appended to PortfolioAnalytics.test.tsx. They live
 * in their own file so the shared pane test file stays exactly as it was.
 */
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

const mockReturn: { current: unknown } = { current: null };
const mockArgs: {
  current: { code?: string; symbol?: string; params?: Record<string, unknown> } | null;
} = { current: null };
vi.mock("@/lib/useFunction", () => ({
  useFunction: (args: unknown) => {
    mockArgs.current = args as (typeof mockArgs)["current"];
    return mockReturn.current;
  },
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
  mockArgs.current = null;
});

const LIVE_ROWS = [
  { symbol: "SPY", weight_pct: 0.4, total_pnl: 1200, return: 0.08 },
  { symbol: "QQQ", weight_pct: 0.6, total_pnl: -800, return: -0.03 },
];

describe("PORTX BLAK honest no-prior state (BLAK#6 / BLAK#3-RQ)", () => {
  it("shows an Input Required state for needs_input and no prior rows", () => {
    mockOk({
      status: "needs_input",
      reason: "Live market data is off. The Black-Litterman prior needs historical returns.",
      next_actions: ["Turn Live on and run again to compute the prior from market returns."],
      market_weights: { SPY: 0.5, QQQ: 0.5 },
    });
    render(<PortfolioAnalyticsPane code="BLAK" symbol="" />);
    expect(screen.getByText("Input Required")).toBeInTheDocument();
    expect(screen.getByText(/Live market data is off/)).toBeInTheDocument();
    expect(screen.queryByText("No data available")).toBeNull();
  });
});

describe("PORTX BLAK prior inputs reachable from the pane (BLAK#5)", () => {
  it("exposes window, tau, delta and views controls and sends them", () => {
    mockOk({ status: "ok", rows: LIVE_ROWS });
    render(<PortfolioAnalyticsPane code="BLAK" symbol="" />);
    expect((screen.getByLabelText("Window") as HTMLSelectElement).value).toBe("1Y");
    expect((screen.getByLabelText("Tau") as HTMLInputElement).value).toBe("0.05");
    expect((screen.getByLabelText("Risk aversion (δ)") as HTMLInputElement).value).toBe("2.5");
    expect(mockArgs.current?.params).toMatchObject({
      window: "1Y",
      tau: "0.05",
      delta: "2.5",
      views_text: "",
    });
    fireEvent.change(screen.getByLabelText("Window"), { target: { value: "2Y" } });
    fireEvent.change(screen.getByLabelText("Views"), { target: { value: "aapl:8, spy:5" } });
    expect(mockArgs.current?.params).toMatchObject({
      window: "2Y",
      views_text: "AAPL:8, SPY:5",
    });
  });

  it("sends relative views typed as LONG>SHORT:percent", () => {
    mockOk({ status: "ok", rows: LIVE_ROWS });
    render(<PortfolioAnalyticsPane code="BLAK" symbol="" />);
    fireEvent.change(screen.getByLabelText("Views"), { target: { value: "aapl>spy:2, msft:9" } });
    expect(mockArgs.current?.params).toMatchObject({ views_text: "AAPL>SPY:2, MSFT:9" });
  });

  it("exposes a market-cap override control and sends it as SYMBOL:USD text", () => {
    mockOk({ status: "ok", rows: LIVE_ROWS });
    render(<PortfolioAnalyticsPane code="BLAK" symbol="" />);
    const caps = screen.getByLabelText("Market caps") as HTMLInputElement;
    expect(caps.value).toBe("");
    expect(mockArgs.current?.params).toMatchObject({ market_caps: "" });
    fireEvent.change(caps, { target: { value: "SPY:7.9e11, QQQ:3e11" } });
    expect(mockArgs.current?.params).toMatchObject({ market_caps: "SPY:7.9e11, QQQ:3e11" });
  });
});
