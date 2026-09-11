/**
 * PIB pane — load states, section map, form-filter interaction + honesty.
 *
 * The backend PIB combines recent SEC EDGAR filing rows with a public-info
 * section map (profile / financials / filings / holders / news, each stamped
 * with availability and the ShowMe function that serves it). When the EDGAR
 * feed returns nothing it reports status "provider_unavailable" with a
 * reason; these tests pin that the pane shows that reason instead of a
 * fabricated book, and that the FORM chips actually filter the table.
 *
 * `useFunction` is mocked via a mutable shared state so each test drives
 * the pane into a specific branch without the real sidecar transport.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, render, screen, fireEvent } from "@testing-library/react";
import { PIBPane } from "./PIB";

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

// SymbolBar pulls router/symbol-resolver side effects we don't need here.
vi.mock("@/shell/SymbolBar", () => ({
  SymbolBar: () => null,
}));

/* ── fixtures ──────────────────────────────────────────────────────── */

function okPayload() {
  return {
    data: {
      sources: ["sec_edgar"],
      elapsed_ms: 42,
      data: {
        status: "ok",
        rows: [
          {
            symbol: "AAPL",
            section: "filing",
            form: "4",
            filingDate: "2026-09-03",
            reportDate: "2026-09-01",
            accession: "0001140361-26-035636",
            url: "https://www.sec.gov/Archives/edgar/data/320193/000114036126035636/xslF345X06/form4.xml",
            source_mode: "sec_edgar_filing_metadata",
          },
          {
            symbol: "AAPL",
            section: "filing",
            form: "10-Q",
            filingDate: "2026-07-31",
            reportDate: "2026-06-27",
            accession: "0000320193-26-000020",
            // EDGAR primaryDocument arrives as a RELATIVE stub — must never
            // be rendered as an <a>.
            url: "xslF345X06/form4.xml",
            source_mode: "sec_edgar_filing_metadata",
          },
          {
            symbol: "AAPL",
            section: "filing",
            form: "8-K",
            filingDate: "2026-07-30",
            reportDate: "2026-07-30",
            accession: "0000320193-26-000018",
            source_mode: "sec_edgar_filing_metadata",
          },
        ],
        sections: [
          { section: "profile", status: "available_via_DES", function: "DES" },
          { section: "filings", status: "included", count: 3 },
          { section: "holders", status: "available_via_HDS", function: "HDS" },
        ],
        methodology: "PIB is a public information book index.",
      },
    },
  };
}

