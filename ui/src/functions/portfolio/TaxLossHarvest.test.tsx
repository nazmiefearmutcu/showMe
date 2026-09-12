/**
 * TLH — specialized Tax-Loss Harvesting pane tests.
 *
 * Pins the four render states, the savings KPI + wash-sale callout, the
 * candidate table and the live-with-no-losers empty copy.
 */
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

const mockReturn: { current: unknown } = { current: null };
const recordedCalls: Array<{ params?: Record<string, unknown> }> = [];
vi.mock("@/lib/useFunction", () => ({
  useFunction: (opts: { params?: Record<string, unknown> }) => {
    recordedCalls.push(opts);
    return mockReturn.current;
  },
}));
vi.mock("@/lib/router", () => ({ navigate: vi.fn() }));

import { TaxLossHarvestPane, deriveWashWindow } from "./TaxLossHarvest";

function ok(
  payload: Record<string, unknown>,
  envelope: { sources?: string[]; warnings?: string[]; metadata?: Record<string, unknown> } = {},
) {
  mockReturn.current = {
    state: "ok",
    data: {
      code: "TLH",
      instrument: null,
      data: payload,
      metadata: envelope.metadata ?? { live: true },
      fetched_at: "2026-09-11T00:00:00Z",
      sources: envelope.sources ?? ["yfinance"],
      warnings: envelope.warnings ?? [],
      elapsed_ms: 120,
    },
    error: undefined,
    refetch: vi.fn(),
  };
}

afterEach(() => {
  cleanup();
  mockReturn.current = null;
  recordedCalls.length = 0;
});

const LIVE_PAYLOAD = {
  status: "ok",
  candidates: [
    {
      symbol: "AAPL",
      asset_class: "EQUITY",
      quantity: 100,
      avg_cost: 200,
      current_price: 180,
      unrealized_pnl: -2000,
      held_days: 400,
      long_term: true,
      tax_rate_applied: 0.15,
      estimated_tax_savings: 300,
      sector: "Technology",
      replacement_etf: "VGT",
      wash_sale_window: ["2026-08-12", "2026-10-11"],
    },
    {
      symbol: "MITO",
      asset_class: "CRYPTO",
      quantity: 50,
      avg_cost: 10,
      current_price: 8,
      unrealized_pnl: -100,
      held_days: 90,
      long_term: false,
      tax_rate_applied: 0.24,
      estimated_tax_savings: 24,
      sector: null,
      replacement_etf: null,
      wash_sale_window: ["2026-08-12", "2026-10-11"],
    },
  ],
  total_estimated_tax_savings: 324,
  n_loss_positions: 2,
  tax_bracket_used: 0.24,
  lt_cap_rate_used: 0.15,
  methodology: "Loss lots × applicable rate.",
};

describe("TLH Tax-Loss Harvesting pane", () => {
  it("renders a loading skeleton", () => {
    mockReturn.current = { state: "loading", data: undefined, error: undefined, refetch: vi.fn() };
    const { container } = render(<TaxLossHarvestPane code="TLH" />);
    expect(container.querySelector('[aria-busy="true"]')).not.toBeNull();
  });

  it("renders the error state with a working Retry", () => {
    const refetch = vi.fn();
    mockReturn.current = { state: "error", data: undefined, error: new Error("tlh boom"), refetch };
    render(<TaxLossHarvestPane code="TLH" />);
    expect(screen.getByText(/tlh boom/i)).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Retry" }));
    expect(refetch).toHaveBeenCalled();
  });

  it("renders the no-positions empty state", () => {
    ok({ status: "ready_no_positions", candidates: [], rows: [], total_estimated_tax_savings: 0, n_loss_positions: 0 });
    render(<TaxLossHarvestPane code="TLH" />);
    expect(screen.getByText("No portfolio positions")).toBeInTheDocument();
  });

  it("renders the live no-losers empty copy", () => {
    ok({ candidates: [], rows: [], total_estimated_tax_savings: 0, n_loss_positions: 0 });
    render(<TaxLossHarvestPane code="TLH" />);
    expect(screen.getByText("No harvest candidates")).toBeInTheDocument();
    expect(screen.getByText(/below its cost basis/i)).toBeInTheDocument();
  });

  it("renders the savings hero, wash-sale callout and candidate table", () => {
    ok(LIVE_PAYLOAD, { metadata: { live: true, note: "US §1091 wash-sale observation applies." } });
    const { container } = render(<TaxLossHarvestPane code="TLH" />);
    // Savings show in the hero + the savings tile.
    expect(screen.getAllByText("$324").length).toBeGreaterThan(0);
    expect(screen.getByText("US §1091 wash-sale observation applies.")).toBeInTheDocument();
    expect(screen.getByText("AAPL")).toBeInTheDocument();
    expect(screen.getByText("MITO")).toBeInTheDocument();
    expect(screen.getByText("VGT")).toBeInTheDocument();
    expect(container.querySelectorAll("table").length).toBe(1);
    expect(screen.queryByTestId("portx-data-badge")).toBeNull();
  });

  it("keeps the sample-data disclosure visible for the baseline model", () => {
    ok(
      {
        candidates: [
          {
            symbol: "BTCUSDT",
            quantity: 1,
            avg_cost: 100,
            current_price: 92,
            unrealized_pnl: -8,
            held_days: 366,
            long_term: true,
            tax_rate_applied: 0.15,
            estimated_tax_savings: 1.2,
            replacement_etf: null,
            wash_sale_window: ["2026-08-12", "2026-10-11"],
          },
        ],
        rows: [],
        total_estimated_tax_savings: 1.2,
        n_loss_positions: 1,
      },
      { sources: ["tax_loss_model"], metadata: { live: false } },
    );
    render(<TaxLossHarvestPane code="TLH" />);
    expect(screen.getByTestId("portx-data-badge")).toBeInTheDocument();
  });

  it("toggles the MODEL control state", () => {
    ok(LIVE_PAYLOAD);
    render(<TaxLossHarvestPane code="TLH" />);
    fireEvent.click(screen.getByRole("button", { name: "LIVE" }));
    expect(screen.getByRole("button", { name: "MODEL" })).toBeInTheDocument();
  });
});

