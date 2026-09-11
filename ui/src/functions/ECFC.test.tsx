/**
 * ECFC pane — forecast render + honesty tests.
 *
 * The backend (macro/ecfc.py) returns IMF WEO rows on success and an honest
 * `provider_unavailable` envelope on a genuine upstream outage. Pins:
 *
 *  - the load states (loading / error / empty-country / ok) render;
 *  - a LIVE payload renders the KPI ribbon, the forecast DataGrid and the
 *    green "live" pill;
 *  - a `provider_unavailable` envelope (HTTP 200, empty rows) renders an
 *    honest outage Empty with the backend `reason` — and NEVER the green
 *    "live" pill (regression: isLive used to key on transport state only);
 *  - the KPI ribbon applies per-metric polarity — unemployment / government
 *    debt are NOT painted green just because the number is >= 0.
 *
 * `useFunction` is mocked via mutable shared state.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, render, screen, within } from "@testing-library/react";

interface MockFnState {
  state: "idle" | "loading" | "ok" | "error" | "refreshing";
  data?: {
    data?: unknown;
    sources?: string[];
    warnings?: string[];
    metadata?: Record<string, unknown>;
    elapsed_ms?: number;
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

import { ECFCPane } from "./ECFC";

/* ── fixtures: row/card shape mirrors macro/ecfc.py ────────────────── */

const ROWS = [
  {
    country: "USA",
    indicator: "NGDP_RPCH",
    metric: "Real GDP growth",
    year: 2026,
    forecast_value: 2.1,
    unit: "% y/y",
    source_mode: "imf_weo",
  },
  {
    country: "USA",
    indicator: "LUR",
    metric: "Unemployment rate",
    year: 2026,
    forecast_value: 4.5,
    unit: "%",
    source_mode: "imf_weo",
  },
  {
    country: "USA",
    indicator: "GGXWDG_NGDP",
    metric: "Government debt",
    year: 2026,
    forecast_value: 120,
    unit: "% GDP",
    source_mode: "imf_weo",
  },
];

const CARDS = [
  { label: "Real GDP growth", value: 2.1 },
  { label: "Unemployment rate", value: 4.5 },
  { label: "Government debt", value: 120 },
];

function livePayload() {
  return {
    data: {
      data: {
        country: "USA",
        rows: ROWS,
        series: ROWS,
        cards: CARDS,
        status: "ok",
        data_state: "live",
        source_mode: "imf_weo",
        methodology: "IMF WEO via DataMapper.",
      },
      sources: ["imf"],
      warnings: [],
      elapsed_ms: 240,
    },
  };
}

function outagePayload() {
  return {
    data: {
      data: {
        country: "USA",
        rows: [],
        series: [],
        cards: [],
        status: "provider_unavailable",
        data_state: "provider_unavailable",
        source_mode: "provider_unavailable",
        reason: "LUR: ConnectError: imf datamapper unreachable",
        next_actions: ["Retry ECFC."],
      },
      sources: ["no_live_source"],
      warnings: ["LUR: ConnectError: imf datamapper unreachable"],
      elapsed_ms: 20000,
    },
  };
}

/* ── tests ─────────────────────────────────────────────────────────── */

beforeEach(() => {
  localStorage.clear();
  setMockFn({ state: "idle", data: undefined });
});
afterEach(() => {
  cleanup();
});

describe("ECFC pane — load states", () => {
  it("renders a skeleton while loading", () => {
    setMockFn({ state: "loading", data: undefined });
    const { container } = render(<ECFCPane code="ECFC" />);
    expect(container.querySelector('[aria-busy="true"]')).not.toBeNull();
  });

  it("renders the error state when the fetch errors", () => {
    setMockFn({
      state: "error",
      data: undefined,
      error: new Error("sidecar exploded"),
    });
    render(<ECFCPane code="ECFC" />);
    expect(screen.getByText(/sidecar exploded/i)).toBeInTheDocument();
  });

  it("renders the empty-country state when the provider has no rows", () => {
    setMockFn({
      state: "ok",
      data: {
        data: {
          country: "TUR",
          rows: [],
          series: [],
          cards: [],
          status: "ok",
          source_mode: "imf_weo",
        },
        sources: ["imf"],
      },
    });
    render(<ECFCPane code="ECFC" />);
    expect(screen.getByText(/No forecast rows/i)).toBeInTheDocument();
  });
});

