/**
 * SRCH pane — data-honesty + render-contract tests.
 *
 * `useFunction` is mocked via a mutable shared state (GEX pattern) so
 * each test drives the pane into a specific branch without the real
 * sidecar transport. Pins:
 *
 *  - the load states (loading / empty / error / ok) render;
 *  - the ok state renders the bond table + matched/scanned note;
 *  - the reference-universe honesty note is present (no live quotes);
 *  - the type chip + yield/duration controls compose the server-side
 *    DSL filter, echoed in the note / footer;
 *  - the empty state offers a working filter reset.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { SRCHPane } from "./SRCH";

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
      sources: ["showme_bond_reference_universe"],
      elapsed_ms: 12,
      data: {
        status: "ok",
        query: "yield >= 0",
        filter: "yield >= 0",
        scanned: 4,
        matched: 4,
        rows: [
          {
            symbol: "US3M",
            issuer: "US Treasury",
            type: "Bill",
            country: "US",
            currency: "USD",
            maturity: "3M",
            tenor_years: 0.25,
            yield: 5.32,
            duration: 0.24,
            rating: "AA+",
          },
          {
            symbol: "DE10Y",
            issuer: "Germany",
            type: "Bund",
            country: "DE",
            currency: "EUR",
            maturity: "10Y",
            tenor_years: 10.0,
            yield: 2.42,
            duration: 8.8,
            rating: "AAA",
          },
          {
            symbol: "GB10Y",
            issuer: "United Kingdom",
            type: "Gilt",
            country: "GB",
            currency: "GBP",
            maturity: "10Y",
            tenor_years: 10.0,
            yield: 4.12,
            duration: 8.4,
            rating: "AA",
          },
          {
            symbol: "JP10Y",
            issuer: "Japan",
            type: "JGB",
            country: "JP",
            currency: "JPY",
            maturity: "10Y",
            tenor_years: 10.0,
            yield: 0.88,
            duration: 9.4,
            rating: "A+",
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

describe("SRCH pane — load states", () => {
  it("renders a skeleton while loading", () => {
    setMockFn({ state: "loading", data: undefined });
    const { container } = render(<SRCHPane code="SRCH" />);
    expect(container.querySelector("[aria-busy='true']")).not.toBeNull();
  });

  it("renders the error state when the fetch errors", () => {
    setMockFn({
      state: "error",
      data: undefined,
      error: new Error("sidecar exploded"),
    });
    render(<SRCHPane code="SRCH" />);
    expect(screen.getByText(/sidecar exploded/i)).toBeInTheDocument();
  });

  it("renders the honest empty state with backend guidance + reset", () => {
    setMockFn({
      state: "ok",
      data: {
        data: {
          status: "empty",
          query: 'type = "Bill" AND yield >= 5',
          rows: [],
          matched: 0,
          scanned: 8,
          reason: "No rows matched filter `type = \"Bill\" AND yield >= 5`.",
          next_actions: ["Broaden the filter or clear it."],
        },
      },
    });
    render(<SRCHPane code="SRCH" />);
    expect(screen.getByText(/No rows matched your filters/i)).toBeInTheDocument();
    expect(screen.getByText(/No rows matched filter/i)).toBeInTheDocument();
    // Type chips stay reachable so the user can recover.
    expect(screen.getByTitle("Bond type ALL")).toBeInTheDocument();
  });

  it("renders the bond table + count note when ok", () => {
    setMockFn({ state: "ok", ...okPayload() });
    render(<SRCHPane code="SRCH" />);
    expect(screen.getByText("US3M")).toBeInTheDocument();
    expect(screen.getByText("Germany")).toBeInTheDocument();
    expect(screen.getByText(/4 of 4 matched/i)).toBeInTheDocument();
    expect(screen.getAllByText(/4 scanned/i).length).toBeGreaterThan(0);
  });
});

describe("SRCH pane — data honesty", () => {
  it("labels the universe as a reference bond universe with no live quotes", () => {
    setMockFn({ state: "ok", ...okPayload() });
    render(<SRCHPane code="SRCH" />);
    expect(
      screen.getByText(/reference bond universe \(no live quotes\)/i),
    ).toBeInTheDocument();
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
    render(<SRCHPane code="SRCH" />);
    expect(screen.getByText(/Filter error/i)).toBeInTheDocument();
    expect(screen.getByText(/unknown columns/i)).toBeInTheDocument();
  });
});

describe("SRCH pane — live yield coverage", () => {
  function livePayload() {
    return {
      data: {
        sources: ["fred_csv", "showme_bond_reference_universe"],
        elapsed_ms: 55,
        data: {
          status: "ok",
          query: "yield >= 0",
          filter: "yield >= 0",
          scanned: 2,
          matched: 2,
          rows: [
            {
              symbol: "US10Y",
              issuer: "US Treasury",
              type: "Note",
              maturity: "10Y",
              tenor_years: 10.0,
              yield: 4.97,
              duration: 8.2,
              rating: "AA+",
              currency: "USD",
              quote_type: "live",
              yield_state: "live",
              yield_source: "fred_csv",
              yield_as_of: "2026-09-14",
              yield_cadence: "daily",
            },
            {
              symbol: "DE2Y",
              issuer: "Germany",
              type: "Bund",
              maturity: "2Y",
              tenor_years: 2.0,
              yield: 2.85,
              duration: 1.9,
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

  it("shows a PARTIAL chip + per-row LIVE/N-A pills for mixed coverage", () => {
    setMockFn({ state: "ok", ...livePayload() });
    render(<SRCHPane code="SRCH" />);
    expect(screen.getByTestId("srch-coverage-pill").textContent).toMatch(
      /PARTIAL 1\/2 LIVE/,
    );
    expect(screen.getByTestId("srch-quote-US10Y").textContent).toMatch(/LIVE/);
    expect(screen.getByTestId("srch-quote-DE2Y").textContent).toMatch(/N\/A/);
    expect(screen.getByText(/live yields 1\/2/i)).toBeInTheDocument();
    expect(
      screen.queryByText(/reference bond universe \(no live quotes\)/i),
    ).toBeNull();
  });

  it("shows a full LIVE chip when every row resolved live", () => {
    const payload = livePayload();
    payload.data.data.rows = [payload.data.data.rows[0]];
    payload.data.data.rows[0].quote_type = "live";
    payload.data.data.scanned = 1;
    payload.data.data.matched = 1;
    setMockFn({ state: "ok", ...payload });
    render(<SRCHPane code="SRCH" />);
    expect(screen.getByTestId("srch-coverage-pill").textContent).toMatch(/LIVE 1/);
    expect(screen.queryByTestId("srch-quote-DE2Y")).toBeNull();
  });

  it("keeps the provider_unavailable outage honest: rows render with N/A pills", () => {
    setMockFn({
      state: "ok",
      data: {
        data: {
          status: "provider_unavailable",
          query: "yield >= 0",
          scanned: 1,
          matched: 1,
          rows: [
            {
              symbol: "US10Y",
              issuer: "US Treasury",
              type: "Note",
              maturity: "10Y",
              tenor_years: 10.0,
              yield: 4.45,
              duration: 8.2,
              rating: "AA+",
              currency: "USD",
              quote_type: "unavailable",
              yield_state: "reference",
            },
          ],
        },
      },
    });
    render(<SRCHPane code="SRCH" />);
    expect(screen.getByText("US10Y")).toBeInTheDocument();
    expect(screen.getByTestId("srch-quote-US10Y").textContent).toMatch(/N\/A/);
    expect(screen.getByTestId("srch-coverage-pill").textContent).toMatch(
      /REFERENCE/,
    );
  });
});

describe("SRCH pane — filter controls compose the server-side query", () => {
  it("composes a type predicate when a chip is clicked", () => {
    setMockFn({ state: "ok", ...okPayload() });
    render(<SRCHPane code="SRCH" />);
    fireEvent.click(screen.getByTitle("Bond type Gilt"));
    expect(screen.getAllByText(/type = "Gilt"/).length).toBeGreaterThan(0);
  });

  it("exposes the expanded bond-type chips", () => {
    // Session-17: the bond universe grew to the full US nominal curve + TIPS
    // + DE/FR/IT/ES/GB/JP 2Y & 10Y; the new instrument types are selectable.
    setMockFn({ state: "ok", ...okPayload() });
    render(<SRCHPane code="SRCH" />);
    expect(screen.getByTitle("Bond type TIPS")).toBeInTheDocument();
    expect(screen.getByTitle("Bond type OAT")).toBeInTheDocument();
    expect(screen.getByTitle("Bond type BTP")).toBeInTheDocument();
    expect(screen.getByTitle("Bond type Bono")).toBeInTheDocument();
  });

  it("composes yield and duration clauses from the segmented controls", () => {
    setMockFn({ state: "ok", ...okPayload() });
    render(<SRCHPane code="SRCH" />);
    fireEvent.click(screen.getByTitle("Min yield 4%"));
    fireEvent.click(screen.getByTitle("Max duration 10y"));
    expect(
      screen.getAllByText(/yield >= 4 AND duration <= 10/).length,
    ).toBeGreaterThan(0);
  });

  it("combines type AND yield clauses, then resets to match-all", () => {
    setMockFn({ state: "ok", ...okPayload() });
    render(<SRCHPane code="SRCH" />);
    fireEvent.click(screen.getByTitle("Bond type Note"));
    fireEvent.click(screen.getByTitle("Min yield 5%"));
    expect(
      screen.getAllByText(/type = "Note" AND yield >= 5/).length,
    ).toBeGreaterThan(0);
    // Reset path: ALL chip clears the type clause.
    fireEvent.click(screen.getByTitle("Bond type ALL"));
    fireEvent.click(screen.getByTitle("Min yield ANY"));
    expect(screen.getAllByText(/yield >= 0/).length).toBeGreaterThan(0);
  });
});
