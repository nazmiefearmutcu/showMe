/**
 * GC3D pane — P2A-G09 honesty cases (fallback notice and template span).
 *
 * Kept in its own file so the base GC3D.test.tsx stays untouched.
 */
import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, render, screen } from "@testing-library/react";
import { GC3DPane } from "./GC3D";

interface MockFnState {
  state: "idle" | "loading" | "ok" | "error" | "refreshing";
  data?: {
    data?: unknown;
    sources?: string[];
    elapsed_ms?: number;
    warnings?: string[];
  };
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

const TENORS = ["3M", "2Y", "10Y", "30Y"];
const TENOR_YEARS: Record<string, number> = { "3M": 0.25, "2Y": 2, "10Y": 10, "30Y": 30 };
const DATES = ["2026-07-24", "2026-08-08", "2026-09-07"];
const LEVELS: Record<string, Record<string, number>> = {
  "2026-07-24": { "3M": 5.28, "2Y": 4.62, "10Y": 4.45, "30Y": 4.67 },
  "2026-08-08": { "3M": 5.295, "2Y": 4.635, "10Y": 4.465, "30Y": 4.685 },
  "2026-09-07": { "3M": 5.31, "2Y": 4.65, "10Y": 4.48, "30Y": 4.7 },
};

const SURFACE = DATES.flatMap((date) =>
  TENORS.map((tenor) => ({
    date,
    tenor,
    tenor_years: TENOR_YEARS[tenor],
    yield: LEVELS[date][tenor],
  })),
);

function modelPayload() {
  return {
    data: {
      data: {
        surface: SURFACE,
        rows: SURFACE,
        tenors: TENORS,
        dates: DATES,
        summary: {
          source_mode: "yield_curve_model",
          dates: 3,
          tenors: 4,
          points: 12,
          days: 365,
        },
        methodology: "GC3D builds a date-by-tenor yield surface.",
      },
      sources: ["yield_curve_model"],
      elapsed_ms: 2,
    },
  };
}

afterEach(() => {
  cleanup();
});

describe("GC3D pane — honest fallback notice and span (P2A-G09)", () => {
  it("shows the backend warning text, not an asserted missing FRED key", () => {
    const payload = modelPayload();
    const warning =
      "Live FRED curve unavailable (keyed adapter or keyless CSV); showing the labelled reference template with a 45-day span.";
    setMockFn({ state: "ok", ...payload, data: { ...payload.data, warnings: [warning] } });
    render(<GC3DPane code="GC3D" symbol="US10Y" />);
    expect(screen.getByText(/Live FRED curve unavailable/)).toBeInTheDocument();
    expect(screen.queryByText(/No FRED key is configured/i)).toBeNull();
  });

  it("reports the template span in the header caption and footer, not the requested window", () => {
    const payload = modelPayload();
    payload.data.data.summary.days = 45;
    setMockFn({ state: "ok", ...payload });
    render(<GC3DPane code="GC3D" symbol="US10Y" />);
    expect(screen.getByText("LOOK-BACK 45D")).toBeInTheDocument();
    expect(screen.queryByText("LOOK-BACK 30D")).toBeNull();
    expect(screen.getByText("45")).toBeInTheDocument();
  });
});
