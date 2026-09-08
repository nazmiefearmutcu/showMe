/**
 * FLY pane — data-honesty + render-contract tests.
 *
 * Pins the FLY flight-tracking contract:
 *  - the four load states (loading / empty / error / ok) render;
 *  - the provider_unavailable payload (OpenSky down or live_flight off)
 *    renders its reason as an explicit empty state — no sample traffic;
 *  - aircraft rows render callsign, country, altitude, speed and an
 *    honest on-ground / airborne pill;
 *  - the coverage note states positions are ADS-B snapshots and routes
 *    are not inferred;
 *  - one interaction: callsign filter Apply updates the applied filter.
 *
 * `useFunction` is mocked via a mutable shared state so each test drives
 * the pane into a specific branch without the real sidecar transport.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { FLYPane } from "./FLY";

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

function aircraft(callsign: string, onGround: boolean) {
  return {
    icao24: callsign.toLowerCase().replace(/[^a-z0-9]/g, "") + "ab",
    callsign,
    origin_country: "Turkey",
    last_contact_utc: "2026-09-07T22:16:54+00:00",
    lon: 28.72,
    lat: 41.26,
    altitude_ft: onGround ? 0 : 35000,
    speed_kt: onGround ? 12 : 430,
    heading: 359.17,
    vertical_rate_mps: 0,
    on_ground: onGround,
    source_mode: "opensky_states_all",
  };
}

function livePayload() {
  return {
    warnings: [],
    sources: ["opensky"],
    elapsed_ms: 1200,
    data: {
      status: "live",
      rows: [
        aircraft("THY6439", false),
        aircraft("THY1", true),
        aircraft("PGT1234", false),
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

describe("FLY pane — load states", () => {
  it("renders a skeleton while loading", () => {
    setMockFn({ state: "loading", data: undefined });
    const { container } = render(<FLYPane code="FLY" />);
    expect(container.querySelector('[aria-busy="true"]')).not.toBeNull();
  });

  it("renders the error state when the fetch errors", () => {
    setMockFn({
      state: "error",
      data: undefined,
      error: new Error("sidecar exploded"),
    });
    render(<FLYPane code="FLY" />);
    expect(screen.getByText(/sidecar exploded/i)).toBeInTheDocument();
  });

  it("renders the OpenSky outage reason without inventing aircraft", () => {
    setMockFn({
      state: "ok",
      data: {
        data: {
          status: "provider_unavailable",
          reason:
            "OpenSky live tracking is unavailable or live_flight is disabled; no sample aircraft are shown.",
          rows: [],
        },
      },
    });
    render(<FLYPane code="FLY" />);
    expect(screen.getByText("No live aircraft")).toBeInTheDocument();
    expect(screen.getByText(/no sample aircraft are shown/i)).toBeInTheDocument();
    expect(
      screen.getByRole("status", { name: /tracking coverage note/i }),
    ).toHaveTextContent(/never\s+substituted/i);
  });
});

describe("FLY pane — table + honesty", () => {
  it("renders aircraft rows with state pills in the accessible table", () => {
    setMockFn({ state: "ok", data: livePayload() });
    render(<FLYPane code="FLY" />);
    expect(
      screen.getByRole("table", { name: /FLY aircraft table/i }),
    ).toBeInTheDocument();
    expect(screen.getByText("THY6439")).toBeInTheDocument();
    expect(screen.getByText("PGT1234")).toBeInTheDocument();
    expect(screen.getAllByText("airborne").length).toBe(2);
    expect(screen.getAllByText("on ground").length).toBe(1);
  });

  it("states that routes are not inferred (coverage note)", () => {
    setMockFn({ state: "ok", data: livePayload() });
    render(<FLYPane code="FLY" />);
    expect(
      screen.getByRole("status", { name: /tracking coverage note/i }),
    ).toHaveTextContent(/not inferred/i);
  });

  it("shows honest KPI counts (airborne vs ground)", () => {
    setMockFn({ state: "ok", data: livePayload() });
    const { container } = render(<FLYPane code="FLY" />);
    expect(container.textContent).toContain("2 AIRBORNE · 1 GROUND");
  });
});

describe("FLY pane — interaction", () => {
  it("applies a callsign filter and shows it on the KPI card", () => {
    setMockFn({ state: "ok", data: livePayload() });
    render(<FLYPane code="FLY" />);
    fireEvent.change(screen.getByLabelText("Callsign filter"), {
      target: { value: "thy" },
    });
    fireEvent.click(screen.getByText("Apply"));
    // The applied filter is uppercased and surfaced on the KPI card.
    expect(screen.getByText("THY")).toBeInTheDocument();
  });
});
