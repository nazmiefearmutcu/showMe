/**
 * GREEKS pane — render-contract + honesty tests.
 *
 * Pins:
 *  - loading / error / backend error-envelope paths (input_required,
 *    calc_error) render as honest states;
 *  - the per-position greeks table renders delta/gamma/theta/vega/rho per
 *    row PLUS the aggregate NET row from `totals`;
 *  - net summary cards mirror the aggregate totals;
 *  - backend `assumptions_used` (defaulted vol/T) renders a prominent
 *    synthetic-input note;
 *  - the persisted JSON book editor: invalid JSON shows a parse error and
 *    keeps the last valid book; valid JSON re-issues the call with the new
 *    positions array.
 *
 * `useFunction` is mocked with a mutable shared state + an args recorder.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { GreeksPane } from "./GREEKS";

/* ── mocks ─────────────────────────────────────────────────────────── */

interface MockFnState {
  state: "idle" | "loading" | "ok" | "error" | "refreshing";
  data?: { data?: unknown; warnings?: string[] } | undefined;
  error?: Error | null;
}

const mockFn: MockFnState = { state: "idle", data: undefined, error: null };
const refetchMock = vi.fn();

interface RecordedArgs {
  code: string;
  symbol?: string;
  params?: Record<string, unknown>;
}

const lastArgs: RecordedArgs[] = [];

vi.mock("@/lib/useFunction", () => ({
  useFunction: (args: RecordedArgs) => {
    lastArgs.push(args);
    return {
      state: mockFn.state,
      data: mockFn.data,
      error: mockFn.error,
      refetch: refetchMock,
    };
  },
}));

/* ── fixtures ──────────────────────────────────────────────────────── */

interface TestRow {
  symbol?: string;
  kind?: string;
  strike?: number;
  quantity?: number;
  contract_size?: number;
  delta?: number;
  gamma?: number;
  vega?: number;
  theta?: number;
  rho?: number;
  error?: string;
}

interface TestData {
  status?: string;
  reason?: string;
  positions?: TestRow[];
  totals?: Record<string, number>;
  n?: number;
  units?: Record<string, string>;
  assumptions_used?: string[];
  summary?: Record<string, number>;
}

interface MockPayload {
  data: TestData;
  warnings: string[];
  sources: string[];
  elapsed_ms: number;
}

function okPayload(): MockPayload {
  return {
    data: {
      positions: [
        {
          symbol: "AAPL 240C",
          kind: "call",
          strike: 240,
          quantity: 10,
          contract_size: 100,
          delta: 636.5,
          gamma: 32.4,
          vega: 197.2,
          theta: -85.4,
          rho: 41.2,
        },
        {
          symbol: "SPY 600P",
          kind: "put",
          strike: 600,
          quantity: -5,
          contract_size: 100,
          delta: 211.5,
          gamma: -14.6,
          vega: -98.6,
          theta: 42.7,
          rho: -20.3,
        },
      ],
      totals: { delta: 848, gamma: 17.8, vega: 98.6, theta: -42.7, rho: 20.9 },
      n: 2,
      units: {
        delta: "per 1.0 underlying move (USD)",
        gamma: "per 1.0 underlying move",
        vega: "per 1% vol move (USD)",
        theta: "per calendar day (USD)",
        rho: "per 1 bp rate move (USD)",
      },
      summary: { positions: 2, delta: 848, gamma: 17.8, vega: 98.6, theta: -42.7, rho: 20.9 },
    },
    warnings: [],
    sources: ["greeks"],
    elapsed_ms: 5,
  };
}

beforeEach(() => {
  lastArgs.length = 0;
  refetchMock.mockClear();
  mockFn.state = "idle";
  mockFn.data = undefined;
  mockFn.error = null;
  localStorage.clear();
});
afterEach(() => {
  cleanup();
});

/* ── tests ─────────────────────────────────────────────────────────── */

