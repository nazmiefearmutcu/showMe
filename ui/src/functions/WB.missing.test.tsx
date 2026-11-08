/**
 * WB#2 — countries the live FRED fetch could not supply must be visible in the
 * pane, not silently dropped from a shorter grid.
 *
 * The backend returns `missing_countries` (keyless FRED CSV 404 / no usable
 * observation). Before the fix the pane never read it: the subtitle read
 * "N of N countries" and the Emerging tab showed no notice about TR/BR/IN/CN/ID.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
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

function partialLivePayload() {
  return {
    data: {
      data: {
        rows: [
          { country: "US", tenor: "10Y", yield: 4.84, as_of: "2026-11-05", source_mode: "fred" },
          { country: "DE", tenor: "10Y", yield: 2.58, as_of: "2026-09-01", source_mode: "fred" },
          { country: "MX", tenor: "10Y", yield: 9.1, as_of: "2026-09-01", source_mode: "fred" },
        ],
        summary: { countries: 3, tenor: "10Y", source_mode: "fred", latest_observation: "2026-11-05" },
        missing_countries: ["TR", "BR", "IN", "CN", "ID"],
        methodology: "m",
        field_dictionary: {},
      },
      sources: ["fred"],
      elapsed_ms: 10,
    },
  };
}

beforeEach(() => {
  localStorage.clear();
  setMockFn({ state: "ok", ...partialLivePayload(), refetch: vi.fn() });
});

afterEach(() => {
  cleanup();
});

describe("WB pane — missing countries (WB#2)", () => {
  it("names the missing countries in a notice on the All tab", () => {
    render(<WBPane code="WB" />);
    expect(screen.getByText(/Live data missing for TR, BR, IN, CN, ID/)).toBeInTheDocument();
  });

  it("reports the requested roster size in the subtitle, not the shorter grid", () => {
    render(<WBPane code="WB" />);
    expect(screen.getByText(/3 of 8 countries/)).toBeInTheDocument();
    expect(screen.queryByText(/3 of 3 countries/)).toBeNull();
  });

  it("keeps the missing emerging countries visible on the Emerging tab", () => {
    render(<WBPane code="WB" />);
    fireEvent.click(screen.getByRole("tab", { name: "Emerging" }));
    expect(screen.getByText(/Live data missing for TR, BR, IN, CN, ID/)).toBeInTheDocument();
    expect(screen.getByText(/1 of 6 countries/)).toBeInTheDocument();
  });

  it("does not list missing emerging countries on the Developed tab", () => {
    render(<WBPane code="WB" />);
    fireEvent.click(screen.getByRole("tab", { name: "Developed" }));
    expect(screen.queryByText(/Live data missing/)).toBeNull();
  });

  it("shows the missing notice even when the Emerging tab has no rows at all", () => {
    setMockFn({
      state: "ok",
      data: {
        data: {
          rows: [{ country: "US", tenor: "10Y", yield: 4.84, as_of: "2026-11-05", source_mode: "fred" }],
          summary: { countries: 1, tenor: "10Y", source_mode: "fred" },
          missing_countries: ["TR", "BR"],
          methodology: "m",
        },
      },
      refetch: vi.fn(),
    });
    render(<WBPane code="WB" />);
    fireEvent.click(screen.getByRole("tab", { name: "Emerging" }));
    expect(screen.getByText(/No yields/i)).toBeInTheDocument();
    expect(screen.getByText(/Live data missing for TR, BR/)).toBeInTheDocument();
  });
});
