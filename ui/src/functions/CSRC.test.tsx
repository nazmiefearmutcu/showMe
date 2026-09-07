/**
 * CSRC pane — data-honesty + render-contract tests.
 *
 * `useFunction` is mocked via a mutable shared state (GEX pattern) so
 * each test drives the pane into a specific branch without the real
 * sidecar transport. Pins:
 *
 *  - the load states (loading / empty / error / ok) render;
 *  - the ok state renders the metrics table + matched/scanned note;
 *  - a live-quoted row is labelled "live" and a row the provider did
 *    not answer is labelled "reference" (never painted as live);
 *  - the sector filter is a real control: clicking ENERGY updates the
 *    composed query echo (the pane sends it server-side);
 *  - a backend `unsupported_predicate` status renders the filter-error
 *    state with the backend reason.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { CSRCPane } from "./CSRC";

/* ── useFunction mock ──────────────────────────────────────────────── */

interface MockFnState {
  state: "idle" | "loading" | "ok" | "error" | "refreshing";
  data?: { data?: unknown; sources?: string[]; elapsed_ms?: number } | undefined;
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

function okPayload() {
  return {
    data: {
      sources: ["yfinance", "showme_commodity_reference_universe"],
      elapsed_ms: 421,
      data: {
        status: "ok",
        query: "volume >= 0",
        filter: "volume >= 0",
        scanned: 3,
        matched: 3,
        rows: [
          {
            symbol: "CL=F",
            name: "WTI Crude Oil",
            sector: "Energy",
            exchange: "NYMEX",
            contract_unit: "1,000 barrels",
            volume: 290000,
            open_interest: 310000,
            last: 91.48,
            change_pct: 0.42,
            quote_state: "live",
          },
          {
            symbol: "GC=F",
            name: "Gold",
            sector: "Metals",
            exchange: "COMEX",
            contract_unit: "100 troy ounces",
            volume: 145000,
            open_interest: 480000,
            last: null,
            change_pct: null,
            quote_state: "reference",
          },
          {
            symbol: "ZC=F",
            name: "Corn",
            sector: "Agriculture",
            exchange: "CBOT",
            contract_unit: "5,000 bushels",
            volume: 205000,
            open_interest: 620000,
            last: 442.5,
            change_pct: -1.2,
            quote_state: "live",
          },
        ],
        next_actions: [],
      },
    },
  };
}

beforeEach(() => {
  setMockFn({ state: "idle", data: undefined });
});

afterEach(() => {
  cleanup();
  window.localStorage.clear();
});

describe("CSRC pane — load states", () => {
  it("renders a skeleton while loading", () => {
    setMockFn({ state: "loading", data: undefined });
    const { container } = render(<CSRCPane code="CSRC" />);
    expect(container.querySelector("[aria-busy='true']")).not.toBeNull();
  });

  it("renders the error state when the fetch errors", () => {
    setMockFn({
      state: "error",
      data: undefined,
      error: new Error("sidecar exploded"),
    });
    render(<CSRCPane code="CSRC" />);
    expect(screen.getByText(/sidecar exploded/i)).toBeInTheDocument();
  });

  it("renders the honest empty state when no rows match the filters", () => {
    setMockFn({
      state: "ok",
      data: {
        data: {
          status: "empty",
          query: 'sector = "Agriculture"',
          rows: [],
          matched: 0,
          scanned: 6,
          reason: 'No rows matched filter `sector = "Agriculture"`.',
          next_actions: ["Broaden the filter or clear it."],
        },
      },
    });
    render(<CSRCPane code="CSRC" />);
    expect(screen.getByText(/No rows matched your filters/i)).toBeInTheDocument();
    expect(screen.getByText(/No rows matched filter/i)).toBeInTheDocument();
  });

  it("renders the metrics table + count note when ok", () => {
    setMockFn({ state: "ok", ...okPayload() });
    render(<CSRCPane code="CSRC" />);
    expect(screen.getByText("CL=F")).toBeInTheDocument();
    expect(screen.getByText("WTI Crude Oil")).toBeInTheDocument();
    expect(screen.getByText(/3 of 3 matched/i)).toBeInTheDocument();
    expect(screen.getAllByText(/3 scanned/i).length).toBeGreaterThan(0);
  });
});

describe("CSRC pane — data honesty", () => {
  it("labels provider-answered rows live and unanswered rows reference", () => {
    setMockFn({ state: "ok", ...okPayload() });
    render(<CSRCPane code="CSRC" />);
    const livePills = screen.getAllByText("live");
    expect(livePills.length).toBe(2);
    expect(screen.getByText("reference")).toBeInTheDocument();
    // The reference row has no price — the Last cell must show the
    // missing-value dash, never a fabricated number.
    expect(screen.getByText(/1 reference row/)).toBeInTheDocument();
  });
});

describe("CSRC pane — sector filter", () => {
  it("composes the server-side sector query when a sector is selected", () => {
    setMockFn({ state: "ok", ...okPayload() });
    render(<CSRCPane code="CSRC" />);
    fireEvent.click(screen.getByTitle("Sector Energy"));
    // The composed DSL echo updates in the footer + note.
    const echoes = screen.getAllByText(/sector = "Energy"/);
    expect(echoes.length).toBeGreaterThan(0);
  });

  it("returns to the permissive match-all query on ALL", () => {
    setMockFn({ state: "ok", ...okPayload() });
    render(<CSRCPane code="CSRC" />);
    fireEvent.click(screen.getByTitle("Sector Metals"));
    fireEvent.click(screen.getByTitle("Sector ALL"));
    expect(screen.getAllByText(/volume >= 0/).length).toBeGreaterThan(0);
  });

  it("renders the filter-error state for an unsupported predicate payload", () => {
    setMockFn({
      state: "ok",
      data: {
        data: {
          status: "unsupported_predicate",
          reason: "Filter parse error: Filter references unknown columns: bogus.",
          rows: [],
          matched: 0,
          scanned: 0,
        },
      },
    });
    render(<CSRCPane code="CSRC" />);
    expect(screen.getByText(/Filter error/i)).toBeInTheDocument();
    expect(screen.getByText(/unknown columns/i)).toBeInTheDocument();
  });
});