describe("ECFC pane — provider outage honesty", () => {
  it("renders an honest outage Empty with the backend reason", () => {
    setMockFn({ state: "ok", ...outagePayload() });
    render(<ECFCPane code="ECFC" />);
    expect(
      screen.getByText("Forecast provider unavailable"),
    ).toBeInTheDocument();
    expect(
      screen.getByText(/ConnectError: imf datamapper unreachable/i),
    ).toBeInTheDocument();
    // Regression: HTTP-200 provider_unavailable must NOT light the green
    // "live" pill just because the transport state is `ok`.
    expect(screen.queryByText("live")).toBeNull();
    expect(screen.getByText("provider unavailable")).toBeInTheDocument();
  });

  it("falls back to the envelope warning when the envelope omits reason", () => {
    setMockFn({
      state: "ok",
      data: {
        data: {
          country: "USA",
          rows: [],
          cards: [],
          status: "provider_unavailable",
          data_state: "provider_unavailable",
        },
        sources: ["no_live_source"],
        warnings: ["PCPIPCH: no series for USA"],
      },
    });
    render(<ECFCPane code="ECFC" />);
    expect(screen.getByText(/no series for USA/i)).toBeInTheDocument();
    expect(screen.queryByText("live")).toBeNull();
  });
});

describe("ECFC pane — live payload", () => {
  it("renders the forecast grid rows with indicator / year / value", () => {
    setMockFn({ state: "ok", ...livePayload() });
    render(<ECFCPane code="ECFC" />);
    const table = screen.getByRole("table");
    expect(within(table).getAllByText("2026").length).toBe(3);
    // NGDP_RPCH is a delta indicator -> DeltaChip with the signed label;
    // LUR is a plain numeric cell.
    expect(
      within(table).getByRole("status", { name: "change +2.1" }),
    ).toBeInTheDocument();
    expect(within(table).getByText("4.5")).toBeInTheDocument();
    expect(within(table).getByText("Real GDP growth")).toBeInTheDocument();
    expect(screen.getByText("live")).toBeInTheDocument();
  });

  it("applies per-metric KPI polarity (unemployment/debt not green)", () => {
    setMockFn({ state: "ok", ...livePayload() });
    render(<ECFCPane code="ECFC" />);
    const ribbon = screen.getByLabelText("ECFC KPI ribbon");
    const growth = within(ribbon)
      .getByText("Real GDP growth")
      .closest(".stat-card");
    const unemployment = within(ribbon)
      .getByText("Unemployment rate")
      .closest(".stat-card");
    const debt = within(ribbon)
      .getByText("Government debt")
      .closest(".stat-card");
    expect(growth?.className).toContain("stat-card--positive");
    expect(unemployment?.className).toContain("stat-card--negative");
    expect(debt?.className).toContain("stat-card--negative");
  });

  it("keeps neutral-tone cards neutral (unknown/contextual metrics)", () => {
    setMockFn({
      state: "ok",
      data: {
        data: {
          country: "USA",
          rows: ROWS,
          series: ROWS,
          cards: [{ label: "Inflation", value: 2.8 }],
          status: "ok",
          source_mode: "imf_weo",
        },
        sources: ["imf"],
      },
    });
    render(<ECFCPane code="ECFC" />);
    const ribbon = screen.getByLabelText("ECFC KPI ribbon");
    const inflation = within(ribbon)
      .getByText("Inflation")
      .closest(".stat-card");
    expect(inflation?.className).toContain("stat-card--neutral");
  });
});
