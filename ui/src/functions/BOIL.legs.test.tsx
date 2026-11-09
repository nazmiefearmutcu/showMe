/**
 * BOIL pane — per-leg render tests (BOIL#1 history, BOIL#4 day range/volume).
 *
 * Kept apart from BOIL.test.tsx, which is the pane's base contract file.
 * Same useFunction mock and fixtures as that file.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, render } from "@testing-library/react";
import { BOILPane } from "./BOIL";

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

/* ── fixtures: shape mirrors commodity/_funcs.py BOILFunction ──────── */

function oilRow(symbol: string, name: string, last: number, changePct: number) {
  return {
    symbol,
    name,
    unit: "USD/bbl",
    exchange: symbol === "CL=F" ? "NYMEX" : "ICE",
    last,
    prev: last - 0.4,
    change: 0.4,
    change_pct: changePct,
    open: last - 0.2,
    high: last + 0.6,
    low: last - 0.9,
    volume: 120000,
    source: "yfinance",
    source_mode: "live_yfinance",
    as_of: "2026-09-07T22:20:00+00:00",
  };
}

function livePayload() {
  return {
    data: {
      data: {
        status: "ok",
        market: "oil",
        source_mode: "live_yfinance",
        rows: [
          oilRow("CL=F", "WTI Crude Oil", 91.48, 0.71),
          oilRow("BZ=F", "Brent Crude Oil", 96.28, 0.5),
        ],
        history: [
          { date: "2026-09-01", close: 90.1 },
          { date: "2026-09-02", close: 90.9 },
          { date: "2026-09-03", close: 91.2 },
          { date: "2026-09-04", close: 91.48 },
        ],
        spread: 4.8,
        methodology: "BOIL reports front-month WTI and Brent futures.",
      },
      sources: ["yfinance_futures"],
      elapsed_ms: 21,
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


describe("BOIL pane — per-leg history (BOIL#1)", () => {
  function payloadWithLegHistory() {
    const base = livePayload();
    base.data.data = {
      ...base.data.data,
      history_by_symbol: {
        "CL=F": [
          { date: "2026-09-01", close: 90.1 },
          { date: "2026-09-02", close: 90.9 },
          { date: "2026-09-03", close: 91.48 },
        ],
        "BZ=F": [
          { date: "2026-09-01", close: 94.0 },
          { date: "2026-09-02", close: 95.5 },
          { date: "2026-09-03", close: 96.1 },
          { date: "2026-09-04", close: 96.28 },
        ],
      },
    } as typeof base.data.data;
    return base;
  }

  it("charts each leg from its own closes, labelled by symbol", () => {
    setMockFn({ state: "ok", ...payloadWithLegHistory() });
    const { container } = render(<BOILPane code="BOIL" symbol="CL=F" />);
    const brent = container.querySelector(
      'figure[aria-label="BOIL BZ=F history chart"] svg',
    );
    const wti = container.querySelector(
      'figure[aria-label="BOIL CL=F history chart"] svg',
    );
    expect(brent?.getAttribute("aria-label")).toMatch(/4 points/i);
    expect(wti?.getAttribute("aria-label")).toMatch(/3 points/i);
    expect(
      container.querySelector('figure[aria-label="BOIL BZ=F history chart"]')
        ?.textContent,
    ).toContain("BZ=F");
  });

  it("never draws the WTI series under the Brent card", () => {
    setMockFn({ state: "ok", ...payloadWithLegHistory() });
    const { container } = render(<BOILPane code="BOIL" symbol="CL=F" />);
    // Brent's last close is 96.28; the WTI-only series must not be its chart.
    const brentFigure = container.querySelector(
      'figure[aria-label="BOIL BZ=F history chart"]',
    );
    expect(brentFigure?.textContent).toContain("96.280");
    expect(brentFigure?.textContent).not.toContain("91.480");
  });
});

describe("BOIL pane — per-leg day range and volume (BOIL#4)", () => {
  it("shows each leg's own day range and volume under its symbol", () => {
    setMockFn({ state: "ok", ...livePayload() });
    const { container } = render(<BOILPane code="BOIL" symbol="CL=F" />);
    // CL=F: low 90.58 (last − 0.9 = 90.58), high 92.08; Brent: low 95.38, high 96.88.
    expect(container.textContent).toContain("CL=F day range");
    expect(container.textContent).toContain("BZ=F day range");
    expect(container.textContent).toContain("CL=F volume");
    expect(container.textContent).toContain("BZ=F volume");
    // Brent's own low/high reach the page, not WTI's duplicated under it.
    expect(container.textContent).toContain("95.380");
    expect(container.textContent).toContain("96.880");
  });
});

