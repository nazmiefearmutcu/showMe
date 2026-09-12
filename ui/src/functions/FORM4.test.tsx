/**
 * FORM4 pane — data-honesty + render-contract tests.
 *
 * Follows the GEX.test.tsx mock pattern: `useFunction` is mocked via a
 * mutable shared state so each test drives the pane into a specific branch
 * without the real sidecar transport.
 *
 * Pins:
 *  - the four load states (loading / empty / error / ok) render;
 *  - a live_official payload shows the live pill, table rows and the
 *    monthly histogram bars;
 *  - filing-metadata-only payloads disclose that shares/prices are not
 *    parsed (no fabricated numbers);
 *  - the WINDOW segmented control is interactive.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import {
  FORM4Pane,
  monthlyNetBuckets,
  recentChronological,
  type MonthlyNetBucket,
} from "./FORM4";

/* ── useFunction mock ──────────────────────────────────────────────── */

interface MockFnState {
  state: "idle" | "loading" | "ok" | "error" | "refreshing";
  data?: { data?: unknown } | undefined;
  error?: Error | null;
  refetch: ReturnType<typeof vi.fn>;
}

const mockFn: MockFnState = {
  state: "idle",
  data: undefined,
  error: null,
  refetch: vi.fn(),
};

function setMockFn(next: Partial<MockFnState>) {
  mockFn.state = next.state ?? "idle";
  mockFn.data = next.data;
  mockFn.error = next.error ?? null;
  if (next.refetch) mockFn.refetch = next.refetch;
}

const mockTick = { current: 0 };
let lastFnArgs: Record<string, unknown> | undefined;

vi.mock("@/lib/useFunction", () => ({
  useFunction: (args: Record<string, unknown>) => {
    lastFnArgs = args;
    return {
      state: mockFn.state,
      data: mockFn.data,
      error: mockFn.error,
      refetch: mockFn.refetch,
    };
  },
}));

vi.mock("@/lib/useVisibilityTick", () => ({
  useVisibilityTick: () => mockTick.current,
}));

vi.mock("@/shell/SymbolBar", () => ({
  SymbolBar: () => null,
}));

/* ── fixtures ──────────────────────────────────────────────────────── */

function livePayload() {
  return {
    data: {
      data: {
        status: "ok",
        data_mode: "live_official",
        symbol: "AAPL",
        n: 3,
        rows: [
          {
            filingDate: "2026-09-03",
            insider: "Tim Cook",
            role: "Chief Executive Officer",
            transaction_type: "sell",
            shares: 1000,
            price: 175.25,
            filing_url: "https://www.sec.gov/Archives/edgar/data/320193/f1.xml",
            source_mode: "yfinance_insider_transactions",
          },
          {
            filingDate: "2026-09-01",
            insider: "Luca Maestri",
            role: "CFO",
            transaction_type: "buy",
            shares: 500,
            price: 170.0,
            filing_url: "https://www.sec.gov/Archives/edgar/data/320193/f2.xml",
            source_mode: "yfinance_insider_transactions",
          },
          {
            filingDate: "2026-08-27",
            insider: null,
            role: null,
            transaction_type: "",
            transaction: "Form 4 filing document",
            shares: null,
            price: null,
            filing_url: "https://www.sec.gov/Archives/edgar/data/320193/f3.xml",
            source_mode: "sec_form4_filing_metadata",
          },
        ],
        filings: [],
        by_month: [
          { month: "2026-09", count: 2 },
          { month: "2026-08", count: 1 },
        ],
        as_of: "2026-09-03T00:00:00+00:00",
      },
    },
  };
}

beforeEach(() => {
  mockTick.current = 0;
  lastFnArgs = undefined;
  setMockFn({ state: "idle", data: undefined, refetch: vi.fn() });
});
afterEach(() => {
  cleanup();
});

describe("FORM4 pane — load states", () => {
  it("renders a skeleton while loading", () => {
    setMockFn({ state: "loading", data: undefined });
    const { container } = render(<FORM4Pane code="FORM4" symbol="AAPL" />);
    expect(container.querySelector('[aria-busy="true"]')).not.toBeNull();
  });

  it("renders the error state with a working Retry", () => {
    const refetch = vi.fn();
    setMockFn({
      state: "error",
      data: undefined,
      error: new Error("sidecar exploded"),
      refetch,
    });
    render(<FORM4Pane code="FORM4" symbol="AAPL" />);
    expect(screen.getByText(/sidecar exploded/i)).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Retry" }));
    expect(refetch).toHaveBeenCalled();
  });

  it("renders the empty state when the provider returns no filings", () => {
    setMockFn({
      state: "ok",
      data: {
        data: {
          status: "provider_unavailable",
          data_mode: "provider_unavailable",
          rows: [],
          by_month: [],
        },
      },
    });
    render(<FORM4Pane code="FORM4" symbol="AAPL" />);
    expect(screen.getByText(/No Form 4 filings returned/i)).toBeInTheDocument();
  });
});

