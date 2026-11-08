/**
 * NGAS pane — unsupported-contract state (NGAS#1).
 *
 * NGAS serves only Henry Hub (NG=F). A TTF request must render an explicit
 * "Contract not served" empty state with the backend reason, never a
 * Henry Hub price card.
 *
 * `useFunction` is mocked via a mutable shared state.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, render, screen } from "@testing-library/react";
import { NGASPane } from "./NGAS";

interface MockFnState {
  state: "idle" | "loading" | "ok" | "error" | "refreshing";
  data?: { data?: unknown; sources?: string[]; elapsed_ms?: number };
  error?: Error | null;
}

const mockFn: MockFnState = { state: "idle", data: undefined, error: null };

function setMockFn(next: MockFnState) {
  mockFn.state = next.state;
  mockFn.data = next.data;
  mockFn.error = next.error ?? null;
}

let lastFunctionArgs: { enabled?: boolean; symbol?: string } | undefined;

vi.mock("@/lib/useFunction", () => ({
  useFunction: (args: { enabled?: boolean; symbol?: string }) => {
    lastFunctionArgs = args;
    return {
      state: mockFn.state,
      data: mockFn.data,
      error: mockFn.error,
      refetch: vi.fn(),
    };
  },
}));

function unsupportedPayload() {
  return {
    data: {
      data: {
        status: "input_error",
        error_kind: "unsupported_contract",
        reason:
          "TTF=F is not served by NGAS. NGAS only serves the Henry Hub contract (NG=F, USD/MMBtu); no other contract's rows are substituted.",
        contract: "TTF=F",
        supported_contracts: ["NG=F"],
        rows: [],
        history: [],
      },
      sources: [],
      elapsed_ms: 3,
    },
  };
}

beforeEach(() => {
  localStorage.clear();
  setMockFn({ state: "idle", data: undefined });
});
afterEach(() => {
  cleanup();
});

describe("NGAS pane — unsupported contract", () => {
  it("shows an explicit contract-not-served state with the backend reason", () => {
    setMockFn({ state: "ok", ...unsupportedPayload() });
    render(<NGASPane code="NGAS" symbol="TTF=F" />);
    expect(screen.getByText("Contract not served")).toBeInTheDocument();
    expect(screen.getByText(/TTF=F is not served by NGAS/i)).toBeInTheDocument();
  });

  it("does not send a TTF request to the backend at all", () => {
    setMockFn({ state: "idle", data: undefined });
    render(<NGASPane code="NGAS" symbol="TTF=F" />);
    expect(lastFunctionArgs?.enabled).toBe(false);
    expect(screen.getByText("Contract not served")).toBeInTheDocument();
  });

  it("still requests the served NG=F contract", () => {
    setMockFn({ state: "loading", data: undefined });
    render(<NGASPane code="NGAS" symbol="NG=F" />);
    expect(lastFunctionArgs?.enabled).toBe(true);
  });

  it("renders no Henry Hub price card for the unsupported request", () => {
    setMockFn({ state: "ok", ...unsupportedPayload() });
    const { container } = render(<NGASPane code="NGAS" symbol="TTF=F" />);
    expect(container.querySelector('[aria-label="NGAS spot cards"]')).toBeNull();
    expect(screen.queryByText("No live quote returned")).toBeNull();
  });
});
