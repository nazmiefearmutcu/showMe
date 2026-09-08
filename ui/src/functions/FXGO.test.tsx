/**
 * FXGO pane — data-honesty + render-contract tests.
 *
 * The FXGO defect: the backend labels the dealing board
 * `data_mode=live_exchange` even when most pairs 404 at the provider and
 * only a fraction of the board survives. These tests pin the pane's
 * honesty recomputation:
 *
 *  - the four load states (loading / empty / error / ok) render;
 *  - a full board (10 rows, no warnings) shows the live mode WITHOUT the
 *    degraded banner;
 *  - a partial board with provider warnings (the real-world defect) gets
 *    the prominent "reference · degraded" pill + a REFERENCE/NOT
 *    executable banner;
 *  - a provider_unavailable payload renders the honest empty state and
 *    never fabricates rows;
 *  - every state carries the indicative "not executable" notice — FXGO
 *    quotes are never executable venue quotes;
 *  - clicking a board row focuses that pair (one interaction).
 *
 * `useFunction` is mocked via a mutable shared state so each test drives
 * the pane into a specific branch without the real sidecar transport.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { FXGOPane } from "./FXGO";

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

function boardRow(pair: string, mid: number, changePct: number) {
  const pip = pair.endsWith("JPY") ? 0.01 : 0.0001;
  return {
    pair,
    symbol: pair,
    bid: mid - pip / 2,
    ask: mid + pip / 2,
    mid,
    spread: pip,
    spread_pips: 1,
    change: mid * (changePct / 100),
    change_pct: changePct,
    previous_close: mid - mid * (changePct / 100),
  };
}

const FULL_PAIRS = [
  "EURUSD", "GBPUSD", "USDJPY", "USDCHF", "AUDUSD",
  "USDCAD", "NZDUSD", "EURGBP", "EURJPY", "GBPJPY",
];

function fullLivePayload() {
  return {
    warnings: [],
    sources: ["yfinance"],
    elapsed_ms: 950,
    data: {
      status: "ok",
      rows: FULL_PAIRS.map((p, i) =>
        boardRow(p, p === "USDJPY" ? 154.2 : 1.1 + i * 0.05, i % 2 ? 0.12 : -0.08),
      ),
      data_mode: "live_exchange",
      as_of: "2026-09-07T22:16:36+00:00",
    },
  };
}

function degradedPayload() {
  // The real-world defect: 9/10 pairs 404 → one survivor, yet the
  // backend still stamps data_mode=live_exchange.
  return {
    warnings: [
      "errors: ['GBPUSD=X: 404 Client Error: Not Found', 'USDJPY=X: 404 Client Error: Not Found']",
    ],
    sources: ["yfinance"],
    elapsed_ms: 1200,
    data: {
      status: "ok",
      rows: [boardRow("EURUSD", 1.1628, 0.0861)],
      data_mode: "live_exchange",
      as_of: "2026-09-07T22:16:36+00:00",
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

describe("FXGO pane — load states", () => {
  it("renders a skeleton while loading", () => {
    setMockFn({ state: "loading", data: undefined });
    const { container } = render(<FXGOPane code="FXGO" />);
    expect(container.querySelector('[aria-busy="true"]')).not.toBeNull();
  });

  it("renders the error state when the fetch errors", () => {
    setMockFn({
      state: "error",
      data: undefined,
      error: new Error("sidecar exploded"),
    });
    render(<FXGOPane code="FXGO" />);
    expect(screen.getByText(/sidecar exploded/i)).toBeInTheDocument();
  });

  it("renders the honest empty state for provider_unavailable (no fabricated rows)", () => {
    setMockFn({
      state: "ok",
      data: {
        data: {
          status: "provider_unavailable",
          reason: "FX spot board unavailable from yfinance.",
          rows: [],
        },
      },
    });
    render(<FXGOPane code="FXGO" />);
    expect(screen.getByText("FX spot board unavailable")).toBeInTheDocument();
    expect(screen.getByText(/Reference quotes only/i)).toBeInTheDocument();
  });
});

describe("FXGO pane — data honesty (the live_exchange defect)", () => {
  it("shows the live mode WITHOUT the degraded banner for a full board", () => {
    setMockFn({ state: "ok", data: fullLivePayload() });
    render(<FXGOPane code="FXGO" />);
    // Pill + footer both echo the mode — both may say live_exchange here.
    expect(
      screen.getAllByText("live_exchange").length,
    ).toBeGreaterThan(0);
    expect(screen.getByText("FULL BOARD")).toBeInTheDocument();
    expect(screen.queryByText(/DEGRADED BOARD/i)).toBeNull();
    // Indicative notice is still mandatory — never executable.
    expect(screen.getByText(/Indicative quotes only/i)).toBeInTheDocument();
  });

  it("downgrades a partial board with provider errors to reference · degraded", () => {
    setMockFn({ state: "ok", data: degradedPayload() });
    render(<FXGOPane code="FXGO" />);
    // Prominent banner with the honest count and the non-executable rule.
    expect(screen.getByText(/DEGRADED BOARD/i)).toBeInTheDocument();
    expect(screen.getByText(/1 of 10 pairs returned/i)).toBeInTheDocument();
    // The honesty pill never repeats the backend's overclaimed mode.
    expect(screen.queryByText("live_exchange")).toBeNull();
    // Pill, footer and KPI caption all carry the downgraded mode.
    expect(
      screen.getAllByText(/reference · degraded/i).length,
    ).toBeGreaterThan(0);
  });

  it("keeps the indicative notice in every ok state", () => {
    setMockFn({ state: "ok", data: degradedPayload() });
    render(<FXGOPane code="FXGO" />);
    expect(
      screen.getByRole("status", { name: /quote mode notice/i }),
    ).toHaveTextContent(/NOT executable/i);
  });
});

describe("FXGO pane — board interaction", () => {
  it("focuses a pair when its board row is clicked", () => {
    setMockFn({ state: "ok", data: fullLivePayload() });
    render(<FXGOPane code="FXGO" symbol="EURUSD" />);
    // Initial focus falls back to the navigated symbol.
    expect(screen.getByText("focus EURUSD")).toBeInTheDocument();
    // Clicking another row moves the focus pill.
    fireEvent.click(screen.getByText("USDJPY"));
    expect(screen.getByText("focus USDJPY")).toBeInTheDocument();
  });

  it("renders the dealing board grid with an accessible label", () => {
    setMockFn({ state: "ok", data: fullLivePayload() });
    render(<FXGOPane code="FXGO" />);
    expect(
      screen.getByRole("table", { name: /FXGO dealing board/i }),
    ).toBeInTheDocument();
  });
});
