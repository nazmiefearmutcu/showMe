/**
 * WB#4 — the Δ-vs-US column must say when a spread mixes observation dates.
 *
 * US is a daily FRED print while most foreign rows are monthly prints, so
 * the spread can subtract values from different days. Each Δ cell carries
 * the day gap to the US observation; same-day spreads carry no note.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, render, screen, within } from "@testing-library/react";
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

function mixedFrequencyPayload() {
  return {
    data: {
      data: {
        rows: [
          { country: "US", tenor: "10Y", yield: 4.84, as_of: "2026-11-05", source_mode: "fred" },
          { country: "DE", tenor: "10Y", yield: 3.4695, as_of: "2026-09-01", source_mode: "fred" },
          { country: "JP", tenor: "10Y", yield: 1.0, as_of: "2026-11-05", source_mode: "fred" },
        ],
        summary: { countries: 3, tenor: "10Y", source_mode: "fred", latest_observation: "2026-11-05" },
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
  setMockFn({ state: "ok", ...mixedFrequencyPayload(), refetch: vi.fn() });
});

afterEach(() => {
  cleanup();
});

describe("WB pane — Δ vs US date alignment (WB#4)", () => {
  it("flags a spread whose foreign observation is a different day from the US print", () => {
    render(<WBPane code="WB" />);
    const table = within(screen.getByRole("table"));
    const deRow = table.getByText("DE").closest("tr");
    expect(deRow).not.toBeNull();
    expect(within(deRow as HTMLElement).getByText(/-137 bp/)).toBeInTheDocument();
    expect(within(deRow as HTMLElement).getByText("65d apart")).toBeInTheDocument();
  });

  it("adds no date note to a spread on the same observation day as US", () => {
    render(<WBPane code="WB" />);
    const table = within(screen.getByRole("table"));
    const jpRow = table.getByText("JP").closest("tr");
    expect(jpRow).not.toBeNull();
    expect(within(jpRow as HTMLElement).queryByText(/d apart/)).toBeNull();
  });
});
