/**
 * MARS partial-live labelling (MARS#3-RQ). A result where some live series
 * feed the regression but a leg or factor proxy was dropped or templated is
 * data_mode "partial_live": it must show the partial-live badge, never the
 * SAMPLE/MODEL badge. Kept in its own file beside MultiAssetRisk.test.tsx.
 */
import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

const mockReturn: { current: unknown } = { current: null };
vi.mock("@/lib/useFunction", () => ({
  useFunction: () => mockReturn.current,
}));
vi.mock("@/lib/router", () => ({ navigate: vi.fn() }));

import { MultiAssetRiskPane } from "./MultiAssetRisk";

function ok(
  payload: Record<string, unknown>,
  envelope: { sources: string[]; warnings: string[]; metadata: Record<string, unknown> },
) {
  mockReturn.current = {
    state: "ok",
    data: {
      code: "MARS",
      instrument: null,
      data: payload,
      metadata: envelope.metadata,
      fetched_at: "2026-09-11T00:00:00Z",
      sources: envelope.sources,
      warnings: envelope.warnings,
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

const PARTIAL_PAYLOAD = {
  status: "ok",
  alpha_daily: 0.0002,
  alpha_annualized: 0.05,
  factor_loadings: { MKT: 1.1, SMB: -0.3 },
  rows: [
    { factor: "MKT", loading: 1.1, abs_loading: 1.1, meaning: "Broad equity market beta." },
    { factor: "SMB", loading: -0.3, abs_loading: 0.3, meaning: "Small-cap versus large-cap tilt." },
  ],
  r_squared: 0.8,
  annualized_volatility: 0.18,
  var_95_daily_loss: 0.02,
  etl_95_daily_loss: 0.03,
  samples: 500,
  methodology: "Fama-French style regression on ETF proxies.",
};

describe("MARS partial-live badge", () => {
  it("labels a partial_live result partial live, not sample or model", () => {
    ok(PARTIAL_PAYLOAD, {
      sources: ["yfinance", "multi_asset_risk_model"],
      warnings: [
        "Live return series unavailable for: BTCUSDT; the portfolio was computed over the 1/2 requested legs that loaded (AAPL) only.",
      ],
      metadata: {
        live: false,
        fallback: true,
        data_mode: "partial_live",
        factor_proxies_loaded: ["MKT", "SMB"],
        legs_loaded: ["AAPL"],
        legs_missing: ["BTCUSDT"],
      },
    });
    render(<MultiAssetRiskPane code="MARS" />);
    const badge = screen.getByTestId("portx-data-badge");
    expect(badge).toHaveTextContent("PARTIAL LIVE DATA");
    expect(badge).not.toHaveTextContent("SAMPLE/MODEL DATA");
    expect(screen.getByTestId("portx-warning-strip")).toHaveTextContent("BTCUSDT");
  });

  it("keeps the modeled badge for a fully templated result", () => {
    ok(PARTIAL_PAYLOAD, {
      sources: ["multi_asset_risk_model"],
      warnings: ["Live symbol return series were unavailable; portfolio legs use the labelled template series."],
      metadata: { live: false, fallback: true, data_mode: "modeled", factor_proxies_loaded: [] },
    });
    render(<MultiAssetRiskPane code="MARS" />);
    expect(screen.getByTestId("portx-data-badge")).toHaveTextContent("SAMPLE/MODEL DATA");
  });
});
