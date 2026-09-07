/**
 * TAUC pane — render-contract + data-honesty tests.
 *
 * The backend TAUC function lists Treasury auctions either from the live
 * TreasuryDirect adapter or from an honest, source-labelled calendar model.
 * These tests pin:
 *
 *  - the load states (loading / error / empty / ok) render;
 *  - rows render date-sorted with a correct totals strip;
 *  - the horizon segmented control changes the fetch params (persisted);
 *  - the window control toggles upcoming/recent params;
 *  - security-type chips filter rows and recompute totals;
 *  - a MODEL payload renders a prominent "NOT live TreasuryDirect" note,
 *    a live payload does not.
 *
 * `useFunction` is mocked via a mutable shared state (GEX pattern) plus a
 * `lastParams` capture so tests can assert the params the pane passes.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { TAUCPane } from "./TAUC";

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

let lastParams: Record<string, unknown> | undefined;

vi.mock("@/lib/useFunction", () => ({
  useFunction: (args: { code: string; params?: Record<string, unknown> }) => {
    lastParams = args.params;
    return {
      state: mockFn.state,
      data: mockFn.data,
      error: mockFn.error,
      refetch: vi.fn(),
    };
  },
}));

/* ── fixtures: 3 auctions, 2 types, deliberately unsorted dates ────── */

function auctionRow(overrides: Record<string, unknown>) {
  return {
    auction_date: "2026-09-08T00:00:00",
    issue_date: "2026-09-10T00:00:00",
    security_type: "Bill",
    security_term: "13-Week",
    term: "13-Week",
    offering_amount: "92000000000",
    cusip: "912797VG9",
    reopening: "Yes",
    high_yield: "",
    bid_to_cover: "",
    ...overrides,
  };
}

const FIXTURE_ROWS = [
  // Out of order on purpose — the pane must sort by auction date.
  auctionRow({
    auction_date: "2026-09-10T00:00:00",
    security_type: "Note",
    security_term: "10-Year",
    term: "10-Year",
    offering_amount: "39000000000",
    cusip: "91282CRF0",
    reopening: "Yes",
  }),
  auctionRow({
    security_type: "Bill",
    security_term: "13-Week",
    term: "13-Week",
    offering_amount: "92000000000",
    cusip: "912797VG9",
    reopening: "No",
  }),
  auctionRow({
    auction_date: "2026-09-09T00:00:00",
    security_term: "6-Week",
    term: "6-Week",
    offering_amount: "75000000000",
    cusip: "912797UL9",
    reopening: "No",
  }),
];

const BY_TYPE = [
  { security_type: "Bill", count: 2, total_offering: 167e9 },
  { security_type: "Note", count: 1, total_offering: 39e9 },
];

function payloadWith(sourceMode: string) {
  return {
    data: {
      data: {
        status: "ok",
        rows: FIXTURE_ROWS,
        n: 3,
        by_type: BY_TYPE,
        horizon_days: 30,
        summary: {
          action: "upcoming",
          horizon_days: 30,
          auctions: 3,
          source_mode: sourceMode,
          security_filter: "all",
        },
      },
      sources: [sourceMode],
      elapsed_ms: 12,
    },
  };
}

/* ── tests ─────────────────────────────────────────────────────────── */

beforeEach(() => {
  setMockFn({ state: "idle", data: undefined });
  lastParams = undefined;
  if (typeof localStorage !== "undefined") localStorage.clear();
});
afterEach(() => {
  cleanup();
});

