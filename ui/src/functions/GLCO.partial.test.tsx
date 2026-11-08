/**
 * GLCO pane — partial board (GLCO#1-RQ).
 *
 * A board that misses contracts is `status: partial`. The pane must say so,
 * name each missing contract with its reason, and never show it as a live
 * complete board. The sector empty state also names what is not served.
 *
 * `useFunction` is mocked via a mutable shared state.
 */
import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

interface MockFnState {
  state: "idle" | "loading" | "ok" | "error" | "refreshing";
  data?: { data?: unknown; sources?: string[]; elapsed_ms?: number };
  error?: Error | null;
}

const mockFn: MockFnState = { state: "idle", data: undefined, error: null };

vi.mock("@/lib/useFunction", () => ({
  useFunction: () => ({
    state: mockFn.state,
    data: mockFn.data,
    error: mockFn.error,
    refetch: vi.fn(),
  }),
}));
vi.mock("@/lib/router", () => ({ navigate: vi.fn() }));

import { GLCOPane } from "./GLCO";

function partialData(rows: unknown[]) {
  return {
    data: {
      status: "partial",
      reason:
        "2 of 14 contracts not served by the live quote feed: SB=F, KC=F.",
      source_mode: "live_yfinance",
      rows,
      missing: [
        { symbol: "SB=F", reason: "quote: TimeoutError" },
        { symbol: "KC=F", reason: "quote: TimeoutError" },
      ],
      served_count: rows.length,
      requested_count: 14,
    },
    sources: ["yfinance"],
    elapsed_ms: 9,
  };
}

const oneRow = [
  {
    symbol: "CL=F",
    name: "WTI Crude",
    sector: "energy",
    last: 80,
    change_pct: 1.2,
    source_mode: "live_yfinance",
  },
];

beforeEach(() => {
  mockFn.state = "ok";
  mockFn.data = partialData(oneRow);
  mockFn.error = null;
});

afterEach(() => {
  cleanup();
});

describe("GLCO pane — partial board (GLCO#1-RQ)", () => {
  it("labels a partial board and names each missing contract with its reason", () => {
    render(<GLCOPane code="GLCO" />);
    expect(screen.getByText("partial")).toBeInTheDocument();
    expect(screen.getByText(/SB=F: quote: TimeoutError/)).toBeInTheDocument();
    expect(screen.getByText(/KC=F: quote: TimeoutError/)).toBeInTheDocument();
    expect(screen.queryByText(/^live$/)).not.toBeInTheDocument();
  });

  it("names the unserved contracts when a sector filter leaves no rows", () => {
    mockFn.data = partialData([]);
    render(<GLCOPane code="GLCO" />);
    expect(screen.getByText(/Not served: SB=F, KC=F/)).toBeInTheDocument();
  });
});
