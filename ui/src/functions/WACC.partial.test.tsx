/**
 * WACC pane — honest states (wc1-g34 T10 / WACC#6).
 *
 * provider_unavailable (a required input missing) shows the sidecar reason and
 * no percentage, never the generic "No WACC payload". A result with a labelled
 * default input (data_state partial) is not presented as live.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, render, screen } from "@testing-library/react";
import { WACCPane } from "./WACC";

const mockFn: {
  state: "idle" | "loading" | "ok" | "error" | "refreshing";
  data?: { data?: unknown; warnings?: string[]; sources?: string[] } | undefined;
  error?: Error | null;
} = { state: "idle", data: undefined, error: null };

vi.mock("@/lib/useFunction", () => ({
  useFunction: () => ({
    state: mockFn.state,
    data: mockFn.data,
    error: mockFn.error,
    refetch: vi.fn(),
  }),
}));

const REASON =
  "WACC is not available: no live value for risk-free rate (FRED DGS10). No substitute is used, so no discount rate is reported.";

beforeEach(() => {
  mockFn.state = "ok";
  mockFn.error = null;
  mockFn.data = {
    data: {
      status: "provider_unavailable",
      reason: REASON,
      wacc: null,
      re_capm: null,
      rf: null,
      beta: 1.1,
      erp: 0.046,
      rd: 0.0593,
      rows: [],
      surface: [],
      data_state: "provider_unavailable",
    },
    sources: ["yfinance"],
    warnings: ["fred: timeout"],
  };
});

afterEach(() => {
  cleanup();
});

describe("WACC pane — provider unavailable", () => {
  it("shows the sidecar reason and no percentage", () => {
    const { container } = render(<WACCPane code="WACC" symbol="AAPL" />);
    expect(screen.getByText("WACC not available")).toBeInTheDocument();
    expect(screen.getByText(REASON)).toBeInTheDocument();
    expect(screen.queryByText("No WACC payload")).toBeNull();
    expect(container.textContent).not.toMatch(/\d+\.\d+%/);
  });
});

describe("WACC pane — partial inputs", () => {
  it("labels a result with a default input as partial, not live", () => {
    mockFn.data = {
      data: {
        status: "ok",
        wacc: 0.0842,
        re_capm: 0.0912,
        rf: 0.04,
        beta: 1.2,
        erp: 0.05,
        rd: 0.0593,
        tax_rate: 0.21,
        equity_weight: 0.7,
        debt_weight: 0.3,
        rows: [{ component: "WACC", value: 0.0842, formula: "x" }],
        surface: [],
        data_state: "partial",
        partial_inputs: ["erp", "tax"],
      },
      sources: ["fred", "yfinance"],
      warnings: [],
    };
    const { container } = render(<WACCPane code="WACC" symbol="AAPL" />);
    expect(container.textContent).toContain("partial inputs");
    expect(container.textContent).not.toContain("live");
  });
});
