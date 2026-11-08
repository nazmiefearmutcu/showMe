/**
 * TLH — partial state with unpriced positions (TLH#1).
 *
 * When a loss position has no quote, the pane must not claim nothing-to-harvest.
 * Helper and mocks match TaxLossHarvest.test.tsx; kept in a separate file so
 * that suite stays untouched.
 */
import { cleanup, render, screen } from "@testing-library/react";
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

import { TaxLossHarvestPane } from "./TaxLossHarvest";

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

describe("TLH partial state with unpriced positions", () => {
  it("does not claim nothing-to-harvest while a position has no quote", () => {
    ok(
      {
        status: "partial",
        candidates: [],
        rows: [],
        total_estimated_tax_savings: 0,
        n_loss_positions: 0,
        unpriced_symbols: ["TLT"],
        summary: { positions_evaluated: 1, positions_unpriced: 1 },
      },
      { warnings: ["No current quote for TLT; those positions were not evaluated."] },
    );
    render(<TaxLossHarvestPane code="TLH" />);
    expect(screen.queryByText(/below its cost basis/i)).toBeNull();
    expect(screen.getByText("Loss status unknown for some positions")).toBeInTheDocument();
    expect(screen.getAllByText(/No current quote for TLT/).length).toBeGreaterThan(0);
  });
});
