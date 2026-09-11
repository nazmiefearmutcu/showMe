/**
 * PORTX — Portfolio Analytics shared-pane tests.
 *
 * The single PortfolioAnalyticsPane backs 20 function codes. These tests
 * pin the SHARED honesty-first hardening that lifts all of them at once:
 *
 *  H1 — a single data-quality badge (`portx-data-badge`, role=status) that
 *       detects the HETEROGENEOUS "not-fully-live" signals the backend
 *       already emits (sources matching /model|template|reference|sample|
 *       synthetic/i, data_mode "modeled", return_data_state
 *       "synthetic_fallback", source_mode, fallback flags, metadata.degraded)
 *       and surfaces them prominently — in BOTH the populated and the empty
 *       branch — while staying silent for a genuinely live payload.
 *  D1 — sign-coloured financial numerics (P&L / return / drawdown / …),
 *       neutral keys (weight / vol / price) left uncoloured.
 *  A2 — DataGrid ariaLabel, warnings strip role=status, bound control label.
 *  U1 — all 20 codes reachable from the toolbar strip.
 */
import { cleanup, fireEvent, render, screen, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

// Each test installs its own useFunction mock via this mutable holder.
const mockReturn: { current: unknown } = { current: null };
// Captures the args useFunction was last called with, so parameter wiring
// (REBA capital, MLSIG live_ml, BTUNE/BMTX live_backtest, LOTS defaults) can
// be asserted without a real fetch.
const mockArgs: {
  current: { code?: string; symbol?: string; params?: Record<string, unknown> } | null;
} = { current: null };
vi.mock("@/lib/useFunction", () => ({
  useFunction: (args: unknown) => {
    mockArgs.current = args as (typeof mockArgs)["current"];
    return mockReturn.current;
  },
}));
// Router navigate is a side-effect we don't need to drive here.
vi.mock("@/lib/router", () => ({ navigate: vi.fn() }));

import { PortfolioAnalyticsPane, buildRebaOrdersCsv } from "./PortfolioAnalytics";

/**
 * Build a useFunction "ok" result. `payload` is the inner `data.data`
 * object (the PortfolioPayload); the outer envelope carries
 * sources / warnings / metadata exactly like the real hook.
 */
function mockOk(
  payload: Record<string, unknown>,
  envelope: {
    sources?: string[];
    warnings?: string[];
    metadata?: Record<string, unknown>;
  } = {},
) {
  mockReturn.current = {
    state: "ok",
    data: {
      data: payload,
      metadata: envelope.metadata ?? { live: true },
      sources: envelope.sources ?? ["showme engine"],
      warnings: envelope.warnings ?? [],
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

describe("PORTX shared data-quality badge (H1)", () => {
  it("fires for a synthetic source (sources: computed_return_model)", () => {
    mockOk(
      { status: "ok", rows: LIVE_ROWS },
      { sources: ["computed_return_model"] },
    );
    render(<PortfolioAnalyticsPane code="PORT_OPT" symbol="" />);
    const badge = screen.getByTestId("portx-data-badge");
    expect(badge).toBeTruthy();
    expect(badge.getAttribute("role")).toBe("status");
    expect(badge.textContent?.toLowerCase()).toContain("not a live market");
  });

  it("fires for data_mode: modeled", () => {
    mockOk({ status: "ok", data_mode: "modeled", rows: LIVE_ROWS });
    render(<PortfolioAnalyticsPane code="PVAR" symbol="" />);
    expect(screen.getByTestId("portx-data-badge")).toBeTruthy();
  });

  it("fires for return_data_state: synthetic_fallback", () => {
    mockOk({ status: "ok", return_data_state: "synthetic_fallback", rows: LIVE_ROWS });
    render(<PortfolioAnalyticsPane code="BLAK" symbol="" />);
    expect(screen.getByTestId("portx-data-badge")).toBeTruthy();
  });

  it("fires for source_mode containing template/reference", () => {
    mockOk({ status: "reference", source_mode: "reference_template", rows: LIVE_ROWS });
    render(<PortfolioAnalyticsPane code="BTUNE" symbol="" />);
    expect(screen.getByTestId("portx-data-badge")).toBeTruthy();
  });

  it("fires for metadata.degraded / fallback envelope", () => {
    mockOk({ status: "ok", rows: LIVE_ROWS }, { metadata: { degraded: true } });
    render(<PortfolioAnalyticsPane code="MARS" symbol="" />);
    expect(screen.getByTestId("portx-data-badge")).toBeTruthy();
  });

  it("fires for a sources entry matching the synthetic regex (total_return_model)", () => {
    mockOk({ status: "ok", rows: LIVE_ROWS }, { sources: ["yfinance", "total_return_model"] });
    render(<PortfolioAnalyticsPane code="TRA" symbol="" />);
    expect(screen.getByTestId("portx-data-badge")).toBeTruthy();
  });

  it("surfaces the reason in the badge title for fallback payloads", () => {
    mockOk({
      status: "ok",
      fallback: true,
      fallback_reason: "live provider timeout",
      rows: LIVE_ROWS,
    });
    render(<PortfolioAnalyticsPane code="RPAR" symbol="" />);
    const badge = screen.getByTestId("portx-data-badge");
    expect(badge.getAttribute("title")?.toLowerCase()).toContain("live provider timeout");
  });

  it("renders the badge in the EMPTY-rows branch for a synthetic payload", () => {
    mockOk(
      { status: "ready_no_positions", rows: [] },
      { sources: ["sample_template"] },
    );
    render(<PortfolioAnalyticsPane code="TLH" symbol="" />);
    // Empty state still renders, AND the disclosure survives zero rows.
    expect(screen.getByTestId("portx-data-badge")).toBeTruthy();
  });

  it("does NOT fire for a genuinely live payload", () => {
    mockOk(
      { status: "ok", rows: LIVE_ROWS },
      { sources: ["yfinance", "binance"], metadata: { live: true } },
    );
    render(<PortfolioAnalyticsPane code="MARS" symbol="" />);
    expect(screen.queryByTestId("portx-data-badge")).toBeNull();
  });

  // P2a — "reference" in a FREE-TEXT provider source name must NOT brand
  // live data as MODEL. The token is too ambiguous (e.g. a security-master
  // "*_reference_*"); only the CONTROLLED enum fields may detect "reference".
  it("does NOT fire for a live payload whose sources name contains 'reference'", () => {
    mockOk(
      { status: "ok", rows: LIVE_ROWS },
      { sources: ["bloomberg_reference"], metadata: { live: true } },
    );
    render(<PortfolioAnalyticsPane code="MARS" symbol="" />);
    expect(screen.queryByTestId("portx-data-badge")).toBeNull();
  });

  // …but the CONTROLLED `status` enum still detects "reference".
  it("STILL fires for status: reference (a controlled enum field)", () => {
    mockOk({ status: "reference", rows: LIVE_ROWS });
    render(<PortfolioAnalyticsPane code="MARS" symbol="" />);
    expect(screen.getByTestId("portx-data-badge")).toBeTruthy();
  });
});

describe("PORTX classifier coverage for placeholder/sample payloads (F3)", () => {
  it("badges the BTFW placeholder payload (status/source/is_placeholder)", () => {
    mockOk(
      { status: "placeholder", is_placeholder: true, rows: [{ metric: "sharpe", value: null }] },
      { sources: ["placeholder_no_backtest_run"], metadata: { live: false, is_placeholder: true } },
    );
    render(<PortfolioAnalyticsPane code="BTFW" symbol="" />);
    const badge = screen.getByTestId("portx-data-badge");
    expect(badge.getAttribute("data-mode")).toBe("sample");
  });

  it("badges the MGN sample margin book on status + source_mode", () => {
    mockOk(
      {
        status: "sample",
        source_mode: "sample_margin_positions",
        is_sample: true,
        rows: [{ account: "paper", equity: 10000, maintenance_cushion_pct: 12.3 }],
      },
      { sources: ["margin_engine", "sample_margin_positions"], metadata: { live: false, is_sample: true } },
    );
    render(<PortfolioAnalyticsPane code="MGN" symbol="" />);
    const badge = screen.getByTestId("portx-data-badge");
    expect(badge.getAttribute("data-mode")).toBe("sample");
  });

  it("badges an explicit metadata.live=false payload (model admission)", () => {
    mockOk({ status: "ok", rows: LIVE_ROWS }, { metadata: { live: false } });
    render(<PortfolioAnalyticsPane code="MARS" symbol="" />);
    expect(screen.getByTestId("portx-data-badge")).toBeTruthy();
  });
});

describe("PORTX generic renderer shape fixes (F3)", () => {
  it("renders BTUNE params dict as k=v, never [object Object]", () => {
    mockOk({
      status: "reference",
      source_mode: "reference_model",
      rows: [{ label: "fast=5, slow=30", params: { fast: 5, slow: 30 }, sharpe: 1.25, calmar: 1.9 }],
    });
    const { container } = render(<PortfolioAnalyticsPane code="BTUNE" symbol="" />);
    const text = container.textContent ?? "";
    expect(text).not.toContain("[object Object]");
    expect(text).toContain("fast=5");
  });

  it("extracts BMTX cells/surface so the matrix renders (not 'No data')", () => {
    mockOk({
      status: "reference",
      cells: [
        { label: "AAPL sma_crossover", symbol: "AAPL", strategy: "sma_crossover", sharpe: 1.2, total_return: 0.1 },
      ],
      surface: [
        { label: "AAPL sma_crossover", symbol: "AAPL", strategy: "sma_crossover", sharpe: 1.2, total_return: 0.1 },
      ],
    });
    render(<PortfolioAnalyticsPane code="BMTX" symbol="" />);
    expect(screen.queryByText(/No data available/i)).toBeNull();
    expect(screen.getAllByText("AAPL").length).toBeGreaterThan(0);
  });

  it("formats LOTS opened_at epoch seconds as a date, not a magnitude", () => {
    mockOk({
      status: "ok",
      rows: [
        { lot_id: "L1", symbol: "AAPL", quantity: 15, price: 180, remaining: 15, opened_at: 1735689600 },
      ],
    });
    const { container } = render(<PortfolioAnalyticsPane code="LOTS" symbol="" />);
    const text = container.textContent ?? "";
    expect(text).toContain("2025-01-01");
    expect(text).not.toContain("1.74B");
  });

  it("prefers portfolio_vol over a leading symbol count in the hero KPI", () => {
    mockOk({
      status: "ok",
      summary: { method: "inverse_vol", symbols: 5, portfolio_vol: 0.123 },
      rows: [{ symbol: "AAPL", weight_pct: 20, risk_contribution_pct: 20 }],
    });
    const { container } = render(<PortfolioAnalyticsPane code="RPAR" symbol="" />);
    const hero = container.querySelector(".portfolio-analytics-summary__hero strong");
    expect(hero?.textContent).toBe("12.30%");
  });

  it("defaults PORT_WHATIF to a 100-share ticket, not 10,000", () => {
    mockOk({ status: "ok", rows: [{ metric: "cost", before: 0, after: 10000 }] });
    render(<PortfolioAnalyticsPane code="PORT_WHATIF" symbol="" />);
    expect(mockArgs.current?.params?.quantity).toBe(100);
  });
});

describe("PORTX parameter wiring (F3)", () => {
  it("sends the user-entered REBA capital and keeps zero-weight targets", () => {
    mockOk({ status: "ok", rows: [{ symbol: "SPY", target_weight_pct: 50 }] });
    render(<PortfolioAnalyticsPane code="REBA" symbol="" />);
    fireEvent.change(screen.getByLabelText("Capital"), { target: { value: "250000" } });
    fireEvent.change(screen.getByLabelText("Targets"), { target: { value: "SPY:60, QQQ:0" } });
    expect(mockArgs.current?.params?.max_notional).toBe(250000);
    expect(mockArgs.current?.params?.targets).toEqual({ SPY: 0.6, QQQ: 0 });
  });

  it("wires the MLSIG LIVE toggle to live_ml", () => {
    mockOk({
      status: "reference",
      source_mode: "reference_model",
      rows: [{ feature: "ret_5", importance: 0.24, meaning: "Five-day momentum." }],
    });
    render(<PortfolioAnalyticsPane code="MLSIG" symbol="" />);
    fireEvent.click(screen.getByRole("button", { name: "MODEL" }));
    expect(mockArgs.current?.params?.live_ml).toBe(true);
  });

  it("wires the BTUNE LIVE toggle to live_backtest and opens on the default symbol", () => {
    mockOk({
      status: "reference",
      source_mode: "reference_model",
      rows: [{ label: "fast=5, slow=30", params: { fast: 5, slow: 30 }, sharpe: 1.25 }],
    });
    render(<PortfolioAnalyticsPane code="BTUNE" symbol="" />);
    // Cold open: the pane must supply a default instrument so the backend's
    // "BTUNE requires an instrument symbol" ValueError is never reachable.
    expect(mockArgs.current?.symbol).toBe("AAPL");
    fireEvent.click(screen.getByRole("button", { name: "MODEL" }));
    expect(mockArgs.current?.params?.live_backtest).toBe(true);
  });

  it("wires the BMTX LIVE toggle to live_backtest", () => {
    mockOk({ status: "reference", cells: [{ symbol: "SPY", strategy: "sma_crossover", sharpe: 1 }] });
    render(<PortfolioAnalyticsPane code="BMTX" symbol="" />);
    fireEvent.click(screen.getByRole("button", { name: "MODEL" }));
    expect(mockArgs.current?.params?.live_backtest).toBe(true);
  });
});

describe("PORTX STRS stress-test coverage (F3)", () => {
  it("renders the compare payload (comparisons/rows/summary)", () => {
    mockOk({
      status: "ok",
      comparisons: [
        { scenario: "GFC_2008", total_pnl: -1200, pct: -12, severity: "severe" },
        { scenario: "RATE_2022", total_pnl: -300, pct: -3, severity: "moderate" },
      ],
      summary: { scenarios: 2, positions: 4, price_source: "portfolio_state_cost", worst_total_pnl: -1200 },
    });
    const { container } = render(<PortfolioAnalyticsPane code="STRS" symbol="" />);
    expect(container.textContent).toContain("GFC_2008");
    expect(container.textContent).toContain("portfolio_state_cost");
  });

  it("keeps the empty-portfolio branch honest", () => {
    mockOk({
      status: "empty_portfolio",
      rows: [],
      comparisons: [],
      reason: "empty portfolio",
    });
    render(<PortfolioAnalyticsPane code="STRS" symbol="" />);
    expect(screen.getByText("No portfolio positions")).toBeInTheDocument();
  });
});

describe("PORTX exposure ladder value format (P1)", () => {
  // The ladder must format its value with the REAL field key, not a
  // hardcoded "weight_pct". A dollar field (total_pnl) rendered as a
  // percent turns 1200 into a wildly-wrong "120,000%".
  it("formats a total_pnl ladder value as currency (NOT a giant percent)", () => {
    mockOk({
      status: "ok",
      // No weight_pct / risk keys, so the ladder resolves to total_pnl.
      rows: [
        { symbol: "AAA", total_pnl: 1200 },
        { symbol: "BBB", total_pnl: -800 },
      ],
    });
    const { container } = render(<PortfolioAnalyticsPane code="PORT" symbol="" />);
    const ladder = container.querySelector(".portfolio-ladder");
    expect(ladder).toBeTruthy();
    const text = ladder!.textContent ?? "";
    // Dollar P&L must not be percent-formatted.
    expect(text).not.toContain("%");
    expect(text).not.toContain("120,000");
    // And the real currency value is present (1,200 / $1,200 etc.).
    expect(text).toMatch(/1[,.]?200/);
  });

  it("still formats a weight_pct ladder value as a percent", () => {
    mockOk({
      status: "ok",
      rows: [
        { symbol: "AAA", weight_pct: 0.4 },
        { symbol: "BBB", weight_pct: 0.6 },
      ],
    });
    const { container } = render(<PortfolioAnalyticsPane code="PORT" symbol="" />);
    const ladder = container.querySelector(".portfolio-ladder");
    expect(ladder).toBeTruthy();
    expect(ladder!.textContent).toContain("%");
  });
});

describe("PORTX sign-coloured financial numerics (D1)", () => {
  it("colours a negative P&L cell negative and a positive cell positive", () => {
    mockOk({
      status: "ok",
      rows: [
        { symbol: "AAA", total_pnl: -5000, weight_pct: 0.5 },
        { symbol: "BBB", total_pnl: 5000, weight_pct: 0.5 },
      ],
    });
    const { container } = render(<PortfolioAnalyticsPane code="PORT" symbol="" />);
    const neg = container.querySelectorAll(".u-text-negative");
    const pos = container.querySelectorAll(".u-text-positive");
    expect(neg.length).toBeGreaterThan(0);
    expect(pos.length).toBeGreaterThan(0);
  });

  it("does not colour a neutral key (weight) by sign", () => {
    mockOk({
      status: "ok",
      rows: [{ symbol: "AAA", weight_pct: 0.5, vol: 0.2, price: 100 }],
    });
    const { container } = render(<PortfolioAnalyticsPane code="PORT" symbol="" />);
    // weight/vol/price are neutral — none of their cells get sign tone.
    const tbody = container.querySelector("tbody");
    expect(tbody).toBeTruthy();
    const toned = tbody!.querySelectorAll(".u-text-negative, .u-text-positive");
    expect(toned.length).toBe(0);
  });

  it("colours a negative KPI metric (e.g. drawdown) negative", () => {
    mockOk({
      status: "ok",
      summary: { max_drawdown: -0.25, total_return: 0.12, weight: 1 },
      rows: [{ symbol: "AAA", weight_pct: 1 }],
    });
    const { container } = render(<PortfolioAnalyticsPane code="TRA" symbol="" />);
    const summary = container.querySelector(".portfolio-analytics-summary__metrics");
    expect(summary).toBeTruthy();
    expect(summary!.querySelector(".u-text-negative")).toBeTruthy();
    expect(summary!.querySelector(".u-text-positive")).toBeTruthy();
  });
});

describe("PORTX a11y (A2)", () => {
  it("DataGrid carries an ariaLabel naming the code", () => {
    mockOk({ status: "ok", rows: LIVE_ROWS });
    render(<PortfolioAnalyticsPane code="PORT" symbol="" />);
    expect(screen.getByLabelText(/PORT portfolio analytics/i)).toBeTruthy();
  });

  it("warnings strip is a role=status live region", () => {
    mockOk({ status: "ok", rows: LIVE_ROWS }, { warnings: ["stale risk window"] });
    render(<PortfolioAnalyticsPane code="PORT" symbol="" />);
    const strip = screen.getByTestId("portx-warning-strip");
    expect(strip.getAttribute("role")).toBe("status");
    expect(strip.getAttribute("aria-live")).toBe("polite");
  });

  it("a per-code control input has a bound label", () => {
    mockOk({ status: "ok", rows: LIVE_ROWS });
    render(<PortfolioAnalyticsPane code="MARS" symbol="" />);
    // MARS usesUniverse → a "Universe" labelled input must exist and be bound.
    const input = screen.getByLabelText("Universe");
    expect(input.tagName).toBe("INPUT");
  });
});

describe("PORTX toolbar discoverability (U1)", () => {
  it("exposes all 20 codes in the tool strip", () => {
    mockOk({ status: "ok", rows: LIVE_ROWS });
    render(<PortfolioAnalyticsPane code="PORT" symbol="" />);
    const strip = screen.getByRole("navigation", { name: /portfolio tools/i });
    const labels = within(strip)
      .getAllByRole("button")
      .map((b) => b.textContent);
    const expected = [
      "PORT", "PVAR", "RPAR", "PORT_OPT", "REBA", "STRS", "BLAK", "PCAS",
      "PFA", "PSC", "PORT_WHATIF", "MARS", "TRA", "ACCT", "BMTX", "BTFW",
      "BTUNE", "LOTS", "MGN", "MLSIG", "TLH",
    ];
    // The formerly-missing six are now present.
    for (const code of ["ACCT", "BMTX", "BTUNE", "LOTS", "MGN", "MLSIG"]) {
      expect(labels).toContain(code);
    }
    // And every registered code is reachable (>= 20 distinct).
    const distinct = new Set(labels.filter((l): l is string => Boolean(l)));
    for (const code of expected) {
      expect(distinct.has(code)).toBe(true);
    }
  });
});

describe("PORTX REBA live book + order CSV (G3)", () => {
  it("defaults to the model book and toggles live_portfolio", () => {
    mockOk({ status: "ok", rows: [{ symbol: "SPY", action: "BUY", target_weight_pct: 100 }] });
    render(<PortfolioAnalyticsPane code="REBA" symbol="" />);
    // Untouched default: the model path (explicit false, not omitted).
    expect(mockArgs.current?.params?.live_portfolio).toBe(false);
    fireEvent.click(screen.getByRole("button", { name: "MODEL" }));
    expect(mockArgs.current?.params?.live_portfolio).toBe(true);
    // The existing capital + zero-target contract is untouched.
    expect(mockArgs.current?.params?.max_notional).toBe(100000);
  });

  it("builds the order-list CSV from the broker-shaped fields", () => {
    const csv = buildRebaOrdersCsv([
      {
        symbol: "SPY", action: "BUY", quantity: 10, price: 100,
        notional_delta: 1000, current_weight_pct: 0, target_weight_pct: 50, drift_pct: 50,
      },
      {
        symbol: "QQQ", action: "SELL", quantity: 4, price: 250,
        notional_delta: -1000, current_weight_pct: 50, target_weight_pct: 0, drift_pct: -50,
      },
    ]);
    const lines = csv.split("\n");
    expect(lines.length).toBe(3);
    expect(lines[0]).toContain("Symbol");
    expect(lines[0]).toContain("Notional delta");
    expect(lines[1]).toBe("SPY,BUY,10,100,1000,0,50,50");
    expect(lines[2]).toBe("QQQ,SELL,4,250,-1000,50,0,-50");
  });

  it("shows the CSV export control for REBA only", () => {
    mockOk({
      status: "ok",
      rows: [{ symbol: "SPY", action: "BUY", quantity: 10, price: 100, notional_delta: 1000 }],
    });
    const { unmount } = render(<PortfolioAnalyticsPane code="REBA" symbol="" />);
    expect(screen.getByTestId("portx-reba-export-csv")).toBeEnabled();
    unmount();
    mockOk({ status: "ok", rows: LIVE_ROWS });
    render(<PortfolioAnalyticsPane code="PORT" symbol="" />);
    expect(screen.queryByTestId("portx-reba-export-csv")).toBeNull();
  });

  it("removes the dead PSC Symbol control but keeps the sizing inputs", () => {
    mockOk({ status: "ok", rows: [{ metric: "shares", value: 100 }] });
    render(<PortfolioAnalyticsPane code="PSC" symbol="" />);
    expect(screen.queryByLabelText("Symbol")).toBeNull();
    expect(screen.getByLabelText("Account")).toBeInTheDocument();
    expect(screen.getByLabelText("Entry")).toBeInTheDocument();
    expect(screen.getByLabelText("Stop")).toBeInTheDocument();
    expect(screen.getByLabelText("Target")).toBeInTheDocument();
  });
});
