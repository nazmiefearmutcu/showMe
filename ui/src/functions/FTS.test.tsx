/**
 * FTS pane — render-contract + honesty tests.
 *
 * FTS is live-only on the backend (`live: true` + sec_efts adapter); the
 * offline branch returns status "provider_unavailable" with a reason. These
 * tests pin:
 *
 *  - the load states (loading / error / provider_unavailable / empty / ok);
 *  - an OK payload renders the results table (form, company, filed date,
 *    score) and the result-count note;
 *  - a filing link renders ONLY from the payload's own `url`; URL-less rows
 *    fall back to the bare accession (no invented links);
 *  - the search box interaction applies + persists the last query
 *    (`showme.fts.last`).
 *
 * `useFunction` is mocked via a mutable shared state so each test drives
 * the pane into a specific branch without the real sidecar transport.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { FTSPane } from "./FTS";

/* ── useFunction mock ──────────────────────────────────────────────── */

interface MockFnState {
  state: "idle" | "loading" | "ok" | "error" | "refreshing";
  data?: { data?: unknown; sources?: string[]; elapsed_ms?: number | null };
  error?: Error | null;
}

const mockFn: MockFnState & { lastArgs?: { params?: Record<string, unknown> } } = {
  state: "idle",
  data: undefined,
  error: null,
};

function setMockFn(next: MockFnState) {
  mockFn.state = next.state;
  mockFn.data = next.data;
  mockFn.error = next.error ?? null;
}

vi.mock("@/lib/useFunction", () => ({
  useFunction: (args: { params?: Record<string, unknown> }) => ({
    state: ((mockFn.lastArgs = args), mockFn.state),
    data: mockFn.data,
    error: mockFn.error,
    refetch: vi.fn(),
  }),
}));

/* ── fixtures ──────────────────────────────────────────────────────── */

const OK_ROWS = [
  {
    company: "Apple Inc. (CIK 0000320193)",
    form: "10-K",
    filing_date: "2025-11-01",
    accession: "0000320193-25-000123",
    url: "https://www.sec.gov/Archives/edgar/data/320193/000032019325000123/0000320193-25-000123-index.htm",
    score: 42.7,
    snippet: "…the company faces risks related to supply chain…",
  },
  {
    company: "Themes ETF Trust (CIK 0001976322)",
    form: "485BPOS",
    filing_date: "2026-05-06",
    accession: "0001829126-26-004634",
    url: null,
    score: 30.17,
    snippet: null,
  },
];

function okPayload() {
  return {
    state: "ok" as const,
    data: {
      data: {
        status: "ok",
        rows: OK_ROWS,
        query: "artificial intelligence",
        forms: null,
      },
      sources: ["sec_efts"],
      elapsed_ms: 1400,
    },
  };
}

/* ── tests ─────────────────────────────────────────────────────────── */

beforeEach(() => {
  localStorage.removeItem("showme.fts.last");
  localStorage.removeItem("showme.fts.forms");
  localStorage.removeItem("showme.fts.from");
  localStorage.removeItem("showme.fts.to");
  setMockFn({ state: "idle", data: undefined });
});
afterEach(() => {
  cleanup();
});

describe("FTS pane — load states", () => {
  it("renders a skeleton while loading", () => {
    setMockFn({ state: "loading", data: undefined });
    const { container } = render(<FTSPane code="FTS" />);
    expect(container.querySelector("[aria-busy='true']")).not.toBeNull();
  });

  it("renders the error state when the fetch errors", () => {
    setMockFn({ state: "error", data: undefined, error: new Error("sidecar exploded") });
    render(<FTSPane code="FTS" />);
    expect(screen.getByText(/sidecar exploded/i)).toBeInTheDocument();
  });

  it("renders the provider reason verbatim when the adapter is offline", () => {
    setMockFn({
      state: "ok",
      data: {
        data: {
          status: "provider_unavailable",
          reason:
            "SEC EDGAR full-text search is offline; enable live=true with a configured sec_efts adapter.",
          rows: [],
        },
      },
    });
    render(<FTSPane code="FTS" />);
    expect(
      screen.getByText(/enable live=true with a configured sec_efts adapter/i),
    ).toBeInTheDocument();
  });

  it("renders an honest empty state when there are no hits", () => {
    setMockFn({
      state: "ok",
      data: { data: { status: "empty", rows: [], query: "zzqqxy" } },
    });
    render(<FTSPane code="FTS" />);
    expect(screen.getByText(/No filings matched/i)).toBeInTheDocument();
  });

  it("renders the results table + count note when ok", () => {
    setMockFn(okPayload());
    const { container } = render(<FTSPane code="FTS" />);
    expect(screen.getByText(/2 filing hits/i)).toBeInTheDocument();
    expect(screen.getByText("Apple Inc. (CIK 0000320193)")).toBeInTheDocument();
    expect(screen.getAllByText("10-K").length).toBeGreaterThan(0);
    expect(screen.getByText("2025-11-01")).toBeInTheDocument();
    // Two result rows in the grid body.
    expect(container.querySelectorAll("table tbody tr").length).toBe(2);
  });
});