describe("FORM4 pane — live payload", () => {
  it("renders the data_mode pill, table rows and histogram bars", () => {
    setMockFn({ state: "ok", ...livePayload() });
    const { container } = render(<FORM4Pane code="FORM4" symbol="AAPL" />);
    // Live-official pill.
    expect(screen.getByText("live_official")).toBeInTheDocument();
    // Insider rows render.
    expect(screen.getByText("Tim Cook")).toBeInTheDocument();
    expect(screen.getByText("Luca Maestri")).toBeInTheDocument();
    // Formatted shares/price from the payload (not invented).
    expect(screen.getByText("1,000")).toBeInTheDocument();
    expect(screen.getByText("175.25")).toBeInTheDocument();
    // Histogram: one bar group per by_month bucket.
    expect(container.querySelectorAll("rect").length).toBe(2);
    // SEC links only for absolute URLs.
    expect(screen.getAllByLabelText(/Open SEC primary document/i).length).toBe(
      3,
    );
  });

  it("discloses filing-metadata-only payloads instead of faking values", () => {
    setMockFn({
      state: "ok",
      data: {
        data: {
          status: "ok",
          data_mode: "live_official",
          symbol: "AAPL",
          rows: [
            {
              filingDate: "2026-09-03",
              insider: null,
              role: null,
              transaction_type: "",
              transaction: "Form 4 filing document",
              shares: null,
              price: null,
              filing_url: "xslF345X06/form4.xml",
              source_mode: "sec_form4_filing_metadata",
            },
          ],
          by_month: [{ month: "2026-09", count: 1 }],
        },
      },
    });
    const { container } = render(<FORM4Pane code="FORM4" symbol="AAPL" />);
    // Inline honesty note is present.
    expect(
      screen.getByText(/Filing metadata only/i),
    ).toBeInTheDocument();
    // Missing numbers render as em-dash, never a fabricated value.
    expect(container.textContent).toContain("—");
    // Relative URL stub is NOT rendered as a SEC link.
    expect(
      screen.queryByLabelText(/Open SEC primary document/i),
    ).toBeNull();
  });
});

describe("FORM4 pane — controls", () => {
  it("switches the WINDOW segmented control on click", () => {
    setMockFn({ state: "ok", ...livePayload() });
    render(<FORM4Pane code="FORM4" symbol="AAPL" />);
    const m12 = screen.getByRole("button", { name: "12m" });
    expect(m12).not.toBeDisabled();
    fireEvent.click(m12);
    // The newly selected option becomes the active (disabled) one.
    expect(screen.getByRole("button", { name: "12m" })).toBeDisabled();
  });
});

describe("FORM4 pane — filings grid sorting (audit A3 M)", () => {
  it("sorts newest-first by default and enables keyboard grid navigation", () => {
    const payload = livePayload();
    // Reverse the fixture so only the built-in sorter can put 09-03 first.
    payload.data.data.rows = [...payload.data.data.rows].reverse();
    setMockFn({ state: "ok", ...payload });
    render(<FORM4Pane code="FORM4" symbol="AAPL" />);
    // keyboardNavigable upgrades the table to a keyboard grid.
    const grid = screen.getByRole("grid");
    // Scope to the filings grid: the monthly net table is also a <table>.
    const rows = Array.from(grid.querySelectorAll("tbody tr"));
    expect(rows[0]?.textContent).toContain("2026-09-03");
    expect(rows.at(-1)?.textContent).toContain("2026-08-27");
  });
});

