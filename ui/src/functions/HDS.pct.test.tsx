/**
 * HDS#8: pct_outstanding is a fraction of shares outstanding (0 to 1). The pane
 * must not guess the unit from magnitude: a value above 1 is missing, not
 * rescaled, and a fraction renders as a percent.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, render, screen } from "@testing-library/react";
import { HDSPane } from "./HDS";

interface MockFnState {
  state: "idle" | "loading" | "ok" | "error" | "refreshing";
  data?: { data?: unknown } | undefined;
}

const mockFn: MockFnState = { state: "idle", data: undefined };

vi.mock("@/lib/useFunction", () => ({
  useFunction: () => ({
    state: mockFn.state,
    data: mockFn.data,
    error: null,
    refetch: vi.fn(),
  }),
}));

vi.mock("@/shell/SymbolBar", () => ({
  SymbolBar: () => null,
}));

function payloadWithPct(pct: number) {
  return {
    data: {
      status: "ok",
      rows: [
        {
          symbol: "AAPL",
          holder: "Vanguard Group, Inc.",
          holder_type: "institutional",
          shares: 1_300_000_000,
          pct_outstanding: pct,
          date_reported: "2026-03-31",
          source_mode: "yfinance_holders",
        },
      ],
      methodology: "HDS shows holder rows from Yahoo holder tables.",
    },
  };
}

beforeEach(() => {
  mockFn.state = "ok";
});
afterEach(() => {
  cleanup();
});

describe("HDS pct_outstanding unit (HDS#8)", () => {
  it("renders a fraction as a percent", () => {
    mockFn.data = payloadWithPct(0.08);
    render(<HDSPane code="HDS" symbol="AAPL" />);
    expect(screen.getAllByText("8.00%").length).toBeGreaterThanOrEqual(1);
  });

  it("does not rescale a value above 1 as if it were a percent", () => {
    // RED before fix: 1.2 was shown as "120.00%" by the magnitude heuristic.
    mockFn.data = payloadWithPct(1.2);
    const { container } = render(<HDSPane code="HDS" symbol="AAPL" />);
    expect(container.textContent ?? "").not.toContain("120.00%");
    expect(container.textContent ?? "").not.toContain("120%");
  });

  it("does not rescale a value of 2.5 into 2.50%", () => {
    mockFn.data = payloadWithPct(2.5);
    const { container } = render(<HDSPane code="HDS" symbol="AAPL" />);
    expect(container.textContent ?? "").not.toContain("2.50%");
  });
});
