/**
 * DINE pane — data-honesty + render-contract tests.
 *
 * Pins the DINE restaurant-lookup contract:
 *  - the four load states (loading / empty / error / ok) render;
 *  - provider_unavailable / empty payloads carry the backend reason in
 *    an explicit empty state (nothing fabricated);
 *  - place cards render name, type pill, distance and full OSM address;
 *  - a missing rating renders "—" (ratings are NOT fabricated);
 *  - the place-type filter is derived from the payload's own `type`
 *    values and filters the card list (one interaction).
 *
 * `useFunction` is mocked via a mutable shared state so each test drives
 * the pane into a specific branch without the real sidecar transport.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { DINEPane } from "./DINE";

/* ── useFunction mock ──────────────────────────────────────────────── */

interface MockFnState {
  state: "idle" | "loading" | "ok" | "error" | "refreshing";
  data?: {
    data?: unknown;
    warnings?: string[];
    sources?: string[];
    elapsed_ms?: number;
  } | undefined;
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

// SymbolBar pulls router/symbol-resolver side effects we don't need here.
vi.mock("@/shell/SymbolBar", () => ({
  SymbolBar: () => null,
}));

/* ── fixtures ──────────────────────────────────────────────────────── */

function place(
  name: string,
  type: string,
  distance: number | null,
  rating: number | null = null,
) {
  return {
    name,
    display_name: `${name}, Test Street 1, Testville, United States`,
    lat: 40.72,
    lon: -74.0,
    distance_km: distance,
    osm_type: "way",
    osm_id: 1234,
    place_id: 1000 + (distance ?? 0),
    category: "amenity",
    type,
    opening_hours: "Mo-Su 11:00-22:00",
    rating,
    price: null,
    source_mode: "openstreetmap_nominatim",
  };
}

function livePayload() {
  return {
    warnings: [],
    sources: ["openstreetmap_nominatim"],
    elapsed_ms: 800,
    data: {
      status: "live",
      location: "SoHo New York",
      query: "restaurant",
      rows: [
        place("Bistro A", "restaurant", 0.12),
        place("Burger B", "fast_food", 0.45),
        place("Cafe C", "cafe", 0.9, 4.5),
      ],
    },
  };
}

/* ── tests ─────────────────────────────────────────────────────────── */

beforeEach(() => {
  setMockFn({ state: "idle", data: undefined });
});
afterEach(() => {
  cleanup();
});

describe("DINE pane — load states", () => {
  it("renders a skeleton while loading", () => {
    setMockFn({ state: "loading", data: undefined });
    const { container } = render(<DINEPane code="DINE" />);
    expect(container.querySelector('[aria-busy="true"]')).not.toBeNull();
  });

  it("renders the error state when the fetch errors", () => {
    setMockFn({
      state: "error",
      data: undefined,
      error: new Error("sidecar exploded"),
    });
    render(<DINEPane code="DINE" />);
    expect(screen.getByText(/sidecar exploded/i)).toBeInTheDocument();
  });

  it("renders the provider failure reason as an explicit empty state", () => {
    setMockFn({
      state: "ok",
      data: {
        data: {
          status: "provider_unavailable",
          reason: "OpenStreetMap lookup failed: Nominatim rate-limited (HTTP 429).",
          rows: [],
        },
      },
    });
    render(<DINEPane code="DINE" />);
    expect(screen.getByText("OpenStreetMap lookup failed")).toBeInTheDocument();
    expect(screen.getByText(/Nominatim rate-limited/i)).toBeInTheDocument();
  });

  it("renders the empty state with the backend reason when nothing matched", () => {
    setMockFn({
      state: "ok",
      data: {
        data: {
          status: "empty",
          reason: 'No OpenStreetMap restaurants matched \'zzz\' near "Nowhere".',
          rows: [],
        },
      },
    });
    render(<DINEPane code="DINE" />);
    expect(screen.getByText("No restaurants matched")).toBeInTheDocument();
    expect(screen.getByText(/matched 'zzz'/i)).toBeInTheDocument();
  });
});

describe("DINE pane — cards + honesty", () => {
  it("renders place cards with name, type pill, distance and address", () => {
    setMockFn({ state: "ok", data: livePayload() });
    const { container } = render(<DINEPane code="DINE" />);
    const list = screen.getByRole("list", { name: /restaurant results/i });
    expect(list.children.length).toBe(3);
    expect(screen.getByText("Bistro A")).toBeInTheDocument();
    expect(screen.getByText("Burger B")).toBeInTheDocument();
    expect(container.textContent).toContain("0.45 km");
    expect(container.textContent).toContain("Test Street 1");
  });

  it("never fabricates a missing rating — it renders an em dash", () => {
    setMockFn({ state: "ok", data: livePayload() });
    const { container } = render(<DINEPane code="DINE" />);
    // Two rows have rating null; only Cafe C carries 4.5.
    expect(container.textContent).toContain("rating 4.5");
    expect(container.textContent).toContain("rating —");
    expect(container.textContent).toContain("price —");
  });

  it("shows the data-coverage note (ratings not fabricated)", () => {
    setMockFn({ state: "ok", data: livePayload() });
    render(<DINEPane code="DINE" />);
    expect(
      screen.getByRole("status", { name: /data coverage note/i }),
    ).toHaveTextContent(/Ratings and prices are NOT fabricated/i);
  });
});

describe("DINE pane — interaction", () => {
  it("filters the card list by a payload-derived place type", () => {
    setMockFn({ state: "ok", data: livePayload() });
    render(<DINEPane code="DINE" />);
    // Type chips derive from the payload: ALL / CAFE / FAST_FOOD / RESTAURANT.
    fireEvent.click(screen.getByRole("button", { name: "CAFE" }));
    const list = screen.getByRole("list", { name: /restaurant results/i });
    expect(list.children.length).toBe(1);
    expect(screen.getByText("Cafe C")).toBeInTheDocument();
    expect(screen.queryByText("Bistro A")).toBeNull();
  });
});
