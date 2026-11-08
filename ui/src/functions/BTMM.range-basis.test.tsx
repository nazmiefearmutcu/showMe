/**
 * BTMM#1 follow-up — the Range KPI must say when its min/max come from stale
 * rows. When no row is fresh the backend falls back to the full set and sets
 * range_is_stale; the card must not read as a current range.
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

const legacyRow = {
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

function envelope(rangeIsStale: boolean) {
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
        rows: [legacyRow],
        summary: {
          rows: 1,
          universe: 1,
          average_policy_rate: null,
          max_policy_rate: 3.0,
          min_policy_rate: 3.0,
          range_basis: rangeIsStale ? "no_fresh_rows_full_set" : "fresh_183d",
          range_is_stale: rangeIsStale,
          hikes: 0,
          cuts: 0,
          holds: 0,
          fresh_rows: 0,
          stale_rows: 1,
          largest_last_move: null,
        },
      },
      sources: ["BIS CBPOL"],
      warnings: [],
      elapsed_ms: 50,
    },
  };
}

describe("BTMM Range basis (BTMM#1)", () => {
  it("labels a range built from stale rows as stale", () => {
    useFunctionMock.mockReturnValue(envelope(true));
    render(<BTMMPane code="BTMM" />);
    const card = screen.getByText("Range").closest(".stat-card");
    expect(card?.textContent).toMatch(/stale/i);
    expect(card?.textContent).toMatch(/no fresh rows/i);
    expect(screen.getByTestId("btmm-range-basis").textContent).toMatch(/stale/i);
  });

  it("keeps the plain MIN – MAX caption when the range is fresh", () => {
    useFunctionMock.mockReturnValue(envelope(false));
    render(<BTMMPane code="BTMM" />);
    const card = screen.getByText("Range").closest(".stat-card");
    expect(card?.textContent).toContain("MIN – MAX");
    expect(screen.queryByTestId("btmm-range-basis")).toBeNull();
  });
});
