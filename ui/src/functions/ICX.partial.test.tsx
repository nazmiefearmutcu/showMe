/**
 * ICX pane — partial-coverage honesty (P2A G14, ICX#1).
 *
 * A curated subset table (e.g. DAX 10 of 40) arrives with status "partial"
 * and a coverage block. The pane must say so in the header and in a note,
 * and must not present the subset as the full index.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, render, screen } from "@testing-library/react";
import { ICXPane } from "./ICX";

interface MockFnState {
  state: "idle" | "loading" | "ok" | "error" | "refreshing";
  data?: { data?: unknown; sources?: string[]; elapsed_ms?: number } | undefined;
  error?: Error | null;
}

const mockFn: MockFnState = { state: "idle", data: undefined, error: null };
const refetchMock = vi.fn();

vi.mock("@/lib/useFunction", () => ({
  useFunction: () => ({
    state: mockFn.state,
    data: mockFn.data,
    error: mockFn.error,
    refetch: refetchMock,
  }),
}));

function partialDaxPayload() {
  return {
    sources: ["showme_index_reference"],
    elapsed_ms: 12,
    data: {
        status: "partial",
        index: "DAX",
        constituents: 10,
        coverage: { listed: 10, official: 40, complete: false },
        reason:
          "Showing 10 of 40 DAX members from a curated subset table; the full roster is not bundled.",
        rows: [
          { symbol: "SAP.DE", company: "SAP SE", index: "DAX", last: null, change_pct: null },
          { symbol: "SIE.DE", company: "Siemens AG", index: "DAX", last: null, change_pct: null },
        ],
        summary: { index: "DAX", constituent_count: 10 },
    },
  };
}

beforeEach(() => {
  mockFn.state = "ok";
  mockFn.data = partialDaxPayload();
  mockFn.error = null;
  refetchMock.mockReset();
});

afterEach(() => {
  cleanup();
  window.localStorage.clear();
});

describe("ICX pane — partial index coverage", () => {
  it("labels the header with the listed-of-official count and partial", () => {
    render(<ICXPane code="ICX" />);
    expect(screen.getAllByText(/10 of 40 constituents/i).length).toBeGreaterThan(0);
    expect(screen.getAllByText(/partial/i).length).toBeGreaterThan(0);
  });

  it("shows the coverage reason as a status note", () => {
    render(<ICXPane code="ICX" />);
    const note = screen.getByLabelText("Partial coverage note");
    expect(note).toHaveTextContent("Showing 10 of 40 DAX members");
  });

  it("does not show the partial note for a complete index", () => {
    mockFn.data = {
      sources: ["showme_index_reference"],
      elapsed_ms: 12,
      data: {
          status: "ok",
          index: "DJIA",
          constituents: 30,
          coverage: { listed: 30, official: 30, complete: true },
          rows: [{ symbol: "AAPL", company: "Apple Inc.", index: "DJIA", last: null, change_pct: null }],
          summary: { index: "DJIA", constituent_count: 30 },
      },
    };
    render(<ICXPane code="ICX" />);
    expect(screen.queryByLabelText("Partial coverage note")).toBeNull();
    expect(screen.getAllByText(/30 constituents/i).length).toBeGreaterThan(0);
  });
});
