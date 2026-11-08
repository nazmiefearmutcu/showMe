/**
 * FSRC pane — AUM / YTD are not served (finding FSRC#1).
 *
 * The backend no longer serves fund AUM or YTD (no provider supplies them,
 * and the earlier curated figures were stale). The pane must show a dash
 * instead of a number, must not offer AUM / YTD as sort keys, must sort rows
 * without a value last rather than as zero, and must show an explicit
 * "Data unavailable" state for a backend provider_unavailable payload.
 *
 * `useFunction` is mocked the same way as FSRC.test.tsx.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { FSRCPane } from "./FSRC";

interface MockFnState {
  state: "idle" | "loading" | "ok" | "error" | "refreshing";
  data?: { data?: unknown; sources?: string[]; elapsed_ms?: number } | undefined;
  error?: Error | null;
}

const mockFn: MockFnState = { state: "idle", data: undefined, error: null };

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
    refetch: vi.fn(),
  }),
}));

function unservedPayload() {
  return {
    data: {
      sources: ["showme_fund_reference_universe"],
      elapsed_ms: 12,
      data: {
        status: "ok",
        query: "expenseRatio < 0.01",
        filter: "expenseRatio < 0.01",
        scanned: 3,
        matched: 3,
        rows: [
          {
            symbol: "AAA",
            name: "Alpha Fund",
            issuer: "Issuer A",
            category: "US Large Blend",
            aum_usd: null,
            expenseRatio: 0.0009,
            ytd_return_pct: null,
            dividend_yield: 0.01,
            last: 100,
            change_pct: 1.0,
            quote_state: "live",
            aum_state: "unavailable",
            ytd_state: "unavailable",
          },
          {
            symbol: "BBB",
            name: "Bravo Fund",
            issuer: "Issuer B",
            category: "US Large Blend",
            aum_usd: null,
            expenseRatio: 0.002,
            ytd_return_pct: null,
            dividend_yield: 0.01,
            last: null,
            change_pct: null,
            quote_state: "reference",
            aum_state: "unavailable",
            ytd_state: "unavailable",
          },
          {
            symbol: "CCC",
            name: "Charlie Fund",
            issuer: "Issuer C",
            category: "US Large Blend",
            aum_usd: null,
            expenseRatio: 0.004,
            ytd_return_pct: null,
            dividend_yield: 0.01,
            last: 50,
            change_pct: -1.0,
            quote_state: "live",
            aum_state: "unavailable",
            ytd_state: "unavailable",
          },
        ],
        next_actions: [],
      },
    },
  };
}

beforeEach(() => {
  setMockFn({ state: "idle", data: undefined });
});

afterEach(() => {
  cleanup();
  window.localStorage.clear();
});

describe("FSRC pane — AUM / YTD unserved (FSRC#1)", () => {
  it("renders a dash, never a number, for null AUM and YTD", () => {
    setMockFn({ state: "ok", ...unservedPayload() });
    render(<FSRCPane code="FSRC" />);
    expect(screen.getAllByTitle("AUM is not served: no provider supplies fund AUM").length).toBe(3);
    expect(screen.getAllByTitle("YTD is not served: no provider supplies fund YTD returns").length).toBe(3);
    expect(screen.queryByText("$0")).toBeNull();
    expect(screen.queryByText("0.0%")).toBeNull();
  });

  it("does not offer AUM or YTD as sort keys", () => {
    setMockFn({ state: "ok", ...unservedPayload() });
    render(<FSRCPane code="FSRC" />);
    expect(screen.queryByTitle("Sort by AUM")).toBeNull();
    expect(screen.queryByTitle("Sort by YTD return")).toBeNull();
    expect(screen.getByTitle("Sort by expense ratio")).toBeInTheDocument();
    expect(screen.getByTitle("Sort by change %")).toBeInTheDocument();
  });

  it("sorts rows without a value for the key last, never as zero", () => {
    setMockFn({ state: "ok", ...unservedPayload() });
    render(<FSRCPane code="FSRC" />);
    fireEvent.click(screen.getByTitle("Sort by change %"));
    const a = screen.getByText("AAA");
    const c = screen.getByText("CCC");
    const b = screen.getByText("BBB");
    // Descending by change: AAA (+1), CCC (-1), then BBB (no change value).
    expect(a.compareDocumentPosition(c) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    expect(c.compareDocumentPosition(b) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
  });

  it("composes the match-all predicate on expense ratio, not AUM", () => {
    setMockFn({ state: "ok", ...unservedPayload() });
    render(<FSRCPane code="FSRC" />);
    expect(screen.getAllByText(/expenseRatio >= 0/).length).toBeGreaterThan(0);
    expect(screen.queryByText(/aum_usd/)).toBeNull();
  });

  it("shows an explicit data-unavailable state for a provider_unavailable payload", () => {
    setMockFn({
      state: "ok",
      data: {
        data: {
          status: "provider_unavailable",
          reason: "Filter references aum_usd, which ShowMe does not serve.",
          rows: [],
          matched: 0,
          scanned: 68,
          next_actions: [],
        },
      },
    });
    render(<FSRCPane code="FSRC" />);
    expect(screen.getByText("Data unavailable")).toBeInTheDocument();
    expect(screen.getByText(/does not serve/)).toBeInTheDocument();
    expect(screen.queryByText("No rows matched your filters")).toBeNull();
  });
});
