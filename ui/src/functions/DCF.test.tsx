/**
 * DCF pane — render-contract + model-input tests.
 *
 * The backend DCF runs a two-stage FCFE valuation from user params
 * (fcfe, shares_outstanding, growth_high, growth_terminal, wacc, years).
 * These tests pin:
 *
 *  - the load states (loading / error / empty / ok) render;
 *  - headline cards (fair value/share, implied upside vs the user mark,
 *    PV explicit, PV terminal) format from the payload;
 *  - the discounted-cashflow table and value bridge render;
 *  - a needs_input payload surfaces the honest notice;
 *  - a wacc ≤ terminal-growth payload surfaces the model error;
 *  - every input drives the fetch params (converted $M → USD, % →
 *    decimal) and persists under `showme.dcf.*`.
 *
 * Fixture: FCFE $10B, g_high 10%, WACC 8%, g_term 2.5%, 5y —
 * equity = Σ FCFE_t/(1.08^t) + TV term = 257.10B → $17.14/share @ 15B sh.
 *
 * `useFunction` is mocked via a mutable shared state (GEX pattern) with
 * lastParams capture.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { DCFPane } from "./DCF";

/* ── useFunction mock ──────────────────────────────────────────────── */

interface MockFnState {
  state: "idle" | "loading" | "ok" | "error" | "refreshing";
  data?: {
    data?: unknown;
    sources?: string[];
    elapsed_ms?: number;
    warnings?: string[];
  };
  error?: Error | null;
}

const mockFn: MockFnState = { state: "idle", data: undefined, error: null };

function setMockFn(next: MockFnState) {
  mockFn.state = next.state;
  mockFn.data = next.data;
  mockFn.error = next.error ?? null;
}

let lastParams: Record<string, unknown> | undefined;

vi.mock("@/lib/useFunction", () => ({
  useFunction: (args: { code: string; symbol?: string; params?: Record<string, unknown> }) => {
    lastParams = args.params;
    return {
      state: mockFn.state,
      data: mockFn.data,
      error: mockFn.error,
      refetch: vi.fn(),
    };
  },
}));

/* ── fixtures: closed-form two-stage FCFE ──────────────────────────── */

const CASHFLOWS = [
  { year: 1, fcfe: 11.0e9, pv: 10.185185185e9, discount_factor: 0.925925926 },
  { year: 2, fcfe: 12.1e9, pv: 10.374897119e9, discount_factor: 0.85733882 },
  { year: 3, fcfe: 13.31e9, pv: 10.565975603e9, discount_factor: 0.793832241 },
  { year: 4, fcfe: 14.641e9, pv: 10.758779169e9, discount_factor: 0.735029854 },
  { year: 5, fcfe: 16.1051e9, pv: 10.960488078e9, discount_factor: 0.680583198 },
];

const BRIDGE = [
  { component: "PV explicit FCFE", value: 52.845325155e9 },
  { component: "PV terminal value", value: 204.251261295e9 },
  { component: "Equity value", value: 257.09658645e9 },
  { component: "Fair value/share", value: 17.13977243 },
];

function okPayload() {
  return {
    data: {
      data: {
        status: "ok",
        wacc: 0.08,
        g_high: 0.1,
        g_terminal: 0.025,
        years: 5,
        starting_fcfe: 10e9,
        pv_explicit: 52.845325155e9,
        terminal_value: 300.140500434e9,
        pv_terminal: 204.251261295e9,
        equity_value: 257.09658645e9,
        fair_value_per_share: 17.13977243,
        shares_outstanding: 15e9,
        rows: CASHFLOWS,
        bridge: BRIDGE,
        methodology: "Two-stage FCFE DCF.",
      },
      sources: ["damodaran", "beta"],
      elapsed_ms: 12,
    },
  };
}

function needsInputPayload() {
  return {
    data: {
      data: {
        status: "needs_input",
        wacc: 0.08,
        g_high: 0.1,
        g_terminal: 0.025,
        years: 5,
        starting_fcfe: 0,
        pv_explicit: 0,
        pv_terminal: 0,
        equity_value: 0,
        fair_value_per_share: null,
        shares_outstanding: null,
        rows: CASHFLOWS.map((r) => ({ ...r, fcfe: 0, pv: 0 })),
        bridge: BRIDGE.map((r) => ({ ...r, value: 0 })),
        methodology: "Two-stage FCFE DCF.",
      },
      warnings: [
        "free_cash_flow: provider returned missing or non-positive free cash flow; user should override fcfe for a tradable DCF.",
      ],
    },
  };
}

