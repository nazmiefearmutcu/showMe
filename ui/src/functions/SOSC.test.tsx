/**
 * SOSC pane — load-state + honesty tests.
 *
 * `useFunction` is mocked via a mutable shared object. Pins:
 *  - loading skeleton and error branches render;
 *  - an ok payload renders the news KPIs, the bucket chart with the native-scale
 *    GDELT tone legend, headlines, the source table and the methodology;
 *  - provider_unavailable renders the awareness-down state with the reason and
 *    no sentiment figures;
 *  - zero articles render the quiet-coverage empty state;
 *  - the window control sends `window` and persists under showme.sosc.window.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { SOSCPane } from "./SOSC";

interface MockFnState {
  state: "idle" | "loading" | "ok" | "error" | "refreshing";
  data?: { data?: unknown } | undefined;
  error?: Error | null;
}

const mockFn: MockFnState = { state: "idle", data: undefined, error: null };
const lastCall: { params?: unknown } = {};

function setMockFn(next: Partial<MockFnState>) {
  mockFn.state = next.state ?? "idle";
  mockFn.data = next.data;
  mockFn.error = next.error ?? null;
}

vi.mock("@/lib/useFunction", () => ({
  useFunction: (opts: { params?: unknown }) => {
    lastCall.params = opts.params;
    return {
      state: mockFn.state,
      data: mockFn.data,
      error: mockFn.error,
      refetch: vi.fn(),
    };
  },
}));

function okPayload() {
  return {
    status: "ok",
    symbol: "AAPL",
    news: {
      count: 22,
      mean: 0.1,
      weighted_mean: 0.12,
      positive_share: 0.55,
      negative_share: 0.23,
      momentum_z: 0.8,
      dispersion: 0.31,
      latest_at: "2026-11-08T10:00:00Z",
      publishers: ["reuters.com", "cnbc.com"],
      series: [
        { ts: "2026-11-06T00:00:00Z", mean: 0.2, count: 9 },
        { ts: "2026-11-07T00:00:00Z", mean: -0.3, count: 13 },
      ],
    },
    headlines: [
      {
        title: "Apple beats estimates",
        publisher_name: "Reuters",
        published_at: "2026-11-08T10:00:00Z",
        url: "https://example.com/a",
        sentiment: "positive",
        sentiment_score: 0.42,
        sentiment_model: "finbert:ProsusAI/finbert",
      },
    ],
    social: { rank: 3, mentions: 800, mention_change_pct: 4.5, rank_change: 1 },
    gdelt_tone: [
      { ts: "2026-11-06T00:00:00Z", value: -2.5 },
      { ts: "2026-11-07T00:00:00Z", value: 3.1 },
    ],
    rows: [
      { platform: "reuters.com", mentions: 12, sentiment: 0.24, trend: "bullish" },
      { platform: "cnbc.com", mentions: 7, sentiment: -0.31, trend: "bearish" },
      { platform: "forums.stocktwits", mentions: 3, sentiment: 0.01, trend: "flat" },
    ],
    methodology:
      "Mean of FinBERT (ProsusAI/finbert) headline scores per day; weighted mean uses quality scores.",
  };
}

function unavailablePayload() {
  return {
    status: "provider_unavailable",
    symbol: "AAPL",
    reason: "awareness-markets not reachable at 127.0.0.1:8086",
    rows: [],
    news: { count: 0 },
  };
}

beforeEach(() => {
  localStorage.clear();
  lastCall.params = undefined;
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
  it("renders the news KPIs, the bucket chart, headlines and methodology when ok", () => {
    setMockFn({ state: "ok", data: { data: okPayload() } });
    const { container } = render(<SOSCPane code="SOSC" symbol="AAPL" />);
    expect(container.textContent).toContain("+0.12");
    expect(container.textContent).toContain("22");
    expect(container.textContent).toContain("POSITIVE 55%");
    expect(
      screen.getByRole("img", { name: /AAPL news sentiment buckets/ }),
    ).toBeInTheDocument();
    expect(screen.getByText("Apple beats estimates")).toBeInTheDocument();
    expect(screen.getByText(/FinBERT \(ProsusAI\/finbert\)/)).toBeInTheDocument();
  });

  it("labels the GDELT tone line and KPI on its native scale", () => {
    setMockFn({ state: "ok", data: { data: okPayload() } });
    const { container } = render(<SOSCPane code="SOSC" symbol="AAPL" />);
    expect(container.textContent).toContain("GDELT tone, native scale");
    expect(container.textContent).toContain("NATIVE GDELT SCALE");
    // Latest tone sample is +3.1 on GDELT's own scale, not clamped to [-1, 1].
    expect(container.textContent).toContain("+3.10");
    expect(screen.getByTestId("gdelt-tone-line")).toBeInTheDocument();
  });

  it("renders each headline's label and signed score from the flat shape", () => {
    setMockFn({ state: "ok", data: { data: okPayload() } });
    render(<SOSCPane code="SOSC" symbol="AAPL" />);
    expect(screen.getByText("positive +0.42")).toBeInTheDocument();
  });

  it("names a mixed-model window in its source row", () => {
    const payload = {
      ...okPayload(),
      rows: [
        {
          platform: "News (mixed: finbert+lexicon)",
          mentions: 22,
          sentiment: 0.1,
          trend: "bullish",
        },
      ],
    };
    setMockFn({ state: "ok", data: { data: payload } });
    render(<SOSCPane code="SOSC" symbol="AAPL" />);
    expect(screen.getByText("News (mixed: finbert+lexicon)")).toBeInTheDocument();
  });

  it("renders the per-source table", () => {
    setMockFn({ state: "ok", data: { data: okPayload() } });
    render(<SOSCPane code="SOSC" symbol="AAPL" />);
    expect(screen.getByText("reuters.com")).toBeInTheDocument();
    expect(screen.getByText("cnbc.com")).toBeInTheDocument();
  });

  it("renders the awareness-down state with the backend reason and no figures", () => {
    setMockFn({ state: "ok", data: { data: unavailablePayload() } });
    render(<SOSCPane code="SOSC" symbol="AAPL" />);
    expect(screen.getByRole("alert").textContent).toMatch(
      /Awareness service is not running/,
    );
    expect(screen.getByText(/127\.0\.0\.1:8086/)).toBeInTheDocument();
    expect(screen.queryByText("Weighted mean")).toBeNull();
  });

  it("renders the quiet-coverage empty state when no articles matched", () => {
    setMockFn({
      state: "ok",
      data: { data: { status: "empty", news: { count: 0, series: [] }, rows: [] } },
    });
    render(<SOSCPane code="SOSC" symbol="AAPL" />);
    expect(screen.getByText(/No recent coverage/i)).toBeInTheDocument();
  });
});

describe("SOSC pane — controls", () => {
  it("sends `window` (not `days`) and persists the choice", () => {
    setMockFn({ state: "ok", data: { data: okPayload() } });
    render(<SOSCPane code="SOSC" symbol="AAPL" />);
    expect(lastCall.params).toEqual({ window: "7d" });
    const wide = screen.getByRole("button", { name: "30d" });
    fireEvent.click(wide);
    expect(wide).toBeDisabled();
    expect(lastCall.params).toEqual({ window: "30d" });
    expect(localStorage.getItem("showme.sosc.window")).toBe("30d");
  });
});

describe("SOSC pane — grid", () => {
  it("filters sources by trend chip", () => {
    setMockFn({ state: "ok", data: { data: okPayload() } });
    const { container } = render(<SOSCPane code="SOSC" symbol="AAPL" />);
    expect(container.querySelectorAll("tbody tr").length).toBe(3);
    fireEvent.click(screen.getByTitle("Filter trend bearish"));
    expect(container.querySelectorAll("tbody tr").length).toBe(1);
    expect(container.textContent).toContain("cnbc.com");
    expect(container.textContent).not.toContain("reuters.com");
  });
});
