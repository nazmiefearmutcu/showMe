/**
 * NGAS pane — alias-pane render tests (CRVF/GEX pattern).
 *
 * NGAS is the backend alias of BGAS (NGASFunction extends BGASFunction),
 * so this file pins the alias wiring + the honesty surface rather than
 * re-testing the whole shared commodity-spot body:
 *
 *  - loading / error / ok render through the shared body;
 *  - the live NG=F snapshot renders price + history chart;
 *  - a model payload shows the reference-model honesty notice.
 *
 * `useFunction` is mocked via a mutable shared state.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, render, screen } from "@testing-library/react";
import { NGASPane } from "./NGAS";

/* ── useFunction mock ──────────────────────────────────────────────── */

interface MockFnState {
  state: "idle" | "loading" | "ok" | "error" | "refreshing";
  data?: { data?: unknown; sources?: string[]; elapsed_ms?: number };
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

/* ── fixtures ──────────────────────────────────────────────────────── */

function livePayload() {
  return {
    data: {
      data: {
        status: "ok",
        symbol: "NG=F",
        source_mode: "live_yfinance",
        rows: [
          {
            symbol: "NG=F",
            name: "Henry Hub Natural Gas",
            unit: "USD/MMBtu",
            last: 2.975,
            change_pct: 1.2,
            high: 2.998,
            low: 2.921,
            volume: 34220,
            as_of: "2026-09-07T22:15:56+00:00",
          },
        ],
        history: [
          { date: "2026-09-03", close: 2.9 },
          { date: "2026-09-04", close: 2.95 },
          { date: "2026-09-05", close: 2.975 },
        ],
      },
      sources: ["yfinance_futures"],
      elapsed_ms: 9,
    },
  };
}

function modelPayload() {
  const p = livePayload();
  p.data.data.source_mode = "model";
  p.data.data.status = "reference_model";
  p.data.data.history = [];
  return p;
}

/* ── tests ─────────────────────────────────────────────────────────── */

beforeEach(() => {
  localStorage.clear();
  setMockFn({ state: "idle", data: undefined });
});
afterEach(() => {
  cleanup();
});

describe("NGAS pane — load states", () => {
  it("renders a skeleton while loading", () => {
    setMockFn({ state: "loading", data: undefined });
    const { container } = render(<NGASPane code="NGAS" symbol="NG=F" />);
    expect(container.querySelector('[aria-busy="true"]')).not.toBeNull();
  });

  it("renders the error state when the fetch errors", () => {
    setMockFn({
      state: "error",
      data: undefined,
      error: new Error("sidecar exploded"),
    });
    render(<NGASPane code="NGAS" symbol="NG=F" />);
    expect(screen.getByText(/sidecar exploded/i)).toBeInTheDocument();
  });
});

describe("NGAS pane — ok payload", () => {
  it("renders the NG=F snapshot price and history chart", () => {
    setMockFn({ state: "ok", ...livePayload() });
    const { container } = render(<NGASPane code="NGAS" symbol="NG=F" />);
    expect(screen.getAllByText("2.975").length).toBeGreaterThanOrEqual(1);
    const svg = container.querySelector('svg[role="img"]');
    expect(svg?.getAttribute("aria-label")).toMatch(/3 points/i);
    // The alias pane keeps its own persistent control key (showme.ngas.days).
    expect(screen.getByLabelText("HISTORY")).toBeInTheDocument();
  });

  it("shows the reference-model honesty notice for model payloads", () => {
    setMockFn({ state: "ok", ...modelPayload() });
    render(<NGASPane code="NGAS" symbol="NG=F" />);
    expect(
      screen.getByText(/NOT a live market price/i),
    ).toBeInTheDocument();
  });
});

describe("commodity-spot shared body — audit fixes (NGAS, second code)", () => {
  it("stamps the % unit on the change caption (audit A1-M)", () => {
    setMockFn({ state: "ok", ...livePayload() });
    const { container } = render(<NGASPane code="NGAS" symbol="NG=F" />);
    expect(container.textContent).toContain("+1.200%");
  });

  it("gives a missing change a neutral tone instead of green (audit A3-L)", () => {
    const p = livePayload();
    delete (p.data.data.rows[0] as unknown as Record<string, unknown>).change_pct;
    setMockFn({ state: "ok", ...p });
    render(<NGASPane code="NGAS" symbol="NG=F" />);
    const card = screen.getByText("NG=F").closest(".stat-card");
    expect(card?.className).toContain("stat-card--neutral");
    expect(card?.className).not.toContain("stat-card--positive");
  });
});
