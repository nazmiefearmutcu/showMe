/**
 * ECST requested-but-not-applied disclosure (WC1-G24 ECST#3) and the input
 * error state (WC1-G24 ECST#4).
 *
 * When the keyless FRED source cannot honour a requested frequency or vintage
 * the response lists it in unhonoured_params; the pane must say so rather than
 * show native observations as if the request had been applied. An input_error
 * must show the backend reason, not a generic "returned no rows".
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, render, screen } from "@testing-library/react";
import { ECSTPane } from "./ECST";

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

vi.mock("@/lib/useFunction", () => ({
  useFunction: () => ({
    state: mockFn.state,
    data: mockFn.data,
    error: mockFn.error,
    refetch: mockFn.refetch,
  }),
}));

function livePayload(extra: Record<string, unknown>) {
  return {
    data: {
      data: {
        series_id: "DGS10",
        series_name: "US 10Y Treasury yield",
        unit: "%",
        frequency: "daily",
        source_mode: "fred",
        status: "ok",
        rows: [
          { date: "2026-09-01", value: 4.0, unit: "%", frequency: "daily", source_mode: "fred" },
          { date: "2026-09-02", value: 4.1, unit: "%", frequency: "daily", source_mode: "fred" },
        ],
        cards: [{ label: "Latest", value: 4.1 }],
        methodology: "…",
        field_dictionary: {},
        ...extra,
      },
    },
    sources: ["fred"],
    warnings: [],
    elapsed_ms: 9,
  };
}

beforeEach(() => {
  localStorage.clear();
  setMockFn({ state: "idle", data: undefined, refetch: vi.fn() });
});
afterEach(() => {
  cleanup();
});

describe("ECST pane — request not applied", () => {
  it("says the monthly frequency was not applied and shows the native frequency", () => {
    setMockFn({
      state: "ok",
      ...livePayload({ unhonoured_params: ["frequency"] }),
    });
    render(<ECSTPane code="ECST" />);
    const note = screen.getByRole("note", { name: "ECST request not applied" });
    expect(note.textContent).toContain("frequency not applied");
    expect(note.textContent).toContain("native frequency (daily)");
  });

  it("shows no notice when every requested parameter was honoured", () => {
    setMockFn({ state: "ok", ...livePayload({}) });
    render(<ECSTPane code="ECST" />);
    expect(screen.queryByRole("note", { name: "ECST request not applied" })).toBeNull();
  });
});

describe("ECST pane — input error", () => {
  it("shows the backend reason for an invalid date range", () => {
    setMockFn({
      state: "ok",
      ...livePayload({
        status: "input_error",
        rows: [],
        history: [],
        reason: "unsupported date_range '6X': use a positive count with unit D, M or Y",
      }),
    });
    render(<ECSTPane code="ECST" />);
    expect(screen.getByText("Invalid request")).toBeTruthy();
    expect(screen.getByText(/unsupported date_range '6X'/)).toBeTruthy();
    expect(screen.queryByText(/returned no rows/)).toBeNull();
  });
});
