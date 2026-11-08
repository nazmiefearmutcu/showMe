/**
 * WHAL#3 — the pane must not present rows with no USD value as threshold-tested.
 *
 * FX impulse rows and SEC filings carry no USD value, so the Min USD floor cannot
 * be applied to them. The header must not read "0 crossed $1M" as if a test ran,
 * and the backend summary that says so must reach the user while rows are shown.
 */
import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, render, screen } from "@testing-library/react";
import { WHALPane } from "./WHAL";

const SUMMARY = "EURUSD (FX): no row has a USD value, so $1,000,000 could not be tested.";

vi.mock("@/lib/useFunction", () => ({
  useFunction: () => ({
    state: "ok",
    data: {
      data: {
        status: "ok",
        provider: "cross_market_public_proxy",
        market: "FX",
        lookback_hours: 24,
        rows: [
          {
            timestamp: "2026-09-11T00:00:00Z",
            alert_type: "liquidity_impulse_proxy",
            symbol: "EURUSD",
            usd_value: null,
            threshold_crossed: null,
            direction: "up",
            severity: "low",
            source_mode: "yahoo_price_impulse_proxy",
          },
        ],
        cards: [],
        summary: SUMMARY,
      },
      sources: ["yahoo_chart_public"],
    },
    error: null,
    refetch: vi.fn(),
  }),
}));

vi.mock("@/lib/useVisibilityTick", () => ({
  useVisibilityTick: () => 0,
}));

afterEach(() => {
  cleanup();
});

describe("WHAL pane — USD basis disclosure (WHAL#3)", () => {
  it("shows the backend summary next to the rows", () => {
    render(<WHALPane code="WHAL" symbol="EURUSD" />);
    expect(screen.getByText(SUMMARY)).toBeInTheDocument();
  });

  it("does not claim a threshold test ran when no row has a USD value", () => {
    render(<WHALPane code="WHAL" symbol="EURUSD" />);
    expect(screen.getByText(/no USD basis to test \$1M/)).toBeInTheDocument();
    expect(screen.queryByText(/0 crossed/)).toBeNull();
  });
});