describe("GREEKS pane — load + error states", () => {
  it("renders a skeleton while loading", () => {
    mockFn.state = "loading";
    const { container } = render(<GreeksPane code="GREEKS" />);
    expect(container.querySelector('[aria-busy="true"]')).not.toBeNull();
  });

  it("renders the function error state when the fetch errors", () => {
    mockFn.state = "error";
    mockFn.error = new Error("sidecar exploded");
    render(<GreeksPane code="GREEKS" />);
    expect(screen.getByText(/sidecar exploded/i)).toBeInTheDocument();
  });

  it("renders the empty-book envelope with its reason verbatim", () => {
    mockFn.state = "ok";
    // REAL wire shape (F8 regression): the empty-book envelope used to ship
    // `positions: 0` — a scalar, while the pane spreads it as an array.
    // `[...0]` threw during render (error boundary). This fixture must keep
    // the scalar so the guard stays pinned; a prior fixture omitted the field
    // entirely and the bug sailed through.
    mockFn.data = {
      data: {
        status: "input_required",
        reason: "No option positions were supplied or found in the local option book.",
        positions: 0,
      },
      warnings: [],
    };
    render(<GreeksPane code="GREEKS" />);
    expect(screen.getByText("Empty option book")).toBeInTheDocument();
    expect(
      screen.getByText(/no option positions were supplied/i),
    ).toBeInTheDocument();
  });

  it("does not crash when a scalar `positions` smuggles past the wire (defensive guard)", () => {
    // The crash repro from the audit: render the full input_required payload
    // with the scalar field plus totals absent — must render, not throw.
    mockFn.state = "ok";
    mockFn.data = {
      data: {
        status: "input_required",
        reason: "No option positions were supplied or found in the local option book.",
        positions: 0,
        n: 0,
        rows: [],
      },
      warnings: [],
    };
    let thrown: unknown = null;
    try {
      render(<GreeksPane code="GREEKS" />);
    } catch (err) {
      thrown = err;
    }
    expect(thrown).toBeNull();
    expect(screen.getByText("Empty option book")).toBeInTheDocument();
    // No fabricated NET aggregate row leaks from the malformed payload.
    expect(screen.queryByText(/NET — book/)).toBeNull();
  });

  it("treats a non-array positions payload as an empty book on the ok path (no crash)", () => {
    mockFn.state = "ok";
    mockFn.data = {
      data: {
        status: "ok",
        positions: 0,
        totals: { delta: 848, gamma: 17.8, vega: 98.6, theta: -42.7, rho: 20.9 },
        n: 0,
        units: {},
      },
      warnings: [],
    };
    let thrown: unknown = null;
    try {
      render(<GreeksPane code="GREEKS" />);
    } catch (err) {
      thrown = err;
    }
    expect(thrown).toBeNull();
    // The aggregate row still renders from `totals`; no per-position rows.
    expect(screen.getByText(/NET — book/)).toBeInTheDocument();
  });

  it("renders a calc_error envelope without fabricating totals", () => {
    mockFn.state = "ok";
    mockFn.data = {
      data: { status: "calc_error", reason: "Greeks aggregation failed: spot missing." },
      warnings: [],
    };
    render(<GreeksPane code="GREEKS" />);
    expect(screen.getByText("Greeks unavailable")).toBeInTheDocument();
    expect(screen.getByText(/aggregation failed: spot missing/i)).toBeInTheDocument();
    expect(screen.queryByText(/NET — book/)).toBeNull();
  });
});

