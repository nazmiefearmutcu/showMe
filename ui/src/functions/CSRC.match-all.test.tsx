/**
 * CSRC pane — the ALL-sectors request must not test volume (CSRC#2).
 *
 * Volume is null for most reference contracts, and the DSL evaluates a null volume
 * as no match, so a `volume >= 0` predicate silently dropped 20 of 29 contracts when
 * quotes were not live. This test pins the query the pane actually sends.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { CSRCPane } from "./CSRC";

interface MockFnState {
  state: "idle" | "loading" | "ok" | "error" | "refreshing";
  data?: { data?: unknown; sources?: string[]; elapsed_ms?: number } | undefined;
  error?: Error | null;
}

const mockFn: MockFnState = { state: "idle", data: undefined, error: null };
const lastParams: { current: Record<string, unknown> | undefined } = { current: undefined };

vi.mock("@/lib/useFunction", () => ({
  useFunction: (opts: { params?: Record<string, unknown> }) => {
    lastParams.current = opts?.params;
    return {
      state: mockFn.state,
      data: mockFn.data,
      error: mockFn.error,
      refetch: vi.fn(),
    };
  },
}));

beforeEach(() => {
  localStorage.clear();
  mockFn.state = "ok";
  mockFn.data = { data: { status: "ok", rows: [], matched: 0, scanned: 0 } };
  mockFn.error = null;
});
afterEach(() => {
  cleanup();
});

describe("CSRC pane — ALL-sectors predicate (CSRC#2)", () => {
  it("sends a match-all query that does not test volume", () => {
    render(<CSRCPane code="CSRC" />);
    fireEvent.click(screen.getByTitle("Sector Metals"));
    fireEvent.click(screen.getByTitle("Sector ALL"));
    expect(lastParams.current?.query).toBe('sector != "NONE"');
    expect(String(lastParams.current?.query)).not.toMatch(/volume/);
  });
});
