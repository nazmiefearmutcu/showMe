/**
 * READ pane — load-state + honesty tests (GEX/NSE mock pattern).
 *
 * `useFunction` is mocked via a mutable shared object. Pins:
 *  - loading skeleton, error, provider-unavailable, empty-store and
 *    filtered-empty branches each render their own honest state (no
 *    fabricated rows anywhere);
 *  - an ok payload renders the article cards with headline links taken
 *    ONLY from the payload's absolute URLs (linkless rows stay unlinked
 *    with a "no link provided" note);
 *  - the derivation honesty strip names the payload-declared store
 *    backend (sqlite) and cached-snapshot mode;
 *  - clicking a STATUS filter persists it under `showme.read.status`.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { READPane } from "./READ";

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

/* ── fixtures (shape mirrors the live /api/fn/READ probe) ──────────── */

function okPayload(): Partial<MockFnState> {
  return {
    state: "ok",
    data: {
      status: "ok",
      sources: ["internal_reading_list"],
      metadata: {
        store_present: true,
        store_total: 3,
        persistence: "sqlite_reading_list_v1",
        data_mode: "cached_snapshot",
      },
      elapsed_ms: 12.3,
      data: {
        status: "ok",
        rows: [
          {
            article_id: "a1",
            title: "Fed minutes hint at slower hikes",
            source: "reuters.com",
            status: "unread",
            saved_utc: "2026-09-06T12:00:00+00:00",
            link: "https://example.com/a",
            tags: ["macro"],
            matched_symbol: "SPY",
          },
          {
            article_id: "a2",
            title: "Chip demand stabilising, says supplier",
            source: "bloomberg.com",
            status: "in_progress",
            saved_utc: "2026-09-05T09:30:00+00:00",
            link: "https://example.com/b",
          },
          {
            article_id: "a3",
            title: "Archived note without a URL",
            source: "internal index",
            status: "archived",
            saved_utc: "2026-09-01T08:00:00+00:00",
          },
        ],
        article_count: 3,
        unread_count: 1,
        in_progress_count: 1,
        summary: "3 saved article(s) in view (1 unread, 1 in progress).",
      },
    },
  };
}

function emptyStorePayload(): Partial<MockFnState> {
  return {
    state: "ok",
    data: {
      status: "empty",
      sources: ["internal_reading_list"],
      metadata: {
        store_present: true,
        store_total: 0,
        persistence: "sqlite_reading_list_v1",
        data_mode: "cached_snapshot",
      },
      data: {
        status: "empty",
        rows: [],
        article_count: 0,
        unread_count: 0,
        in_progress_count: 0,
      },
    },
  };
}

function filteredEmptyPayload(): Partial<MockFnState> {
  return {
    state: "ok",
    data: {
      status: "empty",
      sources: ["internal_reading_list"],
      metadata: { store_total: 7, persistence: "sqlite_reading_list_v1" },
      data: {
        status: "empty",
        rows: [],
        article_count: 0,
        unread_count: 2,
        in_progress_count: 1,
      },
    },
  };
}

function unavailablePayload(): Partial<MockFnState> {
  return {
    state: "ok",
    data: {
      status: "provider_unavailable",
      sources: ["no_live_source"],
      metadata: { store_present: false },
      data: {
        status: "provider_unavailable",
        reason: "Saved-articles store read failed: OSError('disk io').",
        rows: [],
        next_actions: ["Retry; if it persists, check reading_list.sqlite permissions."],
      },
    },
  };
}

/* ── tests ─────────────────────────────────────────────────────────── */

beforeEach(() => {
  localStorage.clear();
  setMockFn({ state: "idle", data: undefined });
});

afterEach(() => {
  cleanup();
});

describe("READ pane — load states", () => {
  it("renders a skeleton while loading", () => {
    setMockFn({ state: "loading", data: undefined });
    const { container } = render(<READPane code="READ" />);
    expect(container.querySelector('[aria-busy="true"]')).not.toBeNull();
  });

  it("renders the error state when the fetch errors", () => {
    setMockFn({
      state: "error",
      data: undefined,
      error: new Error("sidecar exploded"),
    });
    render(<READPane code="READ" />);
    expect(screen.getByText(/sidecar exploded/i)).toBeInTheDocument();
  });

  it("renders the store-failure reason verbatim (no fabricated rows)", () => {
    setMockFn(unavailablePayload());
    render(<READPane code="READ" />);
    expect(
      screen.getByText(/Saved-articles store read failed/i),
    ).toBeInTheDocument();
    expect(screen.queryByLabelText("Reading list articles")).toBeNull();
  });

  it("renders the honest empty-store state when nothing was ever saved", () => {
    setMockFn(emptyStorePayload());
    render(<READPane code="READ" />);
    expect(screen.getByText(/Reading list is empty/i)).toBeInTheDocument();
    expect(
      screen.getByText(/Save articles from CN \/ NI \/ NSE \/ TOP/i),
    ).toBeInTheDocument();
  });

  it("distinguishes filter-no-match from an empty store", () => {
    setMockFn(filteredEmptyPayload());
    render(<READPane code="READ" />);
    expect(
      screen.getByText(/No saved articles match the filters/i),
    ).toBeInTheDocument();
    expect(screen.getByText(/store has 7 article/i)).toBeInTheDocument();
  });
});

describe("READ pane — ok payload", () => {
  it("renders the article cards with a KPI ribbon when ok", () => {
    setMockFn(okPayload());
    render(<READPane code="READ" />);
    expect(screen.getByLabelText("Reading list articles").children.length).toBe(
      3,
    );
    expect(screen.getByText(/Fed minutes hint at slower hikes/)).toBeInTheDocument();
    expect(screen.getByLabelText("READ queue summary")).toHaveTextContent(
      "In view",
    );
  });

  it("links headlines ONLY from payload URLs and marks linkless rows honestly", () => {
    setMockFn(okPayload());
    render(<READPane code="READ" />);
    const links = screen.getAllByRole("link");
    expect(links.map((a) => a.getAttribute("href"))).toEqual([
      "https://example.com/a",
      "https://example.com/b",
    ]);
    expect(screen.getByText(/no link provided/i)).toBeInTheDocument();
  });

  it("surfaces the derivation honesty strip from payload-declared metadata", () => {
    setMockFn(okPayload());
    render(<READPane code="READ" />);
    expect(screen.getByLabelText("READ data derivation")).toHaveTextContent(
      "sqlite store",
    );
    expect(screen.getByLabelText("READ data derivation")).toHaveTextContent(
      "cached snapshot",
    );
  });
});

describe("READ pane — interactions", () => {
  it("persists the STATUS filter under showme.read.status", () => {
    setMockFn(okPayload());
    render(<READPane code="READ" />);
    const group = screen.getByLabelText("Filter by read state");
    const readOpt = group.querySelector(
      '.fn-segmented__opt[title="STATUS Read"]',
    );
    expect(readOpt).not.toBeNull();
    fireEvent.click(readOpt as Element);
    expect(localStorage.getItem("showme.read.status")).toBe("read");
  });
});
