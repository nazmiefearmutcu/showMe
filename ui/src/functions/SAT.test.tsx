/**
 * SAT — satellite & alt-data pane tests.
 *
 * Pins the canonical refresh pattern: `tick` stays OUT of `params` and drives
 * `refetch()` from an effect (the 60s poll must not flash the skeleton), plus
 * the honest `not_configured` disclosure.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, render, screen } from "@testing-library/react";
import { SATPane } from "./SAT";

interface MockFnState {
  state: "idle" | "loading" | "ok" | "error" | "refreshing";
  data?: { data?: unknown; sources?: string[]; warnings?: string[] } | undefined;
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

function payload() {
  return {
    data: {
      data: {
        data_mode: "not_configured",
        as_of: "2026-09-11",
        imagery: {
          primary_url: "https://gibs.earthdata.nasa.gov/tile.png",
          fallback_url: "https://gibs.earthdata.nasa.gov/fallback.png",
          layer: "true_color",
          capture_utc: "2026-09-11",
          attribution: "NASA EOSDIS GIBS",
        },
        weather: { temperature_c: 21.5, cloud_cover_pct: 12, summary: "Clear" },
        cards: [{ label: "Cloud", value: 12, unit: "%" }],
        rows: [],
      },
      sources: ["nasa_gibs"],
      warnings: [],
    },
  };
}

beforeEach(() => {
  localStorage.clear();
  mockTick.current = 0;
  lastFnArgs = undefined;
  setMockFn({ state: "ok", ...payload(), refetch: vi.fn() });
});
afterEach(() => {
  cleanup();
});

describe("SAT pane — honesty", () => {
  it("renders the not_configured disclosure verbatim", () => {
    render(<SATPane code="SAT" />);
    expect(
      screen.getByText(/Imagery provider not configured/i),
    ).toBeInTheDocument();
    expect(screen.getByText("not configured")).toBeInTheDocument();
  });
});

describe("SAT pane — visibility poll (live adoption)", () => {
  it("refetches on a visibility tick but not on mount", () => {
    const refetch = vi.fn();
    setMockFn({ state: "ok", ...payload(), refetch });
    const { rerender } = render(<SATPane code="SAT" />);
    expect(refetch).not.toHaveBeenCalled();

    mockTick.current = 1;
    rerender(<SATPane code="SAT" />);
    expect(refetch).toHaveBeenCalledTimes(1);
  });

  it("keeps the AOI params stable across ticks (no tick key)", () => {
    const { rerender } = render(<SATPane code="SAT" />);
    const before = JSON.stringify(lastFnArgs?.params ?? null);
    expect(before).toContain("aoi");
    expect(before).not.toContain("tick");

    mockTick.current = 4;
    rerender(<SATPane code="SAT" />);
    expect(JSON.stringify(lastFnArgs?.params ?? null)).toBe(before);
  });
});
