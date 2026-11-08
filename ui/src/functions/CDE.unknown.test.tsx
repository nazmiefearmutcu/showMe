/**
 * CDE pane — an evaluation with a missing referenced field renders UNKNOWN
 * (CDE#3), never a silent FALSE. Kept in its own file so the group's owned
 * scope stays limited to new test files for this check.
 *
 * `useFunction` is mocked via mutable shared state (GEX pattern).
 */
import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, render, screen } from "@testing-library/react";
import { CDEPane } from "./CDE";

interface MockFnState {
  state: "idle" | "loading" | "ok" | "error" | "refreshing";
  data?: { data?: unknown } | undefined;
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

describe("CDE pane — unknown evaluation", () => {
  afterEach(() => {
    cleanup();
  });

  it("renders UNKNOWN, not FALSE, when the row is missing a referenced field", () => {
    setMockFn({
      state: "ok",
      data: {
        data: {
          status: "ready",
          rows: [],
          count: 1,
          evaluation: {
            name: "cheap",
            value: null,
            formula: "pe != 20",
            missing_fields: ["pe"],
          },
        },
      },
    });
    render(<CDEPane code="CDE" />);
    expect(screen.getByText("UNKNOWN")).toBeInTheDocument();
    expect(screen.queryByText("FALSE")).not.toBeInTheDocument();
    expect(screen.getByText(/Row is missing: pe/)).toBeInTheDocument();
  });
});
