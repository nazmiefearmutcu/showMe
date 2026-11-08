/**
 * CORR pane — a missing pair coefficient is never drawn as zero (UI-15 follow-up).
 *
 * The matrix cells already pass `null` through to HeatCell. The "Top +/−
 * correlations" list used `row.correlation ?? 0`, so a missing coefficient was
 * tinted and printed as 0.00 / 0.000. This file pins the honest empty state.
 */
import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, render, screen } from "@testing-library/react";

const mockReturn: { current: unknown } = { current: null };
vi.mock("@/lib/useFunction", () => ({
  useFunction: () => mockReturn.current,
}));

import { CORRPane } from "./CORR";

const SYMBOLS = ["AAPL", "BTCUSDT"];

function payloadWithMissingPair() {
  const nested = {
    AAPL: { AAPL: 1, BTCUSDT: null },
    BTCUSDT: { AAPL: null, BTCUSDT: 1 },
  };
  const missingPair = {
    left: "AAPL",
    right: "BTCUSDT",
    market_pair: "Equity / Crypto",
    correlation: null,
    covariance: null,
    observations: 12,
  };
  return {
    data: {
      data: {
        symbols: SYMBOLS,
        pearson: nested,
        spearman: {},
        downside: {},
        annualized_vol: { AAPL: 0.22, BTCUSDT: 0.65 },
        rows: [],
        impactor: {
          label: "integrated_correlation_impact",
          formula: { correlation: "rho = cov / sigma sigma" },
          options: { return_method: "log", source_mode: "live" },
          observation_range: { min: 12, max: 12 },
          market_coverage: [],
          analysis_steps: [],
          return_series_summary: [],
          matrix: [
            {
              y: "AAPL", x: "BTCUSDT", left: "AAPL", right: "BTCUSDT",
              market_y: "Equity", market_x: "Crypto",
              correlation: null, covariance: null, observations: 12,
            },
          ],
          top_positive_pairs: [missingPair],
          top_negative_pairs: [missingPair],
          selected_pair: null,
          bug_analysis: [],
        },
      },
      sources: ["yfinance"],
      elapsed_ms: 120,
      cached: false,
    },
    error: null,
    refetch: vi.fn(),
  };
}

afterEach(() => {
  cleanup();
  mockReturn.current = null;
});

describe("CORR — missing pair coefficient is not drawn as zero (UI-15)", () => {
  it("does not print or tint a null pair coefficient as 0.00 / 0.000", () => {
    mockReturn.current = { state: "ok", ...payloadWithMissingPair() };
    render(<CORRPane code="CORR" />);

    expect(screen.queryByText("0.000")).toBeNull();
    expect(screen.queryByText("0.00")).toBeNull();
    expect(screen.queryByLabelText("value 0.00")).toBeNull();
  });

  it("renders the missing sentinel for a null pair coefficient in the pair list", () => {
    mockReturn.current = { state: "ok", ...payloadWithMissingPair() };
    render(<CORRPane code="CORR" />);

    // HeatCell's default aria for a null value is "no value"; the pair list
    // renders its swatch without a custom label, so it is the one that shows it.
    expect(screen.getAllByLabelText("no value").length).toBeGreaterThan(0);
  });
});
