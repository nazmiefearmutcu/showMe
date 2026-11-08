/**
 * BRIEF pane — warming / timed-out envelopes (BRIEF#4) and citation labels.
 *
 * A cold call can answer with a provider_unavailable envelope whose reason
 * says the brief is still composing (or timed out while it keeps running in the
 * background). That is not an outage: the pane must say it is warming and retry
 * on its own, bounded. A genuine outage keeps the honest empty state.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, render, screen } from "@testing-library/react";
import { BRIEFPane } from "./BRIEF";

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
  mockFn.refetch = next.refetch ?? vi.fn();
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

/** The useFunction envelope: the pane reads `data.data` as the BRIEF payload. */
function envelope(inner: Record<string, unknown>) {
  return { sources: [], elapsed_ms: 1070, data: inner };
}

beforeEach(() => {
  localStorage.clear();
  setMockFn({ state: "idle", data: undefined });
});
afterEach(() => {
  vi.useRealTimers();
  cleanup();
});

describe("BRIEF pane — warming envelopes (BRIEF#4)", () => {
  it("says the brief is warming, not that no briefing was returned", () => {
    setMockFn({
      state: "ok",
      data: envelope({
        status: "provider_unavailable",
        articles: [],
        reason: "function timed out after 25s",
      }),
    });
    render(<BRIEFPane code="BRIEF" />);
    expect(screen.getByText(/Briefing is warming up/i)).toBeInTheDocument();
    expect(screen.queryByText(/No briefing returned/i)).toBeNull();
  });

  it("treats a timed-out cold call as warming too", () => {
    setMockFn({
      state: "ok",
      data: envelope({
        status: "provider_unavailable",
        articles: [],
        reason: "function timed out after 8s",
      }),
    });
    render(<BRIEFPane code="BRIEF" />);
    expect(screen.getByText(/Briefing is warming up/i)).toBeInTheDocument();
  });

  it("retries on its own while warming", () => {
    vi.useFakeTimers();
    const refetch = vi.fn();
    setMockFn({
      state: "ok",
      refetch,
      data: envelope({
        status: "provider_unavailable",
        articles: [],
        reason: "function timed out after 25s",
      }),
    });
    render(<BRIEFPane code="BRIEF" />);
    expect(refetch).not.toHaveBeenCalled();
    vi.advanceTimersByTime(3000);
    expect(refetch).toHaveBeenCalledTimes(1);
  });

  it("does not treat a provider exception that says 'timed out' as warming (BRIEF#4 follow-up)", () => {
    vi.useFakeTimers();
    const refetch = vi.fn();
    setMockFn({
      state: "ok",
      refetch,
      data: envelope({
        status: "provider_unavailable",
        articles: [],
        reason: "The read operation timed out",
      }),
    });
    render(<BRIEFPane code="BRIEF" />);
    expect(screen.queryByText(/Briefing is warming up/i)).toBeNull();
    expect(screen.getByText(/No briefing returned/i)).toBeInTheDocument();
    vi.advanceTimersByTime(30000);
    expect(refetch).not.toHaveBeenCalled();
  });

  it("does not auto-retry a genuine outage and keeps the honest empty state", () => {
    vi.useFakeTimers();
    const refetch = vi.fn();
    setMockFn({
      state: "ok",
      refetch,
      data: envelope({
        status: "provider_unavailable",
        articles: [],
        reason: "all news adapters are down",
      }),
    });
    render(<BRIEFPane code="BRIEF" />);
    expect(screen.getByText(/No briefing returned/i)).toBeInTheDocument();
    vi.advanceTimersByTime(30000);
    expect(refetch).not.toHaveBeenCalled();
  });
});

describe("BRIEF pane — citation line", () => {
  it("does not repeat the publisher when the feed title is the same", () => {
    setMockFn({
      state: "ok",
      data: envelope({
        status: "ok",
        watchlist: [],
        articles: [
          {
            title: "Reuters macro headline",
            link: "https://news.example.com/reuters/1",
            source: "Reuters",
            feed: "Reuters",
            published_at: "2026-09-04T21:45:03+00:00",
            matched_symbol: "MACRO",
            section: "top_stories",
          },
        ],
      }),
    });
    const { container } = render(<BRIEFPane code="BRIEF" />);
    expect(container.textContent).toContain("Reuters · 2026-09-04 21:45 UTC · MACRO");
    expect(container.textContent).not.toContain("Reuters · Reuters");
  });
});
