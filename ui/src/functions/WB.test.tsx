/**
 * WB pane — live-by-default polarity, EM tab, template vintage + poll tests
 * (F4 macro lane).
 *
 * Pins:
 *  - the live toggle defaults ON (backend is live-by-default) and the fetch
 *    params carry `reference: false` with no `tick` key;
 *  - the visibility poll refetches via `refetch()`;
 *  - the Emerging tab filters the backend's EM rows;
 *  - template rows show the labelled model vintage, not "today".
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen, within } from "@testing-library/react";
import { WBPane } from "./WB";

/* ── useFunction / tick mocks ─────────────────────────────────────── */

interface MockFnState {
  state: "idle" | "loading" | "ok" | "error" | "refreshing";
  data?: { data?: unknown; sources?: string[]; warnings?: string[]; elapsed_ms?: number } | undefined;
  error?: Error | null;
  refetch: ReturnType<typeof vi.fn>;
}

const mockFn: MockFnState = {
  state: "idle",
  data: undefined,
  error: null,
  refetch: vi.fn(),
};

function setMockFn(next: Partial<MockFnState>) {
  mockFn.state = next.state ?? "idle";
  mockFn.data = next.data;
  mockFn.error = next.error ?? null;
  if (next.refetch) mockFn.refetch = next.refetch;
}

const mockTick = { current: 0 };
let lastFnArgs: Record<string, unknown> | undefined;

vi.mock("@/lib/useFunction", () => ({
  useFunction: (args: Record<string, unknown>) => {
    lastFnArgs = args;
    return {
      state: mockFn.state,
      data: mockFn.data,
      error: mockFn.error,
      refetch: mockFn.refetch,
    };
  },
}));

vi.mock("@/lib/useVisibilityTick", () => ({
  useVisibilityTick: () => mockTick.current,
}));

/* ── fixtures ──────────────────────────────────────────────────────── */

function livePayload() {
  return {
    data: {
      data: {
        rows: [
          { country: "US", tenor: "10Y", yield: 4.45, as_of: "2026-09-11", source_mode: "fred" },
          { country: "DE", tenor: "10Y", yield: 2.58, as_of: "2026-09-11", source_mode: "fred" },
          { country: "TR", tenor: "10Y", yield: 28.5, as_of: "2026-09-11", source_mode: "fred" },
          { country: "BR", tenor: "10Y", yield: 12.8, as_of: "2026-09-11", source_mode: "fred" },
        ],
        summary: { countries: 4, tenor: "10Y", source_mode: "fred" },
        methodology: "…",
      },
    },
    sources: ["fred"],
    warnings: [],
    elapsed_ms: 10,
  };
}

function templatePayload() {
  return {
    data: {
      data: {
        rows: [
          {
            country: "US",
            tenor: "10Y",
            yield: 4.45,
            as_of: "2025-12-31",
            source_mode: "sovereign_yield_model",
            reference_vintage: "2025-12-31",
          },
          {
            country: "TR",
            tenor: "10Y",
            yield: 28.5,
            as_of: "2025-12-31",
            source_mode: "sovereign_yield_model",
            reference_vintage: "2025-12-31",
          },
        ],
        summary: {
          countries: 2,
          tenor: "10Y",
          source_mode: "sovereign_yield_model",
          reference_vintage: "2025-12-31",
        },
        methodology: "…",
      },
    },
    sources: ["sovereign_yield_model"],
    warnings: ["Live yields unavailable"],
  };
}

beforeEach(() => {
  localStorage.clear();
  mockTick.current = 0;
  lastFnArgs = undefined;
  setMockFn({ state: "idle", data: undefined, refetch: vi.fn() });
});
afterEach(() => {
  cleanup();
});

describe("WB pane — live-by-default polarity", () => {
  it("defaults to live (reference:false) and keeps params tick-free", () => {
    setMockFn({ state: "ok", ...livePayload() });
    render(<WBPane code="WB" />);
    expect(lastFnArgs?.params).toEqual({ reference: false });
    expect(within(screen.getByTestId("wb-mode-pill")).getByText("live")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /live on/i })).toBeInTheDocument();
  });

  it("flips to reference when the live toggle is switched off", () => {
    setMockFn({ state: "ok", ...livePayload() });
    render(<WBPane code="WB" />);
    fireEvent.click(screen.getByRole("button", { name: /live on/i }));
    expect(lastFnArgs?.params).toEqual({ reference: true });
  });
});

describe("WB pane — emerging tab", () => {
  it("filters the backend EM rows under the Emerging tab", () => {
    setMockFn({ state: "ok", ...livePayload() });
    render(<WBPane code="WB" />);
    fireEvent.click(screen.getByRole("tab", { name: "Emerging" }));
    const grid = within(screen.getByRole("table"));
    expect(grid.getAllByText("TR").length).toBeGreaterThan(0);
    expect(grid.getAllByText("BR").length).toBeGreaterThan(0);
    expect(grid.queryByText("DE")).toBeNull();
  });

  it("renders an honest empty state when no EM rows exist", () => {
    const payload = livePayload();
    payload.data.data.rows = payload.data.data.rows.filter((r) => r.country === "US");
    setMockFn({ state: "ok", ...payload });
    render(<WBPane code="WB" />);
    fireEvent.click(screen.getByRole("tab", { name: "Emerging" }));
    expect(screen.getByText(/No yields/i)).toBeInTheDocument();
  });
});

describe("WB pane — template vintage", () => {
  it("stamps the model vintage, not today, on template rows", () => {
    setMockFn({ state: "ok", ...templatePayload() });
    render(<WBPane code="WB" />);
    expect(screen.getByText(/reference vintage 2025-12-31/i)).toBeInTheDocument();
    expect(screen.getAllByText("2025-12-31").length).toBeGreaterThan(0);
    expect(within(screen.getByTestId("wb-mode-pill")).getByText("stub")).toBeInTheDocument();
  });
});

describe("WB pane — visibility poll", () => {
  it("refetches on a visibility tick but not on mount", () => {
    const refetch = vi.fn();
    setMockFn({ state: "ok", ...livePayload(), refetch });
    const { rerender } = render(<WBPane code="WB" />);
    expect(refetch).not.toHaveBeenCalled();
    mockTick.current = 1;
    rerender(<WBPane code="WB" />);
    expect(refetch).toHaveBeenCalledTimes(1);
    expect(lastFnArgs?.params).toEqual({ reference: false });
  });
});