function providerDownPayload() {
  return {
    data: {
      sources: ["pib_model"],
      elapsed_ms: 5,
      data: {
        status: "provider_unavailable",
        reason: "SEC filing feed returned no rows.",
        rows: [
          {
            symbol: "AAPL",
            section: "filing",
            form: null,
            filingDate: null,
            source_mode: "sec_edgar_unavailable",
          },
        ],
      },
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
  localStorage.clear();
});

describe("PIB pane — load states", () => {
  it("renders a skeleton while loading", () => {
    setMockFn({ state: "loading", data: undefined });
    const { container } = render(<PIBPane code="PIB" symbol="AAPL" />);
    expect(container.querySelector('[aria-busy="true"]')).not.toBeNull();
  });

  it("renders the error state when the fetch errors", () => {
    setMockFn({
      state: "error",
      data: undefined,
      error: new Error("sidecar exploded"),
    });
    render(<PIBPane code="PIB" symbol="AAPL" />);
    expect(screen.getByText(/sidecar exploded/i)).toBeInTheDocument();
  });

  it("renders the honest provider-unavailable state with the backend reason", () => {
    setMockFn({ state: "ok", ...providerDownPayload() });
    render(<PIBPane code="PIB" symbol="AAPL" />);
    expect(
      screen.getByText(/Public information book unavailable/i),
    ).toBeInTheDocument();
    expect(
      screen.getByText(/SEC filing feed returned no rows/i),
    ).toBeInTheDocument();
  });

  it("distinguishes an empty healthy feed from a provider outage (audit A3 L)", () => {
    setMockFn({
      state: "ok",
      data: { sources: ["sec_edgar"], data: { status: "ok", rows: [], sections: [] } },
    });
    render(<PIBPane code="PIB" symbol="AAPL" />);
    expect(screen.getByText(/No filings returned/i)).toBeInTheDocument();
    expect(screen.queryByText(/book unavailable/i)).toBeNull();
  });
});

describe("PIB pane — section map + filings table", () => {
  it("renders the section map with delegation stamps", () => {
    setMockFn({ state: "ok", ...okPayload() });
    render(<PIBPane code="PIB" symbol="AAPL" />);
    expect(screen.getByText("PROFILE")).toBeInTheDocument();
    expect(screen.getByText("HOLDERS")).toBeInTheDocument();
    expect(screen.getByText(/via HDS/i)).toBeInTheDocument();
    expect(screen.getByText(/available_via_DES/i)).toBeInTheDocument();
  });

  it("renders filing rows with accession + source stamps", () => {
    setMockFn({ state: "ok", ...okPayload() });
    const { container } = render(<PIBPane code="PIB" symbol="AAPL" />);
    expect(container.textContent).toContain("0001140361-26-035636");
    expect(container.textContent).toContain("0000320193-26-000020");
    expect(container.textContent).toContain("sec_edgar_filing_metadata");
  });

  it("sorts filings newest-first by default and is keyboard navigable (audit A3 M)", () => {
    const payload = okPayload();
    // Reverse the fixture so only the built-in sorter can put 09-03 first.
    payload.data.data.rows = [...payload.data.data.rows].reverse();
    setMockFn({ state: "ok", ...payload });
    const { container } = render(<PIBPane code="PIB" symbol="AAPL" />);
    expect(screen.getByRole("grid")).toBeInTheDocument();
    const firstRow = container.querySelector("tbody tr");
    expect(firstRow?.textContent).toContain("2026-09-03");
  });
});

describe("PIB pane — filing links (audit A3 OPP)", () => {
  it("renders the payload url as a safe SEC link and refuses relative stubs", () => {
    setMockFn({ state: "ok", ...okPayload() });
    render(<PIBPane code="PIB" symbol="AAPL" />);
    // Exactly one absolute URL exists in the fixture; the relative stub and
    // the url-less row must stay unlinked (FORM4 absolute-URL guard).
    const links = screen.getAllByRole("link");
    expect(links).toHaveLength(1);
    expect(links[0]).toHaveAttribute(
      "href",
      "https://www.sec.gov/Archives/edgar/data/320193/000114036126035636/xslF345X06/form4.xml",
    );
    expect(links[0]).toHaveAttribute("target", "_blank");
    expect(links[0]).toHaveAttribute("rel", "noopener noreferrer");
    expect(links[0]).toHaveTextContent("SEC ↗");
  });
});

describe("PIB pane — form filter interaction", () => {
  it("filters the table to 8-K rows when the 8-K chip is active", () => {
    setMockFn({ state: "ok", ...okPayload() });
    const { container } = render(<PIBPane code="PIB" symbol="AAPL" />);

    // The FORM segmented control carries a descriptive aria-label; the plain
    // "8-K" string also appears in table pills, so scope the query.
    const formGroup = container.querySelector('[aria-label="Filing form filter"]');
    expect(formGroup).not.toBeNull();
    const chip = Array.from(formGroup!.querySelectorAll("button")).find(
      (b) => b.textContent === "8-K",
    );
    expect(chip).toBeDefined();
    fireEvent.click(chip!);

    const table = container.querySelector('[aria-label="PIB filings table"]');
    expect(table?.textContent).toContain("0000320193-26-000018");
    expect(table?.textContent).not.toContain("0001140361-26-035636");
    expect(table?.textContent).not.toContain("0000320193-26-000020");
  });

  it("filters the table to insider forms when the INSIDER chip is active", () => {
    setMockFn({ state: "ok", ...okPayload() });
    const { container } = render(<PIBPane code="PIB" symbol="AAPL" />);

    const formGroup = container.querySelector('[aria-label="Filing form filter"]');
    const chip = Array.from(formGroup!.querySelectorAll("button")).find(
      (b) => b.textContent === "INSIDER",
    );
    fireEvent.click(chip!);

    const table = container.querySelector('[aria-label="PIB filings table"]');
    expect(table?.textContent).toContain("0001140361-26-035636");
    expect(table?.textContent).not.toContain("0000320193-26-000018");
  });
});
