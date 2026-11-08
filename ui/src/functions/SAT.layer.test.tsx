/**
 * SAT#3 — the pane exposes the GIBS layer choice instead of hard-coding true colour.
 *
 * Before the fix the params were always `{ aoi, layer: "true_color" }`, so the
 * NDVI, moisture, thermal and SWIR layers the backend serves could not be chosen.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { SATPane } from "./SAT";

interface MockFnState {
  state: "idle" | "loading" | "ok" | "error" | "refreshing";
  data?: { data?: unknown; sources?: string[]; warnings?: string[] } | undefined;
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
  useVisibilityTick: () => 0,
}));

function okEnvelope() {
  return {
    data: {
      data: {
        status: "ok",
        data_mode: "delayed_reference",
        aoi: "cushing_ok",
        aoi_label: "Cushing OK tank farm",
        layer: "true_color",
        capture_date: "2026-09-12",
        tile_url: "https://gibs.earthdata.nasa.gov/wms/realtile.png",
        conditions: {},
        rows: [],
        cards: [],
        methodology: "m",
      },
      sources: ["nasa_gibs"],
      warnings: [],
    },
  };
}

beforeEach(() => {
  localStorage.clear();
  lastFnArgs = undefined;
  setMockFn({ state: "ok", ...okEnvelope(), refetch: vi.fn() });
});

afterEach(() => {
  cleanup();
});

describe("SAT pane — layer control (SAT#3)", () => {
  it("offers every backend layer as a choice", () => {
    render(<SATPane code="SAT" />);
    for (const label of ["True colour", "NDVI", "Moisture", "Thermal", "SWIR"]) {
      expect(screen.getByRole("tab", { name: label })).toBeInTheDocument();
    }
  });

  it("sends the chosen layer in the fetch params", () => {
    render(<SATPane code="SAT" />);
    expect(lastFnArgs?.params).toEqual({ aoi: "cushing_ok", layer: "true_color" });
    fireEvent.click(screen.getByRole("tab", { name: "SWIR" }));
    expect(lastFnArgs?.params).toEqual({ aoi: "cushing_ok", layer: "swir" });
  });

  it("keeps the layer choice out of the tick key", () => {
    render(<SATPane code="SAT" />);
    fireEvent.click(screen.getByRole("tab", { name: "NDVI" }));
    // The layer is a fetch param, not a poll trigger: choosing it must not
    // refetch by itself, and the params carry exactly the aoi and layer keys.
    expect(mockFn.refetch).not.toHaveBeenCalled();
    expect(Object.keys(lastFnArgs?.params ?? {}).sort()).toEqual(["aoi", "layer"]);
    expect(lastFnArgs?.params).toEqual({ aoi: "cushing_ok", layer: "ndvi" });
  });
});