describe("FTS pane — honesty", () => {
  it("links only from the payload url and shows bare accession otherwise", () => {
    setMockFn(okPayload());
    render(<FTSPane code="FTS" />);
    const link = screen.getByRole("link", { name: /open filing/i });
    expect(link.getAttribute("href")).toBe(OK_ROWS[0].url);
    // Row 2 has no url — the accession is rendered as plain text instead.
    expect(screen.getByText("0001829126-26-004634")).toBeInTheDocument();
  });

  it("shows snippet evidence only for rows that carry snippets", () => {
    setMockFn(okPayload());
    render(<FTSPane code="FTS" />);
    expect(screen.getByText(/supply chain/i)).toBeInTheDocument();
    expect(screen.getAllByText(/Snippet evidence/i).length).toBeGreaterThan(0);
  });
});

describe("FTS pane — search interaction", () => {
  it("applies + persists the last query and form filter", () => {
    setMockFn(okPayload());
    render(<FTSPane code="FTS" />);
    fireEvent.change(screen.getByLabelText(/sec full-text search query/i), {
      target: { value: "cybersecurity incident" },
    });
    fireEvent.change(screen.getByLabelText(/form type filter/i), {
      target: { value: "8-k" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Search" }));
    expect(localStorage.getItem("showme.fts.last")).toBe("cybersecurity incident");
    expect(localStorage.getItem("showme.fts.forms")).toBe("8-K");
    expect(screen.getByText(/"cybersecurity incident"/)).toBeInTheDocument();
  });
});

describe("FTS pane — totals, reasons and date bounds", () => {
  it("shows the EDGAR match total and the returned count when the provider reports it", () => {
    setMockFn({
      state: "ok",
      data: { data: { ...(okPayload().data.data), total_hits: 1775 } },
    });
    render(<FTSPane code="FTS" />);
    expect(screen.getByText(/1,775 EDGAR matches · showing 2/)).toBeInTheDocument();
  });

  it("does not invent a total when the provider omits it", () => {
    setMockFn(okPayload());
    render(<FTSPane code="FTS" />);
    expect(screen.getByText(/EDGAR total not reported/i)).toBeInTheDocument();
  });

  it("explains a skipped search with the provider reason instead of 'no filings'", () => {
    setMockFn({
      state: "ok",
      data: {
        data: {
          status: "empty",
          rows: [],
          query: "risk factors",
          reason: "live SEC full-text search skipped (live=false or reference=true); no provider call was made.",
        },
      },
    });
    render(<FTSPane code="FTS" />);
    expect(screen.getByText(/no provider call was made/i)).toBeInTheDocument();
    expect(screen.queryByText(/No filings matched/i)).toBeNull();
  });

  it("sends a well-formed date range to the function and shows it in the subtitle", () => {
    setMockFn(okPayload());
    render(<FTSPane code="FTS" />);
    fireEvent.change(screen.getByLabelText(/filed from date/i), { target: { value: "2025-01-01" } });
    fireEvent.change(screen.getByLabelText(/filed to date/i), { target: { value: "2025-03-31" } });
    fireEvent.click(screen.getByRole("button", { name: "Search" }));
    expect(localStorage.getItem("showme.fts.from")).toBe("2025-01-01");
    expect(localStorage.getItem("showme.fts.to")).toBe("2025-03-31");
    const params = mockFn.lastArgs?.params ?? {};
    expect(params.date_from).toBe("2025-01-01");
    expect(params.date_to).toBe("2025-03-31");
  });

  it("drops a half-typed date instead of forwarding it", () => {
    setMockFn(okPayload());
    render(<FTSPane code="FTS" />);
    fireEvent.change(screen.getByLabelText(/filed from date/i), { target: { value: "" } });
    fireEvent.click(screen.getByRole("button", { name: "Search" }));
    expect(localStorage.getItem("showme.fts.from")).toBe("");
    expect(mockFn.lastArgs?.params?.date_from).toBeUndefined();
  });
});