describe("FORM4 pane — visibility poll (live adoption)", () => {
  it("refetches on a visibility tick but not on mount", () => {
    const refetch = vi.fn();
    setMockFn({ state: "ok", ...livePayload(), refetch });
    const { rerender } = render(<FORM4Pane code="FORM4" symbol="AAPL" />);
    expect(refetch).not.toHaveBeenCalled();

    mockTick.current = 1;
    rerender(<FORM4Pane code="FORM4" symbol="AAPL" />);
    expect(refetch).toHaveBeenCalledTimes(1);
  });

  it("keeps the window params stable across ticks (no tick key)", () => {
    setMockFn({ state: "ok", ...livePayload() });
    const { rerender } = render(<FORM4Pane code="FORM4" symbol="AAPL" />);
    const before = JSON.stringify(lastFnArgs?.params ?? null);
    expect(before).not.toContain("tick");

    mockTick.current = 4;
    rerender(<FORM4Pane code="FORM4" symbol="AAPL" />);
    expect(JSON.stringify(lastFnArgs?.params ?? null)).toBe(before);
  });
});

describe("FORM4 pane — new filings badge (live adoption)", () => {
  it("shows no badge on the first payload, then +N when the count grows", () => {
    setMockFn({ state: "ok", ...livePayload() });
    const { rerender } = render(<FORM4Pane code="FORM4" symbol="AAPL" />);
    expect(screen.queryByTestId("form4-new-filings")).toBeNull();

    const grown = livePayload();
    grown.data.data.n = 5;
    setMockFn({ state: "ok", ...grown });
    mockTick.current = 1;
    rerender(<FORM4Pane code="FORM4" symbol="AAPL" />);
    const badge = screen.getByTestId("form4-new-filings");
    expect(badge.textContent).toMatch(/\+2 new filings since last poll/);
    expect(badge.getAttribute("aria-live")).toBe("polite");
  });

  it("re-baselines on a WINDOW change instead of reporting phantom new filings", () => {
    setMockFn({ state: "ok", ...livePayload() });
    render(<FORM4Pane code="FORM4" symbol="AAPL" />);

    const bigger = livePayload();
    bigger.data.data.n = 9;
    setMockFn({ state: "ok", ...bigger });
    fireEvent.click(screen.getByRole("button", { name: "12m" }));
    // New (symbol, window) key → the count difference is a window artefact.
    expect(screen.queryByTestId("form4-new-filings")).toBeNull();
  });
});

/* ── monthly net insider flow (audit A3 OPP) ────────────────────────── */

const NET_BY_MONTH = [
  { month: "2026-09", count: 2 },
  { month: "2026-08", count: 2 },
  { month: "2026-07", count: 1 },
  { month: "2026-06", count: 2 },
  { month: "2026-05", count: 0 },
];

const NET_ROWS = [
  // 2026-09: buy 500×170 = 85,000; sell 1,000×175.25 = 175,250 → net −90,250.
  { filingDate: "2026-09-03", transaction_type: "sell", shares: 1000, price: 175.25 },
  { filingDate: "2026-09-02", transaction_type: "grant", shares: 10, price: 100 },
  { filingDate: "2026-09-01", transaction_type: "buy", shares: 500, price: 170 },
  // 2026-08: reported `value` + `shares × price` fallback; no sells → +44,000.
  { filingDate: "2026-08-27", transaction_type: "buy", value: 30000 },
  { filingDate: "2026-08-20", side: "buy", shares: 100, price: 140 },
  // 2026-07: metadata only (no direction, no numbers) → unresolved.
  {
    filingDate: "2026-07-15",
    transaction_type: "",
    side: "",
    shares: null,
    price: null,
    value: null,
  },
  // 2026-06: buy is known but the sell has no size → NO partial sum, em-dash.
  { filingDate: "2026-06-10", transaction_type: "buy", shares: 100, price: 10 },
  { filingDate: "2026-06-02", transaction_type: "sell", shares: 50, price: null },
  // 2026-05: no rows at all → unresolved.
];