function modelErrorPayload() {
  return {
    data: {
      data: {
        error: "wacc must exceed terminal growth",
      },
      warnings: ["wacc ≤ g_terminal"],
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

describe("DCF pane — load states", () => {
  it("renders a skeleton while loading", () => {
    setMockFn({ state: "loading", data: undefined });
    const { container } = render(<DCFPane code="DCF" symbol="AAPL" />);
    expect(container.querySelector('[aria-busy="true"]')).not.toBeNull();
  });

  it("renders the error state when the fetch errors", () => {
    setMockFn({
      state: "error",
      data: undefined,
      error: new Error("sidecar exploded"),
    });
    render(<DCFPane code="DCF" symbol="AAPL" />);
    expect(screen.getByText(/sidecar exploded/i)).toBeInTheDocument();
  });

  it("renders the empty state when no cashflow rows come back", () => {
    setMockFn({ state: "ok", data: { data: { status: "ok", rows: [], bridge: [] } } });
    render(<DCFPane code="DCF" symbol="AAPL" />);
    expect(screen.getByText(/No model output/i)).toBeInTheDocument();
  });
});

describe("DCF pane — headline + tables", () => {
  it("renders fair value per share and PV cards from the payload", () => {
    setMockFn({ state: "ok", ...okPayload() });
    render(<DCFPane code="DCF" symbol="AAPL" />);
    // Fair value/share 17.14 appears on the headline card; $52.85B appears
    // on the PV-explicit card AND the bridge row.
    expect(screen.getByText("17.14")).toBeInTheDocument();
    expect(screen.getAllByText("$52.85B").length).toBe(2);
    // PV terminal: headline card + bridge row.
    expect(screen.getAllByText("$204.25B").length).toBe(2);
  });

  it("computes implied upside once the user sets the market mark", () => {
    setMockFn({ state: "ok", ...okPayload() });
    render(<DCFPane code="DCF" symbol="AAPL" />);
    // Before a mark is set the card reads "—".
    expect(screen.getByText("SET MARK $ TO COMPARE")).toBeInTheDocument();
    fireEvent.change(screen.getByLabelText("Market price per share for comparison"), {
      target: { value: "15" },
    });
    // 17.1398 / 15 − 1 = +14.3%.
    expect(screen.getByText("+14.3%")).toBeInTheDocument();
  });

  it("renders the cashflow table and value bridge", () => {
    setMockFn({ state: "ok", ...okPayload() });
    const { container } = render(<DCFPane code="DCF" symbol="AAPL" />);
    const tables = Array.from(container.querySelectorAll("tbody"));
    expect(tables.length).toBe(2);
    const [cfBody, bridgeBody] = tables;
    expect(cfBody.querySelectorAll("tr").length).toBe(5);
    // Year-1 row: FCFE $11.00B discounted by 0.9259.
    expect(cfBody.textContent).toContain("$11.00B");
    expect(cfBody.textContent).toContain("0.9259");
    expect(bridgeBody.querySelectorAll("tr").length).toBe(4);
    expect(bridgeBody.textContent).toContain("$257.10B");
  });
});

describe("DCF pane — honest model states", () => {
  it("surfaces the needs_input notice without hiding the tables", () => {
    setMockFn({ state: "ok", ...needsInputPayload() });
    render(<DCFPane code="DCF" symbol="AAPL" />);
    expect(screen.getByText(/Needs input/i)).toBeInTheDocument();
    expect(screen.getByText(/override FCFE or shares/i)).toBeInTheDocument();
    // The (zeroed) tables still render — nothing is faked to look positive.
    expect(screen.getAllByText("$0").length).toBeGreaterThanOrEqual(1);
  });

  it("surfaces the wacc ≤ g_terminal model error", () => {
    setMockFn({ state: "ok", ...modelErrorPayload() });
    render(<DCFPane code="DCF" symbol="AAPL" />);
    expect(screen.getByText(/Model error/i)).toBeInTheDocument();
    expect(screen.getByText(/wacc must exceed terminal growth/i)).toBeInTheDocument();
    // No valuation tables are rendered for a broken model.
    expect(screen.queryByText(/discounted FCFE forecast/i)).toBeNull();
  });
});

describe("DCF pane — model inputs", () => {
  it("sends default inputs converted to backend units", () => {
    setMockFn({ state: "ok", ...okPayload() });
    render(<DCFPane code="DCF" symbol="AAPL" />);
    expect(lastParams).toMatchObject({
      fcfe: 10e9,
      shares_outstanding: 15e9,
      growth_high: 0.1,
      growth_terminal: 0.025,
      wacc: 0.08,
      years: 5,
    });
  });

  it("drives fcfe from the $M input and persists it", () => {
    setMockFn({ state: "ok", ...okPayload() });
    render(<DCFPane code="DCF" symbol="AAPL" />);
    fireEvent.change(screen.getByLabelText("FCFE base in millions"), {
      target: { value: "12000" },
    });
    expect(lastParams?.fcfe).toBe(12e9);
    expect(localStorage.getItem("showme.dcf.fcfe")).toBe("12000");
  });

  it("converts WACC percent to a decimal and persists it", () => {
    setMockFn({ state: "ok", ...okPayload() });
    render(<DCFPane code="DCF" symbol="AAPL" />);
    fireEvent.change(screen.getByLabelText("WACC percent"), {
      target: { value: "9" },
    });
    expect(lastParams?.wacc).toBe(0.09);
    expect(localStorage.getItem("showme.dcf.wacc")).toBe("9");
  });

  it("switches the forecast horizon via the segmented control", () => {
    setMockFn({ state: "ok", ...okPayload() });
    render(<DCFPane code="DCF" symbol="AAPL" />);
    fireEvent.click(screen.getByText("7y"));
    expect(lastParams?.years).toBe(7);
    expect(localStorage.getItem("showme.dcf.years")).toBe("7");
  });
});
