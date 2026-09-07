/**
 * REGM pane — verbatim-classification + honesty tests (GEX/NSE mock
 * pattern).
 *
 * `useFunction` is mocked via a mutable shared object. Pins:
 *  - loading skeleton, error and provider-unavailable branches render
 *    honest states (the provider error is surfaced verbatim);
 *  - regime cards render the backend's values VERBATIM — an UNKNOWN /
 *    null / "Cannot classify" component gets an explicit unknown-state
 *    card ("not reported — not guessed"), never a guessed label;
 *  - the indicator table mirrors payload.rows with honest "—" for
 *    missing numeric values;
 *  - envelope warnings (e.g. the FRED curve note) are displayed;
 *  - changing LOOKBACK persists under `showme.regm.days`.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { REGMPane } from "./REGM";

/* ── useFunction mock ──────────────────────────────────────────────── */

interface MockFnState {
  state: "idle" | "loading" | "ok" | "error" | "refreshing";
  data?: {
    data?: unknown;
    status?: string;
    sources?: string[];
    warnings?: string[];
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

/* ── fixtures (shape mirrors the live /api/fn/REGM probe) ──────────── */

function okPayload(warnings: string[] = []): Partial<MockFnState> {
  return {
    state: "ok",
    data: {
      status: "ok",
      sources: ["yfinance", "fred"],
      warnings,
      elapsed_ms: 321.4,
      data: {
        symbol: "SPY",
        status: "ok",
        data_state: "ok",
        confidence: 1.0,
        current: {
          regime: "Risk-on bull",
          trend: "BULL",
          vol: "NORMAL",
          drawdown: "NORMAL",
          curve: "UNKNOWN",
        },
        cards: [
          { label: "Regime", value: "Risk-on bull" },
          { label: "Trend", value: "BULL" },
          { label: "Vol", value: "NORMAL" },
          { label: "Curve", value: "UNKNOWN" },
        ],
        rows: [
          {
            component: "trend",
            label: "BULL",
            value: 3.42,
            unit: "%",
            rule: "50d MA vs 200d MA",
          },
          {
            component: "volatility",
            label: "NORMAL",
            value: 14.8,
            unit: "% annualized",
            rule: "21d realized vol vs long-run vol",
          },
          {
            component: "curve",
            label: "UNKNOWN",
            value: null,
            unit: "bp",
            rule: "10Y-2Y yield spread",
          },
        ],
      },
    },
  };
}

function insufficientPayload(): Partial<MockFnState> {
  return {
    state: "ok",
    data: {
      status: "ok",
      sources: ["yfinance"],
      data: {
        symbol: "SPY",
        status: "ok",
        data_state: "insufficient_inputs",
        confidence: 0.25,
        cards: [
          { label: "Regime", value: "Cannot classify — no inputs available" },
          { label: "Trend", value: "UNKNOWN" },
        ],
        rows: [],
      },
    },
  };
}

function unavailablePayload(): Partial<MockFnState> {
  return {
    state: "ok",
    data: {
      status: "provider_unavailable",
      sources: ["yfinance"],
      warnings: ["yfinance benchmark unavailable: ConnectError: timeout"],
      data: {
        symbol: "SPY",
        status: "provider_unavailable",
        provider_error: "ConnectError: timeout",
        rows: [],
        history: [],
        current: {},
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

describe("REGM pane — load states", () => {
  it("renders a skeleton while loading", () => {
    setMockFn({ state: "loading", data: undefined });
    const { container } = render(<REGMPane code="REGM" symbol="SPY" />);
    expect(container.querySelector('[aria-busy="true"]')).not.toBeNull();
  });

  it("renders the error state when the fetch errors", () => {
    setMockFn({
      state: "error",
      data: undefined,
      error: new Error("sidecar exploded"),
    });
    render(<REGMPane code="REGM" symbol="SPY" />);
    expect(screen.getByText(/sidecar exploded/i)).toBeInTheDocument();
  });

  it("renders the provider error verbatim when the benchmark is unreachable", () => {
    setMockFn(unavailablePayload());
    render(<REGMPane code="REGM" symbol="SPY" />);
    expect(screen.getByText(/ConnectError: timeout/i)).toBeInTheDocument();
    expect(screen.queryByLabelText("REGM regime cards")).toBeNull();
  });
});

describe("REGM pane — verbatim classification", () => {
  it("renders classified cards verbatim and UNKNOWN as an explicit unknown card", () => {
    setMockFn(okPayload());
    render(<REGMPane code="REGM" symbol="SPY" />);
    const regimeCard = screen.getByLabelText("REGM card Regime");
    expect(regimeCard).toHaveTextContent("Risk-on bull");
    expect(regimeCard).not.toHaveTextContent("not reported");
    const curveCard = screen.getByLabelText("REGM card Curve");
    expect(curveCard).toHaveTextContent("UNKNOWN");
    expect(curveCard).toHaveTextContent("not reported — not guessed");
  });

  it("renders an explicit unknown-state card when the backend cannot classify", () => {
    setMockFn(insufficientPayload());
    render(<REGMPane code="REGM" symbol="SPY" />);
    const regimeCard = screen.getByLabelText("REGM card Regime");
    expect(regimeCard).toHaveTextContent(
      "Cannot classify — no inputs available",
    );
    expect(regimeCard).toHaveTextContent("not reported — not guessed");
    expect(screen.getByLabelText("REGM data-state notes")).toHaveTextContent(
      "insufficient_inputs",
    );
  });

  it("mirrors the indicator table with an honest dash for missing values", () => {
    setMockFn(okPayload());
    render(<REGMPane code="REGM" symbol="SPY" />);
    const table = screen.getByLabelText("REGM indicator table");
    expect(table.querySelectorAll("tbody tr").length).toBe(3);
    expect(table).toHaveTextContent("3.42 %");
    expect(table).toHaveTextContent("50d MA vs 200d MA");
    const curveRow = Array.from(table.querySelectorAll("tbody tr")).find(
      (tr) => tr.textContent?.includes("curve"),
    );
    expect(curveRow?.textContent).toContain("—");
  });

  it("surfaces envelope warnings (curve component note)", () => {
    setMockFn(
      okPayload(["FRED curve spread unavailable; curve component is UNKNOWN"]),
    );
    render(<REGMPane code="REGM" symbol="SPY" />);
    expect(
      screen.getByText(/FRED curve spread unavailable/i),
    ).toBeInTheDocument();
  });
});

describe("REGM pane — interactions", () => {
  it("persists the LOOKBACK control under showme.regm.days", () => {
    setMockFn(okPayload());
    render(<REGMPane code="REGM" symbol="SPY" />);
    const group = screen.getByLabelText("Benchmark history window");
    const fiveYear = group.querySelector('.fn-segmented__opt[title="LOOKBACK 5Y"]');
    expect(fiveYear).not.toBeNull();
    fireEvent.click(fiveYear as Element);
    expect(localStorage.getItem("showme.regm.days")).toBe("1825");
  });
});
