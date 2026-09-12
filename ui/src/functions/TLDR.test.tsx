/**
 * TLDR pane — render-contract + honesty tests.
 *
 * The backend TLDR composes live quotes/news/calendar and asks an LLM for a
 * markdown briefing; when no LLM answers it falls back to a deterministic
 * local template. These tests pin:
 *
 *  - the load states (loading / error / provider_unavailable / ok) render;
 *  - an OK payload renders the briefing prose, movers table, and headline
 *    bullets, plus a generated-at stamp;
 *  - the summary-engine pill honestly reads "local template" when the
 *    summary_model is the deterministic fallback and "llm summary" only for
 *    an llm:* model;
 *  - the symbol-scope Apply interaction updates the visible scope.
 *
 * `useFunction` is mocked via a mutable shared state so each test drives
 * the pane into a specific branch without the real sidecar transport.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { TLDRPane } from "./TLDR";

/* ── useFunction mock ──────────────────────────────────────────────── */

interface MockFnState {
  state: "idle" | "loading" | "ok" | "error" | "refreshing";
  data?: {
    data?: unknown;
    metadata?: Record<string, unknown>;
    fetched_at?: string;
    asOf?: string;
    sources?: string[];
    elapsed_ms?: number | null;
  };
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

function okPayload(overrides: Record<string, unknown> = {}) {
  return {
    state: "ok" as const,
    data: {
      data: {
        status: "ok",
        markdown:
          "# ShowMe TL;DR — 2026-09-07\n\n- **Top movers up:** AAPL (+0.08%)\n- **Top movers down:** MSFT (-2.69%)",
        quotes: [
          { symbol: "AAPL", last: 319.97, change_pct: 0.084, quote_source: "yahoo_chart" },
          { symbol: "MSFT", last: 499.7, change_pct: -2.693, quote_source: "yahoo_chart" },
        ],
        news: ["Fed flags slower path for cuts", "Oil slips on demand worries"],
        events: [{ Country: "US", Event: "Nonfarm Payrolls" }],
        watchlist: ["AAPL", "MSFT"],
        summary_model: "local_deterministic_tldr_v2",
        quote_count: 2,
        mover_count: 2,
      },
      metadata: { summary_model: "local_deterministic_tldr_v2" },
      fetched_at: "2026-09-07T18:08:06.154171+00:00",
      asOf: "2026-09-07T18:08:06.154171+00:00",
      sources: ["yfinance"],
      elapsed_ms: 2997,
      ...overrides,
    },
  };
}

function unavailablePayload() {
  return {
    state: "ok" as const,
    data: {
      data: {
        status: "provider_unavailable",
        reason: "TLDR providers returned no usable content within the latency budget.",
        markdown: "",
        quotes: [],
        news: [],
        events: [],
      },
      sources: ["showme_tldr"],
      elapsed_ms: 9000,
    },
  };
}

/* ── tests ─────────────────────────────────────────────────────────── */

beforeEach(() => {
  localStorage.removeItem("showme.tldr.symbols");
  setMockFn({ state: "idle", data: undefined });
});
afterEach(() => {
  cleanup();
});

describe("TLDR pane — load states", () => {
  it("renders a skeleton while loading", () => {
    setMockFn({ state: "loading", data: undefined });
    const { container } = render(<TLDRPane code="TLDR" symbol="AAPL" />);
    expect(container.querySelector("[aria-busy='true']")).not.toBeNull();
  });

  it("renders the error state when the fetch errors", () => {
    setMockFn({ state: "error", data: undefined, error: new Error("sidecar exploded") });
    render(<TLDRPane code="TLDR" />);
    expect(screen.getByText(/sidecar exploded/i)).toBeInTheDocument();
  });

  it("renders the honest empty state for a provider_unavailable payload", () => {
    setMockFn(unavailablePayload());
    render(<TLDRPane code="TLDR" />);
    expect(screen.getByText(/No digest available/i)).toBeInTheDocument();
    expect(
      screen.getByText(/no usable content within the latency budget/i),
    ).toBeInTheDocument();
  });

  it("renders the digest sections when ok", () => {
    setMockFn(okPayload());
    render(<TLDRPane code="TLDR" />);
    expect(screen.getByText(/ShowMe TL;DR — 2026-09-07/i)).toBeInTheDocument();
    expect(screen.getByText("AAPL")).toBeInTheDocument();
    expect(screen.getByText(/Fed flags slower path for cuts/i)).toBeInTheDocument();
    expect(screen.getByText(/Nonfarm Payrolls/i)).toBeInTheDocument();
  });
});

describe("TLDR pane — honesty", () => {
  it("labels a deterministic fallback summary as local template", () => {
    setMockFn(okPayload());
    render(<TLDRPane code="TLDR" />);
    expect(screen.getByText("local template")).toBeInTheDocument();
    expect(screen.queryByText(/llm summary/i)).toBeNull();
  });

  it("labels an llm:* summary as llm summary", () => {
    setMockFn(
      okPayload({
        data: {
          status: "ok",
          markdown: "- llm bullets",
          quotes: [],
          news: [],
          events: [],
          summary_model: "llm:zai-mini",
          quote_count: 0,
          mover_count: 0,
        },
        metadata: { summary_model: "llm:zai-mini" },
      }),
    );
    render(<TLDRPane code="TLDR" />);
    expect(screen.getByText("llm summary")).toBeInTheDocument();
    expect(screen.queryByText(/local template/i)).toBeNull();
  });

  it("stamps the generated-at time from the envelope asOf", () => {
    setMockFn(okPayload());
    render(<TLDRPane code="TLDR" />);
    expect(screen.getByText(/generated 2026-09-07 18:08/i)).toBeInTheDocument();
  });
});

describe("TLDR pane — scope interaction", () => {
  it("applies a typed symbol scope and persists it", () => {
    setMockFn(okPayload());
    render(<TLDRPane code="TLDR" />);
    const input = screen.getByLabelText(/tldr symbol scope/i);
    fireEvent.change(input, { target: { value: "btcusdt, eurusd" } });
    fireEvent.click(screen.getByRole("button", { name: "Apply" }));
    // The footer scope reflects the applied (uppercased) value.
    expect(screen.getByText("BTCUSDT, EURUSD")).toBeInTheDocument();
    expect(localStorage.getItem("showme.tldr.symbols")).toBe("BTCUSDT, EURUSD");
  });

  it("falls back to portfolio scope wording when empty", () => {
    setMockFn(okPayload());
    render(<TLDRPane code="TLDR" />);
    expect(screen.getAllByText(/portfolio \+ watchlist/i).length).toBeGreaterThan(0);
  });
});

describe("TLDR pane — movers grid sort + keyboard (lane B4)", () => {
  it("defaults to biggest movers first and enables keyboard grid navigation", () => {
    const payload = okPayload();
    // Reverse the quotes so only the built-in sorter can put AAPL first.
    const data = payload.data.data as { quotes: unknown[] };
    data.quotes = [...data.quotes].reverse();
    setMockFn(payload);
    const { container } = render(<TLDRPane code="TLDR" />);

    const grid = screen.getByRole("grid", { name: "TLDR quote movers" });
    expect(grid).toBeInTheDocument();
    // Roving keyboard cell: the first cell owns the tab stop.
    expect(
      grid.querySelector('td[data-cell="0-0"]')?.getAttribute("tabindex"),
    ).toBe("0");

    // change_pct descending -> AAPL (+0.084) first, MSFT (-2.693) last.
    const rowsBefore = Array.from(container.querySelectorAll("tbody tr"));
    expect(rowsBefore[0]?.textContent).toContain("AAPL");
    expect(rowsBefore.at(-1)?.textContent).toContain("MSFT");

    // Activating the sort cycles desc -> none: reversed fixture order returns.
    fireEvent.click(container.querySelector('th[aria-sort="descending"]')!);
    const rowsAfter = Array.from(container.querySelectorAll("tbody tr"));
    expect(rowsAfter[0]?.textContent).toContain("MSFT");
  });
});
