/**
 * FSRC pane — data-honesty + render-contract tests.
 *
 * `useFunction` is mocked via a mutable shared state (GEX pattern) so
 * each test drives the pane into a specific branch without the real
 * sidecar transport. Pins:
 *
 *  - the load states (loading / empty / error / ok) render;
 *  - the ok state renders the fund table + matched/scanned note;
 *  - live vs reference quote honesty (reference rows show no price);
 *  - the category chip + max-expense controls compose the server-side
 *    DSL filter, echoed in the note / footer;
 *  - the empty state offers a working filter reset.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { FSRCPane } from "./FSRC";
import { downloadGridCsv } from "@/design-system/grid-csv";

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

// Keep the real CSV builder, but capture the download call so the export
// payload can be asserted (jsdom has no Blob download).
vi.mock("@/design-system/grid-csv", async (importOriginal) => {
  const actual =
    await importOriginal<typeof import("@/design-system/grid-csv")>();
  return { ...actual, downloadGridCsv: vi.fn(() => true) };
});

/* ── fixtures ──────────────────────────────────────────────────────── */

function okPayload() {
  return {
    data: {
      sources: ["yfinance", "showme_fund_reference_universe"],
      elapsed_ms: 380,
      data: {
        status: "ok",
        query: "aum_usd >= 0",
        filter: "aum_usd >= 0",
        scanned: 3,
        matched: 3,
        rows: [
          {
            symbol: "SPY",
            name: "SPDR S&P 500 ETF Trust",
            issuer: "State Street",
            category: "US Large Blend",
            aum_usd: 500000000000,
            expenseRatio: 0.000945,
            ytd_return_pct: 8.6,
            dividend_yield: 0.012,
            last: 770.19,
            change_pct: -0.385,
            quote_state: "live",
          },
          {
            symbol: "QQQ",
            name: "Invesco QQQ Trust",
            issuer: "Invesco",
            category: "US Large Growth",
            aum_usd: 250000000000,
            expenseRatio: 0.002,
            ytd_return_pct: 10.4,
            dividend_yield: 0.006,
            last: 512.4,
            change_pct: 0.9,
            quote_state: "live",
          },
          {
            symbol: "EEM",
            name: "iShares MSCI Emerging Markets ETF",
            issuer: "BlackRock",
            category: "Emerging Markets",
            aum_usd: 20000000000,
            expenseRatio: 0.0068,
            ytd_return_pct: 5.2,
            dividend_yield: 0.021,
            last: null,
            change_pct: null,
            quote_state: "reference",
          },
        ],
        next_actions: [],
      },
    },
  };
}

beforeEach(() => {
  setMockFn({ state: "idle", data: undefined });
  (downloadGridCsv as ReturnType<typeof vi.fn>).mockClear();
});

afterEach(() => {
  cleanup();
  window.localStorage.clear();
});

describe("FSRC pane — load states", () => {
  it("renders a skeleton while loading", () => {
    setMockFn({ state: "loading", data: undefined });
    const { container } = render(<FSRCPane code="FSRC" />);
    expect(container.querySelector("[aria-busy='true']")).not.toBeNull();
  });

  it("renders the error state when the fetch errors", () => {
    setMockFn({
      state: "error",
      data: undefined,
      error: new Error("sidecar exploded"),
    });
    render(<FSRCPane code="FSRC" />);
    expect(screen.getByText(/sidecar exploded/i)).toBeInTheDocument();
  });

  it("renders the honest empty state with backend guidance + reset", () => {
    setMockFn({
      state: "ok",
      data: {
        data: {
          status: "empty",
          query: 'category = "High Yield Bond" AND expenseRatio <= 0.001',
          rows: [],
          matched: 0,
          scanned: 10,
          reason: "No rows matched filter `category = \"High Yield Bond\"…`.",
          next_actions: ["Broaden the filter or clear it."],
        },
      },
    });
    render(<FSRCPane code="FSRC" />);
    expect(screen.getByText(/No rows matched your filters/i)).toBeInTheDocument();
    expect(screen.getByText(/No rows matched filter/i)).toBeInTheDocument();
    // The category chips stay reachable so the user can recover.
    expect(screen.getByTitle("Category ALL")).toBeInTheDocument();
  });

  it("renders the fund table + count note when ok", () => {
    setMockFn({ state: "ok", ...okPayload() });
    render(<FSRCPane code="FSRC" />);
    expect(screen.getByText("SPY")).toBeInTheDocument();
    expect(screen.getByText("Invesco QQQ Trust")).toBeInTheDocument();
    expect(screen.getByText(/3 of 3 matched/i)).toBeInTheDocument();
    expect(screen.getAllByText(/3 scanned/i).length).toBeGreaterThan(0);
  });
});

