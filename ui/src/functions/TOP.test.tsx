/**
 * TOP — Awareness-backed news pane states, params and honesty.
 *
 * Covers §0.4 states (loading, provider_unavailable, empty with relaxers, ok, stale strip),
 * the contract param set (no legacy live/_epoch/timeout toggles) and story rows.
 */
import { cleanup, fireEvent, render, screen, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const useFunctionMock = vi.fn();

/** Calls made by the pane itself (row story-detail hooks carry story_id and are excluded). */
function paneCalls() {
  return useFunctionMock.mock.calls
    .map((c) => c[0])
    .filter((a) => a.params && !("story_id" in a.params));
}
function paneCall() {
  return paneCalls().at(-1);
}

vi.mock("@/lib/useFunction", () => ({
  useFunction: (...args: unknown[]) => useFunctionMock(...args),
}));
vi.mock("@/lib/workspace", () => ({
  useWorkspace: (selector: (s: { setFocusedTarget: () => void }) => unknown) =>
    selector({ setFocusedTarget: () => undefined }),
}));

import { TOPPane } from "./TOP";

const NOW_ISO = new Date().toISOString();

const ROW_A = {
  id: "a1",
  title: "Fed officials signal patience on rate cuts",
  url: "https://news.example/fed",
  publisher: "Reuters",
  publisher_tier: 1,
  published_at: NOW_ISO,
  summary: "Policymakers stressed a data-dependent path.",
  symbols: ["SPY"],
  countries: ["US"],
  topics: ["monetary_policy"],
  asset_classes: ["rates"],
  entities: [],
  sentiment: "negative",
  sentiment_score: -0.31,
  sentiment_confidence: 0.9,
  sentiment_model: "ProsusAI/finbert",
  importance: 74,
  quality_label: "premium",
  quality_score: 84,
  quality_reasons: ["tier2:+10"],
  story_id: null,
  story_size: 1,
  is_paywalled: false,
};

const ROW_B = {
  ...ROW_A,
  id: "b2",
  title: "Oil inventories fall for a third week",
  url: "https://news.example/oil",
  publisher: "Bloomberg",
  publisher_tier: 2,
  quality_label: "standard",
  quality_score: 61,
  importance: 42,
  topics: ["energy"],
};

function result(
  data: Record<string, unknown>,
  state: "ok" | "loading" | "error" = "ok",
  extra: Record<string, unknown> = {},
) {
  return {
    state,
    error: state === "error" ? new Error("boom") : undefined,
    refetch: vi.fn(),
    data:
      state === "ok"
        ? {
            code: "TOP",
            instrument: null,
            data,
            metadata: {},
            fetched_at: NOW_ISO,
            sources: ["awareness:news"],
            warnings: [],
            elapsed_ms: 12,
            ...extra,
          }
        : undefined,
  };
}

beforeEach(() => {
  useFunctionMock.mockReset();
  window.localStorage.clear();
});

afterEach(() => {
  cleanup();
});

describe("TOP display states", () => {
  it("shows a skeleton while loading", () => {
    useFunctionMock.mockReturnValue(result({}, "loading"));
    render(<TOPPane code="TOP" />);
    expect(screen.getByTestId("pane-state-loading")).toBeInTheDocument();
  });

  it("renders the awareness-down state with the backend reason verbatim and no rows", () => {
    useFunctionMock.mockReturnValue(
      result({
        status: "provider_unavailable",
        reason: "connect ECONNREFUSED 127.0.0.1:8086",
        rows: [],
        next_actions: ["Start awareness-markets"],
      }),
    );
    render(<TOPPane code="TOP" />);
    const alert = screen.getByRole("alert");
    expect(within(alert).getByText("Awareness service is not running")).toBeInTheDocument();
    expect(
      within(alert).getByText("connect ECONNREFUSED 127.0.0.1:8086"),
    ).toBeInTheDocument();
    expect(within(alert).getByRole("button", { name: "Retry" })).toBeInTheDocument();
    expect(document.querySelectorAll(".aw-row")).toHaveLength(0);
  });

  it("renders the empty state with the active filters and relaxers", () => {
    useFunctionMock.mockReturnValue(result({ status: "empty", rows: [], count: 0 }));
    render(<TOPPane code="TOP" />);
    expect(screen.getByTestId("pane-state-empty")).toBeInTheDocument();
    expect(screen.getByText("No stories match these filters")).toBeInTheDocument();
    expect(screen.getByText(/Window 24h, quality Standard and above/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Lower quality floor" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Widen to 7d" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Clear filters" })).toBeInTheDocument();
  });

  it("lowering the quality floor from the empty state sends min_quality low", () => {
    useFunctionMock.mockReturnValue(result({ status: "empty", rows: [], count: 0 }));
    render(<TOPPane code="TOP" />);
    fireEvent.click(screen.getByRole("button", { name: "Lower quality floor" }));
    const last = paneCall();
    expect(last.params).toMatchObject({ min_quality: "low" });
  });

  it("renders story rows with publisher, tier and UTC time, and the footer summary", () => {
    useFunctionMock.mockReturnValue(
      result({ status: "ok", rows: [ROW_A, ROW_B], count: 2 }),
    );
    render(<TOPPane code="TOP" />);
    expect(document.querySelectorAll(".aw-row")).toHaveLength(2);
    expect(screen.getByText("Reuters")).toBeInTheDocument();
    expect(screen.getByLabelText("Tier 2")).toBeInTheDocument();
    expect(
      screen.getByText("2 stories in 24h, quality Standard and above from 2 publishers"),
    ).toBeInTheDocument();
    expect(screen.getByText("awareness /v1/markets/news")).toBeInTheDocument();
  });

  it("keeps the rows and shows the warn health strip when a provider is failing", () => {
    useFunctionMock.mockReturnValue(
      result({
        status: "ok",
        rows: [ROW_A],
        meta: {
          providers: [
            {
              provider: "google_news",
              status: "degraded",
              last_ok_at: "2026-11-08T06:00:00Z",
              last_error: "timeout after 10s",
            },
          ],
          feed_health: { ok: 4, degraded: 1 },
          generated_at: NOW_ISO,
          notes: [],
        },
      }),
    );
    render(<TOPPane code="TOP" />);
    expect(screen.getByText("Reuters")).toBeInTheDocument();
    const strip = document.querySelector(".aw-health--warn");
    expect(strip).not.toBeNull();
    expect(strip).toHaveTextContent("Last good update 06:00 UTC");
    expect(strip).toHaveTextContent("google_news degraded: timeout after 10s");
  });

  it("offers Show low quality when the backend hid items below the floor", () => {
    useFunctionMock.mockReturnValue(
      result({
        status: "ok",
        rows: [ROW_A],
        hidden_note: "3 items below the quality floor are hidden.",
      }),
    );
    render(<TOPPane code="TOP" />);
    fireEvent.click(
      screen.getByRole("button", { name: "3 items below the quality floor are hidden." }),
    );
    const last = paneCall();
    expect(last.params).toMatchObject({ min_quality: "low" });
  });
});

describe("TOP params", () => {
  it("sends only contract params (no live, _epoch, timeout or news_timeout)", () => {
    useFunctionMock.mockReturnValue(result({ status: "ok", rows: [ROW_A] }));
    render(<TOPPane code="TOP" />);
    const first = paneCalls()[0];
    expect(first.code).toBe("TOP");
    expect(first.params).toEqual({ hours: 24, limit: 50, min_quality: "standard" });
    expect(first.params).not.toHaveProperty("live");
    expect(first.params).not.toHaveProperty("_epoch");
    expect(first.params).not.toHaveProperty("timeout");
    expect(first.params).not.toHaveProperty("news_timeout");
  });

  it("switching the window sends hours and persists the choice", () => {
    useFunctionMock.mockReturnValue(result({ status: "ok", rows: [ROW_A] }));
    render(<TOPPane code="TOP" />);
    fireEvent.click(screen.getByRole("button", { name: "7d" }));
    const last = paneCall();
    expect(last.params).toMatchObject({ hours: 168 });
    expect(window.localStorage.getItem("aw.top.hours")).toBe("168");
  });

  it("the search box sends q on submit", () => {
    useFunctionMock.mockReturnValue(result({ status: "ok", rows: [ROW_A] }));
    render(<TOPPane code="TOP" />);
    fireEvent.change(screen.getByPlaceholderText("Search headlines"), {
      target: { value: " fed " },
    });
    fireEvent.blur(screen.getByPlaceholderText("Search headlines"));
    const last = paneCall();
    expect(last.params).toMatchObject({ q: "fed" });
  });
});

describe("TOP accessibility", () => {
  it("names the toolbar and the feed", () => {
    useFunctionMock.mockReturnValue(result({ status: "ok", rows: [ROW_A] }));
    render(<TOPPane code="TOP" />);
    expect(screen.getByRole("toolbar", { name: "TOP news filters" })).toBeInTheDocument();
    expect(screen.getByRole("feed", { name: "Top news stories" })).toBeInTheDocument();
  });
});
