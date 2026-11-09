/**
 * MARS — default universe, disclosed dropped legs, template regression state
 * and holdings weights input. Kept in its own file so the original
 * MultiAssetRisk.test.tsx stays untouched.
 */
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

const mockReturn: { current: unknown } = { current: null };
const mockCalls: { current: Array<{ params?: Record<string, unknown> }> } = { current: [] };
vi.mock("@/lib/useFunction", () => ({
  useFunction: (args: { params?: Record<string, unknown> }) => {
    mockCalls.current.push(args);
    return mockReturn.current;
  },
}));
vi.mock("@/lib/router", () => ({ navigate: vi.fn() }));

import { MultiAssetRiskPane } from "./MultiAssetRisk";

function ok(
  payload: Record<string, unknown>,
  envelope: { sources?: string[]; warnings?: string[]; metadata?: Record<string, unknown> } = {},
) {
  mockReturn.current = {
    state: "ok",
    data: {
      code: "MARS",
      instrument: null,
      data: payload,
      metadata: envelope.metadata ?? { live: true, factor_proxies_loaded: ["MKT", "SMB"] },
      fetched_at: "2026-09-11T00:00:00Z",
      sources: envelope.sources ?? ["yfinance"],
      warnings: envelope.warnings ?? [],
      elapsed_ms: 280,
    },
    error: undefined,
    refetch: vi.fn(),
  };
}

afterEach(() => {
  cleanup();
  mockReturn.current = null;
});

const LIVE_PAYLOAD = {
  status: "ok",
  alpha_daily: 0.00021,
  alpha_annualized: 0.053,
  factor_loadings: { MKT: 1.12, SMB: -0.31, HML: 0.22, MOM: 0.08, QMJ: 0.14, BAB: -0.05 },
  rows: [
    { factor: "MKT", loading: 1.12, abs_loading: 1.12, meaning: "Broad equity market beta." },
    { factor: "SMB", loading: -0.31, abs_loading: 0.31, meaning: "Small-cap versus large-cap tilt." },
  ],
  r_squared: 0.87,
  annualized_volatility: 0.19,
  var_95_daily_loss: 0.021,
  etl_95_daily_loss: 0.033,
  samples: 756,
  methodology: "Fama-French style regression on ETF proxies.",
};

describe("MARS default universe and disclosed dropped legs", () => {
  it("defaults to the Yahoo-served universe without BTCUSDT", () => {
    ok(LIVE_PAYLOAD);
    render(<MultiAssetRiskPane code="MARS" />);
    expect(screen.getByLabelText("Universe")).toHaveValue("SPY,TLT,GLD");
  });

  it("shows the backend warning naming a leg that had no series", () => {
    ok(LIVE_PAYLOAD, {
      metadata: { live: false, fallback: true, data_mode: "modeled", factor_proxies_loaded: ["MKT", "SMB"] },
      warnings: ["Live return series unavailable for: BTCUSDT; the portfolio was computed over the 1/2 requested legs that loaded (AAPL) only."],
    });
    render(<MultiAssetRiskPane code="MARS" />);
    expect(screen.getByTestId("portx-warning-strip")).toHaveTextContent("BTCUSDT");
    expect(screen.getByTestId("portx-data-badge")).toBeInTheDocument();
  });
});

describe("MARS template regression state", () => {
  const TEMPLATE_PAYLOAD = {
    status: "ok",
    alpha_daily: null,
    alpha_annualized: null,
    factor_loadings: {},
    rows: [],
    r_squared: null,
    regression_state: "not_estimated_template",
    risk_basis: "template_series",
    annualized_volatility: 0.12,
    var_95_daily_loss: 0.011,
    etl_95_daily_loss: 0.017,
    samples: null,
    methodology: "Template regression.",
  };

  it("withholds R2 and loadings, says why, and keeps the labelled risk figures", () => {
    ok(TEMPLATE_PAYLOAD, {
      sources: ["multi_asset_risk_model"],
      metadata: { live: false, fallback: true, data_mode: "modeled", factor_proxies_loaded: [] },
      warnings: [
        "Regression statistics (R-squared, alpha, factor loadings) are not estimated because the regression input is the labelled template series.",
      ],
    });
    render(<MultiAssetRiskPane code="MARS" />);
    expect(screen.queryByText("No data available")).toBeNull();
    expect(
      screen.getByText("Regression not estimated: the regression input is the labelled template series."),
    ).toBeInTheDocument();
    expect(screen.getByTestId("portx-data-badge")).toBeInTheDocument();
    expect(screen.getByTestId("portx-warning-strip")).toHaveTextContent("not estimated");
  });
});

describe("MARS holdings weights input", () => {
  it("sends the holdings weights to the backend and clears them when empty", () => {
    ok(LIVE_PAYLOAD);
    render(<MultiAssetRiskPane code="MARS" />);
    const lastParams = () =>
      mockCalls.current[mockCalls.current.length - 1]?.params as { weights?: string } | undefined;
    expect(lastParams()?.weights).toBe("");
    fireEvent.change(screen.getByLabelText("Holdings weights"), {
      target: { value: "spy:0.6,tlt:0.4" },
    });
    expect(lastParams()?.weights).toBe("SPY:0.6,TLT:0.4");
  });
});
