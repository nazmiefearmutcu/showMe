/**
 * XPORT-R1 — the shared Portfolio pane must not forward the linked dock
 * symbol to a portfolio-wide tool that would read it as a filter or as the
 * analysed instrument with no visible symbol control.
 *
 *  - RPAR takes a symbols universe. With the universe cleared, its handler
 *    used the dock symbol as a one-asset universe, so the dock silently
 *    replaced the book. It never receives the dock symbol now. (MARS renders
 *    in MultiAssetRisk.tsx, which never sends a symbol.)
 *  - MLSIG scores ONE symbol (the handler's instrument). The dock was its only
 *    symbol source and the pane showed no control, so it is now a symbol
 *    tool: the symbol control is shown and the dock symbol is forwarded.
 *  - Tools that really take a symbol (BTFW, TRA) still receive the dock symbol.
 */
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

const mockReturn: { current: unknown } = { current: null };
const mockArgs: {
  current: { code?: string; symbol?: string; params?: Record<string, unknown>; enabled?: boolean } | null;
} = { current: null };
vi.mock("@/lib/useFunction", () => ({
  useFunction: (args: unknown) => {
    mockArgs.current = args as (typeof mockArgs)["current"];
    return mockReturn.current;
  },
}));
vi.mock("@/lib/router", () => ({ navigate: vi.fn() }));

import { PortfolioAnalyticsPane } from "./PortfolioAnalytics";

function mockOk(payload: Record<string, unknown>) {
  mockReturn.current = {
    state: "ok",
    data: {
      data: payload,
      metadata: { live: true },
      sources: ["showme engine"],
      warnings: [],
    },
    error: null,
    refetch: vi.fn(),
  };
}

afterEach(() => {
  cleanup();
  mockReturn.current = null;
  mockArgs.current = null;
});

describe("XPORT-R1 dock symbol forwarding", () => {
  it("never forwards the linked dock symbol to the portfolio-universe tool RPAR", () => {
    mockOk({ status: "ok", rows: [] });
    render(<PortfolioAnalyticsPane code="RPAR" symbol="AAPL" />);
    expect(mockArgs.current?.code).toBe("RPAR");
    expect(mockArgs.current?.symbol).toBeUndefined();
  });

  it("MLSIG forwards the dock symbol and shows its own symbol control", () => {
    mockOk({ status: "ok", rows: [] });
    render(<PortfolioAnalyticsPane code="MLSIG" symbol="MSFT" />);
    expect(mockArgs.current?.code).toBe("MLSIG");
    expect(mockArgs.current?.symbol).toBe("MSFT");
    expect(screen.getByLabelText(/symbol/i)).toBeTruthy();
  });

  it("still forwards the dock symbol to a tool that is a single-symbol analysis (TRA)", () => {
    mockOk({ status: "ok", rows: [] });
    render(<PortfolioAnalyticsPane code="TRA" symbol="NVDA" />);
    expect(mockArgs.current?.symbol).toBe("NVDA");
  });
});

describe("XPORT-R1 typed symbol and blank input", () => {
  it("a symbol typed into MLSIG wins over the linked dock symbol", () => {
    mockOk({ status: "ok", rows: [] });
    render(<PortfolioAnalyticsPane code="MLSIG" symbol="AAPL" />);
    fireEvent.change(screen.getByLabelText(/symbol/i), { target: { value: "msft" } });
    expect(mockArgs.current?.symbol).toBe("MSFT");
  });

  it("a blank MLSIG symbol is never requested, so no backend default (BTCUSDT) runs", () => {
    mockOk({ status: "ok", rows: [] });
    render(<PortfolioAnalyticsPane code="MLSIG" />);
    expect(mockArgs.current?.symbol).toBeUndefined();
    expect(mockArgs.current?.enabled).toBe(false);
    fireEvent.change(screen.getByLabelText(/symbol/i), { target: { value: "" } });
    expect(mockArgs.current?.enabled).toBe(false);
    expect(screen.getByText(/enter a symbol/i)).toBeTruthy();
  });

  it("the dock symbol still drives MLSIG until the user types their own", () => {
    mockOk({ status: "ok", rows: [] });
    const { rerender } = render(<PortfolioAnalyticsPane code="MLSIG" symbol="AAPL" />);
    expect(mockArgs.current?.symbol).toBe("AAPL");
    rerender(<PortfolioAnalyticsPane code="MLSIG" symbol="NVDA" />);
    expect(mockArgs.current?.symbol).toBe("NVDA");
  });

  it("RPAR with a cleared universe is not requested, so the backend list never runs", () => {
    mockOk({ status: "ok", rows: [] });
    render(<PortfolioAnalyticsPane code="RPAR" />);
    expect(mockArgs.current?.enabled).not.toBe(false);
    fireEvent.change(screen.getByLabelText(/universe/i), { target: { value: "" } });
    expect(mockArgs.current?.enabled).toBe(false);
    expect(screen.getByText(/enter at least one symbol/i)).toBeTruthy();
  });
});
