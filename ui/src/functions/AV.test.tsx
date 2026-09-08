/**
 * AV pane — load-state + honesty tests (GEX mock pattern).
 *
 * `useFunction` is mocked via a mutable shared object. Pins:
 *  - loading skeleton and error branches render;
 *  - an ok payload renders archive items (title, date, duration, media-type
 *    chip) with open links taken only from payload URLs;
 *  - `provider_unavailable` and empty payloads render the backend's honest
 *    reason — no placeholder media rows;
 *  - the scope control persists under `showme.av.scope` and activates on
 *    click; the query filter commits via the Filter button.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { AVPane } from "./AV";

/* ── useFunction mock ──────────────────────────────────────────────── */

interface MockFnState {
  state: "idle" | "loading" | "ok" | "error" | "refreshing";
  data?: { data?: unknown } | undefined;
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

/* ── fixtures (shape mirrors a live /api/fn/AV probe) ──────────────── */

function okPayload() {
  return {
    status: "ok",
    symbol: "AAPL",
    count: 2,
    rows: [
      {
        event_date: "2026-07-30",
        filing_date: "2026-07-31",
        symbol: "AAPL",
        title: "AAPL 8-K — Results of Operations",
        media_type: "earnings_call",
        duration_seconds: null,
        play_url: "https://www.sec.gov/Archives/edgar/data/320193/a8k.htm",
        url: "https://www.sec.gov/Archives/edgar/data/320193/a8k.htm",
        source: "sec.gov",
        form: "8-K",
        has_transcript: true,
      },
      {
        event_date: "2026-08-19",
        published: "Wed, 19 Aug 2026 09:00:00 GMT",
        title: "Planet Money: The yield curve episode",
        media_type: "audio/mpeg",
        duration_seconds: 1325,
        play_url: "https://example.com/episode.mp3",
        url: "https://example.com/episode.mp3",
        source: "NPR Planet Money",
        feed: "Planet Money",
        has_transcript: false,
      },
    ],
    items: [],
    cards: {
      total_items: 2,
      items_with_transcript: 1,
      latest_event_date: "2026-08-19",
      data_mode: "live_official",
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

describe("AV pane — load states", () => {
  it("renders a skeleton while loading", () => {
    setMockFn({ state: "loading" });
    const { container } = render(<AVPane code="AV" symbol="AAPL" />);
    expect(container.querySelector('[aria-busy="true"]')).not.toBeNull();
  });

  it("renders the error state when the fetch errors", () => {
    setMockFn({ state: "error", error: new Error("sidecar exploded") });
    render(<AVPane code="AV" symbol="AAPL" />);
    expect(screen.getByText(/sidecar exploded/i)).toBeInTheDocument();
  });
});

describe("AV pane — archive items", () => {
  it("renders items with titles, dates, durations, chips and payload-only links", () => {
    setMockFn({ state: "ok", data: { data: okPayload() } });
    const { container } = render(<AVPane code="AV" symbol="AAPL" />);
    expect(screen.getByText("AAPL 8-K — Results of Operations")).toBeInTheDocument();
    expect(screen.getByText("Planet Money: The yield curve episode")).toBeInTheDocument();
    expect(container.textContent).toContain("2026-07-30");
    expect(container.textContent).toContain("22:05"); // 1325s
    expect(container.textContent).toContain("earnings_call");
    expect(container.textContent).toContain("form 8-K");
    const links = screen.getAllByLabelText(/Open /);
    expect(links.length).toBe(2);
    expect(links[1].getAttribute("href")).toBe("https://example.com/episode.mp3");
    // Summary cards.
    expect(container.textContent).toContain("live_official");
  });

  it("renders the honest provider_unavailable state with the backend reason", () => {
    setMockFn({
      state: "ok",
      data: {
        data: {
          status: "provider_unavailable",
          rows: [],
          items: [],
          reason: "SEC EDGAR is unreachable for AAPL; cannot build the filings/media archive right now.",
          next_actions: ["Retry in a moment — SEC EDGAR rate-limits aggressive polling."],
        },
      },
    });
    render(<AVPane code="AV" symbol="AAPL" />);
    expect(screen.getByText(/Media archive unavailable/i)).toBeInTheDocument();
    expect(screen.getByText(/SEC EDGAR is unreachable for AAPL/i)).toBeInTheDocument();
    expect(screen.queryByText(/AAPL 8-K/)).toBeNull();
  });

  it("renders the honest empty state when no entries match the filters", () => {
    setMockFn({
      state: "ok",
      data: {
        data: {
          status: "empty",
          rows: [],
          items: [],
          reason: "No archive entries for AAPL match these filters.",
          cards: { total_items: 0, items_with_transcript: 0, latest_event_date: null, data_mode: "live_official" },
        },
      },
    });
    render(<AVPane code="AV" symbol="AAPL" />);
    expect(screen.getByText("No archive entries")).toBeInTheDocument();
    expect(screen.getByText(/No archive entries for AAPL match these filters./i)).toBeInTheDocument();
  });
});

describe("AV pane — controls", () => {
  it("persists and activates the scope control", () => {
    setMockFn({ state: "ok", data: { data: okPayload() } });
    render(<AVPane code="AV" symbol="AAPL" />);
    const global = screen.getByRole("button", { name: "global" });
    expect(global).not.toBeDisabled();
    fireEvent.click(global);
    expect(global).toBeDisabled();
    expect(global.className).toContain("fn-segmented__opt--active");
    expect(localStorage.getItem("showme.av.scope")).toBe("global");
  });

  it("commits the query filter via the Filter button", () => {
    setMockFn({ state: "ok", data: { data: okPayload() } });
    const { container } = render(<AVPane code="AV" symbol="AAPL" />);
    fireEvent.change(screen.getByLabelText(/Archive query filter/i), {
      target: { value: "yield curve" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Filter" }));
    expect(container.textContent).toContain('query "yield curve"');
  });
});
