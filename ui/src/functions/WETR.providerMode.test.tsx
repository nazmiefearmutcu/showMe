/**
 * WETR pane — data mode control (WETR#4-RQ).
 *
 * The manifest's provider_mode input (live_official | modeled) must be a real
 * control: the pane sends the chosen mode, defaulting to Live.
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

beforeEach(() => {
  localStorage.clear();
  mockFn.state = "ok";
  mockFn.data = { data: { status: "ok", rows: [], source_mode: "live_open_meteo" }, sources: [] };
  mockFn.error = null;
  recordedCalls.length = 0;
});

afterEach(() => {
  cleanup();
});

describe("WETR pane — data mode control (WETR#4-RQ)", () => {
  it("offers Live and Modeled and sends provider_mode, defaulting to live_official", () => {
    render(<WETRPane code="WETR" />);
    expect(screen.getByRole("tab", { name: "Live" })).toBeInTheDocument();
    expect(screen.getByRole("tab", { name: "Modeled" })).toBeInTheDocument();
    expect(recordedCalls[recordedCalls.length - 1].params).toMatchObject({
      provider_mode: "live_official",
    });
    fireEvent.click(screen.getByRole("tab", { name: "Modeled" }));
    expect(recordedCalls[recordedCalls.length - 1].params).toMatchObject({
      provider_mode: "modeled",
    });
  });
});
