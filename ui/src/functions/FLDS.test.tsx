/**
 * FLDS pane — render-contract + interaction tests.
 *
 * FLDS is a LOCAL field-catalog lookup (the backend says so explicitly),
 * so the pane must never present the rows as live market data. These
 * tests pin:
 *
 *  - the load states (loading / error / ok / empty);
 *  - the "not live market data" scope note is present on ok;
 *  - the category filter narrows rows client-side;
 *  - committing the search box updates the footer query + persists it;
 *  - the catalog pill reads "catalog", never "live".
 *
 * `useFunction` is mocked via mutable shared state (GEX pattern).
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { FLDSPane } from "./FLDS";

/* ── useFunction mock ──────────────────────────────────────────────── */

interface MockFnState {
  state: "idle" | "loading" | "ok" | "error" | "refreshing";
  data?: { data?: unknown } | undefined;
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

const catalogRows = [
  {
    field: "pe",
    category: "valuation",
    description: "Trailing P/E",
    example: "EQS query: pe < 30 AND market_cap > 50000000000",
  },
  {
    field: "fwd_pe",
    category: "valuation",
    description: "Forward P/E",
    example: "EQS query: pe < 30 AND market_cap > 50000000000",
  },
  {
    field: "open",
    category: "market",
    description: "Session open",
    example: "get(close, volume) for(['AAPL']) by(date)",
  },
];

function okPayload() {
  return {
    data: {
      data: {
        status: "ok",
        rows: catalogRows,
        summary: {
          query: "pe",
          matched: 3,
          shown: 3,
          catalog_fields: 35,
        },
        methodology: "FLDS searches the local ShowMe field catalog.",
      },
      sources: ["showme_field_catalog"],
      elapsed_ms: 0.07,
    },
  };
}

beforeEach(() => {
  localStorage.clear();
  setMockFn({ state: "idle", data: undefined });
});
afterEach(() => {
  cleanup();
});

describe("FLDS pane — load states", () => {
  it("renders a skeleton while loading", () => {
    setMockFn({ state: "loading", data: undefined });
    const { container } = render(<FLDSPane code="FLDS" />);
    expect(container.querySelector('[aria-busy="true"]')).not.toBeNull();
  });

  it("renders the error state when the fetch errors", () => {
    setMockFn({
      state: "error",
      data: undefined,
      error: new Error("sidecar exploded"),
    });
    render(<FLDSPane code="FLDS" />);
    expect(screen.getByText(/sidecar exploded/i)).toBeInTheDocument();
  });

  it("renders the empty state when nothing matches", () => {
    setMockFn({
      state: "ok",
      data: {
        data: {
          status: "ok",
          rows: [],
          summary: { query: "zzz", matched: 0, shown: 0, catalog_fields: 35 },
        },
      },
    });
    render(<FLDSPane code="FLDS" />);
    expect(screen.getByText(/No fields match/i)).toBeInTheDocument();
  });

  it("renders catalog rows when ok", () => {
    setMockFn({ state: "ok", ...okPayload() });
    const { container } = render(<FLDSPane code="FLDS" />);
    expect(container.textContent).toContain("fwd_pe");
    expect(container.textContent).toContain("Trailing P/E");
  });
});

describe("FLDS pane — honesty", () => {
  it("labels the pane as a catalog lookup, never live market data", () => {
    setMockFn({ state: "ok", ...okPayload() });
    render(<FLDSPane code="FLDS" />);
    expect(screen.getAllByText(/catalog/i).length).toBeGreaterThan(0);
    expect(
      screen.getByText(/does not fetch live values/i),
    ).toBeInTheDocument();
    expect(screen.queryByText(/^live$/i)).toBeNull();
  });
});

describe("FLDS pane — interactions", () => {
  it("narrows rows when a category filter is selected", () => {
    setMockFn({ state: "ok", ...okPayload() });
    const { container } = render(<FLDSPane code="FLDS" />);
    const grid = container.querySelector('[aria-label="FLDS field catalog"]');
    expect(grid?.textContent).toContain("Session open");
    fireEvent.click(screen.getByTitle("CATEGORY Val"));
    expect(container.textContent).not.toContain("Session open");
    expect(container.textContent).toContain("Trailing P/E");
  });

  it("commits the search box into the footer query and persists it", () => {
    setMockFn({ state: "ok", ...okPayload() });
    render(<FLDSPane code="FLDS" />);
    const input = screen.getByLabelText("Field search prefix");
    fireEvent.change(input, { target: { value: "ytm" } });
    fireEvent.submit(screen.getByTitle("Search the field catalog").closest("form")!);
    expect(localStorage.getItem("showme.flds.prefix")).toBe("ytm");
    expect(screen.getByText("ytm")).toBeInTheDocument();
  });
});
