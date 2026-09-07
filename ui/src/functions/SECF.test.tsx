/**
 * SECF pane — data-honesty + render-contract tests.
 *
 * `useFunction` is mocked via a mutable shared state (GEX pattern) so
 * each test drives a specific branch. Pins:
 *
 *  - the four load states (loading / empty / error / ok) render;
 *  - the ok state renders results + the matched/scanned count note;
 *  - the "reference master" honesty pill shows for the static master
 *    source and is NOT a live-quote claim;
 *  - asset-class chip filtering is a real interaction (rows shrink).
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { SECFPane } from "./SECF";

/* ── useFunction mock ──────────────────────────────────────────────── */

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

/* ── fixtures ──────────────────────────────────────────────────────── */

function okPayload() {
  return {
    data: {
      sources: ["showme_security_master"],
      elapsed_ms: 3,
      data: {
        status: "ok",
        query: "cap",
        match_mode: "text_search",
        scanned: 13,
        matched: 4,
        rows: [
          {
            symbol: "AAPL",
            name: "Apple Inc.",
            asset_class: "EQUITY",
            exchange: "NASDAQ",
            tags: ["mega cap"],
            match: "all_terms",
          },
          {
            symbol: "MSFT",
            name: "Microsoft Corp.",
            asset_class: "EQUITY",
            exchange: "NASDAQ",
            tags: ["mega cap"],
            match: "all_terms",
          },
          {
            symbol: "SPY",
            name: "SPDR S&P 500 ETF Trust",
            asset_class: "ETF",
            exchange: "NYSE Arca",
            tags: ["large cap"],
            match: "partial",
          },
          {
            symbol: "US10Y",
            name: "US Treasury 10Y",
            asset_class: "BOND",
            exchange: "Treasury",
            tags: ["duration"],
            match: "partial",
          },
        ],
        next_actions: [],
      },
    },
  };
}

/* ── tests ─────────────────────────────────────────────────────────── */

beforeEach(() => {
  setMockFn({ state: "idle", data: undefined });
});

afterEach(() => {
  cleanup();
});

describe("SECF pane — load states", () => {
  it("renders a skeleton while loading", () => {
    setMockFn({ state: "loading", data: undefined });
    const { container } = render(<SECFPane code="SECF" symbol="SPY" />);
    expect(container.querySelector("[aria-busy='true']")).not.toBeNull();
  });

  it("renders the error state when the fetch errors", () => {
    setMockFn({
      state: "error",
      data: undefined,
      error: new Error("sidecar exploded"),
    });
    render(<SECFPane code="SECF" symbol="SPY" />);
    expect(screen.getByText(/sidecar exploded/i)).toBeInTheDocument();
  });

  it("renders the empty state with backend guidance when nothing matched", () => {
    setMockFn({
      state: "ok",
      data: {
        data: {
          status: "empty",
          query: "zzz",
          rows: [],
          matched: 0,
          scanned: 13,
          next_actions: [
            "Try a broader symbol, company name, asset class, or tag.",
          ],
        },
      },
    });
    render(<SECFPane code="SECF" symbol="SPY" />);
    expect(screen.getByText(/No securities matched/i)).toBeInTheDocument();
    expect(
      screen.getByText(/Try a broader symbol, company name/i),
    ).toBeInTheDocument();
  });
});

describe("SECF pane — results + honesty", () => {
  it("renders result rows and the matched/scanned note when ok", () => {
    setMockFn({ state: "ok", ...okPayload() });
    render(<SECFPane code="SECF" symbol="SPY" />);
    expect(screen.getByText("AAPL")).toBeInTheDocument();
    expect(screen.getByText("SPY")).toBeInTheDocument();
    expect(screen.getByText(/4 of 4 matched/i)).toBeInTheDocument();
    expect(screen.getAllByText(/13 scanned/i).length).toBeGreaterThan(0);
  });

  it("labels the static security master honestly as reference data", () => {
    setMockFn({ state: "ok", ...okPayload() });
    render(<SECFPane code="SECF" symbol="SPY" />);
    expect(screen.getByText("reference master")).toBeInTheDocument();
  });

  it("does not label a non-master source as reference master", () => {
    setMockFn({
      state: "ok",
      data: {
        sources: ["some_other_source"],
        data: { status: "ok", rows: [], matched: 0, scanned: 0 },
      },
    });
    render(<SECFPane code="SECF" symbol="SPY" />);
    expect(screen.queryByText("reference master")).toBeNull();
  });
});

describe("SECF pane — asset-class chip filter", () => {
  it("filters the table when a chip is clicked", () => {
    setMockFn({ state: "ok", ...okPayload() });
    render(<SECFPane code="SECF" symbol="SPY" />);
    fireEvent.click(screen.getByTitle("Filter asset class ETF"));
    expect(screen.getByText("SPY")).toBeInTheDocument();
    expect(screen.queryByText("AAPL")).toBeNull();
    expect(screen.getByText(/filtered to ETF/i)).toBeInTheDocument();
  });

  it("returns to the full set when the ALL chip is clicked", () => {
    setMockFn({ state: "ok", ...okPayload() });
    render(<SECFPane code="SECF" symbol="SPY" />);
    fireEvent.click(screen.getByTitle("Filter asset class ETF"));
    fireEvent.click(screen.getByTitle("Filter asset class ALL"));
    expect(screen.getByText("AAPL")).toBeInTheDocument();
    expect(screen.getByText("SPY")).toBeInTheDocument();
  });
});
