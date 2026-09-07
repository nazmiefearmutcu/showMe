/**
 * BQL pane — load-state + console-contract tests (GEX mock pattern).
 *
 * `useFunction` is mocked via a mutable shared object. Pins:
 *  - loading skeleton, error, and ok branches render;
 *  - results grid carries dynamic field columns + a live mode pill;
 *  - provider warnings surface verbatim as content;
 *  - provider_unavailable renders the honest empty state (no fake rows);
 *  - the query_plan collapsible renders the backend steps;
 *  - Run commits the edited query, echoes it in the footer, and persists
 *    it under `showme.bql.last`; an empty query cannot be committed.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { BQLPane } from "./BQL";

/* ── useFunction mock ──────────────────────────────────────────────── */

interface MockFnState {
  state: "idle" | "loading" | "ok" | "error" | "refreshing";
  data?: { data?: unknown } | undefined;
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

/* ── fixtures (shape mirrors a live /api/fn/BQL probe) ─────────────── */

function okPayload() {
  return {
    rows: [
      { symbol: "AAPL", date: "2026-09-05T00:00:00+00:00", close: 321.88, volume: 51450000 },
      { symbol: "MSFT", date: "2026-09-05T00:00:00+00:00", close: 428.51, volume: 21300000 },
    ],
    history: [
      { date: "2026-09-05T00:00:00+00:00", symbol: "AAPL", close: 321.88 },
    ],
    summary: {
      mode: "live",
      symbols: 2,
      fields: "close, volume",
      rows: 2,
      first_date: "2026-09-05T00:00:00+00:00",
      last_date: "2026-09-05T00:00:00+00:00",
      by: "date",
    },
    query_plan: [
      { step: "parse", detail: "get(...) fields, for([...]) universe parsed." },
      { step: "fetch", detail: "Live mode requests OHLCV rows from yfinance." },
      { step: "shape", detail: "Rows are symbol/date records." },
    ],
    warnings: ["MSFT: partial window from provider"],
    methodology: "constrained query DSL",
  };
}

function runButton() {
  // Exact-name match: the refresh button's aria-label is "Re-run BQL query".
  return screen.getByRole("button", { name: "Run" });
}

beforeEach(() => {
  localStorage.clear();
  setMockFn({ state: "idle", data: undefined });
});
afterEach(() => {
  cleanup();
});

describe("BQL pane — load states", () => {
  it("renders a skeleton while loading", () => {
    setMockFn({ state: "loading" });
    const { container } = render(<BQLPane code="BQL" symbol="AAPL" />);
    expect(container.querySelector('[aria-busy="true"]')).not.toBeNull();
  });

  it("renders the error state when the fetch errors", () => {
    setMockFn({
      state: "error",
      error: new Error("sidecar exploded"),
    });
    render(<BQLPane code="BQL" symbol="AAPL" />);
    expect(screen.getByText(/sidecar exploded/i)).toBeInTheDocument();
  });

  it("renders the honest empty state for provider_unavailable (no fake rows)", () => {
    setMockFn({
      state: "ok",
      data: {
        data: {
          status: "provider_unavailable",
          reason: "No live rows returned for the requested BQL universe.",
          rows: [],
          next_actions: [
            "Use query like get(close, volume) for(['AAPL']) with(period='1mo') by(date).",
          ],
        },
      },
    });
    render(<BQLPane code="BQL" symbol="AAPL" />);
    expect(screen.getByText(/No rows returned/i)).toBeInTheDocument();
    expect(
      screen.getByText(/No live rows returned for the requested BQL universe\./i),
    ).toBeInTheDocument();
    expect(screen.queryByText("321.88")).toBeNull();
  });
});

describe("BQL pane — results", () => {
  it("renders dynamic field columns, the live mode pill and the query plan", () => {
    setMockFn({ state: "ok", data: { data: okPayload() } });
    const { container } = render(<BQLPane code="BQL" symbol="AAPL" />);
    // Rows + dynamic columns.
    expect(screen.getByText("AAPL")).toBeInTheDocument();
    expect(screen.getByText("MSFT")).toBeInTheDocument();
    expect(container.textContent).toContain("321.88");
    // Live mode pill + KPI echo.
    expect(screen.getAllByText("live").length).toBeGreaterThanOrEqual(1);
    expect(container.textContent).toContain("PROVIDER OHLCV");
    // query_plan collapsible with backend steps.
    const plan = container.querySelector('details[aria-label="BQL query plan"]');
    expect(plan).not.toBeNull();
    expect(plan?.textContent).toContain("parse");
    expect(plan?.textContent).toContain("fetch");
  });

  it("surfaces provider warnings verbatim as content", () => {
    setMockFn({ state: "ok", data: { data: okPayload() } });
    render(<BQLPane code="BQL" symbol="AAPL" />);
    expect(
      screen.getByText(/MSFT: partial window from provider/),
    ).toBeInTheDocument();
  });
});

describe("BQL pane — console interaction", () => {
  it("commits the edited query, echoes it in the footer and persists it", () => {
    setMockFn({ state: "ok", data: { data: okPayload() } });
    const { container } = render(<BQLPane code="BQL" symbol="AAPL" />);
    const input = screen.getByLabelText("BQL query") as HTMLInputElement;
    fireEvent.change(input, {
      target: { value: "get(close) for(['BTCUSDT'])" },
    });
    fireEvent.click(runButton());
    expect(localStorage.getItem("showme.bql.last")).toBe(
      "get(close) for(['BTCUSDT'])",
    );
    expect(container.textContent).toContain("BTCUSDT");
  });

  it("adds a parse note when the query has no for([...]) universe", () => {
    setMockFn({ state: "ok", data: { data: okPayload() } });
    render(<BQLPane code="BQL" symbol="AAPL" />);
    const input = screen.getByLabelText("BQL query");
    fireEvent.change(input, { target: { value: "get(close)" } });
    fireEvent.click(runButton());
    expect(
      screen.getByText(/no for\(\[\.\.\.\]\) block — universe falls back/i),
    ).toBeInTheDocument();
  });

  it("refuses to commit an empty query", () => {
    setMockFn({ state: "ok", data: { data: okPayload() } });
    render(<BQLPane code="BQL" symbol="AAPL" />);
    const input = screen.getByLabelText("BQL query") as HTMLInputElement;
    fireEvent.change(input, { target: { value: "   " } });
    fireEvent.click(runButton());
    // The committed query is still the default one.
    expect(localStorage.getItem("showme.bql.last")).toBe(
      "get(close, volume) for(['AAPL','MSFT']) with(period='1mo') by(date)",
    );
  });
});
