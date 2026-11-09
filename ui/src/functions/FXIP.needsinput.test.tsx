/**
 * FXIP pane — needs_input explanation (FXIP#2 residual, wb1-g19).
 *
 * The backend returns a reason and next_actions with status `needs_input`.
 * A dash alone does not say why a forward or carry is missing, so the pane
 * must render the reason and the next actions verbatim.
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

const REASON = "No policy rate for SEK in the 2024-06 reference table; forwards and carry are unavailable.";
const NEXT_ACTION = "Supply r_base and/or r_quote as decimal annual rates (e.g. 0.04) for the missing currency.";

const needsInputPayload = {
  data: {
    data: {
      status: "needs_input",
      data_mode: "needs_input",
      reason: REASON,
      next_actions: [NEXT_ACTION, "Forwards and carry are computed once both policy rates are known."],
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
        { metric: "quote_rate", value: null, unit: "decimal annual", source: "unavailable_no_reference_rate" },
      ],
      history: [],
    },
    sources: ["manual_input", "covered_interest_parity_formula"],
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

describe("FXIP pane — needs_input explanation", () => {
  it("renders the backend reason for the missing rate", () => {
    render(<FXIPPane code="FXIP" symbol="USDSEK" />);
    expect(screen.getByText(REASON)).toBeInTheDocument();
  });

  it("renders the backend next actions", () => {
    render(<FXIPPane code="FXIP" symbol="USDSEK" />);
    expect(screen.getByText(NEXT_ACTION)).toBeInTheDocument();
  });
});
