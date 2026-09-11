/**
 * NSE pane — load-state + honesty tests (GEX/NALRT mock pattern).
 *
 * `useFunction` is mocked via a mutable shared object. Pins:
 *  - loading skeleton, error, provider-unavailable and no-result branches
 *    render their own honest states (no fabricated rows in any branch);
 *  - an ok payload renders the result list with headline links taken ONLY
 *    from the payload's absolute URLs (rows without a link stay unlinked
 *    with a "no link provided" note);
 *  - the result-count note names the active query;
 *  - submitting the query box persists the last query under
 *    `showme.nse.last` and the DEEP fallback toggle activates on click.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { NSEPane } from "./NSE";
import * as router from "@/lib/router";
import { useWorkspace } from "@/lib/workspace";

/* ── useFunction mock ──────────────────────────────────────────────── */

interface MockFnState {
  state: "idle" | "loading" | "ok" | "error" | "refreshing";
  data?: {
    data?: unknown;
    status?: string;
    reason?: string;
    sources?: string[];
    metadata?: Record<string, unknown>;
    elapsed_ms?: number;
  } | undefined;
  error?: Error | null;
}

const mockFn: MockFnState = { state: "idle", data: undefined, error: null };

function setMockFn(next: Partial<MockFnState>) {
  mockFn.state = next.state ?? "idle";
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

/* ── fixtures (shape mirrors the live /api/fn/NSE probe) ───────────── */

function okPayload(): Partial<MockFnState> {
  return {
    state: "ok",
    data: {
      status: "ok",
      sources: ["sqlite_fts"],
      metadata: { query: "apple" },
      elapsed_ms: 123.4,
      data: [
        {
          title: "Apple previews new silicon",
          source: "reuters",
          url: "https://example.com/a",
          age_minutes: 42,
          relevance_score: 91.5,
          severity: "high",
          // Backend `symbol_terms` emits the RAW symbol first (plus aliases).
          matched_terms: ["AAPL", "apple"],
        },
        {
          title: "Supplier chain note moves the tape",
          source: "bloomberg",
          link: "https://example.com/b",
          published_at: "2026-09-06T14:02:00+00:00",
          relevance_score: 77.0,
          severity: "medium",
        },
        {
          title: "Archive piece without a URL",
          source: "internal index",
          relevance_score: 51.2,
        },
      ],
    },
  };
}

function unavailablePayload(): Partial<MockFnState> {
  return {
    state: "ok",
    data: {
      status: "provider_unavailable",
      sources: [],
      metadata: { query: "apple" },
      data: {
        status: "provider_unavailable",
        reason: "No live news rows returned for query 'apple'.",
        rows: [],
        next_actions: [
          "Try a more specific company, ticker, or topic query.",
          "Click Deep to include the slower GDELT fallback when available.",
        ],
      },
    },
  };
}

/* ── tests ─────────────────────────────────────────────────────────── */

beforeEach(() => {
  localStorage.clear();
  setMockFn({ state: "idle", data: undefined });
  vi.spyOn(router, "navigate").mockImplementation(() => undefined);
});

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

describe("NSE pane — load states", () => {
  it("renders a skeleton while loading", () => {
    setMockFn({ state: "loading", data: undefined });
    const { container } = render(<NSEPane code="NSE" />);
    expect(container.querySelector('[aria-busy="true"]')).not.toBeNull();
  });

  it("renders the error state when the fetch errors", () => {
    setMockFn({
      state: "error",
      data: undefined,
      error: new Error("sidecar exploded"),
    });
    render(<NSEPane code="NSE" />);
    expect(screen.getByText(/sidecar exploded/i)).toBeInTheDocument();
  });

  it("renders the provider-unavailable reason verbatim (no fabricated rows)", () => {
    setMockFn(unavailablePayload());
    render(<NSEPane code="NSE" />);
    expect(
      screen.getByText(/No live news rows returned for query 'apple'/i),
    ).toBeInTheDocument();
    expect(screen.queryByLabelText("News search results")).toBeNull();
  });

  it("renders the no-results empty state when the payload is an empty list", () => {
    setMockFn({
      state: "ok",
      data: {
        status: "ok",
        sources: [],
        metadata: { query: "zzzz-no-hit" },
        data: [],
      },
    });
    render(<NSEPane code="NSE" />);
    expect(screen.getByText(/No results for/i)).toBeInTheDocument();
  });

  it("renders the ranked result list with a count note when ok", () => {
    setMockFn(okPayload());
    render(<NSEPane code="NSE" />);
    expect(screen.getByLabelText("NSE result count")).toHaveTextContent(
      /3 results for .apple./,
    );
    expect(screen.getByLabelText("News search results").children.length).toBe(
      3,
    );
    expect(screen.getByText(/Apple previews new silicon/)).toBeInTheDocument();
  });
});

describe("NSE pane — link honesty", () => {
  it("links headlines ONLY from payload URLs and marks linkless rows honestly", () => {
    setMockFn(okPayload());
    render(<NSEPane code="NSE" />);
    const links = screen.getAllByRole("link");
    expect(links.map((a) => a.getAttribute("href"))).toEqual([
      "https://example.com/a",
      "https://example.com/b",
    ]);
    expect(screen.getByText(/no link provided/i)).toBeInTheDocument();
  });
});

describe("NSE pane — matched-symbol click-through (audit A3 OPP)", () => {
  it("offers a DES click-through for the bound symbol when matched_terms contain it", () => {
    setMockFn(okPayload());
    const focused = vi.spyOn(useWorkspace.getState(), "setFocusedTarget");
    render(<NSEPane code="NSE" symbol="AAPL" />);
    const chip = screen.getByRole("button", { name: "View AAPL details" });
    fireEvent.click(chip);
    expect(focused).toHaveBeenCalledWith("DES", "AAPL");
    expect(router.navigate).toHaveBeenCalledWith("/symbol/AAPL/DES");
  });

  it("never invents a ticker chip from topic terms alone (no bound symbol)", () => {
    setMockFn(okPayload());
    render(<NSEPane code="NSE" />);
    // "apple" is a topic term, not an identified symbol → no chip, no link.
    expect(
      screen.queryByRole("button", { name: /View .* details/i }),
    ).toBeNull();
  });

  it("uses a row-level symbol field when the feed stamps one", () => {
    setMockFn({
      state: "ok",
      data: {
        status: "ok",
        sources: ["rss"],
        metadata: { query: "nvidia" },
        data: [
          {
            title: "Tagged row",
            source: "rss",
            url: "https://example.com/nvda",
            symbol: "NVDA",
            matched_terms: ["nvidia"],
          },
        ],
      },
    });
    render(<NSEPane code="NSE" />);
    const chip = screen.getByRole("button", { name: "View NVDA details" });
    fireEvent.click(chip);
    expect(router.navigate).toHaveBeenCalledWith("/symbol/NVDA/DES");
  });
});

describe("NSE pane — interactions", () => {
  it("persists a submitted query under showme.nse.last", () => {
    setMockFn(okPayload());
    render(<NSEPane code="NSE" />);
    const input = screen.getByLabelText("News search query");
    fireEvent.change(input, { target: { value: "rate cut odds" } });
    fireEvent.click(screen.getByTitle("Run news search"));
    expect(localStorage.getItem("showme.nse.last")).toBe("rate cut odds");
    expect(screen.getByText(/"rate cut odds"/)).toBeInTheDocument();
  });

  it("activates the DEEP fallback toggle on click", () => {
    setMockFn(okPayload());
    render(<NSEPane code="NSE" />);
    const group = screen.getByLabelText(
      "Include the slower GDELT deep fallback",
    );
    const deepOn = group.querySelector(".fn-segmented__opt:last-child");
    expect(deepOn).not.toBeNull();
    fireEvent.click(deepOn as Element);
    expect((deepOn as HTMLElement).className).toContain(
      "fn-segmented__opt--active",
    );
  });
});
