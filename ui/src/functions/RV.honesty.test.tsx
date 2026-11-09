/**
 * RV pane — unit honesty, peer input and provenance (RV#2, RV#3, RV#5).
 *
 * Kept separate from RV.test.tsx so the base comp-table suite stays untouched.
 * `useFunction` is mocked the same way: a mutable state drives each branch and
 * the last call's args are captured so the peers param can be asserted.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, render, screen, fireEvent } from "@testing-library/react";
import { RVPane } from "./RV";

interface MockFnState {
  state: "idle" | "loading" | "ok" | "error" | "refreshing";
  data?: { data?: unknown } | undefined;
  error?: Error | null;
  refetch?: ReturnType<typeof vi.fn>;
}

const mockFn: MockFnState = { state: "idle", data: undefined, error: null };
const lastCall: { args: Record<string, unknown> | undefined } = { args: undefined };

function setMockFn(next: MockFnState) {
  mockFn.state = next.state;
  mockFn.data = next.data;
  mockFn.error = next.error ?? null;
  mockFn.refetch = next.refetch ?? vi.fn();
}

vi.mock("@/lib/useFunction", () => ({
  useFunction: (args: Record<string, unknown>) => {
    lastCall.args = args;
    return {
      state: mockFn.state,
      data: mockFn.data,
      error: mockFn.error,
      refetch: mockFn.refetch ?? vi.fn(),
    };
  },
}));

// SymbolBar pulls router/symbol-resolver side effects we don't need here.
vi.mock("@/shell/SymbolBar", () => ({
  SymbolBar: () => null,
}));

function okRow(symbol: string, pe: number, isTarget: boolean) {
  return {
    symbol,
    marketCap: 2_500_000_000_000,
    pe,
    fwd_pe: pe * 0.9,
    pb: 40,
    ps: 8,
    ev_ebitda: 22,
    roe: 1.5,
    roa: 0.28,
    debt_equity: 145,
    div_yield: 0.005,
    rank_pe: isTarget ? 2 : 1,
    percentile_pe: isTarget ? 50 : 0,
    is_target: isTarget,
    source_mode: "live_yfinance",
  };
}

function okPayload() {
  return {
    data: {
      data: {
        status: "ok",
        rows: [okRow("AAPL", 30.5, true), okRow("MSFT", 25.0, false), okRow("GOOGL", 40.2, false)],
        peers: ["MSFT", "GOOGL"],
        methodology: "RV compares the target against a peer set.",
      },
    },
  };
}

beforeEach(() => {
  setMockFn({ state: "idle", data: undefined });
});
afterEach(() => {
  cleanup();
});

describe("RV pane — unit honesty (RV#2)", () => {
  it("shows debt/equity as a ratio, not a 100x percent guess", () => {
    // Backend delivers the ratio: 0.12 = 0.12x (yfinance 12 percent).
    setMockFn({
      state: "ok",
      data: {
        data: {
          status: "ok",
          rows: [
            { ...okRow("AAPL", 30.5, true), debt_equity: 0.84 },
            { ...okRow("MSFT", 25.0, false), debt_equity: 0.12 },
          ],
          peers: ["MSFT"],
        },
      },
    });
    const { container } = render(<RVPane code="RV" symbol="AAPL" />);
    expect(container.textContent).toContain("0.12");
    expect(container.textContent).not.toContain("1200.0%");
    expect(container.textContent).not.toContain("84.0%");
  });

  it("shows ROE as a fraction without a magnitude guess", () => {
    setMockFn({
      state: "ok",
      data: {
        data: {
          status: "ok",
          rows: [
            { ...okRow("AAPL", 30.5, true), roe: 3.5 },
            { ...okRow("MSFT", 25.0, false), roe: 0.25 },
          ],
          peers: ["MSFT"],
        },
      },
    });
    const { container } = render(<RVPane code="RV" symbol="AAPL" />);
    expect(container.textContent).toContain("350.0%");
    expect(container.textContent).toContain("25.0%");
  });
});

describe("RV pane — peers and provenance (RV#3, RV#5)", () => {
  it("sends a typed peer list to the backend on Enter", () => {
    setMockFn({ state: "ok", ...okPayload() });
    render(<RVPane code="RV" symbol="AAPL" />);
    const input = screen.getByLabelText("Peers") as HTMLInputElement;
    fireEvent.change(input, { target: { value: "msft, googl" } });
    fireEvent.keyDown(input, { key: "Enter" });
    expect(lastCall.args?.params).toEqual({ peers: ["MSFT", "GOOGL"] });
  });

  it("keeps auto-resolve params when the peers control is blank", () => {
    setMockFn({ state: "ok", ...okPayload() });
    render(<RVPane code="RV" symbol="AAPL" />);
    expect(lastCall.args?.params).toEqual({});
  });

  it("shows the peer-set origin in the footer", () => {
    setMockFn({
      state: "ok",
      data: {
        data: {
          status: "ok",
          rows: [okRow("AAPL", 30.5, true), okRow("MSFT", 25.0, false)],
          peers: ["MSFT"],
          peer_source: "reference_sector_map",
        },
      },
    });
    const { container } = render(<RVPane code="RV" symbol="AAPL" />);
    expect(container.textContent).toContain("reference_sector_map");
  });

  it("shows the backend reason on the provider-unavailable state", () => {
    setMockFn({
      state: "ok",
      data: {
        data: {
          status: "provider_unavailable",
          rows: [{ symbol: "AAPL", source_mode: "provider_unavailable", is_target: true }],
          peers: ["MSFT"],
          reason: "yfinance refdata returned no multiples for AAPL; peer multiples are not shown without the target.",
        },
      },
    });
    render(<RVPane code="RV" symbol="AAPL" />);
    expect(screen.getByText(/returned no multiples for AAPL/)).toBeInTheDocument();
  });
});
