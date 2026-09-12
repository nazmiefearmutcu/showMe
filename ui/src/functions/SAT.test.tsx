/**
 * SAT — satellite & alt-data pane tests.
 *
 * Pins the canonical refresh pattern: `tick` stays OUT of `params` and drives
 * `refetch()` from an effect (the 60s poll must not flash the skeleton), the
 * honest `not_configured` disclosure, and — the P0 fix — the pane's wiring to
 * the REAL producer keys (`tile_url` / `true_color_tile.url` + `conditions.*`)
 * with a regression that the old `imagery.*` / `weather.*` paths stay dead.
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

/** Real producer payload (probe: double/raw/a2-sat-probe.json, 2026-09-12). */
function realData(overrides: Record<string, unknown> = {}) {
  return {
    status: "ok",
    data_mode: "delayed_reference",
    aoi: "cushing_ok",
    aoi_label: "Cushing OK tank farm",
    layer: "true_color",
    bbox_label: "-96.91510,35.83510,-96.61510,36.13510",
    capture_date: "2026-09-12",
    tile_url: "https://gibs.earthdata.nasa.gov/wms/realtile.png",
    true_color_tile: {
      label: "NASA GIBS MODIS_Terra_CorrectedReflectance_TrueColor (2026-09-12)",
      url: "https://gibs.earthdata.nasa.gov/wms/realtile.png",
      is_satellite: true,
    },
    conditions: {
      current_temp_c: 17.0,
      current_cloud_pct: 9,
      current_wind_ms: 23.1,
      weather_code: 0,
      daily_cloud_mean_pct: 13.0,
      daily_temp_max_c: 18.7,
      daily_temp_min_c: 14.0,
      daily_precip_mm: 0.0,
      source: "open_meteo",
    },
    cloud_pct: 13.0,
    rows: [],
    cards: [],
    methodology: "SAT surfaces real, keyless satellite tiles from NASA GIBS.",
    as_of: "2026-09-12T00:00:00+00:00",
    ...overrides,
  };
}

function envelope(data: Record<string, unknown>) {
  return {
    data: {
      data,
      sources: ["nasa_gibs", "open_meteo"],
      warnings: [],
    },
  };
}

