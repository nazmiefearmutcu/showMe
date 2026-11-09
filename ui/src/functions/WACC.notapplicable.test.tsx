/**
 * WACC pane — financial issuer (WACC#2) honest state.
 *
 * A bank or insurer returns status "not_applicable" with wacc null. The pane
 * must say so with the sidecar's reason, not the generic "No WACC payload"
 * message and never a percentage.
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
  "WACC is not applicable to a bank or insurer: deposits and policy reserves are operating funding.";

beforeEach(() => {
  mockFn.state = "ok";
  mockFn.error = null;
  mockFn.data = {
    data: {
      status: "not_applicable",
      reason: REASON,
      wacc: null,
      re_capm: 0.1,
      rf: 0.04,
      beta: 1.1,
      erp: 0.05,
      rd: 0.0593,
      rows: [],
      surface: [],
    },
    sources: ["fred", "yfinance"],
    warnings: [],
  };
});

afterEach(() => {
  cleanup();
});

describe("WACC pane — financial issuer", () => {
  it("shows the not-applicable state with the sidecar reason and no percentage", () => {
    const { container } = render(<WACCPane code="WACC" symbol="JPM" />);
    expect(screen.getByText("WACC not applicable")).toBeInTheDocument();
    expect(screen.getByText(REASON)).toBeInTheDocument();
    expect(screen.queryByText("No WACC payload")).toBeNull();
    expect(container.textContent).not.toMatch(/\d+\.\d+%/);
  });
});
