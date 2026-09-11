/**
 * FXFC pane — data-honesty + render-contract tests.
 *
 * Pins the FXFC forecast pane contract:
 *  - the four load states (loading / empty / error / ok) render;
 *  - a LIVE payload (source_mode=live_yfinance_quote) shows the "live
 *    spot" pill and NO warning banner;
 *  - a REFERENCE payload (source_mode=reference_model + backend warning)
 *    shows the "reference spot" pill, the warning banner and the muted
 *    source pill instead of pretending the curve is live;
 *  - the forecast-vs-spot delta column (F − S) renders from the payload;
 *  - the model note never claims vendor analyst forecasts;
 *  - one interaction: the PAIR segmented control switches the pair.
 *
 * `useFunction` is mocked via a mutable shared state so each test drives
 * the pane into a specific branch without the real sidecar transport.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { FXFCPane } from "./FXFC";

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

function forecastRow(
  horizon: string,
  years: number,
  forecast: number,
  sourceMode: string,
) {
  const spot = 154.324;
  const band = spot * 0.085 * Math.sqrt(years);
  return {
    pair: "USDJPY",
    horizon,
    tenor_years: years,
    spot,
    forecast,
    lower_band: forecast - band,
    upper_band: forecast + band,
    forward_points: forecast - spot,
    confidence: 78 - years * 9,
    source_mode: sourceMode,
  };
}

function livePayload() {
  return {
    warnings: [],
    sources: ["yfinance", "covered_interest_parity_formula"],
    elapsed_ms: 420,
    data: {
      pair: "USDJPY",
      base: "USD",
      quote: "JPY",
      spot: 154.324,
      base_rate: 0.045,
      quote_rate: 0.005,
      vol_annualized: 0.085,
      forecast: [
        forecastRow("1M", 1 / 12, 153.804418, "live_yfinance_quote"),
        forecastRow("3M", 0.25, 152.79, "live_yfinance_quote"),
        forecastRow("6M", 0.5, 151.3, "live_yfinance_quote"),
        forecastRow("12M", 1, 148.9, "live_yfinance_quote"),
      ],
    },
  };
}

function referencePayload() {
  const payload = livePayload();
  return {
    warnings: ["live spot unavailable; using labelled reference spot"],
    sources: ["reference_fx_spot", "covered_interest_parity_formula"],
    elapsed_ms: 40,
    data: {
      ...payload.data,
      forecast: payload.data.forecast.map((r) => ({
        ...r,
        source_mode: "reference_model",
      })),
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

describe("FXFC pane — load states", () => {
  it("renders a skeleton while loading", () => {
    setMockFn({ state: "loading", data: undefined });
    const { container } = render(<FXFCPane code="FXFC" />);
    expect(container.querySelector('[aria-busy="true"]')).not.toBeNull();
  });

  it("renders the error state when the fetch errors", () => {
    setMockFn({
      state: "error",
      data: undefined,
      error: new Error("sidecar exploded"),
    });
    render(<FXFCPane code="FXFC" />);
    expect(screen.getByText(/sidecar exploded/i)).toBeInTheDocument();
  });

  it("renders the empty state when no forecast rows come back", () => {
    setMockFn({
      state: "ok",
      data: { data: { pair: "USDJPY", forecast: [], curve: [] } },
    });
    render(<FXFCPane code="FXFC" />);
    expect(screen.getByText(/No forecast horizons returned/i)).toBeInTheDocument();
  });
});

describe("FXFC pane — data honesty", () => {
  it("shows the live-spot pill and no warning for a live payload", () => {
    setMockFn({ state: "ok", data: livePayload() });
    render(<FXFCPane code="FXFC" symbol="USDJPY" />);
    expect(screen.getByText("live spot")).toBeInTheDocument();
    expect(
      screen.queryByRole("status", { name: /data quality warning/i }),
    ).toBeNull();
    // 4 per-row source pills + the source-aware KPI caption.
    expect(screen.getAllByText(/live_yfinance_quote/i).length).toBe(5);
  });

  it("treats the keyless ECB/Frankfurter tiers as live, not reference", () => {
    // The default-on keyless spot chain ships live_official (Frankfurter) /
    // live_ecb_reference; only reference_model is the labelled fallback.
    const payload = livePayload();
    payload.data.forecast = payload.data.forecast.map((r) => ({
      ...r,
      source_mode: "live_official",
    }));
    setMockFn({ state: "ok", data: payload });
    render(<FXFCPane code="FXFC" symbol="USDJPY" />);
    expect(screen.getByText("live spot")).toBeInTheDocument();
    expect(screen.queryByText("reference spot")).toBeNull();
    expect(
      screen.queryByRole("status", { name: /data quality warning/i }),
    ).toBeNull();
    expect(screen.getByText(/LIVE SPOT · live_official/i)).toBeInTheDocument();
  });

  it("downgrades to reference spot + warning banner for reference payloads", () => {
    setMockFn({ state: "ok", data: referencePayload() });
    render(<FXFCPane code="FXFC" symbol="USDJPY" />);
    expect(screen.getByText("reference spot")).toBeInTheDocument();
    expect(
      screen.getByRole("status", { name: /data quality warning/i }),
    ).toHaveTextContent(/labelled reference spot/i);
    expect(screen.getAllByText(/reference_model/i).length).toBe(4);
  });

  it("renders the forecast-vs-spot delta column (F − S) from the payload", () => {
    setMockFn({ state: "ok", data: livePayload() });
    const { container } = render(<FXFCPane code="FXFC" symbol="USDJPY" />);
    // 153.804418 - 154.324 = -0.519582 → "-0.519582" in the F − S column.
    expect(container.textContent).toContain("-0.519582");
  });

  it("labels the KPI with the ladder slot actually used (no silent 3M fallback)", () => {
    const payload = livePayload();
    payload.data.forecast = [
      forecastRow("1M", 1 / 12, 153.8, "live_yfinance_quote"),
      forecastRow("6M", 0.5, 151.3, "live_yfinance_quote"),
    ];
    setMockFn({ state: "ok", data: payload });
    render(<FXFCPane code="FXFC" symbol="USDJPY" />);
    // Without a 3M row the pane used rows[1]; it must say "6M", not "3M".
    expect(screen.getByText("6M forecast")).toBeInTheDocument();
    expect(screen.queryByText("3M forecast")).toBeNull();
  });

  it("never claims vendor analyst forecasts (model note)", () => {
    setMockFn({ state: "ok", data: livePayload() });
    render(<FXFCPane code="FXFC" symbol="USDJPY" />);
    const note = screen.getByRole("note", { name: /model note/i });
    expect(note).toHaveTextContent(/model bands, not vendor analyst forecasts/i);
  });
});

describe("FXFC pane — interaction", () => {
  it("switches the pair via the PAIR segmented control", () => {
    setMockFn({ state: "ok", data: livePayload() });
    render(<FXFCPane code="FXFC" />);
    const usdjpyBtn = screen.getByRole("button", { name: "USDJPY" });
    expect(usdjpyBtn).not.toBeDisabled();
    fireEvent.click(usdjpyBtn);
    // The active option becomes disabled inside SegmentedControl.
    expect(screen.getByRole("button", { name: "USDJPY" })).toBeDisabled();
  });
});
