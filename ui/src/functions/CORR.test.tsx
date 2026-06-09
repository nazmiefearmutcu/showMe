/**
 * CORR pane — data-honesty + a11y render-contract tests.
 *
 * The correlation MATH is correct, but two truths shipped in the payload were
 * hidden from the user:
 *
 *  1. SYNTHETIC fallback shown as real. When a symbol can't be fetched live the
 *     backend substitutes a deterministic reference series (status
 *     "computed_fallback"/"computed_reference") — which even bakes in
 *     cross-market correlation. The pane now NAMES those symbols in a prominent
 *     warning banner above the heatmap, marks them in the matrix headers, and
 *     notes "(sentetik leg)" in any cell aria-label that touches one.
 *  2. SAMPLE SIZE (n) hidden. Each cell carries a real per-pair `observations`
 *     count; the pane now exposes n in every HeatCell aria-label/title and warns
 *     when off-diagonal pairs were computed on < 20 observations.
 *
 * These tests also pin the a11y contract (table caption + scope, run-button
 * aria-busy, role=status error) and the format.ts "—" sentinel (NOT "N/A").
 *
 * `useFunction` is mocked via a mutable holder so each test drives the pane into
 * a specific branch without the real sidecar transport.
 */
import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, render, screen, within } from "@testing-library/react";

// Each test installs its own useFunction return via this mutable holder.
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

function setOk() {
  mockReturn.current = { state: "ok", ...okPayload() };
}

afterEach(() => {
  cleanup();
  mockReturn.current = null;
});

/* ── HONESTY ──────────────────────────────────────────────────────── */

describe("CORR — synthetic-data honesty (H1/H2)", () => {
  it("renders a prominent warning banner that NAMES the synthetic symbol", () => {
    setOk();
    render(<CORRPane code="CORR" />);
    const banner = screen.getByTestId("corr-synthetic-warning");
    expect(banner).toBeInTheDocument();
    expect(banner.getAttribute("role")).toBe("status");
    // Names the synthetic symbol specifically.
    expect(within(banner).getByText(/BTCUSDT/)).toBeInTheDocument();
    // States it is not real market data.
    expect(banner.textContent).toMatch(/sentetik/i);
    expect(banner.textContent).toMatch(/gerçek piyasa/i);
    // A purely-live symbol is NOT named as synthetic in the banner.
    expect(banner.textContent).not.toMatch(/EURUSD/);
  });

  it("does NOT render the synthetic banner when every symbol is live", () => {
    const payload = okPayload();
    // Flip BTCUSDT to live.
    payload.data.data.impactor.market_coverage[1].status = "live";
    mockReturn.current = { state: "ok", ...payload };
    render(<CORRPane code="CORR" />);
    expect(screen.queryByTestId("corr-synthetic-warning")).toBeNull();
  });
});

describe("CORR — per-pair sample size + honest cell labels (H3)", () => {
  it("gives each HeatCell an aria-label with the symbol pair, value, and n", () => {
    setOk();
    render(<CORRPane code="CORR" />);
    // Live healthy pair: AAPL–EURUSD coefficient is null → "—", n=240.
    const liveCell = screen.getByLabelText(/AAPL–EURUSD Pearson: —, n=240/);
    expect(liveCell).toBeInTheDocument();
    // No synthetic-leg note for a fully-live pair.
    expect(liveCell.getAttribute("aria-label")).not.toMatch(/sentetik leg/);
  });

  it("appends (sentetik leg) when a pair touches a synthetic symbol", () => {
    setOk();
    render(<CORRPane code="CORR" />);
    const synthCell = screen.getByLabelText(
      /AAPL–BTCUSDT Pearson: .+, n=10 \(sentetik leg\)/,
    );
    expect(synthCell).toBeInTheDocument();
  });
});

describe("CORR — low-n honesty (H4)", () => {
  it("warns when off-diagonal pairs are computed on < 20 observations", () => {
    setOk();
    render(<CORRPane code="CORR" />);
    const warn = screen.getByTestId("corr-low-n-warning");
    expect(warn).toBeInTheDocument();
    // Exactly one pair (AAPL–BTCUSDT, n=10) is below the threshold.
    expect(warn.textContent).toMatch(/1 çift/);
    expect(warn.textContent).toMatch(/güvenilmez/i);
  });

  it("does NOT render the low-n warning when all pairs are well-sampled", () => {
    const payload = okPayload();
    payload.data.data.impactor.matrix[0].observations = 200; // lift the low pair
    mockReturn.current = { state: "ok", ...payload };
    render(<CORRPane code="CORR" />);
    expect(screen.queryByTestId("corr-low-n-warning")).toBeNull();
  });
});

/* ── A11Y ─────────────────────────────────────────────────────────── */

describe("CORR — accessibility (A1/A2/A3)", () => {
  it("gives the matrix table a caption and scope on headers", () => {
    setOk();
    const { container } = render(<CORRPane code="CORR" />);
    const caption = container.querySelector("table caption");
    expect(caption).not.toBeNull();
    expect(caption?.textContent).toMatch(/korelasyon matrisi/i);
    // Column + row scoped headers exist.
    expect(container.querySelector('th[scope="col"]')).not.toBeNull();
    expect(container.querySelector('th[scope="row"]')).not.toBeNull();
  });

  it("sets aria-busy on the Run button while loading", () => {
    mockReturn.current = {
      state: "loading",
      data: undefined,
      error: null,
      refetch: vi.fn(),
    };
    render(<CORRPane code="CORR" />);
    const runBtn = screen.getByRole("button", {
      name: /run correlation analysis/i,
    });
    expect(runBtn.getAttribute("aria-busy")).toBe("true");
  });

  it("announces the error state via role=status", () => {
    mockReturn.current = {
      state: "error",
      data: undefined,
      error: new Error("sidecar exploded"),
      refetch: vi.fn(),
    };
    const { container } = render(<CORRPane code="CORR" />);
    const status = container.querySelector('[role="status"]');
    expect(status).not.toBeNull();
    expect(status?.textContent).toMatch(/sidecar exploded/i);
  });
});

/* ── DISPLAY (DI1) ────────────────────────────────────────────────── */

describe("CORR — formatter sentinel (DI1)", () => {
  it("renders the em-dash '—' (NOT 'N/A') for a null coefficient", () => {
    setOk();
    const { container } = render(<CORRPane code="CORR" />);
    // The AAPL–EURUSD cell coefficient is null → must be the app-wide sentinel.
    expect(container.textContent).not.toMatch(/N\/A/);
    const nullCell = screen.getByLabelText(/AAPL–EURUSD Pearson: —, n=240/);
    expect(nullCell.textContent).toContain("—");
  });
});