describe("GREEKS pane — ok payload", () => {
  it("renders per-position greeks plus the aggregate NET row", () => {
    mockFn.state = "ok";
    mockFn.data = okPayload();
    const { container } = render(<GreeksPane code="GREEKS" />);
    // Per-position rows.
    expect(container.textContent).toContain("AAPL 240C");
    expect(container.textContent).toContain("SPY 600P");
    expect(container.textContent).toContain("636.5");
    expect(container.textContent).toContain("-85.4");
    // Aggregate NET row carries the summed totals.
    expect(container.textContent).toContain("NET — book");
    expect(container.textContent).toContain("848");
    expect(container.textContent).toContain("-42.7");
  });

  it("mirrors the totals in the net summary cards", () => {
    mockFn.state = "ok";
    mockFn.data = okPayload();
    const { container } = render(<GreeksPane code="GREEKS" />);
    expect(screen.getByText("Net delta")).toBeInTheDocument();
    expect(screen.getByText("Net gamma")).toBeInTheDocument();
    expect(screen.getByText("Net vega")).toBeInTheDocument();
    expect(screen.getByText("Net theta")).toBeInTheDocument();
    // Net delta card value = 848.
    expect(container.textContent).toContain("848");
    // Trader-readable unit captions surface verbatim.
    expect(screen.getAllByText(/per calendar day \(USD\)/i).length).toBeGreaterThan(0);
  });

  it("flags synthetic assumptions from the backend prominently", () => {
    mockFn.state = "ok";
    const payload = okPayload();
    payload.data.assumptions_used = ["AAPL 240C: vol=default 0.30"];
    mockFn.data = payload;
    render(<GreeksPane code="GREEKS" />);
    expect(screen.getByText("synthetic")).toBeInTheDocument();
    expect(screen.getByText(/missing inputs were defaulted by the engine/i)).toBeInTheDocument();
  });

  it("surfaces per-position aggregation failures as errors, not zeros", () => {
    mockFn.state = "ok";
    const payload = okPayload();
    payload.data.positions = [
      { error: "spot missing", symbol: "BAD", kind: "call", strike: 100 },
      ...(okPayload().data.positions ?? []).slice(0, 1),
    ];
    payload.data.totals = { delta: 636.5, gamma: 32.4, vega: 197.2, theta: -85.4, rho: 41.2 };
    mockFn.data = payload;
    const { container } = render(<GreeksPane code="GREEKS" />);
    const errorCells = screen.getAllByText("error");
    expect(errorCells.length).toBeGreaterThan(0);
    expect(errorCells[0].getAttribute("title")).toContain("spot missing");
    // The healthy position still shows its greeks.
    expect(container.textContent).toContain("636.5");
  });
});

describe("GREEKS pane — persisted book editor", () => {
  it("shows a parse error for invalid JSON and keeps the last valid book", () => {
    mockFn.state = "ok";
    mockFn.data = okPayload();
    render(<GreeksPane code="GREEKS" />);
    const editor = screen.getByLabelText("Option book JSON");
    fireEvent.change(editor, { target: { value: "{not json" } });
    fireEvent.click(screen.getByText("Apply book"));
    expect(screen.getByRole("alert")).toHaveTextContent(/invalid JSON/i);
    // The pane did NOT re-issue a broken book.
    const callsWithPositions = lastArgs.filter((a) => a.params?.positions != null);
    const last = callsWithPositions[callsWithPositions.length - 1];
    expect(Array.isArray(last?.params?.positions)).toBe(true);
  });

  it("re-issues the call when a valid edited book is applied", () => {
    mockFn.state = "ok";
    mockFn.data = okPayload();
    render(<GreeksPane code="GREEKS" />);
    const editor = screen.getByLabelText("Option book JSON");
    const single = JSON.stringify([
      { symbol: "TSLA 300P", kind: "put", quantity: 2, contract_size: 100, spot: 310, strike: 300, vol: 0.4, T: 0.25, r: 0.04 },
    ]);
    fireEvent.change(editor, { target: { value: single } });
    fireEvent.click(screen.getByText("Apply book"));
    const callsWithPositions = lastArgs.filter((a) => a.params?.positions != null);
    const last = callsWithPositions[callsWithPositions.length - 1];
    const positions = last?.params?.positions as Array<{ symbol?: string }>;
    expect(positions).toHaveLength(1);
    expect(positions[0]?.symbol).toBe("TSLA 300P");
    // The draft book is persisted for the next session.
    expect(localStorage.getItem("showme.greeks.book")).toContain("TSLA 300P");
  });
});
