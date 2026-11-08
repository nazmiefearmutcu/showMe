/**
 * SAT#4 — the cloud percentage is shown as a modelled Open-Meteo value, never as
 * a satellite observation. The table's source column must not credit NASA GIBS
 * for a number GIBS did not produce.
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

function payloadWithCloudRow() {
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
        conditions: { daily_cloud_mean_pct: 13.0, current_cloud_pct: 9, source: "open_meteo" },
        cloud_pct: 13.0,
        rows: [
          {
            aoi: "Cushing OK tank farm",
            capture_utc: "2026-09-12",
            cloud_pct: 13.0,
            source: "nasa_gibs",
            cloud_source: "open_meteo_model",
            cloud_label: "Open-Meteo modelled cloud cover",
          },
        ],
        cards: [],
        methodology: "m",
      },
      sources: ["nasa_gibs", "open_meteo"],
      warnings: [],
    },
  };
}

beforeEach(() => {
  localStorage.clear();
  setMockFn({ state: "ok", ...payloadWithCloudRow(), refetch: vi.fn() });
});

afterEach(() => {
  cleanup();
});

describe("SAT pane — modelled cloud cover (SAT#4)", () => {
  it("marks the summary cloud figure as a model value from Open-Meteo", () => {
    render(<SATPane code="SAT" />);
    expect(screen.getByText("13% cloud")).toBeInTheDocument();
    expect(screen.getByText("model value (Open-Meteo)")).toBeInTheDocument();
  });

  it("attributes the table cloud row to Open-Meteo, not to NASA GIBS", () => {
    render(<SATPane code="SAT" />);
    expect(screen.getByText("Open-Meteo modelled cloud cover")).toBeInTheDocument();
    expect(screen.queryByText("nasa_gibs")).toBeNull();
  });
});
