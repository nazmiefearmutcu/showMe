/**
 * FRH pane — heatmap + honesty tests (GEX/NSE mock pattern).
 *
 * `useFunction` is mocked via a mutable shared object. Pins:
 *  - loading skeleton, error, empty and ok branches render honest states;
 *  - a LIVE payload renders the symbols × funding grid with tinted cells
 *    and the longs-pay/shorts-pay legend, and does NOT show the template
 *    warning;
 *  - a TEMPLATE payload (backend funding_rate_model, live=false) renders
 *    the prominent "Model template" badge + "NOT live funding rates" note;
 *  - exchange cells the backend could not fill render "—" (never 0);
 *  - switching MODE persists under `showme.frh.mode`.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { FRHPane } from "./FRH";

/* ── useFunction mock ──────────────────────────────────────────────── */

interface MockFnState {
  state: "idle" | "loading" | "ok" | "error" | "refreshing";
  data?: {
    data?: unknown;
    status?: string;
    sources?: string[];
    metadata?: Record<string, unknown>;
    elapsed_ms?: number;
  } | undefined;
  error?: Error | null;
}

const mockFn: MockFnState = { state: "idle", data: undefined, error: null };

function setMockFn(next: Partial<MockFnState>) {
  mockFn.state = next.state ?? "idle";
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

/* ── fixtures (shape mirrors the live /api/fn/FRH probe) ───────────── */

function livePayload(): Partial<MockFnState> {
  return {
    state: "ok",
    data: {
      status: "ok",
      sources: ["binance", "bybit", "okx"],
      metadata: { samples: 3, unit: "fraction per funding interval" },
      elapsed_ms: 812.0,
      data: {
        rows: [
          {
            symbol: "BTCUSDT",
            binance: 0.0001,
            bybit: 0.00009,
            okx: 0.00012,
            avg: 0.00010333,
            interpretation: "longs pay shorts",
            provider_count: 3,
          },
          {
            symbol: "ETHUSDT",
            binance: -0.00075,
            bybit: -0.0006,
            okx: -0.0009,
            avg: -0.00075,
            interpretation: "crowded shorts",
            provider_count: 3,
          },
          {
            symbol: "SOLUSDT",
            binance: 0.00005,
            bybit: null,
            okx: null,
            avg: null,
            interpretation: "missing",
            provider_count: 1,
          },
        ],
        exchanges: ["binance", "bybit", "okx"],
        unit: "funding_rate_fraction_per_interval",
        live: true,
      },
    },
  };
}

function templatePayload(): Partial<MockFnState> {
  return {
    state: "ok",
    data: {
      status: "ok",
      sources: ["funding_rate_model"],
      data: {
        rows: [
          {
            symbol: "BTCUSDT",
            binance: 0.0001,
            bybit: 0.00009,
            okx: 0.00011,
            avg: 0.0001,
            interpretation: "longs pay shorts",
          },
        ],
        exchanges: ["binance", "bybit", "okx"],
        unit: "funding_rate_fraction_per_interval",
        live: false,
      },
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

describe("FRH pane — load states", () => {
  it("renders a skeleton while loading", () => {
    setMockFn({ state: "loading", data: undefined });
    const { container } = render(<FRHPane code="FRH" />);
    expect(container.querySelector('[aria-busy="true"]')).not.toBeNull();
  });

  it("renders the error state when the fetch errors", () => {
    setMockFn({
      state: "error",
      data: undefined,
      error: new Error("sidecar exploded"),
    });
    render(<FRHPane code="FRH" />);
    expect(screen.getByText(/sidecar exploded/i)).toBeInTheDocument();
  });

  it("renders the honest empty state when no rows come back", () => {
    setMockFn({
      state: "ok",
      data: {
        status: "empty",
        sources: [],
        data: { rows: [], exchanges: ["binance"], live: true },
      },
    });
    render(<FRHPane code="FRH" />);
    expect(screen.getByText(/No funding rows returned/i)).toBeInTheDocument();
  });
});

describe("FRH pane — live heatmap", () => {
  it("renders one row per symbol with tinted exchange cells", () => {
    setMockFn(livePayload());
    render(<FRHPane code="FRH" />);
    const grid = screen.getByLabelText("Funding rate heatmap");
    expect(screen.getAllByLabelText(/funding row/).length).toBe(3);
    expect(grid).toHaveTextContent("BTCUSDT");
    expect(grid).toHaveTextContent("ETHUSDT");
    expect(
      screen.getByLabelText("BTCUSDT binance funding +0.0100%"),
    ).toBeInTheDocument();
    expect(
      screen.getByLabelText("ETHUSDT avg funding -0.0750%"),
    ).toBeInTheDocument();
  });

  it("renders missing exchange cells as an honest dash, never zero", () => {
    setMockFn(livePayload());
    render(<FRHPane code="FRH" />);
    const cell = screen.getByLabelText("SOLUSDT bybit funding missing");
    expect(cell).toHaveTextContent("—");
    const avg = screen.getByLabelText("SOLUSDT avg funding missing");
    expect(avg).toHaveTextContent("—");
  });

  it("shows the legend and does NOT show the template warning when live", () => {
    setMockFn(livePayload());
    render(<FRHPane code="FRH" />);
    expect(screen.getByLabelText("FRH legend")).toHaveTextContent(
      "longs pay shorts",
    );
    expect(
      screen.queryByLabelText("FRH template warning"),
    ).toBeNull();
    expect(screen.queryByText(/Model template/i)).toBeNull();
  });
});

describe("FRH pane — template honesty", () => {
  it("renders the prominent model-template badge + NOT-live note", () => {
    setMockFn(templatePayload());
    render(<FRHPane code="FRH" />);
    expect(screen.getByText(/Model template/i)).toBeInTheDocument();
    expect(
      screen.getByText(/NOT live funding rates/i),
    ).toBeInTheDocument();
    expect(screen.getByLabelText("FRH template warning")).toBeInTheDocument();
  });

  it("switching MODE to Live persists showme.frh.mode", () => {
    setMockFn(templatePayload());
    render(<FRHPane code="FRH" />);
    const group = screen.getByLabelText("Template vs live exchange funding");
    const liveOpt = group.querySelector('.fn-segmented__opt[title="MODE Live"]');
    expect(liveOpt).not.toBeNull();
    fireEvent.click(liveOpt as Element);
    expect(localStorage.getItem("showme.frh.mode")).toBe("live");
  });
});
