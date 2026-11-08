/**
 * WETR pane — unsupported-region state (WETR#1).
 *
 * An unknown region is an explicit `input_error` from the backend. The pane
 * must show that reason with no live label and no temperature, never weather
 * for another region. Kept in its own file so the shared WETR.test.tsx stays
 * untouched; the red evidence for WETR#1 is backend/tests/test_wetr_location_presets.py.
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

describe("WETR pane — unsupported region", () => {
  it("shows the explicit unsupported-region state with no rows and no live label (WETR#1)", () => {
    mockFn.state = "ok";
    mockFn.data = {
      data: {
        status: "input_error",
        reason: "MARS_BASE is not a supported WETR region; no other region's weather is substituted.",
        location: "MARS_BASE",
        lat: null,
        lon: null,
        source_mode: "unsupported_region",
        rows: [],
        risk_flags: [],
        next_actions: ["Pick a supported region: ASIA_EAST, BRAZIL_SE, EU_NW."],
      },
      sources: [],
      elapsed_ms: 3,
    };
    render(<WETRPane code="WETR" />);
    expect(screen.getAllByText(/not a supported WETR region/i).length).toBeGreaterThan(0);
    expect(screen.queryByText(/live ·/)).toBeNull();
    expect(screen.queryByText("18.2°")).toBeNull();
  });
});
