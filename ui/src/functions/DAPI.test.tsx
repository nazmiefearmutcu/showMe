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
    const rows = container.querySelectorAll("tbody tr");
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
    const rows = container.querySelectorAll("tbody tr");
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
    expect(
      screen.getByLabelText("Route details for /api/watchlists/{name}"),
    ).toBeInTheDocument();
    // Clicking the same row again collapses the detail panel.
    fireEvent.click(screen.getByText("/api/watchlists/{name}"));
    expect(screen.queryByText(/Request body/i)).toBeNull();
  });
});

describe("DAPI pane — grid upgrade (L7)", () => {
  it("filters by method chip", () => {
    setMockFn({ state: "ok", ...okPayload() });
    const { container } = render(<DAPIPane code="DAPI" />);
    fireEvent.click(screen.getByTitle("Filter method PUT"));
    expect(container.querySelectorAll("tbody tr").length).toBe(1);
    expect(container.textContent).toContain("/api/watchlists/{name}");
    fireEvent.click(screen.getByTitle("Filter method ALL"));
    expect(container.querySelectorAll("tbody tr").length).toBe(4);
  });

  it("filters by state chip", () => {
    setMockFn({ state: "ok", ...okPayload() });
    const { container } = render(<DAPIPane code="DAPI" />);
    fireEvent.click(screen.getByTitle("Filter state read"));
    expect(container.querySelectorAll("tbody tr").length).toBe(2);
    expect(container.textContent).toContain("/api/health");
    fireEvent.click(screen.getByTitle("Filter state mutating"));
    expect(container.querySelectorAll("tbody tr").length).toBe(2);
    expect(container.textContent).toContain("/api/watchlists/{name}");
  });

  it("copies an expanded route as cURL", () => {
    const writeText = vi.fn().mockResolvedValue(undefined);
    Object.defineProperty(navigator, "clipboard", {
      value: { writeText },
      configurable: true,
    });
    setMockFn({ state: "ok", ...okPayload() });
    render(<DAPIPane code="DAPI" />);
    fireEvent.click(screen.getByText("/api/watchlists/{name}"));
    fireEvent.click(screen.getByLabelText("Copy PUT /api/watchlists/{name} as cURL"));
    expect(writeText).toHaveBeenCalledTimes(1);
    const curl = writeText.mock.calls[0][0] as string;
    expect(curl).toContain('curl -X PUT "http://127.0.0.1:<sidecar-port>/api/watchlists/{name}"');
    expect(curl).toContain("-d '{ symbols, meta? }'");
    Reflect.deleteProperty(navigator, "clipboard");
  });

  it("sorts the path column from the header", () => {
    setMockFn({ state: "ok", ...okPayload() });
    const { container } = render(<DAPIPane code="DAPI" />);
    fireEvent.click(screen.getByRole("columnheader", { name: /Path/i }));
    // Ascending path order starts with /api/health.
    expect(container.querySelector("tbody tr")?.textContent).toContain("/api/health");
  });
});

describe("DAPI pane — combined-verb routes (F9/M)", () => {
  function combinedVerbPayload() {
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
              method: "GET/POST",
              path: "/api/fn/{code}",
              purpose: "Run any ShowMe function with JSON params.",
              request_body: "{ symbol?, asset_class?, params... }",
              response_shape: "FunctionCallResult",
              mutates_state: "depends on function",
              example: "/api/fn/BQL",
            },
            {
              method: "GET/POST/DELETE",
              path: "/api/proxy/{path:path}",
              purpose: "Auth-aware proxy to a configured upstream.",
              request_body: "(passthrough)",
              response_shape: "(passthrough)",
              mutates_state: "depends",
              example: "/api/proxy/some/upstream",
            },
          ],
          summary: {
            base_url: "http://127.0.0.1:<sidecar-port>",
            endpoints: 3,
            total_routes: 46,
            state_changing: 2,
            filter: "all",
            source_mode: "curated_manifest",
          },
        },
      },
    };
  }

  it("offers concrete verb chips and matches any verb of a combined route", () => {
    setMockFn({ state: "ok", ...combinedVerbPayload() });
    const { container } = render(<DAPIPane code="DAPI" />);
    // Chips are the split verbs, not the combined token.
    expect(screen.getByTitle("Filter method GET")).toBeInTheDocument();
    expect(screen.getByTitle("Filter method POST")).toBeInTheDocument();
    expect(screen.getByTitle("Filter method DELETE")).toBeInTheDocument();
    expect(screen.queryByTitle("Filter method GET/POST")).toBeNull();

    // POST matches BOTH combined routes but not the GET-only health row.
    fireEvent.click(screen.getByTitle("Filter method POST"));
    expect(container.querySelectorAll("tbody tr").length).toBe(2);
    expect(container.textContent).toContain("/api/fn/{code}");
    expect(container.textContent).toContain("/api/proxy/{path:path}");
    expect(container.textContent).not.toContain("/api/health");
  });

  it("copies a combined-verb route as ONE concrete verb in cURL", () => {
    const writeText = vi.fn().mockResolvedValue(undefined);
    Object.defineProperty(navigator, "clipboard", {
      value: { writeText },
      configurable: true,
    });
    setMockFn({ state: "ok", ...combinedVerbPayload() });
    render(<DAPIPane code="DAPI" />);
    fireEvent.click(screen.getByText("/api/fn/{code}"));
    fireEvent.click(screen.getByLabelText("Copy GET /api/fn/{code} as cURL"));
    expect(writeText).toHaveBeenCalledTimes(1);
    const curl = writeText.mock.calls[0][0] as string;
    // Valid single-verb curl — the old code emitted `curl -X GET/POST` which
    // no shell can run.
    expect(curl).toContain('curl -X GET "http://127.0.0.1:<sidecar-port>/api/fn/{code}"');
    expect(curl).not.toContain("GET/POST");
    Reflect.deleteProperty(navigator, "clipboard");
  });
});
