/**
 * SRCH pane — monthly quote type, duration basis and curve-screener labelling
 * (wb1-g08: SRCH#1, SRCH#3, SRCH#4).
 *
 * A monthly OECD observation is dated, not live: it renders MTH and is not
 * counted as LIVE. A live-yield duration is a par-bond model value and says so.
 * The pane is a sovereign curve screener, not an issue-level bond screener.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, render, screen } from "@testing-library/react";
import { SRCHPane } from "./SRCH";

interface MockFnState {
  state: "idle" | "loading" | "ok" | "error" | "refreshing";
  data?: { data?: unknown; sources?: string[]; elapsed_ms?: number } | undefined;
  error?: Error | null;
}

const mockFn: MockFnState = { state: "idle", data: undefined, error: null };

vi.mock("@/lib/useFunction", () => ({
  useFunction: () => ({
    state: mockFn.state,
    data: mockFn.data,
    error: mockFn.error,
    refetch: vi.fn(),
  }),
}));

function payload() {
  return {
    data: {
      sources: ["fred_csv", "showme_bond_reference_universe"],
      elapsed_ms: 40,
      data: {
        status: "ok",
        query: "yield >= 0",
        filter: "yield >= 0",
        scanned: 3,
        matched: 3,
        rows: [
          {
            symbol: "US10Y",
            issuer: "US Treasury",
            type: "Note",
            maturity: "10Y",
            tenor_years: 10.0,
            yield: 4.84,
            duration: 8.14,
            duration_basis: "par_bond_model_from_live_yield",
            duration_curated: 8.2,
            rating: "AA+",
            currency: "USD",
            quote_type: "live",
            yield_state: "live",
            yield_source: "fred_csv",
            yield_as_of: "2026-09-14",
            yield_cadence: "daily",
          },
          {
            symbol: "FR10Y",
            issuer: "France",
            type: "OAT",
            maturity: "10Y",
            tenor_years: 10.0,
            yield: 4.477,
            duration: 8.3,
            duration_basis: "curated_reference",
            rating: "AA",
            currency: "EUR",
            quote_type: "monthly",
            yield_state: "reference",
            yield_source: "fred_csv",
            yield_as_of: "2026-09-01",
            yield_cadence: "monthly",
          },
          {
            symbol: "DE2Y",
            issuer: "Germany",
            type: "Bund",
            maturity: "2Y",
            tenor_years: 2.0,
            yield: 2.85,
            duration: 1.9,
            duration_basis: "curated_reference",
            rating: "AAA",
            currency: "EUR",
            quote_type: "unavailable",
            yield_state: "reference",
          },
        ],
      },
    },
  };
}

beforeEach(() => {
  localStorage.clear();
  mockFn.state = "ok";
  mockFn.data = payload().data;
  mockFn.error = null;
});
afterEach(() => {
  cleanup();
});

describe("SRCH pane — monthly observations and duration basis", () => {
  it("renders a monthly observation as MTH, never LIVE", () => {
    render(<SRCHPane code="SRCH" />);
    expect(screen.getByTestId("srch-quote-FR10Y").textContent).toMatch(/MTH/);
    expect(screen.getByTestId("srch-quote-FR10Y").textContent).not.toMatch(/LIVE/);
    expect(
      screen.getByTitle(/monthly fred_csv observation, as of 2026-09-01/i),
    ).toBeInTheDocument();
  });

  it("counts only the daily live row as LIVE and states the monthly rows separately", () => {
    render(<SRCHPane code="SRCH" />);
    expect(screen.getByTestId("srch-coverage-pill").textContent).toMatch(
      /PARTIAL 1\/3 LIVE/,
    );
    expect(screen.getByText(/1 live yields|live yields 1\/3/i)).toBeInTheDocument();
    expect(screen.getByText(/1 monthly observation\(s\), dated, not live/i)).toBeInTheDocument();
  });

  it("labels a live-yield duration as a par-bond model with the curated value alongside", () => {
    render(<SRCHPane code="SRCH" />);
    const duration = screen.getByTestId("srch-duration-US10Y");
    expect(duration.getAttribute("title")).toMatch(/model: par-bond modified duration/i);
    expect(duration.getAttribute("title")).toMatch(/curated 8\.2y/);
  });

  it("keeps curated durations labelled as curated reference", () => {
    render(<SRCHPane code="SRCH" />);
    expect(screen.getByTestId("srch-duration-FR10Y").getAttribute("title")).toBe(
      "curated reference duration",
    );
  });
});

describe("SRCH pane — curve screener labelling", () => {
  it("titles the pane as a sovereign curve screener, not a bond screener", () => {
    render(<SRCHPane code="SRCH" />);
    expect(screen.getByText("Sovereign Curve Screener")).toBeInTheDocument();
    expect(screen.queryByText("Bond Screener")).toBeNull();
  });
});
