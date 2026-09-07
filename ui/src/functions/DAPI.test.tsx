/**
 * DAPI pane — data-honesty + render-contract tests.
 *
 * `useFunction` is mocked via a mutable shared state (GEX pattern). Pins:
 *
 *  - loading / error / empty / ok states render;
 *  - the ok state renders the route list with method pills and
 *    honest mutates_state badges (mutating routes badge, read routes do not);
 *  - the filter box is a real interaction (rows shrink + count updates);
 *  - expanding a row reveals the request/response contract.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { DAPIPane } from "./DAPI";

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
      sources: ["showme_fastapi_routes_curated"],
      elapsed_ms: 2,
      data: {
        rows: [
          {
            method: "GET",
            path: "/api/health",
            purpose: "Sidecar and engine health check.",
            request_body: "-",
            response_shape: "{ ok, engine }",
            mutates_state: "no",
            example: "/api/health",
          },
          {
            method: "GET",
            path: "/api/watchlists",
            purpose: "List local watchlists.",
            request_body: "-",
            response_shape: "Watchlist[]",
            mutates_state: "no",
            example: "/api/watchlists",
          },
          {
            method: "PUT",
            path: "/api/watchlists/{name}",
            purpose: "Create/replace a watchlist.",
            request_body: "{ symbols, meta? }",
            response_shape: "Watchlist",
            mutates_state: "yes",
            example: "/api/watchlists/default",
          },
          {
            method: "POST",
            path: "/api/portfolio/positions/{symbol}/close",
            purpose: "Preview or close a local portfolio position.",
            request_body: "{ quantity?, dry_run? }",
            response_shape: "{ closed, realized_pnl, remaining_qty }",
            mutates_state: "yes unless dry_run=true",
            example: "/api/portfolio/positions/BTCUSDT/close",
          },
        ],
        summary: {
          base_url: "http://127.0.0.1:<sidecar-port>",
          endpoints: 4,
          total_routes: 46,
          state_changing: 2,
          filter: "all",
          source_mode: "curated_manifest",
        },
      },
    },
  };
}

/* ── tests ─────────────────────────────────────────────────────────── */

beforeEach(() => {
  setMockFn({ state: "idle", data: undefined });
});

afterEach(() => {
  cleanup();
});

describe("DAPI pane — load states", () => {
  it("renders a skeleton while loading", () => {
    setMockFn({ state: "loading", data: undefined });
    const { container } = render(<DAPIPane code="DAPI" />);
    expect(container.querySelector("[aria-busy='true']")).not.toBeNull();
  });

  it("renders the error state when the fetch errors", () => {
    setMockFn({
      state: "error",
      data: undefined,
      error: new Error("sidecar exploded"),
    });
    render(<DAPIPane code="DAPI" />);
    expect(screen.getByText(/sidecar exploded/i)).toBeInTheDocument();
  });

  it("renders the empty state when the manifest has no routes", () => {
    setMockFn({ state: "ok", data: { data: { rows: [], summary: {} } } });
    render(<DAPIPane code="DAPI" />);
    expect(screen.getByText(/No API routes returned/i)).toBeInTheDocument();
  });
});

describe("DAPI pane — route list + honesty badges", () => {
  it("renders one row per route with method pill and path", () => {
    setMockFn({ state: "ok", ...okPayload() });
    const { container } = render(<DAPIPane code="DAPI" />);
    const rows = container.querySelectorAll(".dapi-route-row");
    expect(rows.length).toBe(4);
    expect(screen.getByText("/api/health")).toBeInTheDocument();
    expect(screen.getByText("/api/watchlists/{name}")).toBeInTheDocument();
  });

  it("badges state-changing routes and leaves read-only routes unbadged", () => {
    setMockFn({ state: "ok", ...okPayload() });
    render(<DAPIPane code="DAPI" />);
    expect(screen.getAllByText("mutates state").length).toBe(2);
    expect(screen.queryByText("may mutate")).toBeNull(); // "yes unless..." also starts with yes
  });

  it("surfaces the curated_manifest source mode honestly", () => {
    setMockFn({ state: "ok", ...okPayload() });
    render(<DAPIPane code="DAPI" />);
    expect(screen.getAllByText("curated_manifest").length).toBeGreaterThan(0); // pill + footer
    expect(screen.getByText(/4 of 46 routes/i)).toBeInTheDocument();
  });
});

describe("DAPI pane — filter + expand interactions", () => {
  it("filters routes by path text and updates the count", () => {
    setMockFn({ state: "ok", ...okPayload() });
    const { container } = render(<DAPIPane code="DAPI" />);
    fireEvent.change(screen.getByLabelText("Filter routes"), {
      target: { value: "watchlist" },
    });
    const rows = container.querySelectorAll(".dapi-route-row");
    expect(rows.length).toBe(2);
    expect(screen.getByText("/api/watchlists")).toBeInTheDocument();
    expect(screen.queryByText("/api/health")).toBeNull();
    expect(screen.getByText(/2 of 46 routes/i)).toBeInTheDocument();
  });

  it("expands a route row to reveal the request/response contract", () => {
    setMockFn({ state: "ok", ...okPayload() });
    render(<DAPIPane code="DAPI" />);
    expect(screen.queryByText(/Request body/i)).toBeNull();
    fireEvent.click(screen.getByText("/api/watchlists/{name}"));
    expect(screen.getByText(/Request body/i)).toBeInTheDocument();
    expect(screen.getByText("{ symbols, meta? }")).toBeInTheDocument();
    expect(screen.getByText("Watchlist")).toBeInTheDocument();
    const row = screen.getByTitle("Collapse route details");
    expect(row.getAttribute("aria-expanded")).toBe("true");
  });
});