function payload() {
  return envelope(realData());
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
    setMockFn({
      state: "ok",
      ...envelope({
        status: "provider_unavailable",
        data_mode: "not_configured",
        reason: "No live satellite/conditions source reachable.",
        rows: [],
        cards: [],
      }),
      refetch: vi.fn(),
    });
    render(<SATPane code="SAT" />);
    expect(
      screen.getByText(/Imagery provider not configured/i),
    ).toBeInTheDocument();
    expect(screen.getByText("not configured")).toBeInTheDocument();
    expect(
      screen.getByText(/No live satellite\/conditions source reachable/),
    ).toBeInTheDocument();
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

describe("SAT pane — P0 key-path wiring", () => {
  it("renders the imagery <img> from tile_url", () => {
    const { container } = render(<SATPane code="SAT" />);
    const img = container.querySelector("img");
    expect(img).not.toBeNull();
    expect(img).toHaveAttribute(
      "src",
      "https://gibs.earthdata.nasa.gov/wms/realtile.png",
    );
    expect(img).toHaveAttribute("alt", "Satellite imagery — Cushing OK tank farm");
  });

  it("falls back to true_color_tile.url when tile_url is absent", () => {
    setMockFn({
      state: "ok",
      ...envelope(
        realData({
          tile_url: undefined,
          true_color_tile: {
            label: "NASA GIBS MODIS_Terra_CorrectedReflectance_TrueColor (2026-09-12)",
            url: "https://gibs.earthdata.nasa.gov/wms/truecolor-only.png",
            is_satellite: true,
          },
        }),
      ),
      refetch: vi.fn(),
    });
    const { container } = render(<SATPane code="SAT" />);
    expect(container.querySelector("img")).toHaveAttribute(
      "src",
      "https://gibs.earthdata.nasa.gov/wms/truecolor-only.png",
    );
  });

  it("maps conditions.* values into the summary card (no em-dash wall)", () => {
    render(<SATPane code="SAT" />);
    expect(screen.getByText("17.0")).toBeInTheDocument();
    expect(screen.getByText("H 18.7° · L 14.0°")).toBeInTheDocument();
    expect(screen.getByText("Clear sky")).toBeInTheDocument();
    expect(screen.getByText("13% cloud")).toBeInTheDocument();
    expect(screen.getByText("now 9% cloud")).toBeInTheDocument();
    expect(screen.getByText("18.7 °C")).toBeInTheDocument();
    expect(screen.getByText("14.0 °C")).toBeInTheDocument();
    expect(screen.getByText("0.0 mm")).toBeInTheDocument();
    expect(screen.getByText("23.1 km/h")).toBeInTheDocument();
    expect(screen.queryByText("conditions unavailable")).toBeNull();
  });

  it("shows the honest image fallback when the tile errors", () => {
    const { container } = render(<SATPane code="SAT" />);
    const img = container.querySelector("img");
    expect(img).not.toBeNull();
    fireEvent.error(img as HTMLImageElement);
    expect(container.querySelector("img")).toBeNull();
    expect(screen.getByText("Imagery tile unavailable")).toBeInTheDocument();
    expect(
      screen.getByText(/NASA GIBS MODIS_Terra_CorrectedReflectance_TrueColor/),
    ).toBeInTheDocument();
  });

  it("degrades honestly when the wire has no tile and no conditions", () => {
    setMockFn({
      state: "ok",
      ...envelope({
        status: "provider_unavailable",
        data_mode: "not_configured",
        reason: "nasa_gibs: connect timeout",
        aoi_label: "Cushing OK tank farm",
        rows: [],
        cards: [],
      }),
      refetch: vi.fn(),
    });
    const { container } = render(<SATPane code="SAT" />);
    expect(container.querySelector("img")).toBeNull();
    expect(screen.getByText("Imagery tile unavailable")).toBeInTheDocument();
    expect(screen.getByText("conditions unavailable")).toBeInTheDocument();
    // No fabricated readings where the wire carried none.
    expect(screen.queryByText("17.0")).toBeNull();
    expect(screen.queryByText("18.7 °C")).toBeNull();
    expect(screen.queryByText("23.1 km/h")).toBeNull();
  });

  it("regression: the old imagery.* / weather.* paths are no longer read", () => {
    setMockFn({
      state: "ok",
      ...envelope({
        data_mode: "delayed_reference",
        as_of: "2026-09-12T00:00:00+00:00",
        imagery: {
          primary_url: "https://old.example/imagery.png",
          fallback_url: "https://old.example/fallback.png",
          attribution: "OLD ATTRIBUTION",
          layer: "true_color",
        },
        weather: {
          temperature_c: 99.9,
          apparent_c: 98.8,
          cloud_cover_pct: 88,
          summary: "OLD SUMMARY",
        },
        cards: [{ label: "OLD CARD", value: 42 }],
        rows: [],
      }),
      refetch: vi.fn(),
    });
    const { container } = render(<SATPane code="SAT" />);
    expect(container.querySelector("img")).toBeNull();
    expect(screen.queryByText(/old\.example/)).toBeNull();
    expect(screen.queryByText("99.9°C")).toBeNull();
    expect(screen.queryByText("OLD SUMMARY")).toBeNull();
    expect(screen.queryByText("OLD CARD")).toBeNull();
    expect(screen.getByText("Imagery tile unavailable")).toBeInTheDocument();
    expect(screen.getByText("NASA EOSDIS GIBS")).toBeInTheDocument();
  });

  it("R1-3: partial conditions render a bare dash, never '— °C / — mm / — km/h'", () => {
    setMockFn({
      state: "ok",
      ...envelope(
        realData({
          conditions: { current_temp_c: 17.0, source: "open_meteo" },
          cloud_pct: undefined,
        }),
      ),
      refetch: vi.fn(),
    });
    render(<SATPane code="SAT" />);

    // The present metric keeps its honest reading + unit…
    expect(screen.getByText("17.0")).toBeInTheDocument();
    // …the absent ones degrade to a single bare em-dash (no orphan units).
    expect(screen.queryByText("— °C")).toBeNull();
    expect(screen.queryByText("— mm")).toBeNull();
    expect(screen.queryByText("— km/h")).toBeNull();
    expect(screen.getAllByText("—").length).toBeGreaterThanOrEqual(4);
    // No fabricated readings where the wire carried none.
    expect(screen.queryByText("18.7")).toBeNull();
  });
});
