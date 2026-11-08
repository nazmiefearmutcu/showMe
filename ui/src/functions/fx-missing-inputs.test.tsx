/**
 * FX panes — missing carry inputs are shown as missing (wb1-g20, UI-5 / UI-10).
 *
 * A missing rate or carry value must never be coerced to 0 and rendered as a
 * real spread or a positive 0.00% carry. These tests pin:
 *  - FRD / FXFC "Rate diff" with one rate absent shows a dash, not the other rate;
 *  - FXIP "Carry (annualized)" with no carry shows a dash, not "+0.000%";
 *  - the complete-input case still shows the real difference.
 *
 * `useFunction` is mocked with a mutable state (same pattern as the pane tests).
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, render } from "@testing-library/react";
import { FRDPane } from "./FRD";
import { FXFCPane } from "./FXFC";
import { FXIPPane } from "./FXIP";

interface MockFnState {
  state: "idle" | "loading" | "ok" | "error" | "refreshing";
  data?: { data?: unknown; warnings?: string[]; sources?: string[]; elapsed_ms?: number } | undefined;
  error?: Error | null;
}

const mockFn: MockFnState = { state: "idle", data: undefined, error: null };

vi.mock("@/lib/useFunction", () => ({
  useFunction: () => ({
    state: mockFn.state,
    data: mockFn.data,
    error: mockFn.error,
    refetch: vi.fn(),
  }),
}));

vi.mock("@/lib/useVisibilityTick", () => ({
  useVisibilityTick: () => 0,
}));

function setOk(data: unknown) {
  mockFn.state = "ok";
  mockFn.error = null;
  mockFn.data = { data, warnings: [], sources: ["yfinance"], elapsed_ms: 5 };
}

beforeEach(() => {
  localStorage.clear();
  mockFn.state = "idle";
  mockFn.data = undefined;
  mockFn.error = null;
});
afterEach(() => {
  cleanup();
});

/* ── FRD ───────────────────────────────────────────────────────────── */

function frdRows() {
  return [
    {
      pair: "EURUSD", spot: 1.1624, base_rate: 0.035, quote_rate: 0.045,
      source_mode: "live_yfinance_quote", tenor: "1M", tenor_years: 0.083333,
      forward: 1.163379, forward_points: 0.000979,
    },
  ];
}

function frdData(extra: Record<string, unknown>) {
  return {
    pair: "EURUSD", base: "EUR", quote: "USD", S: 1.1624, F: 1.165319,
    rows: frdRows(), methodology: "Covered interest parity.", ...extra,
  };
}

describe("FRD pane — rate differential with a missing rate (UI-5)", () => {
  it("does not show the quote rate as the spread when the base rate is missing", () => {
    setOk(frdData({ r_quote: 0.045 }));
    const { container } = render(<FRDPane code="FRD" />);
    expect(container.textContent).not.toContain("+4.500%");
    expect(container.textContent).toContain("Rate diff");
  });

  it("shows the real spread when both rates are present", () => {
    setOk(frdData({ r_quote: 0.045, r_base: 0.035 }));
    const { container } = render(<FRDPane code="FRD" />);
    expect(container.textContent).toContain("+1.000%");
  });
});

/* ── FXFC ──────────────────────────────────────────────────────────── */

function forecastRow(horizon: string, years: number, forecast: number) {
  const spot = 154.324;
  const band = spot * 0.085 * Math.sqrt(years);
  return {
    pair: "USDJPY", horizon, tenor_years: years, spot, forecast,
    lower_band: forecast - band, upper_band: forecast + band,
    forward_points: forecast - spot, confidence: 78 - years * 9,
    source_mode: "live_yfinance_quote",
  };
}

describe("FXFC pane — rate differential with a missing rate (UI-5)", () => {
  it("does not show the quote rate as the spread when the base rate is missing", () => {
    setOk({
      pair: "USDJPY", base: "USD", quote: "JPY", spot: 154.324,
      quote_rate: 0.005, vol_annualized: 0.085,
      forecast: [forecastRow("1M", 1 / 12, 153.8), forecastRow("3M", 0.25, 152.79)],
    });
    const { container } = render(<FXFCPane code="FXFC" />);
    expect(container.textContent).not.toContain("0.50%");
  });
});

/* ── FXIP ──────────────────────────────────────────────────────────── */

describe("FXIP pane — carry with a missing value (UI-10)", () => {
  it("does not show +0.000% carry when carry_annualized is absent", () => {
    setOk({
      pair: "EURUSD", base: "EUR", quote: "USD", spot: 1.1628,
      one_month_forward: 1.16378, three_month_forward: 1.165721,
      implied_vol_atm_1m: 8.45, source_mode: "live_yfinance_quote",
      rows: [{ metric: "spot", value: 1.1628, unit: "USD per EUR", source: "yfinance" }],
      history: [
        { date: "2026-05-10", close: 1.1768 },
        { date: "2026-05-11", close: 1.1779 },
      ],
    });
    const { container } = render(<FXIPPane code="FXIP" />);
    expect(container.textContent).not.toContain("+0.000%");
    expect(container.textContent).toContain("Carry (annualized)");
  });
});
