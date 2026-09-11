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
import { FORM4Pane } from "./FORM4";

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
