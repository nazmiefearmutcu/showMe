/**
 * BRIEF pane — data-honesty + render-contract tests.
 *
 * Follows the FORM4/GEX mock pattern: `useFunction` is mocked via a mutable
 * shared state so each test drives the pane into a specific branch without
 * the real sidecar transport.
 *
 * Pins:
 *  - the load states (loading / empty-provider / error / ok) render;
 *  - headlines link out via the payload `link` field (`url` fallback),
 *    with the citation line attached; link-less articles stay unlinked
 *    with an honest "no link provided" note;
 *  - the generated-at stamp comes from the payload's as_of card;
 *  - the SECTION filter chips actually filter sections.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen, within } from "@testing-library/react";
import { BRIEFPane } from "./BRIEF";

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

vi.mock("@/lib/useFunction", () => ({
  useFunction: () => ({
    state: mockFn.state,
    data: mockFn.data,
    error: mockFn.error,
    refetch: mockFn.refetch,
  }),
}));

vi.mock("@/shell/SymbolBar", () => ({
  SymbolBar: () => null,
}));

/* ── fixtures ──────────────────────────────────────────────────────── */

function livePayload() {
  return {
    data: {
      sources: ["rss"],
      elapsed_ms: 969.1,
      asOf: "2026-09-07T00:52:36+00:00",
      data: {
        status: "ok",
        articles: [
          {
            title: "Apple dips more than broader market today",
            link: "https://www.nasdaq.com/articles/apple-dip",
            url: null,
            summary: "Apple settled at $319.97, -2.51% on the day.",
            published_at: "2026-09-04T21:45:03+00:00",
            source: "rss",
            feed: "AAPL Feed",
            matched_symbol: "AAPL",
            section: "watchlist",
            severity: "low",
          },
          {
            title: "Ingenia rejects buyout bid; shares surge",
            link: "https://www.investing.com/news/ingenia",
            url: null,
            summary: "",
            published_at: "2026-09-07T00:43:57+00:00",
            source: "rss",
            feed: "Stock Market News",
            matched_symbol: "MACRO",
            section: "top_stories",
            severity: "medium",
          },
          {
            title: "Wire service headline without a link",
            link: null,
            url: null,
            summary: "No URL in the payload.",
            published_at: "2026-09-06T18:00:00+00:00",
            source: "rss",
            feed: "Wire",
            matched_symbol: "MACRO",
            section: "top_stories",
            severity: "low",
          },
        ],
        watchlist: ["AAPL", "MSFT", "BTCUSDT"],
        article_count: 3,
        cards: [
          { key: "article_count", label: "Stories", value: 3 },
          { key: "watchlist_size", label: "Watchlist", value: 3 },
          { key: "as_of", label: "As of", value: "2026-09-07T00:52:36.206135+00:00" },
        ],
      },
    },
  };
}

beforeEach(() => {
  localStorage.clear();
  setMockFn({ state: "idle", data: undefined, refetch: vi.fn() });
});
afterEach(() => {
  cleanup();
});

describe("BRIEF pane — load states", () => {
  it("renders a skeleton while loading", () => {
    setMockFn({ state: "loading", data: undefined });
    const { container } = render(<BRIEFPane code="BRIEF" />);
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
    render(<BRIEFPane code="BRIEF" />);
    expect(screen.getByText(/sidecar exploded/i)).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Retry" }));
    expect(refetch).toHaveBeenCalled();
  });

  it("never invents a quiet-day summary when the provider is down", () => {
    setMockFn({
      state: "ok",
      data: {
        data: {
          status: "provider_unavailable",
          articles: [],
          reason: "all news adapters are down",
        },
      },
    });
    render(<BRIEFPane code="BRIEF" />);
    expect(screen.getByText(/No briefing returned/i)).toBeInTheDocument();
    expect(
      screen.getByText(/all news adapters are down/i),
    ).toBeInTheDocument();
  });
});

