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
import { cleanup, render, screen, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

// Each test installs its own useFunction mock via this mutable holder.
const mockReturn: { current: unknown } = { current: null };
vi.mock("@/lib/useFunction", () => ({
  useFunction: () => mockReturn.current,
}));
// Router navigate is a side-effect we don't need to drive here.
vi.mock("@/lib/router", () => ({ navigate: vi.fn() }));

import { PortfolioAnalyticsPane } from "./PortfolioAnalytics";

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
    expect(badge.textContent?.toLowerCase()).toContain("canlı piyasa değil");
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
    expect(screen.getByLabelText(/PORT portföy analitiği/i)).toBeTruthy();
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
