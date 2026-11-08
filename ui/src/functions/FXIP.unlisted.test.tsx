/**
 * FXIP pane — unlisted-currency honesty (FXIP#2 follow-up).
 *
 * When the backend cannot supply a policy rate for an unlisted currency it
 * returns null forwards and carry with status `needs_input`. The pane must
 * show those as "—" and never render a fabricated carry such as "+0.000%".
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, render, screen } from "@testing-library/react";
import { FXIPPane } from "./FXIP";

interface MockFnState {
  state: "idle" | "loading" | "ok" | "error" | "refreshing";
  data?: { data?: unknown; warnings?: string[] } | undefined;
  error?: Error | null;
}

const mockFn: MockFnState = { state: "idle", data: undefined, error: null };
const refetchMock = vi.fn();

function setMockFn(next: MockFnState) {
  mockFn.state = next.state;
  mockFn.data = next.data;
  mockFn.error = next.error ?? null;
}

vi.mock("@/lib/useFunction", () => ({
  useFunction: () => ({
    state: mockFn.state,
    data: mockFn.data,
    error: mockFn.error,
    refetch: refetchMock,
  }),
}));

vi.mock("@/lib/useVisibilityTick", () => ({
  useVisibilityTick: () => 0,
}));

const needsInputPayload = {
  data: {
    data: {
      status: "needs_input",
      reason: "No policy rate for SEK in the 2024-06 reference table; forwards and carry are unavailable.",
      next_actions: ["Supply r_base and/or r_quote as decimal annual rates."],
      pair: "USDSEK",
      base: "USD",
      quote: "SEK",
      spot: 10.5,
      daily_change_pct: null,
      one_month_forward: null,
      three_month_forward: null,
      assumed_vol_atm_1m_pct: 8.45,
      carry_annualized: null,
      source_mode: "manual_input",
      rate_basis: {
        base: "reference_policy_rate_2024-06",
        quote: "unavailable_no_reference_rate",
      },
      rows: [
        { metric: "spot", value: 10.5, unit: "SEK per USD", source: "manual_input" },
        { metric: "base_rate", value: 0.045, unit: "decimal annual", source: "reference_policy_rate_2024-06" },
        { metric: "quote_rate", value: null, unit: "decimal annual", source: "unavailable_no_reference_rate" },
        { metric: "1m_forward", value: null, unit: "rate", source: "covered_interest_parity" },
        { metric: "3m_forward", value: null, unit: "rate", source: "covered_interest_parity" },
        { metric: "carry_annualized", value: null, unit: "decimal annual", source: "rate_differential" },
      ],
      history: [],
    },
    sources: ["manual_input", "covered_interest_parity_formula", "reference_policy_rate"],
    warnings: ["no reference policy rate for SEK; forwards and carry are null"],
    elapsed_ms: 5,
  },
};

beforeEach(() => {
  localStorage.clear();
  setMockFn({ state: "ok", ...needsInputPayload });
  refetchMock.mockReset();
});

afterEach(() => {
  cleanup();
});

describe("FXIP pane — unlisted currency", () => {
  it("never renders a fabricated carry value", () => {
    render(<FXIPPane code="FXIP" symbol="USDSEK" />);
    expect(screen.queryByText(/\+0\.000%/)).toBeNull();
    expect(screen.queryByText(/NaN/)).toBeNull();
    expect(screen.queryByText(/Infinity/)).toBeNull();
  });

  it("shows the carry card and forward cards as explicit unavailable dashes", () => {
    render(<FXIPPane code="FXIP" symbol="USDSEK" />);
    expect(screen.getByText(/LONG BASE EARNS IF NEGATIVE/i)).toBeInTheDocument();
    // 1M/3M forwards, carry card and the null metric rows all render as "—".
    expect(screen.getAllByText("—").length).toBeGreaterThanOrEqual(3);
  });
});
