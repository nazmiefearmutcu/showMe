/**
 * WETR pane — provider outage state (WETR-R1).
 *
 * A provider outage is `provider_unavailable` with no weather rows. The pane
 * must show the reason with no temperature cards and no seasonal-model label,
 * never a synthetic forecast. Kept in its own file so WETR.test.tsx is
 * untouched; the red evidence is backend/tests/test_wb1_g05_commodity_honesty.py.
 *
 * `useFunction` is mocked via a mutable shared state.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, render, screen } from "@testing-library/react";

interface MockFnState {
  state: "idle" | "loading" | "ok" | "error" | "refreshing";
  data?: { data?: unknown; sources?: string[]; elapsed_ms?: number };
  error?: Error | null;
}

const mockFn: MockFnState = { state: "idle", data: undefined, error: null };

vi.mock("@/lib/useFunction", () => ({
  useFunction: () => {
    return {
      state: mockFn.state,
      data: mockFn.data,
      error: mockFn.error,
      refetch: vi.fn(),
    };
  },
}));

import { WETRPane } from "./WETR";

beforeEach(() => {
  localStorage.clear();
  mockFn.state = "idle";
  mockFn.data = undefined;
  mockFn.error = null;
});

afterEach(() => {
  cleanup();
});

describe("WETR pane — provider outage", () => {
  it("shows the outage reason with no weather rows and no seasonal-model label (WETR-R1)", () => {
    mockFn.state = "ok";
    mockFn.data = {
      data: {
        status: "provider_unavailable",
        reason: "Live weather request failed: open-meteo timeout",
        location: "EU_NW",
        lat: 50.1,
        lon: 8.7,
        commodity_context: "European gas",
        source_mode: "provider_unavailable",
        rows: [],
        risk_flags: [],
        next_actions: ["Retry WETR after the public weather providers recover."],
      },
      sources: [],
    };
    const { container } = render(<WETRPane code="WETR" />);
    expect(screen.getByText("No forecast")).toBeInTheDocument();
    expect(screen.getByText(/open-meteo timeout/i)).toBeInTheDocument();
    expect(screen.queryByText(/Seasonal model rows/i)).toBeNull();
    expect(screen.queryByText(/live ·/i)).toBeNull();
    expect(container.querySelector('[aria-label="WETR KPI ribbon"]')).toBeNull();
  });
});
