/**
 * WETR pane — source honesty + poll contract (audit A4 fixes).
 *
 * The backend chain serves KEYLESS Open-Meteo live rows by default
 * (`status: "ok"`, `source_mode: "live_open_meteo"`); the seasonal model is
 * only the `reference=true` / provider-outage fallback. Pins:
 *
 *  - live_open_meteo is labelled live (provider named), never "seasonal model"
 *    (audit A4-H: the old substring check only matched "openweather");
 *  - provider failures with `seasonal_model` keep the amber notice + reason;
 *  - the visibility tick never enters the fetch params (audit A4-M).
 *
 * `useFunction` is mocked via a mutable shared state + recorded calls.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, render, screen } from "@testing-library/react";

interface MockFnState {
  state: "idle" | "loading" | "ok" | "error" | "refreshing";
  data?: { data?: unknown; sources?: string[]; elapsed_ms?: number };
  error?: Error | null;
}

const mockFn: MockFnState = { state: "idle", data: undefined, error: null };
const recordedCalls: Array<{ params?: Record<string, unknown> }> = [];

vi.mock("@/lib/useFunction", () => ({
  useFunction: (opts: { params?: Record<string, unknown> }) => {
    recordedCalls.push(opts);
    return {
      state: mockFn.state,
      data: mockFn.data,
      error: mockFn.error,
      refetch: vi.fn(),
    };
  },
}));

import { WETRPane } from "./WETR";

function row(overrides: Record<string, unknown> = {}) {
  return {
    date: "2026-09-11",
    day: 1,
    location: "US_NORTHEAST",
    lat: 41.01,
    lon: -74,
    temp_c: 18.2,
    precip_mm: 0.0,
    hdd: 0.0,
    cdd: 0.2,
    risk_flag: "normal",
    commodity_impact: "No unusual weather pressure flagged for gas.",
    source_mode: "live_open_meteo",
    ...overrides,
  };
}

function livePayload() {
  return {
    data: {
      status: "ok",
      location: "US_NORTHEAST",
      lat: 41.01,
      lon: -74,
      commodity_context: "natural gas and power demand",
      source_mode: "live_open_meteo",
      rows: [row()],
      risk_flags: ["normal"],
      methodology: "WETR normalizes live daily forecast rows.",
    },
    sources: ["open_meteo"],
    elapsed_ms: 7,
  };
}

function seasonalPayload() {
  const p = livePayload();
  const payload = p.data as Record<string, unknown>;
  payload.status = "provider_unavailable";
  payload.source_mode = "seasonal_model";
  payload.reason = "Live weather request failed: provider boom";
  payload.rows = [row({ source_mode: "seasonal_model" })];
  p.sources = ["seasonal_weather_model"];
  return p;
}

beforeEach(() => {
  localStorage.clear();
  mockFn.state = "idle";
  mockFn.data = undefined;
  mockFn.error = null;
  recordedCalls.length = 0;
});

afterEach(() => {
  cleanup();
});

describe("WETR pane — source honesty", () => {
  it("labels keyless Open-Meteo rows as live, never as a seasonal model (A4-H)", () => {
    mockFn.state = "ok";
    mockFn.data = livePayload();
    render(<WETRPane code="WETR" />);
    expect(screen.getByText(/live · Open-Meteo/)).toBeInTheDocument();
    // The old logic read "live_open_meteo" as a model and rendered this.
    expect(screen.queryByText(/seasonal model/i)).toBeNull();
    expect(screen.queryByText(/OpenWeather is not configured/i)).toBeNull();
    // The rows themselves still render.
    expect(screen.getByText("18.2°")).toBeInTheDocument();
  });

  it("keeps the seasonal-model notice for provider-outage payloads", () => {
    mockFn.state = "ok";
    mockFn.data = seasonalPayload();
    render(<WETRPane code="WETR" />);
    expect(screen.getByText("seasonal model")).toBeInTheDocument();
    expect(screen.getByText(/Seasonal model rows/i)).toBeInTheDocument();
    expect(screen.getByText(/provider boom/i)).toBeInTheDocument();
  });
});

describe("WETR pane — poll contract", () => {
  it("keeps the visibility tick out of the fetch params (A4-M)", () => {
    mockFn.state = "ok";
    mockFn.data = livePayload();
    render(<WETRPane code="WETR" />);
    expect(recordedCalls.length).toBeGreaterThan(0);
    for (const call of recordedCalls) {
      expect(call.params ?? {}).not.toHaveProperty("tick");
      expect(call.params).toMatchObject({ location: "US_NORTHEAST", days: 10 });
    }
  });
});
