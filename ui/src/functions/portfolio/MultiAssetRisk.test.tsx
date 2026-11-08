/**
 * MARS — specialized Multi-Asset Risk pane tests.
 *
 * Pins the four render states, the factor loading table/bars, the proxy
 * disclosure strip, and the MODEL toggle.
 */
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

const mockReturn: { current: unknown } = { current: null };
vi.mock("@/lib/useFunction", () => ({ useFunction: () => mockReturn.current }));
vi.mock("@/lib/router", () => ({ navigate: vi.fn() }));

import { MultiAssetRiskPane, deriveFactorWaterfall } from "./MultiAssetRisk";

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

describe("MARS Multi-Asset Risk pane", () => {
  it("renders a loading skeleton", () => {
    mockReturn.current = { state: "loading", data: undefined, error: undefined, refetch: vi.fn() };
    const { container } = render(<MultiAssetRiskPane code="MARS" />);
    expect(container.querySelector('[aria-busy="true"]')).not.toBeNull();
  });

  it("renders the error state with a working Retry", () => {
    const refetch = vi.fn();
    mockReturn.current = { state: "error", data: undefined, error: new Error("mars boom"), refetch };
    render(<MultiAssetRiskPane code="MARS" />);
    expect(screen.getByText(/mars boom/i)).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Retry" }));
    expect(refetch).toHaveBeenCalled();
  });

  it("renders the empty state when no factor rows are returned", () => {
    ok({ status: "ok", rows: [] });
    render(<MultiAssetRiskPane code="MARS" />);
    expect(screen.getByText("No data available")).toBeInTheDocument();
  });

  it("renders the alpha hero, loading table, proxy strip and warnings", () => {
    ok(LIVE_PAYLOAD, {
      metadata: { live: true, factor_proxies_loaded: ["MKT", "SMB"] },
      warnings: ["Live ETF factor proxy data was unavailable for: HML"],
    });
    const { container } = render(<MultiAssetRiskPane code="MARS" />);
    expect(screen.getByText("+5.30%")).toBeInTheDocument();
    expect(screen.getByText("Broad equity market beta.")).toBeInTheDocument();
    expect(screen.getByText("Factor proxies loaded")).toBeInTheDocument();
    expect(screen.getByTestId("portx-warning-strip")).toBeInTheDocument();
    expect(container.querySelectorAll("table").length).toBe(1);
    expect(screen.queryByTestId("portx-data-badge")).toBeNull();
  });

  it("discloses the template factor model via the shared badge", () => {
    ok(LIVE_PAYLOAD, { sources: ["multi_asset_risk_model"], metadata: { live: false, fallback: true, data_mode: "modeled" } });
    render(<MultiAssetRiskPane code="MARS" />);
    expect(screen.getByTestId("portx-data-badge")).toBeInTheDocument();
  });

  it("toggles the MODEL (reference) control state", () => {
    ok(LIVE_PAYLOAD);
    render(<MultiAssetRiskPane code="MARS" />);
    fireEvent.click(screen.getByRole("button", { name: "LIVE" }));
    expect(screen.getByRole("button", { name: "MODEL" })).toBeInTheDocument();
  });
});

describe("MARS factor contribution waterfall (real derivation)", () => {
  const MIXED_ROWS = [
    { factor: "SMB", loading: -0.31, abs_loading: 0.31, meaning: "Small-cap versus large-cap tilt." },
    { factor: "MKT", loading: 1.12, abs_loading: 1.12, meaning: "Broad equity market beta." },
    { factor: "BAB", loading: -0.05, abs_loading: 0.05, meaning: "Low-volatility tilt." },
    { factor: "QMJ", loading: 0.14, abs_loading: 0.14, meaning: "Quality tilt." },
  ];

  it("sorts by |loading| descending and keeps the signed beta", () => {
    const factors = deriveFactorWaterfall(MIXED_ROWS);
    expect(factors.map((entry) => entry.factor)).toEqual(["MKT", "SMB", "QMJ", "BAB"]);
    expect(factors.find((entry) => entry.factor === "SMB")!.loading).toBe(-0.31);
    expect(factors.find((entry) => entry.factor === "SMB")!.absLoading).toBe(0.31);
  });

  it("falls back to |loading| and drops rows that carry no real beta", () => {
    const factors = deriveFactorWaterfall([
      { factor: "MKT", loading: 0.8 },
      { factor: "BAD", loading: "x" },
      { loading: 1.0 },
    ]);
    expect(factors.map((entry) => entry.factor)).toEqual(["MKT"]);
    expect(factors[0].absLoading).toBe(0.8);
  });

  it("renders the signed waterfall in |loading| order with direction flags", () => {
    ok({ ...LIVE_PAYLOAD, rows: MIXED_ROWS });
    render(<MultiAssetRiskPane code="MARS" />);
    const panel = screen.getByTestId("mars-waterfall");
    const ordered = [...panel.querySelectorAll("[data-factor]")].map((el) =>
      el.getAttribute("data-factor"),
    );
    expect(ordered).toEqual(["MKT", "SMB", "QMJ", "BAB"]);
    expect(panel.querySelector('[data-factor="SMB"]')!.getAttribute("data-direction")).toBe("neg");
    expect(panel.querySelector('[data-factor="MKT"]')!.getAttribute("data-direction")).toBe("pos");
    expect(panel.textContent).toContain("+1.1200");
    expect(panel.textContent).toContain("-0.3100");
    expect(panel.textContent).toContain("negative = hedges it");
  });

  it("degrades honestly when rows carry no numeric loading", () => {
    ok({ ...LIVE_PAYLOAD, rows: [{ factor: "MKT", meaning: "Broad equity market beta." }] });
    render(<MultiAssetRiskPane code="MARS" />);
    expect(screen.getByText("No factor loadings returned.")).toBeInTheDocument();
  });
});