describe("FSRC pane — data honesty", () => {
  it("labels provider-answered rows live and unanswered rows reference", () => {
    setMockFn({ state: "ok", ...okPayload() });
    render(<FSRCPane code="FSRC" />);
    const livePills = screen.getAllByText("live");
    expect(livePills.length).toBe(2);
    expect(screen.getByText("reference")).toBeInTheDocument();
    // The reference row shows the missing-value dash for Last, never a
    // fabricated price.
    expect(screen.getByText(/1 reference row/)).toBeInTheDocument();
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
    render(<FSRCPane code="FSRC" />);
    expect(screen.getByText(/Filter error/i)).toBeInTheDocument();
    expect(screen.getByText(/unknown columns/i)).toBeInTheDocument();
  });
});

describe("FSRC pane — filter controls compose the server-side query", () => {
  it("composes a category predicate when a chip is clicked", () => {
    setMockFn({ state: "ok", ...okPayload() });
    render(<FSRCPane code="FSRC" />);
    fireEvent.click(screen.getByTitle("Category US Large Growth"));
    expect(
      screen.getAllByText(/category = "US Large Growth"/).length,
    ).toBeGreaterThan(0);
  });

  it("composes the expense clause when a max-expense option is selected", () => {
    setMockFn({ state: "ok", ...okPayload() });
    render(<FSRCPane code="FSRC" />);
    fireEvent.click(screen.getByTitle("Expense max 0.20%"));
    expect(
      screen.getAllByText(/expenseRatio <= 0.002/).length,
    ).toBeGreaterThan(0);
  });

  it("exposes the expanded fund-category chips", () => {
    // Session-17: the backend fund universe grew to 60+ vehicles across 19
    // categories; every category must stay chip-selectable.
    setMockFn({ state: "ok", ...okPayload() });
    render(<FSRCPane code="FSRC" />);
    expect(screen.getByTitle("Category TIPS")).toBeInTheDocument();
    expect(screen.getByTitle("Category International Developed")).toBeInTheDocument();
    expect(screen.getByTitle("Category Closed-End Fund")).toBeInTheDocument();
    expect(screen.getByTitle("Category Aggregate Bond")).toBeInTheDocument();
  });

  it("combines category AND expense clauses, then resets to match-all", () => {
    setMockFn({ state: "ok", ...okPayload() });
    render(<FSRCPane code="FSRC" />);
    fireEvent.click(screen.getByTitle("Category Emerging Markets"));
    fireEvent.click(screen.getByTitle("Expense max 0.50%"));
    expect(
      screen.getAllByText(/category = "Emerging Markets" AND expenseRatio <= 0.005/)
        .length,
    ).toBeGreaterThan(0);
    // Reset path: ALL chip clears the category clause.
    fireEvent.click(screen.getByTitle("Category ALL"));
    fireEvent.click(screen.getByTitle("Expense ANY"));
    expect(screen.getAllByText(/aum_usd >= 0/).length).toBeGreaterThan(0);
  });
});

describe("FSRC pane — grid CSV export", () => {
  it("exports the raw screener rows via the CSV button", () => {
    setMockFn({ state: "ok", ...okPayload() });
    render(<FSRCPane code="FSRC" />);
    const btn = screen.getByTitle("Download CSV");
    expect(btn).not.toBeDisabled();
    fireEvent.click(btn);
    const mock = downloadGridCsv as ReturnType<typeof vi.fn>;
    expect(mock).toHaveBeenCalledTimes(1);
    const [filename, csv] = mock.mock.calls[0] as [string, string];
    expect(filename).toMatch(/^fsrc-funds-\d{4}-\d{2}-\d{2}\.csv$/);
    expect(csv).toContain(
      "Symbol,Fund,Issuer,Category,AUM (USD),Expense ratio,YTD %,Dividend yield,Last,Change %,Source",
    );
    // RAW numbers: expense ratio stays 0.000945, AUM stays 500000000000.
    expect(csv).toContain(
      "SPY,SPDR S&P 500 ETF Trust,State Street,US Large Blend,500000000000,0.000945,8.6,0.012,770.19,-0.385,live",
    );
    // The reference row keeps its empty last/change cells (no fake price).
    expect(csv).toContain("EEM,iShares MSCI Emerging Markets ETF,BlackRock,Emerging Markets,20000000000,0.0068,5.2,0.021,,,reference");
  });

  it("disables the CSV button when no rows matched", () => {
    setMockFn({
      state: "ok",
      data: {
        data: {
          status: "empty",
          query: "aum_usd >= 0",
          rows: [],
          matched: 0,
          scanned: 10,
        },
      },
    });
    render(<FSRCPane code="FSRC" />);
    expect(screen.getByTitle("Download CSV")).toBeDisabled();
    expect(downloadGridCsv).not.toHaveBeenCalled();
  });
});
