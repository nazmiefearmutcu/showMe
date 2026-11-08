/**
 * BTMM#1 — stale policy-rate rows are flagged, and the Largest-move card is dated.
 *
 * The backend now excludes stale observations from the average, range and
 * largest move, and marks each row with `freshness`. The table must show that
 * flag, and the Largest-move card must name the observation date.
 */
import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

const useFunctionMock = vi.fn();

vi.mock("@/lib/useFunction", () => ({
  useFunction: (...args: unknown[]) => useFunctionMock(...args),
}));

import { BTMMPane } from "./BTMM";

afterEach(() => {
  cleanup();
  useFunctionMock.mockReset();
});

const freshRow = {
  country_code: "US",
  bis_ref_area: "US",
  country: "United States",
  central_bank: "Federal Reserve",
  currency: "USD",
  region: "americas",
  policy_rate: 3.625,
  as_of: "2026-11-03",
  freshness: "fresh",
  last_move: "cut",
  change_bp: -25,
  trend_3m_bp: null,
  history: [{ date: "2026-11-03", policy_rate: 3.625 }],
  source: "BIS CBPOL",
};

const staleRow = {
  country_code: "DE",
  bis_ref_area: "DE",
  country: "Germany",
  central_bank: "Deutsche Bundesbank",
  currency: "EUR",
  region: "europe",
  policy_rate: 3.0,
  as_of: "1998-12-31",
  freshness: "stale",
  last_move: "hold",
  change_bp: 0,
  trend_3m_bp: null,
  history: [{ date: "1998-12-31", policy_rate: 3.0 }],
  source: "BIS CBPOL",
};

function envelope(rows: unknown[]) {
  return {
    state: "ok" as const,
    refetch: vi.fn(),
    error: undefined,
    data: {
      data: {
        country: "ALL",
        region: "all",
        as_of: "2026-11-03",
        stale_seconds: 0,
        rows,
        summary: {
          rows: rows.length,
          universe: rows.length,
          average_policy_rate: 3.625,
          max_policy_rate: 3.625,
          min_policy_rate: 3.625,
          hikes: 0,
          cuts: 1,
          holds: 1,
          fresh_rows: 1,
          stale_rows: 1,
          largest_last_move: freshRow,
        },
      },
      sources: ["BIS CBPOL"],
      warnings: ["stale_rows_excluded: 1 policy-rate row(s) dated before the 183-day window"],
      elapsed_ms: 50,
    },
  };
}

describe("BTMM stale-row honesty (BTMM#1)", () => {
  it("flags a stale observation next to its date", () => {
    useFunctionMock.mockReturnValue(envelope([freshRow, staleRow]));
    render(<BTMMPane code="BTMM" />);
    const flags = screen.getAllByTestId("btmm-stale-flag");
    expect(flags).toHaveLength(1);
    expect(flags[0].parentElement?.textContent).toContain("1998-12-31");
  });

  it("does not flag a fresh observation as stale", () => {
    useFunctionMock.mockReturnValue(envelope([freshRow]));
    render(<BTMMPane code="BTMM" />);
    expect(screen.queryByTestId("btmm-stale-flag")).toBeNull();
  });

  it("dates the Largest-move card with the observation it came from", () => {
    useFunctionMock.mockReturnValue(envelope([freshRow, staleRow]));
    render(<BTMMPane code="BTMM" />);
    const card = screen.getByText("Largest move").closest(".stat-card");
    expect(card?.textContent).toContain("2026-11-03");
  });
});