describe("TLH tax assumptions (user-controlled, persisted)", () => {
  it("sends the default bracket / LT-rate as fractions", () => {
    ok(LIVE_PAYLOAD);
    render(<TaxLossHarvestPane code="TLH" />);
    expect(recordedCalls.length).toBeGreaterThan(0);
    const params = recordedCalls[0].params ?? {};
    expect(params.tax_bracket).toBeCloseTo(0.24, 6);
    expect(params.lt_cap_rate).toBeCloseTo(0.15, 6);
  });

  it("lets the operator override the rates (percent inputs, fraction wire)", () => {
    ok(LIVE_PAYLOAD);
    render(<TaxLossHarvestPane code="TLH" />);
    fireEvent.change(screen.getByLabelText("Tax bracket percent"), {
      target: { value: "32" },
    });
    fireEvent.change(
      screen.getByLabelText("Long-term capital gains rate percent"),
      { target: { value: "18" } },
    );
    const latest = recordedCalls[recordedCalls.length - 1].params ?? {};
    expect(latest.tax_bracket).toBeCloseTo(0.32, 6);
    expect(latest.lt_cap_rate).toBeCloseTo(0.18, 6);
    // Persisted under showme.tlh.* so the choice survives remounts.
    expect(localStorage.getItem("showme.tlh.tax-bracket-pct")).toBe("32");
    expect(localStorage.getItem("showme.tlh.lt-cap-rate-pct")).toBe("18");
  });

  it("echoes the assumption labels in the hero copy", () => {
    ok(LIVE_PAYLOAD);
    render(<TaxLossHarvestPane code="TLH" />);
    expect(screen.getByText(/assumed bracket/i)).toBeInTheDocument();
    expect(screen.getByText(/assumed LT rate/i)).toBeInTheDocument();
  });
});

describe("TLH wash-sale window badge (real derivation)", () => {
  const NOW = Date.UTC(2026, 8, 12, 0, 0, 0); // 2026-09-12T00:00Z

  it("derives open / upcoming / expired from the real date pair", () => {
    expect(deriveWashWindow(["2026-08-13", "2026-10-12"], NOW)).toEqual({
      open: "2026-08-13",
      close: "2026-10-12",
      status: "open",
      daysLeft: 30,
    });
    expect(deriveWashWindow(["2026-10-01", "2026-11-30"], NOW)?.status).toBe("upcoming");
    const expired = deriveWashWindow(["2026-01-01", "2026-02-01"], NOW);
    expect(expired?.status).toBe("expired");
    expect(expired?.daysLeft).toBeNull();
  });

  it("rejects malformed windows instead of inventing a status", () => {
    expect(deriveWashWindow(null, NOW)).toBeNull();
    expect(deriveWashWindow(["2026-01-01"], NOW)).toBeNull();
    expect(deriveWashWindow(["nope", "2026-01-01"], NOW)).toBeNull();
    expect(deriveWashWindow(["2026-05-01", "2026-04-01"], NOW)).toBeNull();
  });

  it("badges each candidate with its window state and the §1091 tooltip", () => {
    ok({
      ...LIVE_PAYLOAD,
      candidates: [
        {
          ...LIVE_PAYLOAD.candidates[0],
          symbol: "OPENCO",
          wash_sale_window: ["2020-01-01", "2099-12-31"],
        },
        {
          ...LIVE_PAYLOAD.candidates[1],
          symbol: "EXPCO",
          wash_sale_window: ["2000-01-01", "2000-02-01"],
        },
      ],
    });
    render(<TaxLossHarvestPane code="TLH" />);
    expect(screen.getByText(/^OPEN · \d+d left$/)).toBeInTheDocument();
    expect(screen.getByText("EXPIRED")).toBeInTheDocument();
    expect(
      screen.getByTitle(/US §1091 window 2020-01-01 → 2099-12-31/),
    ).toBeInTheDocument();
  });

  it("renders an em-dash, never a fabricated badge, for malformed windows", () => {
    ok({
      ...LIVE_PAYLOAD,
      candidates: [
        { ...LIVE_PAYLOAD.candidates[0], symbol: "BADWIN", wash_sale_window: ["bad", "worse"] },
      ],
    });
    render(<TaxLossHarvestPane code="TLH" />);
    expect(screen.queryByText(/OPEN ·/)).toBeNull();
    expect(screen.queryByText("EXPIRED")).toBeNull();
    expect(screen.getAllByText("—").length).toBeGreaterThan(0);
  });
});
