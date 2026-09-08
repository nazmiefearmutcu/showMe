/**
 * SOSC pane — load-state + honesty tests (GEX mock pattern).
 *
 * `useFunction` is mocked via a mutable shared object. Pins:
 *  - loading skeleton and error branches render;
 *  - an ok payload renders the sentiment KPI cards + per-outlet table with
 *    trend chips;
 *  - a `provider_unavailable` payload renders the backend's honest reason
 *    (GDELT outage) instead of any fabricated sentiment;
 *  - the window control persists under `showme.sosc.days` and activates on
 *    click.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { SOSCPane } from "./SOSC";

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

/* ── fixtures (shape mirrors a live /api/fn/SOSC probe) ────────────── */

function okPayload() {
  return {
    status: "ok",
    symbol: "AAPL",
    rows: [
      {
        platform: "reuters.com",
        mentions: 12,
        sentiment: 0.24,
        trend: "bullish",
        source_mode: "gdelt",
      },
      {
        platform: "cnbc.com",
        mentions: 7,
        sentiment: -0.31,
        trend: "bearish",
        source_mode: "gdelt",
      },
      {
        platform: "forums.stocktwits",
        mentions: 3,
        sentiment: 0.01,
        trend: "flat",
        source_mode: "gdelt",
      },
    ],
    cards: [
      { key: "net_sentiment", label: "Net sentiment", value: 0.12 },
      { key: "label", label: "Read", value: "bullish" },
      { key: "total_mentions", label: "Articles", value: 22 },
      { key: "gdelt_tone", label: "GDELT tone", value: 0.18 },
      { key: "finbert", label: "FinBERT", value: 0.06 },
    ],
    summary: {
      symbol: "AAPL",
      net_sentiment: 0.12,
      label: "bullish",
      total_mentions: 22,
      gdelt_tone: 0.18,
      finbert_headline_sentiment: 0.06,
      window: "3d",
      outlets: 3,
      source_mode: "gdelt+finbert",
    },
    methodology: "SOSC reads keyless GDELT news/social tone and scores headlines with FinBERT.",
  };
}

function unavailablePayload() {
  return {
    status: "provider_unavailable",
    symbol: "AAPL",
    rows: [],
    summary: { symbol: "AAPL", net_sentiment: null, total_mentions: 0, source_mode: "gdelt_unreachable" },
    reason: "GDELT request failed: ConnectTimeout",
    next_actions: ["Retry once the GDELT endpoint recovers."],
  };
}

beforeEach(() => {
  localStorage.clear();
  setMockFn({ state: "idle", data: undefined });
});
afterEach(() => {
  cleanup();
});

describe("SOSC pane — load states", () => {
  it("renders a skeleton while loading", () => {
    setMockFn({ state: "loading" });
    const { container } = render(<SOSCPane code="SOSC" symbol="AAPL" />);
    expect(container.querySelector('[aria-busy="true"]')).not.toBeNull();
  });

  it("renders the error state when the fetch errors", () => {
    setMockFn({ state: "error", error: new Error("sidecar exploded") });
    render(<SOSCPane code="SOSC" symbol="AAPL" />);
    expect(screen.getByText(/sidecar exploded/i)).toBeInTheDocument();
  });
});

describe("SOSC pane — sentiment payload", () => {
  it("renders net sentiment cards and the per-outlet table when ok", () => {
    setMockFn({ state: "ok", data: { data: okPayload() } });
    const { container } = render(<SOSCPane code="SOSC" symbol="AAPL" />);
    // KPI cards.
    expect(container.textContent).toContain("+0.12");
    expect(container.textContent).toContain("22");
    expect(container.textContent).toContain("gdelt+finbert");
    // Outlet rows with trend chips ("bullish" also appears as the KPI read).
    expect(screen.getByText("reuters.com")).toBeInTheDocument();
    expect(screen.getByText("cnbc.com")).toBeInTheDocument();
    expect(screen.getAllByText("bullish").length).toBeGreaterThanOrEqual(2);
    expect(screen.getByText("bearish")).toBeInTheDocument();
    expect(screen.getByText("flat")).toBeInTheDocument();
    expect(container.textContent).toContain("+0.24");
    expect(container.textContent).toContain("-0.31");
  });

  it("renders the honest provider_unavailable state with the backend reason", () => {
    setMockFn({ state: "ok", data: { data: unavailablePayload() } });
    render(<SOSCPane code="SOSC" symbol="AAPL" />);
    expect(screen.getByText(/Sentiment provider unavailable/i)).toBeInTheDocument();
    expect(screen.getByText(/GDELT request failed: ConnectTimeout/i)).toBeInTheDocument();
    // No fabricated sentiment appears anywhere.
    expect(screen.queryByText(/Net sentiment/i)).toBeNull();
  });

  it("renders the quiet-coverage empty state when no articles matched", () => {
    setMockFn({
      state: "ok",
      data: {
        data: {
          status: "empty",
          rows: [],
          summary: { symbol: "AAPL", net_sentiment: 0, total_mentions: 0, window: "3d" },
        },
      },
    });
    render(<SOSCPane code="SOSC" symbol="AAPL" />);
    expect(screen.getByText(/No recent coverage/i)).toBeInTheDocument();
  });
});

describe("SOSC pane — controls", () => {
  it("persists and activates the window control", () => {
    setMockFn({ state: "ok", data: { data: okPayload() } });
    render(<SOSCPane code="SOSC" symbol="AAPL" />);
    const wide = screen.getByRole("button", { name: "14d" });
    expect(wide).not.toBeDisabled();
    fireEvent.click(wide);
    expect(wide).toBeDisabled();
    expect(wide.className).toContain("fn-segmented__opt--active");
    expect(localStorage.getItem("showme.sosc.days")).toBe("14");
  });
});
