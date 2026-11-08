/**
 * FA pane — date provenance in the footer (FA#5).
 *
 * `period_end` is the statement data date; `filing_date` is the SEC filed date
 * and is shown only when the source supplied it. The pane must never present
 * the period end as a filing date, nor a request timestamp as either.
 */
import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, render, screen } from "@testing-library/react";
import { FAPane } from "./FA";

interface MockFnState {
  state: "ok";
  data: { data?: unknown } | undefined;
}

const mockFn: MockFnState = { state: "ok", data: undefined };

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

vi.mock("./function-control-state", () => ({
  usePersistentOption: () => ["income", vi.fn()],
}));

function payload(extra: Record<string, unknown>) {
  return {
    data: {
      status: "ok",
      symbol: "AAPL",
      currency: "USD",
      income_statement: [],
      balance_sheet: [],
      cash_flow: [],
      ratios: { net_margin: 0.24 },
      last_updated: "2026-11-08T00:07:00Z",
      ...extra,
    },
  };
}

afterEach(() => {
  cleanup();
});

describe("FA — date provenance (FA#5)", () => {
  it("shows the period end and the SEC filing date as separate facts", () => {
    mockFn.data = payload({ period_end: "2026-09-26", filing_date: "2026-11-03" });
    render(<FAPane code="FA" symbol="AAPL" />);
    expect(screen.getByText("period end · 2026-09-26")).toBeInTheDocument();
    expect(screen.getByText("filing · 2026-11-03")).toBeInTheDocument();
  });

  it("does not show a filing date when the source supplied none", () => {
    mockFn.data = payload({ period_end: "2026-09-26", filing_date: null });
    render(<FAPane code="FA" symbol="AAPL" />);
    expect(screen.getByText("period end · 2026-09-26")).toBeInTheDocument();
    expect(screen.queryByText(/^filing · /)).toBeNull();
  });

  it("never substitutes last_updated or the period end as a filing date", () => {
    mockFn.data = payload({ filing_date: null, period_end: null });
    render(<FAPane code="FA" symbol="AAPL" />);
    expect(screen.queryByText(/^filing · /)).toBeNull();
    expect(screen.queryByText(/^period end · /)).toBeNull();
    expect(screen.queryByText(/2026-11-08/)).toBeNull();
  });
});