describe("TAUC pane — load states", () => {
  it("renders a skeleton while loading", () => {
    setMockFn({ state: "loading", data: undefined });
    const { container } = render(<TAUCPane code="TAUC" />);
    expect(container.querySelector('[aria-busy="true"]')).not.toBeNull();
  });

  it("renders the error state with the error message", () => {
    setMockFn({
      state: "error",
      data: undefined,
      error: new Error("sidecar exploded"),
    });
    render(<TAUCPane code="TAUC" />);
    expect(screen.getByText(/sidecar exploded/i)).toBeInTheDocument();
  });

  it("renders the empty state when no auctions are returned", () => {
    setMockFn({
      state: "ok",
      data: { data: { status: "ok", rows: [], summary: {} } },
    });
    render(<TAUCPane code="TAUC" />);
    expect(screen.getByText(/No auctions returned/i)).toBeInTheDocument();
  });

  it("renders rows + totals when ok", () => {
    setMockFn({ state: "ok", ...payloadWith("treasurydirect") });
    const { container } = render(<TAUCPane code="TAUC" />);
    // All three auctions visible.
    expect(container.textContent).toContain("13-Week");
    expect(container.textContent).toContain("6-Week");
    expect(container.textContent).toContain("10-Year");
    // Sorted by auction date ascending.
    const text = container.textContent ?? "";
    expect(text.indexOf("2026-09-08")).toBeGreaterThan(-1);
    expect(text.indexOf("2026-09-08")).toBeLessThan(text.indexOf("2026-09-09"));
    expect(text.indexOf("2026-09-09")).toBeLessThan(text.indexOf("2026-09-10"));
    // Totals strip: 3 auctions, $206.0B offering.
    expect(screen.getByText("$206.0B")).toBeInTheDocument();
    expect(container.textContent).toContain("3 auctions");
    expect(container.textContent).toContain("$206.0B");
  });
});

describe("TAUC pane — controls drive fetch params", () => {
  it("fetches with the default 30d upcoming window", () => {
    setMockFn({ state: "ok", ...payloadWith("treasurydirect") });
    render(<TAUCPane code="TAUC" />);
    expect(lastParams).toEqual({ action: "upcoming", horizon_days: 30 });
  });

  it("changes horizon_days when the horizon segment is clicked", () => {
    setMockFn({ state: "ok", ...payloadWith("treasurydirect") });
    render(<TAUCPane code="TAUC" />);
    fireEvent.click(screen.getByRole("button", { name: "14d" }));
    expect(lastParams?.horizon_days).toBe(14);
  });

  it("switches to recent when the window segment is clicked", () => {
    setMockFn({ state: "ok", ...payloadWith("treasurydirect") });
    render(<TAUCPane code="TAUC" />);
    fireEvent.click(screen.getByRole("button", { name: "Recent" }));
    expect(lastParams?.action).toBe("recent");
  });
});

describe("TAUC pane — type filter chips", () => {
  it("renders one chip per type with counts, plus All", () => {
    setMockFn({ state: "ok", ...payloadWith("treasurydirect") });
    render(<TAUCPane code="TAUC" />);
    expect(screen.getByRole("button", { name: "Bill 2" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Note 1" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "All 3" })).toBeInTheDocument();
  });

  it("filters rows and recomputes totals when a type chip is clicked", () => {
    setMockFn({ state: "ok", ...payloadWith("treasurydirect") });
    const { container } = render(<TAUCPane code="TAUC" />);
    fireEvent.click(screen.getByRole("button", { name: "Bill 2" }));
    // Note row is gone, Bill rows remain.
    expect(container.textContent).not.toContain("10-Year");
    expect(container.textContent).toContain("13-Week");
    expect(container.textContent).toContain("6-Week");
    // Totals recomputed: 2 auctions, $167.0B.
    expect(container.textContent).toContain("2 auctions");
    expect(container.textContent).toContain("$167.0B");
    // Chip is pressed; returning to All restores the full table.
    expect(
      screen.getByRole("button", { name: "Bill 2" }).getAttribute("aria-pressed"),
    ).toBe("true");
    fireEvent.click(screen.getByRole("button", { name: "All 3" }));
    expect(container.textContent).toContain("10-Year");
    expect(container.textContent).toContain("3 auctions");
  });
});

describe("TAUC pane — data honesty", () => {
  it("renders a prominent model note for non-treasurydirect payloads", () => {
    setMockFn({ state: "ok", ...payloadWith("treasury_auction_model") });
    render(<TAUCPane code="TAUC" />);
    expect(screen.getByText(/NOT live TreasuryDirect/i)).toBeInTheDocument();
    expect(screen.getByText(/rows come from the/i)).toBeInTheDocument();
  });

  it("does NOT render the model note for a live payload", () => {
    setMockFn({ state: "ok", ...payloadWith("treasurydirect") });
    render(<TAUCPane code="TAUC" />);
    expect(screen.queryByText(/NOT live TreasuryDirect/i)).toBeNull();
    expect(screen.getByText(/LIVE TREASURYDIRECT/i)).toBeInTheDocument();
  });
});
