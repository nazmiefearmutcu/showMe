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
 *  - changing LOOKBACK persists under `showme.regm.days`;
 *  - the HISTORY toggle fires the `action=history` fetch on demand and
 *    renders the regime timeline + k-means cluster label (honest empty
 *    state otherwise).
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
const mockHistoryFn: { current: MockFnState | null } = { current: null };
const fnCalls: Record<string, unknown>[] = [];

function setMockFn(next: Partial<MockFnState>) {
  mockFn.state = next.state ?? "idle";
  mockFn.data = next.data;
  mockFn.error = next.error ?? null;
}

vi.mock("@/lib/useFunction", () => ({
  useFunction: (args: Record<string, unknown>) => {
    fnCalls.push(args);
    const params = (args.params ?? {}) as Record<string, unknown>;
    if (params.action === "history") {
      const state = mockHistoryFn.current;
      if (!state) {
        return {
          state: "idle",
          data: undefined,
          error: null,
          refetch: vi.fn(),
        };
      }
      return {
        state: state.state,
        data: state.data,
        error: state.error,
        refetch: vi.fn(),
      };
    }
    return {
      state: mockFn.state,
      data: mockFn.data,
      error: mockFn.error,
      refetch: vi.fn(),
    };
  },
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
  fnCalls.length = 0;
  mockHistoryFn.current = null;
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

describe("REGM pane — history timeline (on demand)", () => {
  function historyPayload() {
    return {
      state: "ok" as const,
      data: {
        status: "ok",
        sources: ["yfinance"],
        data: {
          symbol: "SPY",
          status: "ok",
          history: [
            { date: "2024-01-02", regime: "Risk-on bull", trend: "BULL" },
            { date: "2024-01-03", regime: "Risk-on bull", trend: "BULL" },
            { date: "2024-01-04", regime: "Drawdown", trend: "BEAR" },
            { date: "2024-01-05", regime: "Drawdown", trend: "BEAR" },
          ],
          cluster: { labels: [0, 0, 1, 1], centers: [], k: 2 },
        },
      },
    };
  }

  it("stays disabled until toggled, then fetches action=history with the persisted flag", () => {
    setMockFn(okPayload());
    render(<REGMPane code="REGM" symbol="SPY" />);
    const historyCalls = () =>
      fnCalls.filter(
        (call) =>
          ((call.params ?? {}) as Record<string, unknown>).action === "history",
      );
    expect(historyCalls().length).toBeGreaterThan(0);
    expect(historyCalls()[historyCalls().length - 1]?.enabled).toBe(false);
    // Default view never requests history.
    expect(
      fnCalls.some(
        (call) =>
          ((call.params ?? {}) as Record<string, unknown>).action === "current",
      ),
    ).toBe(false);

    fireEvent.click(screen.getByRole("button", { name: "HISTORY" }));
    expect(localStorage.getItem("showme.regm.history")).toBe("1");
    const last = historyCalls()[historyCalls().length - 1];
    expect(last?.enabled).toBe(true);
    expect(last?.params).toEqual({ days: 1095, action: "history" });
  });

  it("renders the coloured run strip + cluster label from the history payload", () => {
    setMockFn(okPayload());
    mockHistoryFn.current = historyPayload();
    render(<REGMPane code="REGM" symbol="SPY" />);
    fireEvent.click(screen.getByRole("button", { name: "HISTORY" }));

    const timeline = screen.getByLabelText("REGM regime timeline");
    // Two consecutive same-regime runs → two segments with run tooltips.
    const segments = timeline.querySelectorAll('[title*="Risk-on bull"]');
    expect(segments.length).toBe(1);
    expect(timeline.querySelectorAll('[title*="Drawdown"]').length).toBe(1);
    expect(timeline).toHaveTextContent("4 sessions · 2 runs · 2024-01-02 → 2024-01-05");
    // Backend cluster label rendered verbatim (k + population per id).
    expect(timeline).toHaveTextContent("k-means k=2 · cluster sizes 2 / 2");
  });

  it("renders an honest empty state when history has no classified points", () => {
    setMockFn(okPayload());
    mockHistoryFn.current = {
      state: "ok",
      data: {
        status: "ok",
        sources: ["yfinance"],
        data: { symbol: "SPY", status: "ok", history: [], cluster: undefined },
      },
    };
    render(<REGMPane code="REGM" symbol="SPY" />);
    fireEvent.click(screen.getByRole("button", { name: "HISTORY" }));
    expect(
      screen.getByText(/History mode returned no classified points/i),
    ).toBeInTheDocument();
  });
});
