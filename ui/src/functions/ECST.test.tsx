/**
 * ECST pane — source-mode honesty + series-switch tests (F4 macro lane).
 *
 * Pins:
 *  - the green "live" pill only appears for real providers (fred/worldbank);
 *    the labelled `macro_series_baseline` fallback renders as "reference";
 *  - the empty state renders honestly;
 *  - the SERIES segmented control drives the fetch params.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
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

/* ── fixtures ──────────────────────────────────────────────────────── */

function seriesPayload(sourceMode: string) {
  return {
    data: {
      data: {
        series_id: "CPIAUCSL",
        series_name: "US CPI all urban consumers",
        unit: "index",
        frequency: "monthly",
        source_mode: sourceMode,
        rows: [
          { date: "2026-04-01", value: 310.1, unit: "index", frequency: "monthly", source_mode: sourceMode },
          { date: "2026-05-01", value: 311.4, unit: "index", frequency: "monthly", source_mode: sourceMode },
        ],
        cards: [{ label: "Latest", value: 311.4 }],
        methodology: "…",
        field_dictionary: {},
      },
    },
    sources: sourceMode === "macro_series_baseline" ? ["macro_series_baseline"] : ["fred"],
    warnings: sourceMode === "macro_series_baseline" ? ["fred unavailable"] : [],
    elapsed_ms: 9,
  };
}

beforeEach(() => {
  localStorage.clear();
  lastFnArgs = undefined;
  setMockFn({ state: "idle", data: undefined, refetch: vi.fn() });
});
afterEach(() => {
  cleanup();
});

describe("ECST pane — source-mode honesty", () => {
  it("labels the macro_series_baseline fallback as reference, never live", () => {
    setMockFn({ state: "ok", ...seriesPayload("macro_series_baseline") });
    render(<ECSTPane code="ECST" />);
    const pill = screen.getByTestId("ecst-mode-pill");
    expect(pill.textContent).toContain("reference");
    expect(pill.textContent).not.toContain("live");
    expect(screen.getAllByText("macro_series_baseline").length).toBeGreaterThan(0);
  });

  it("labels a fred payload live", () => {
    setMockFn({ state: "ok", ...seriesPayload("fred") });
    render(<ECSTPane code="ECST" />);
    expect(screen.getByTestId("ecst-mode-pill").textContent).toContain("live");
  });

  it("labels a worldbank payload live", () => {
    const payload = seriesPayload("worldbank");
    setMockFn({ state: "ok", ...payload });
    render(<ECSTPane code="ECST" />);
    expect(screen.getByTestId("ecst-mode-pill").textContent).toContain("live");
  });

  it("renders the empty state when a series returns no rows", () => {
    const payload = seriesPayload("fred");
    (payload.data.data as Record<string, unknown>).rows = [];
    (payload.data.data as Record<string, unknown>).history = [];
    setMockFn({ state: "ok", ...payload });
    render(<ECSTPane code="ECST" />);
    expect(screen.getByText(/No observations/i)).toBeInTheDocument();
  });
});

describe("ECST pane — series control", () => {
  it("switches the fetched series_id", () => {
    setMockFn({ state: "ok", ...seriesPayload("fred") });
    render(<ECSTPane code="ECST" />);
    expect(lastFnArgs?.params).toEqual({ series_id: "CPIAUCSL" });
    fireEvent.click(screen.getByRole("button", { name: "GDP" }));
    expect(lastFnArgs?.params).toEqual({ series_id: "GDPC1" });
  });
});
