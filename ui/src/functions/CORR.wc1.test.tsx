/**
 * CORR pane — served-source pill and Ref-mode banner contract (wc1-g01).
 *
 * Kept in its own file so the base CORR.test.tsx stays untouched. The
 * fixtures mirror that file's render contract.
 *
 * `useFunction` is mocked via a mutable holder so each test drives the pane into
 * a specific branch without the real sidecar transport.
 */
import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, render, screen } from "@testing-library/react";

const mockReturn: { current: unknown } = { current: null };
vi.mock("@/lib/useFunction", () => ({
  useFunction: () => mockReturn.current,
}));

import { CORRPane } from "./CORR";

/* ── fixtures ──────────────────────────────────────────────────────── */

const SYMBOLS = ["AAPL", "BTCUSDT", "EURUSD"];

// AAPL–BTCUSDT: BTCUSDT is synthetic + this pair has a LOW n (10 < 20).
// AAPL–EURUSD: both live, healthy n.
// BTCUSDT–EURUSD: synthetic leg, healthy n.
function makeMatrix() {
  return [
    {
      y: "AAPL",
      x: "BTCUSDT",
      left: "AAPL",
      right: "BTCUSDT",
      market_y: "Equity",
      market_x: "Crypto",
      correlation: 0.42,
      covariance: 0.0001,
      observations: 10,
    },
    {
      // Coefficient intentionally null (in nested dict AND matrix cell) to
      // prove the "—" sentinel; n=240 is still surfaced honestly.
      y: "AAPL",
      x: "EURUSD",
      left: "AAPL",
      right: "EURUSD",
      market_y: "Equity",
      market_x: "FX",
      correlation: null,
      covariance: null,
      observations: 240,
    },
    {
      y: "BTCUSDT",
      x: "EURUSD",
      left: "BTCUSDT",
      right: "EURUSD",
      market_y: "Crypto",
      market_x: "FX",
      correlation: -0.07,
      covariance: -0.00002,
      observations: 230,
    },
  ];
}

function makeNested() {
  // Pearson nested dict. AAPL–EURUSD intentionally null to prove the "—"
  // sentinel (NOT "N/A") for a missing coefficient.
  return {
    AAPL: { AAPL: 1, BTCUSDT: 0.42, EURUSD: null },
    BTCUSDT: { AAPL: 0.42, BTCUSDT: 1, EURUSD: -0.07 },
    EURUSD: { AAPL: null, BTCUSDT: -0.07, EURUSD: 1 },
  };
}

function makeCoverage() {
  return [
    {
      symbol: "AAPL",
      market: "Equity",
      provider_symbol: "AAPL",
      source: "yfinance",
      status: "live",
      price_points: 252,
      return_observations: 251,
      message: "",
    },
    {
      symbol: "BTCUSDT",
      market: "Crypto",
      provider_symbol: "BTCUSDT",
      source: "computed",
      status: "computed_fallback",
      price_points: 252,
      return_observations: 251,
      message: "Live fetch failed — substituted deterministic reference series.",
    },
    {
      symbol: "EURUSD",
      market: "FX",
      provider_symbol: "EURUSD=X",
      source: "yfinance",
      status: "live",
      price_points: 252,
      return_observations: 251,
      message: "",
    },
  ];
}

function okPayload() {
  return {
    data: {
      data: {
        symbols: SYMBOLS,
        pearson: makeNested(),
        spearman: {},
        downside: {},
        annualized_vol: { AAPL: 0.22, BTCUSDT: 0.65, EURUSD: 0.08 },
        rows: [],
        impactor: {
          label: "integrated_correlation_impact",
          formula: { correlation: "rho = cov / sigma sigma" },
          options: { return_method: "log", source_mode: "live" },
          observation_range: { min: 10, max: 240 },
          market_coverage: makeCoverage(),
          analysis_steps: [],
          return_series_summary: [],
          matrix: makeMatrix(),
          top_positive_pairs: [],
          top_negative_pairs: [],
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

/* ── SOURCE PILL + REF BANNER (CORR#3, CORR#9) ───────────────────── */

describe("CORR — served-source pill and Ref-mode banner (CORR#3/CORR#9)", () => {
  it("shows model, not live, when the backend served a Ref (model) run", () => {
    const payload = okPayload();
    payload.data.data.impactor.options.source_mode = "computed_reference";
    for (const row of payload.data.data.impactor.market_coverage) {
      row.status = "computed_reference";
    }
    (payload.data as unknown as { metadata: Record<string, unknown> }).metadata = {
      live: false,
      data_state: "model",
    };
    mockReturn.current = { state: "ok", ...payload };
    render(<CORRPane code="CORR" />);

    const pill = screen.getByText("model").closest(".ds-pill");
    expect(pill?.className).toMatch(/ds-pill--tone-warn/);
    expect(screen.queryByText("live")).toBeNull();
  });

  it("shows live with the positive tone only when the backend reports a live run", () => {
    const payload = okPayload();
    (payload.data as unknown as { metadata: Record<string, unknown> }).metadata = {
      live: true,
    };
    payload.data.data.impactor.market_coverage[1].status = "live";
    mockReturn.current = { state: "ok", ...payload };
    render(<CORRPane code="CORR" />);

    // The toolbar source pill sits right after the Watchlist pill.
    const served = screen.getByText(/^Watchlist \(/).closest(".ds-pill")?.nextElementSibling;
    expect(served?.textContent).toBe("live");
    expect(served?.className).toMatch(/ds-pill--tone-positive/);
  });

  it("never labels a provider outage envelope as live", () => {
    mockReturn.current = {
      state: "ok",
      data: {
        code: "CORR",
        instrument: null,
        data: { status: "provider_unavailable", reason: "no data", pearson: {}, rows: [] },
        metadata: { live: true },
        sources: [],
        warnings: [],
        elapsed_ms: 5,
        cached: false,
      },
      error: null,
      refetch: vi.fn(),
    };
    render(<CORRPane code="CORR" />);
    expect(screen.queryByText("live")).toBeNull();
  });

  it("describes Ref mode as a reference model, not as a failed live fetch", () => {
    const payload = okPayload();
    payload.data.data.impactor.options.source_mode = "computed_reference";
    payload.data.data.impactor.market_coverage[1].status = "computed_reference";
    mockReturn.current = { state: "ok", ...payload };
    render(<CORRPane code="CORR" />);

    const banner = screen.getByTestId("corr-synthetic-warning");
    expect(banner.textContent).toMatch(/Ref mode/);
    expect(banner.textContent).not.toMatch(/could not be fetched live/i);
    expect(banner.textContent).not.toMatch(/substituted/i);
  });
});
