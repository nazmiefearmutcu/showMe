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
 *  - one interaction: callsign filter Apply updates the applied filter;
 *  - the LIMIT control drives the backend `limit` param (10/25/50/100);
 *  - the Alerts control opens the rule settings and toggles persist;
 *  - a fired rule lands in the pane alert history.
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

/** Last `params` object the pane handed to useFunction. */
const captured = vi.hoisted(() => ({
  params: undefined as Record<string, unknown> | undefined,
}));

vi.mock("@/lib/useFunction", () => ({
  useFunction: (args: { params?: Record<string, unknown> }) => {
    captured.params = args.params;
    return {
      state: mockFn.state,
      data: mockFn.data,
      error: mockFn.error,
      refetch: vi.fn(),
    };
  },
}));

// Toast side effects are asserted (not rendered) — keep the store quiet.
const toastWarn = vi.hoisted(() => vi.fn());
vi.mock("@/lib/toast", () => ({
  toast: {
    info: vi.fn(),
    success: vi.fn(),
    warn: toastWarn,
    error: vi.fn(),
  },
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

/**
 * A live payload that trips the crash rule on the FIRST poll: one aircraft
 * in a −20 m/s (~−3,937 ft/min) descent, well past the −2,500 ft/min
 * default. The other two stay benign.
 */
function crashingPayload() {
  const descender = {
    ...aircraft("THY6439", false),
    vertical_rate_mps: -20,
    altitude_ft: 38000,
  };
  return {
    warnings: [],
    sources: ["opensky"],
    elapsed_ms: 900,
    data: {
      status: "live",
      rows: [descender, aircraft("PGT1234", false)],
    },
  };
}

/* ── tests ─────────────────────────────────────────────────────────── */

beforeEach(() => {
  setMockFn({ state: "idle", data: undefined });
  // Limit + alert config persist to localStorage — every test starts clean.
  window.localStorage.clear();
  toastWarn.mockClear();
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

describe("FLY pane — limit control", () => {
  it("offers the full 10/25/50/100 range (backend cap 100)", () => {
    setMockFn({ state: "ok", data: livePayload() });
    render(<FLYPane code="FLY" />);
    for (const label of ["10", "25", "50", "100"]) {
      expect(screen.getByRole("button", { name: label })).toBeInTheDocument();
    }
  });

  it("sends the selected limit to the backend and persists it", () => {
    setMockFn({ state: "ok", data: livePayload() });
    render(<FLYPane code="FLY" />);
    expect(captured.params?.limit).toBe(25);
    fireEvent.click(screen.getByRole("button", { name: "100" }));
    expect(captured.params?.limit).toBe(100);
    expect(window.localStorage.getItem("showme.fly.limit")).toBe("100");
  });
});

describe("FLY pane — alert settings", () => {
  it("opens the rules popover from the toolbar", () => {
    setMockFn({ state: "ok", data: livePayload() });
    render(<FLYPane code="FLY" />);
    expect(screen.queryByRole("dialog", { name: /FLY alert settings/i })).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: /FLY alerts/i }));
    const dialog = screen.getByRole("dialog", { name: /FLY alert settings/i });
    expect(dialog).toBeInTheDocument();
    expect(screen.getByLabelText("Erratic flight path")).toBeChecked();
    expect(screen.getByLabelText("Crash risk")).toBeChecked();
    expect(screen.getByLabelText("Stale contact")).toBeChecked();
    // Thresholds are visible with their values + units.
    expect(screen.getByLabelText("Erratic heading threshold (deg)")).toHaveValue(60);
    expect(screen.getByLabelText("Crash vertical rate threshold (ft/min)")).toHaveValue(2500);
    expect(screen.getByLabelText("Crash low altitude threshold (ft)")).toHaveValue(2000);
    expect(screen.getByLabelText("Stale contact threshold (minutes)")).toHaveValue(10);
  });

  it("persists a rule toggle and restores it on the next mount", () => {
    setMockFn({ state: "ok", data: livePayload() });
    const first = render(<FLYPane code="FLY" />);
    fireEvent.click(screen.getByRole("button", { name: /FLY alerts/i }));
    fireEvent.click(screen.getByLabelText("Crash risk"));
    expect(screen.getByLabelText("Crash risk")).not.toBeChecked();
    const stored = JSON.parse(window.localStorage.getItem("showme.fly.alerts") ?? "null") as {
      crash?: { enabled?: boolean };
    };
    expect(stored.crash?.enabled).toBe(false);
    first.unmount();

    render(<FLYPane code="FLY" />);
    fireEvent.click(screen.getByRole("button", { name: /FLY alerts/i }));
    expect(screen.getByLabelText("Crash risk")).not.toBeChecked();
    expect(screen.getByLabelText("Stale contact")).toBeChecked();
  });

  it("updates a threshold on commit and persists the clamped value", () => {
    setMockFn({ state: "ok", data: livePayload() });
    render(<FLYPane code="FLY" />);
    fireEvent.click(screen.getByRole("button", { name: /FLY alerts/i }));
    const input = screen.getByLabelText("Stale contact threshold (minutes)");
    fireEvent.change(input, { target: { value: "25" } });
    fireEvent.blur(input);
    const stored = JSON.parse(window.localStorage.getItem("showme.fly.alerts") ?? "null") as {
      stale?: { minutes?: number };
    };
    expect(stored.stale?.minutes).toBe(25);
  });
});

describe("FLY pane — alert history", () => {
  it("records a fired rule and toasts it", () => {
    setMockFn({ state: "ok", data: crashingPayload() });
    render(<FLYPane code="FLY" />);
    const history = screen.getByTestId("fly-alert-history");
    expect(history).toHaveTextContent("THY6439");
    expect(history).toHaveTextContent("FLY rule: crash risk — steep descent");
    expect(history).toHaveTextContent(/3,937 ft\/min/);
    expect(toastWarn).toHaveBeenCalledWith(
      "THY6439",
      expect.stringContaining("FLY rule: crash risk — steep descent"),
    );
  });

  it("respects a disabled rule for the current poll", () => {
    window.localStorage.setItem(
      "showme.fly.alerts",
      JSON.stringify({ crash: { enabled: false } }),
    );
    setMockFn({ state: "ok", data: crashingPayload() });
    render(<FLYPane code="FLY" />);
    expect(screen.queryByTestId("fly-alert-history")).toBeNull();
    expect(toastWarn).not.toHaveBeenCalled();
  });

  it("clears the history on demand", () => {
    setMockFn({ state: "ok", data: crashingPayload() });
    render(<FLYPane code="FLY" />);
    expect(screen.getByTestId("fly-alert-history")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Clear" }));
    expect(screen.queryByTestId("fly-alert-history")).toBeNull();
  });
});