describe("BRIEF pane — live payload", () => {
  it("links headlines via `link`, cites sources, and flags link-less rows", () => {
    setMockFn({ state: "ok", ...livePayload() });
    render(<BRIEFPane code="BRIEF" />);
    // Headline links carry the payload URL (the `link` field).
    const apple = screen.getByRole("link", {
      name: "Apple dips more than broader market today",
    });
    expect(apple).toHaveAttribute(
      "href",
      "https://www.nasdaq.com/articles/apple-dip",
    );
    expect(apple).toHaveAttribute("target", "_blank");
    expect(apple).toHaveAttribute("rel", "noopener noreferrer");
    // Citation line stays attached (source · feed · published · symbol).
    expect(screen.getByText(/rss · AAPL Feed · 2026-09-04 21:45 UTC · AAPL/)).toBeInTheDocument();
    // Generated-at stamp from the payload's as_of card.
    expect(screen.getByText(/generated 2026-09-07 00:52 UTC/i)).toBeInTheDocument();
    // Watchlist echoed from the payload.
    expect(screen.getByText(/Watchlist: AAPL, MSFT, BTCUSDT/)).toBeInTheDocument();
  });

  it("renders link-less articles unlinked with an honest note", () => {
    setMockFn({ state: "ok", ...livePayload() });
    render(<BRIEFPane code="BRIEF" />);
    expect(
      screen.getByText("Wire service headline without a link"),
    ).toBeInTheDocument();
    expect(screen.getByText(/no link provided/i)).toBeInTheDocument();
    // And that headline is NOT an anchor.
    expect(
      screen.queryByRole("link", { name: "Wire service headline without a link" }),
    ).toBeNull();
  });

  it("shows the medium severity pill from the payload", () => {
    setMockFn({ state: "ok", ...livePayload() });
    render(<BRIEFPane code="BRIEF" />);
    expect(screen.getByText("medium")).toBeInTheDocument();
    // "low" severity gets no pill (only medium/high are signalled).
    expect(screen.queryByText("low")).toBeNull();
  });
});

describe("BRIEF pane — KPI ribbon (audit A3 OPP)", () => {
  it("renders the payload's article_count / watchlist_size cards as a KPI ribbon", () => {
    setMockFn({ state: "ok", ...livePayload() });
    render(<BRIEFPane code="BRIEF" />);
    const ribbon = screen.getByLabelText("BRIEF KPI ribbon");
    expect(within(ribbon).getByText("Stories")).toBeInTheDocument();
    expect(within(ribbon).getByText("PAYLOAD CARD · ARTICLE_COUNT")).toBeInTheDocument();
    expect(within(ribbon).getByText("Watchlist")).toBeInTheDocument();
    expect(within(ribbon).getByText("PAYLOAD CARD · WATCHLIST_SIZE")).toBeInTheDocument();
    // Both card values are 3 in the fixture (3 stories / 3 watchlist symbols).
    expect(within(ribbon).getAllByText("3")).toHaveLength(2);
  });

  it("renders no ribbon when the payload carries no count cards (never fake a 0)", () => {
    const payload = livePayload();
    const inner = payload.data.data as { cards?: unknown };
    delete inner.cards;
    setMockFn({ state: "ok", ...payload });
    render(<BRIEFPane code="BRIEF" />);
    expect(screen.queryByLabelText("BRIEF KPI ribbon")).toBeNull();
  });
});

describe("BRIEF pane — controls", () => {
  it("filters sections via the SECTION chips", () => {
    setMockFn({ state: "ok", ...livePayload() });
    render(<BRIEFPane code="BRIEF" />);
    expect(
      screen.getByText("Apple dips more than broader market today"),
    ).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Top stories" }));
    // Watchlist article disappears; top stories stay.
    expect(
      screen.queryByText("Apple dips more than broader market today"),
    ).toBeNull();
    expect(
      screen.getByText("Ingenia rejects buyout bid; shares surge"),
    ).toBeInTheDocument();
    // The active chip becomes the disabled one.
    expect(screen.getByRole("button", { name: "Top stories" })).toBeDisabled();
    fireEvent.click(screen.getByRole("button", { name: "Watchlist" }));
    expect(
      screen.getByText("Apple dips more than broader market today"),
    ).toBeInTheDocument();
  });
});
