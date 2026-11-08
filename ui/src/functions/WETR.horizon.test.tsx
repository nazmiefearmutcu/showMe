/**
 * WETR pane — forecast horizon control (WETR#4).
 *
 * The manifest offers days 3/5/10/14; the pane must expose that choice
 * instead of always sending 10. Kept in its own file so the existing
 * WETR.test.tsx stays untouched.
 *
 * `useFunction` is mocked via a mutable shared state + recorded calls.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";

interface MockFnState {
  state: "idle" | "loading" | "ok" | "error" | "refreshing";
  data?: { data?: unknown; sources?: string[]; elapsed_ms?: number };
  error?: Error | null;
}

const mockFn: MockFnState = { state: "idle", data: undefined, error: null };
const recordedCalls: Array<{ params?: Record<string, unknown> }> = [];

vi.mock("@/lib/useFunction", () => ({
  useFunction: (opts: { params?: Record<string, unknown> }) => {
    recordedCalls.push(opts);
    return {
      state: mockFn.state,
      data: mockFn.data,
      error: mockFn.error,
      refetch: vi.fn(),
    };
  },
}));

import { WETRPane } from "./WETR";

function livePayload() {
  return {
    data: {
      status: "ok",
      location: "US_NORTHEAST",
      lat: 41.01,
      lon: -74,
      commodity_context: "natural gas and power demand",
      source_mode: "live_open_meteo",
      rows: [
        {
          date: "2026-09-11",
          day: 1,
          location: "US_NORTHEAST",
          lat: 41.01,
          lon: -74,
          temp_c: 18.2,
          precip_mm: 0.0,
          hdd: 0.0,
          cdd: 0.2,
          risk_flag: "normal",
          commodity_impact: "No unusual weather pressure flagged for gas.",
          source_mode: "live_open_meteo",
        },
      ],
      risk_flags: ["normal"],
      methodology: "WETR normalizes live daily forecast rows.",
    },
    sources: ["open_meteo"],
    elapsed_ms: 7,
  };
}

beforeEach(() => {
  localStorage.clear();
  mockFn.state = "idle";
  mockFn.data = undefined;
  mockFn.error = null;
  recordedCalls.length = 0;
});

afterEach(() => {
  cleanup();
});

describe("WETR pane — forecast horizon control (WETR#4)", () => {
  it("offers the manifest day options and sends the chosen horizon", () => {
    mockFn.state = "ok";
    mockFn.data = livePayload();
    render(<WETRPane code="WETR" />);
    for (const label of ["3d", "5d", "10d", "14d"]) {
      expect(screen.getByRole("tab", { name: label })).toBeInTheDocument();
    }
    fireEvent.click(screen.getByRole("tab", { name: "5d" }));
    const last = recordedCalls[recordedCalls.length - 1];
    expect(last.params).toMatchObject({ location: "US_NORTHEAST", days: 5 });
  });
});
