/**
 * DARK pane — render-contract + data-honesty tests.
 *
 * FINRA ATS off-exchange volume by venue. FINRA is frequently stale or
 * unreachable, so the honesty contract is the core of this pane. Tests
 * pin:
 *
 *  - the four load states (loading / error / no-rows / ok);
 *  - a provider_unavailable payload WITH rows renders them under a
 *    prominent stale banner (honest degradation, no silent fake "live");
 *  - dark_pool_pct renders as "—" when the weekly total never joined;
 *  - the ok state renders the venue table + weekly sparkline;
 *  - the weeks control persists under `showme.dark.weeks`.
 *
 * `useFunction` is mocked via a mutable shared state (GEX pattern).
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { DARKPane } from "./DARK";

/* ── useFunction mock ──────────────────────────────────────────────── */

interface MockFnState {
  state: "idle" | "loading" | "ok" | "error" | "refreshing";
  data?: { data?: unknown; warnings?: string[] } | undefined;
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

function venueRow(venue: string, vol: number, share: number) {
  return {
    venue,
    ats_share_volume: vol,
    ats_trade_count: Math.round(vol / 70),
    share_of_ats_pct: share,
    dark_pool_pct: null,
    weekStartDate: "2026-08-31",
    source_mode: "finra_otc_weekly_ats",
  };
}

function okPayload() {
  const venues = [
    venueRow("HUDA", 34_086_313, 46.2),
    venueRow("MSGS", 22_100_775, 30.0),
    venueRow("UBSA", 17_550_600, 23.8),
  ];
  return {
    warnings: [],
    data: {
      data: {
        status: "ok",
        symbol: "AAPL",
        n_rows: 24,
        total_shares_off_exchange: 5_123_456_789,
        top_venue_share_pct: 46.2,
        venues,
        by_venue: venues,
        rows: venues,
        by_week: [
          { weekStartDate: "2026-08-31", ats_share_volume: 74_000_000, ats_trade_count: 1_050_000, n_venues: 3, total_weekly_volume: 160_000_000, dark_pool_pct: 46.25 },
          { weekStartDate: "2026-08-24", ats_share_volume: 68_500_000, ats_trade_count: 980_000, n_venues: 3, total_weekly_volume: 150_000_000, dark_pool_pct: 45.67 },
        ],
        history: [],
        cards: {
          latest_dark_pool_pct: 46.25,
          latest_ats_volume: 74_000_000,
          venue_count: 3,
          data_mode: "delayed_reference",
          as_of: "2026-08-31",
        },
        summary: { latest_week: "2026-08-31", latest_dark_pool_pct: 46.25, venue_count: 3 },
      },
    },
  };
}

function staleWithRowsPayload() {
  const venues = [venueRow("0", 34_086_313, 100)];
  return {
    warnings: ["FINRA latest week 2025-10-20 is stale for a current market cockpit."],
    data: {
      data: {
        status: "provider_unavailable",
        reason: "FINRA latest week 2025-10-20 is stale for a current market cockpit.",
        symbol: "AAPL",
        n_rows: 8,
        total_shares_off_exchange: 4_671_240_618,
        top_venue_share_pct: 100.0,
        venues,
        by_venue: venues,
        rows: venues,
        by_week: [
          { weekStartDate: "2025-10-20", ats_share_volume: 34_086_313, ats_trade_count: 488_608, n_venues: 1, total_weekly_volume: null, dark_pool_pct: null },
        ],
        history: [],
        cards: {
          latest_dark_pool_pct: null,
          latest_ats_volume: 34_086_313,
          venue_count: 1,
          data_mode: "provider_unavailable",
          as_of: "2025-10-20",
        },
        summary: { latest_week: "2025-10-20", latest_dark_pool_pct: null, venue_count: 1 },
      },
    },
  };
}

function emptyUnavailablePayload() {
  return {
    warnings: ["FINRA endpoint unreachable"],
    data: {
      data: {
        status: "provider_unavailable",
        reason: "FINRA OTC Transparency weekly ATS endpoint returned no rows for AAPL.",
        symbol: "AAPL",
        n_rows: 0,
        total_shares_off_exchange: 0.0,
        top_venue_share_pct: null,
        venues: [],
        by_venue: [],
        rows: [],
        by_week: [],
        history: [],
        next_actions: [
          "Retry once the FINRA OTC Transparency API is reachable.",
          "Confirm the symbol reports off-exchange ATS volume.",
        ],
      },
    },
  };
}

/* ── harness ───────────────────────────────────────────────────────── */

beforeEach(() => {
  localStorage.clear();
  setMockFn({ state: "idle", data: undefined });
});
afterEach(() => {
  cleanup();
  localStorage.clear();
});

describe("DARK pane — load states", () => {
  it("renders a skeleton while loading", () => {
    setMockFn({ state: "loading", data: undefined });
    const { container } = render(<DARKPane code="DARK" symbol="AAPL" />);
    expect(container.querySelector('[aria-busy="true"]')).not.toBeNull();
  });

  it("renders the error state when the fetch errors", () => {
    setMockFn({
      state: "error",
      data: undefined,
      error: new Error("sidecar exploded"),
    });
    render(<DARKPane code="DARK" symbol="AAPL" />);
    expect(screen.getByText(/sidecar exploded/i)).toBeInTheDocument();
  });

  it("renders next_actions (not fake rows) when FINRA returns nothing", () => {
    setMockFn({ state: "ok", ...emptyUnavailablePayload() });
    render(<DARKPane code="DARK" symbol="AAPL" />);
    expect(screen.getByText(/FINRA ATS data unavailable/i)).toBeInTheDocument();
    expect(screen.getByText(/returned no rows/i)).toBeInTheDocument();
    // No venue table rows are fabricated.
    expect(screen.queryByText(/Venue ranking/i)).toBeNull();
  });

  it("renders venue table + sparkline when ok", () => {
    setMockFn({ state: "ok", ...okPayload() });
    const { container } = render(<DARKPane code="DARK" symbol="AAPL" />);
    // Headline cards.
    expect(screen.getByText("5.12B")).toBeInTheDocument();
    expect(screen.getByText("46.25%")).toBeInTheDocument();
    // Venue rows with tint bars.
    expect(screen.getByText("HUDA")).toBeInTheDocument();
    expect(screen.getByText("MSGS")).toBeInTheDocument();
    expect(container.querySelectorAll('td span[aria-hidden]').length).toBeGreaterThan(0);
    // Weekly sparkline.
    const spark = container.querySelector(
      'section[aria-label="Weekly ATS volume history"] svg[role="img"]',
    );
    expect(spark?.getAttribute("aria-label")).toMatch(/ATS share volume/i);
    // No stale banner on a healthy payload.
    expect(screen.queryByText(/PROVIDER DATA STALE/)).toBeNull();
  });
});

describe("DARK pane — data honesty", () => {
  it("renders stale rows only under a prominent stale banner", () => {
    setMockFn({ state: "ok", ...staleWithRowsPayload() });
    render(<DARKPane code="DARK" symbol="AAPL" />);
    // Banner carries the backend reason.
    expect(screen.getByText(/PROVIDER DATA STALE/i)).toBeInTheDocument();
    expect(screen.getByText(/2025-10-20 is stale/i)).toBeInTheDocument();
    // Rows are still visible (honest degradation), inside the venue table.
    expect(screen.getByText("0")).toBeInTheDocument();
    // Dark % of total is an explicit em-dash — the weekly total never joined.
    expect(screen.getByText(/NO WEEKLY TOTAL JOINED/i)).toBeInTheDocument();
  });
});

describe("DARK pane — interactions", () => {
  it("changing the weeks window persists it", () => {
    setMockFn({ state: "ok", ...okPayload() });
    render(<DARKPane code="DARK" symbol="AAPL" />);
    fireEvent.click(screen.getByText("12w"));
    expect(localStorage.getItem("showme.dark.weeks")).toBe("12");
  });
});
