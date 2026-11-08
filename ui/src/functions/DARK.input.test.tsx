/**
 * DARK#4 — a request with no symbol is an input_required state, not a FINRA
 * outage. The empty state must say so instead of "FINRA ATS data unavailable".
 */
import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, render, screen } from "@testing-library/react";
import { DARKPane } from "./DARK";

const mockFn: { data?: unknown; state: string } = { state: "ok", data: undefined };

vi.mock("@/lib/useFunction", () => ({
  useFunction: () => ({
    state: mockFn.state,
    data: mockFn.data,
    error: null,
    refetch: vi.fn(),
  }),
}));

afterEach(() => {
  cleanup();
  mockFn.state = "ok";
  mockFn.data = undefined;
});

describe("DARK input_required empty state", () => {
  it("names the missing symbol rather than blaming FINRA", () => {
    mockFn.state = "ok";
    mockFn.data = {
      warnings: [],
      data: {
        status: "input_required",
        reason: "DARK requires an equity or ETF symbol (instrument or params.symbol).",
        venues: [],
        by_venue: [],
        rows: [],
        by_week: [],
        cards: {},
        summary: {},
        next_actions: ["Provide an equity or ETF ticker in the symbol field or Params JSON."],
      },
    };
    render(<DARKPane code="DARK" symbol="AAPL" />);
    expect(screen.getByText("Symbol needed")).toBeTruthy();
    expect(screen.queryByText("FINRA ATS data unavailable")).toBeNull();
  });
});