describe("FORM4 pane — monthly net flow math (audit A3 OPP)", () => {
  const buckets = monthlyNetBuckets(NET_BY_MONTH, NET_ROWS);

  it("computes buys − sells in USD per mixed month (value + shares×price)", () => {
    const sep = buckets.find((b) => b.month === "2026-09") as MonthlyNetBucket;
    expect(sep.resolved).toBe(true);
    expect(sep.buy).toBeCloseTo(85000, 6);
    expect(sep.sell).toBeCloseTo(175250, 6);
    expect(sep.net).toBeCloseTo(-90250, 6);

    const aug = buckets.find((b) => b.month === "2026-08") as MonthlyNetBucket;
    expect(aug.buy).toBeCloseTo(44000, 6);
    expect(aug.sell).toBe(0);
    expect(aug.net).toBeCloseTo(44000, 6);
  });

  it("ignores grants and never returns a partial sum when a side lacks values", () => {
    // The 2026-06 buy would sum to 1,000 — but the sell has no notional, so
    // the honest result is null (em-dash), not a one-sided understatement.
    const jun = buckets.find((b) => b.month === "2026-06") as MonthlyNetBucket;
    expect(jun.resolved).toBe(false);
    expect(jun.net).toBeNull();
    expect(jun.buy).toBeNull();
    expect(jun.sell).toBeNull();
    expect(jun.missing).toBe(1);
  });

  it("marks months with no directional rows (metadata-only) unresolved", () => {
    const jul = buckets.find((b) => b.month === "2026-07") as MonthlyNetBucket;
    const may = buckets.find((b) => b.month === "2026-05") as MonthlyNetBucket;
    expect(jul.net).toBeNull();
    expect(jul.missing).toBe(0);
    expect(may.net).toBeNull();
    expect(may.resolved).toBe(false);
  });

  it("keeps the newest 12 buckets in oldest-left chronological order", () => {
    const months = [
      ...Array.from({ length: 12 }, (_, i) => ({
        month: `2026-${String(i + 1).padStart(2, "0")}`,
        count: i,
      })),
      { month: "2027-01", count: 12 },
      { month: "2027-02", count: 13 },
    ];
    const recent = recentChronological(months);
    expect(recent).toHaveLength(12);
    // Oldest two (2026-01/02) drop off; the rest are ascending by month.
    expect(recent[0].month).toBe("2026-03");
    expect(recent.at(-1)?.month).toBe("2027-02");
    expect(recent.map((m) => m.month)).toEqual(
      [...recent.map((m) => m.month)].sort(),
    );
  });
});

describe("FORM4 pane — monthly net flow render", () => {
  function netPayload() {
    return {
      data: {
        data: {
          status: "ok",
          data_mode: "delayed_reference",
          symbol: "AAPL",
          n: NET_ROWS.length,
          rows: NET_ROWS,
          filings: [],
          by_month: NET_BY_MONTH,
          as_of: "2026-09-03T00:00:00+00:00",
        },
      },
    };
  }

  it("renders the NET column with honest signs and a signed bar per resolved month", () => {
    setMockFn({ state: "ok", ...netPayload() });
    const { container } = render(<FORM4Pane code="FORM4" symbol="AAPL" />);
    // Column labels.
    for (const label of ["Month", "Buy", "Sell", "Net"]) {
      expect(screen.getByRole("columnheader", { name: label })).toBeInTheDocument();
    }
    // Negative month carries the sign-first compact value.
    const sep = container.querySelector(
      '[data-testid="form4-net-row"][data-net="-90250"]',
    );
    expect(sep).not.toBeNull();
    expect(sep?.textContent).toContain("-$90.3K");
    expect(sep?.textContent).toContain("$175.3K");
    // Positive month renders the + sign.
    const aug = container.querySelector(
      '[data-testid="form4-net-row"][data-net="44000"]',
    );
    expect(aug?.textContent).toContain("+$44K");
    // Unresolved months: em-dash, no bar, no fabricated partial sum.
    const jul = container.querySelector(
      '[data-testid="form4-net-row"][data-net="na"]',
    );
    expect(jul?.textContent).toContain("—");
    // Bars: exactly the two resolved months (SEP + AUG).
    expect(screen.getAllByTestId("form4-net-bar")).toHaveLength(2);
  });

  it("stays all em-dash (no bars) for a metadata-only feed", () => {
    setMockFn({
      state: "ok",
      data: {
        data: {
          status: "ok",
          data_mode: "live_official",
          symbol: "AAPL",
          n: 2,
          rows: [
            {
              filingDate: "2026-09-10",
              transaction_type: "",
              transaction: "Form 4 filing document",
              shares: null,
              value: null,
              price: null,
              source_mode: "sec_form4_filing_metadata",
            },
          ],
          filings: [],
          by_month: [{ month: "2026-09", count: 1 }],
        },
      },
    });
    const { container } = render(<FORM4Pane code="FORM4" symbol="AAPL" />);
    const row = container.querySelector('[data-testid="form4-net-row"]');
    expect(row?.getAttribute("data-net")).toBe("na");
    expect(row?.textContent).toContain("—");
    expect(screen.queryAllByTestId("form4-net-bar")).toHaveLength(0);
    // The existing honesty disclosure is still present.
    expect(screen.getByText(/Filing metadata only/i)).toBeInTheDocument();
  });
});
