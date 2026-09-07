/**
 * HDS pane — data-honesty + render-contract tests.
 *
 * The backend HDS function has a live path (yfinance holder tables + local
 * SEC 13F) but falls back to labelled public-reference holder rows when both
 * providers are unavailable. These tests pin:
 *
 *  - the load states (loading / error / ok) render;
 *  - a REFERENCE payload renders a prominent "Reference data" badge + note;
 *  - a LIVE payload does NOT render that warning and shows the "live" pill;
 *  - share bars and holder rows render from payload data (no fake rows);
 *  - refresh button interaction triggers a refetch.
 *
 * `useFunction` is mocked via a mutable shared state so each test drives
 * the pane into a specific branch without the real sidecar transport.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, render, screen, fireEvent } from "@testing-library/react";
import { HDSPane } from "./HDS";

/* ── useFunction mock ──────────────────────────────────────────────── */

interface MockFnState {
  state: "idle" | "loading" | "ok" | "error" | "refreshing";
  data?: { data?: unknown } | undefined;
  error?: Error | null;
  refetch?: ReturnType<typeof vi.fn>;
}

const mockFn: MockFnState = { state: "idle", data: undefined, error: null };

function setMockFn(next: MockFnState) {
  mockFn.state = next.state;
  mockFn.data = next.data;
  mockFn.error = next.error ?? null;
  mockFn.refetch = next.refetch ?? vi.fn();
}

vi.mock("@/lib/useFunction", () => ({
  useFunction: () => ({
    state: mockFn.state,
    data: mockFn.data,
    error: mockFn.error,
    refetch: mockFn.refetch ?? vi.fn(),
  }),
}));

// SymbolBar pulls router/symbol-resolver side effects we don't need here.
vi.mock("@/shell/SymbolBar", () => ({
  SymbolBar: () => null,
}));

/* ── fixtures ──────────────────────────────────────────────────────── */

const referenceRows = [
  {
    symbol: "AAPL",
    holder: "Vanguard Group",
    holder_type: "institutional",
    shares: 1_318_000_000,
    pct_outstanding: 0.087,
    quarter: "latest public 13F reference",
    source_mode: "reference_13f_public",
  },
  {
    symbol: "AAPL",
    holder: "BlackRock",
    holder_type: "institutional",
    shares: 1_040_000_000,
    pct_outstanding: 0.069,
    quarter: "latest public 13F reference",
    source_mode: "reference_13f_public",
  },
];

function referencePayload() {
  return {
    data: {
      data: {
        status: "reference_holders",
        rows: referenceRows,
        methodology:
          "Reference holder rows preserve expected HDS shape when live holders are disabled.",
      },
    },
  };
}

const liveRows = [
  {
    symbol: "AAPL",
    holder: "Vanguard Group",
    holder_type: "institutional_13f",
    shares: 1_300_000_000,
    market_value: 250_000_000_000,
    quarter: "2026-Q2",
    source_mode: "sec_13f",
  },
  {
    symbol: "AAPL",
    holder: "BlackRock",
    holder_type: "institutional_13f",
    shares: 1_100_000_000,
    market_value: 210_000_000_000,
    quarter: "2026-Q2",
    source_mode: "sec_13f",
  },
];

function livePayload() {
  return {
    data: {
      data: {
        status: "ok",
        rows: liveRows,
        methodology: "HDS shows holder rows from local SEC 13F data.",
      },
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

describe("HDS pane — load states", () => {
  it("renders a skeleton while loading", () => {
    setMockFn({ state: "loading", data: undefined });
    const { container } = render(<HDSPane code="HDS" symbol="AAPL" />);
    expect(container.querySelector('[aria-busy="true"]')).not.toBeNull();
  });

  it("renders the error state when the fetch errors", () => {
    setMockFn({
      state: "error",
      data: undefined,
      error: new Error("sidecar exploded"),
    });
    render(<HDSPane code="HDS" symbol="AAPL" />);
    expect(screen.getByText(/sidecar exploded/i)).toBeInTheDocument();
  });

  it("renders the empty state when there are no rows", () => {
    setMockFn({
      state: "ok",
      data: { data: { status: "provider_unavailable", rows: [] } },
    });
    render(<HDSPane code="HDS" symbol="AAPL" />);
    expect(screen.getByText(/No holder rows returned/i)).toBeInTheDocument();
  });
});

describe("HDS pane — data honesty", () => {
  it("renders a prominent Reference data badge + note for reference payloads", () => {
    setMockFn({ state: "ok", ...referencePayload() });
    render(<HDSPane code="HDS" symbol="AAPL" />);
    expect(screen.getByText(/Reference data/i)).toBeInTheDocument();
    expect(
      screen.getByText(/NOT live 13F filings/i),
    ).toBeInTheDocument();
  });

  it("does NOT render the reference warning for a live payload", () => {
    setMockFn({ state: "ok", ...livePayload() });
    render(<HDSPane code="HDS" symbol="AAPL" />);
    expect(screen.queryByText(/Reference data/i)).toBeNull();
    // The header live pill is present.
    expect(screen.getByText(/^live$/i)).toBeInTheDocument();
  });

  it("renders holder rows from the payload with a shares bar", () => {
    setMockFn({ state: "ok", ...referencePayload() });
    const { container } = render(<HDSPane code="HDS" symbol="AAPL" />);
    // Holders render (top-holder StatCard + table rows → multiple matches).
    expect(screen.getAllByText("Vanguard Group").length).toBeGreaterThanOrEqual(1);
    expect(screen.getAllByText("BlackRock").length).toBeGreaterThanOrEqual(1);
    // Share-tint bar is rendered for rows with shares.
    expect(container.querySelectorAll("span[aria-hidden='true']").length)
      .toBeGreaterThan(0);
    // Fractions normalize to percent: 0.087 -> 8.70%.
    expect(screen.getByText("8.70%")).toBeInTheDocument();
  });
});

describe("HDS pane — interaction", () => {
  it("triggers a refetch when the refresh button is clicked", () => {
    const refetch = vi.fn();
    setMockFn({ state: "ok", ...referencePayload(), refetch });
    render(<HDSPane code="HDS" symbol="AAPL" />);
    fireEvent.click(screen.getByTitle(/Refresh holders/i));
    expect(refetch).toHaveBeenCalledTimes(1);
  });
});
