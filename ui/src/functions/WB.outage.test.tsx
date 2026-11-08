/**
 * WB — a failed live fetch is shown as an explicit unavailable state.
 *
 * The backend returns data.status = "provider_unavailable" with no rows when no
 * keyless FRED series is usable (it no longer substitutes the reference template).
 * The pane must say so with the backend reason, not render an empty grid or the
 * "Template rows" notice, which only applies to rows the user asked for (reference).
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, render, screen } from "@testing-library/react";
import { WBPane } from "./WB";

interface MockFnState {
  state: "idle" | "loading" | "ok" | "error" | "refreshing";
  data?: { data?: unknown; sources?: string[]; warnings?: string[]; elapsed_ms?: number } | undefined;
  error?: Error | null;
  refetch: ReturnType<typeof vi.fn>;
}

const mockFn: MockFnState = { state: "idle", data: undefined, error: null, refetch: vi.fn() };

function setMockFn(next: Partial<MockFnState>) {
  mockFn.state = next.state ?? "idle";
  mockFn.data = next.data;
  mockFn.error = next.error ?? null;
  if (next.refetch) mockFn.refetch = next.refetch;
}

vi.mock("@/lib/useFunction", () => ({
  useFunction: () => ({
    state: mockFn.state,
    data: mockFn.data,
    error: mockFn.error,
    refetch: mockFn.refetch,
  }),
}));

vi.mock("@/lib/useVisibilityTick", () => ({
  useVisibilityTick: () => 0,
}));

const REASON = "No live FRED sovereign yield returned a usable observation (keyless fredgraph.csv).";

function outagePayload() {
  return {
    data: {
      data: {
        status: "provider_unavailable",
        reason: REASON,
        next_actions: ["Retry the live fetch later."],
        rows: [],
        missing_countries: ["US", "DE"],
        summary: { countries: 0, tenor: "10Y", source_mode: "fred", missing_countries: 2 },
        as_of: null,
        methodology: "m",
        field_dictionary: {},
      },
      sources: [],
      warnings: ["Live sovereign yields unavailable; no rows substituted."],
      elapsed_ms: 10,
    },
  };
}

beforeEach(() => {
  localStorage.clear();
  setMockFn({ state: "ok", ...outagePayload(), refetch: vi.fn() });
});

afterEach(() => {
  cleanup();
});

describe("WB pane — provider outage", () => {
  it("says live yields are unavailable and gives the backend reason", () => {
    render(<WBPane code="WB" />);
    expect(screen.getByText("Live yields unavailable")).toBeInTheDocument();
    expect(screen.getByText(REASON)).toBeInTheDocument();
  });

  it("does not present the reference template as live or as rows", () => {
    render(<WBPane code="WB" />);
    expect(screen.queryByText("Template rows")).toBeNull();
    expect(screen.queryByText("Avg yield")).toBeNull();
  });
});
