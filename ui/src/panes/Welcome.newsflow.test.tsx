/**
 * Home Newsflow reads the Awareness TOP payload: `data.rows`, publisher and tier,
 * tone from the sentiment label, a cached note for stale envelopes, the honest
 * empty and outage states, and only http(s) links.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, render, screen, within } from "@testing-library/react";
import { useAppStore } from "@/lib/store";
import { useSentimentStore } from "@/lib/sentiment-store";
import { Welcome } from "./Welcome";

let topState = "ok";
let topPayload: unknown = null;
let topMetadata: Record<string, unknown> = {};
const topCalls: Array<Record<string, unknown>> = [];

vi.mock("@/lib/useFunction", () => ({
  useFunction: (args: Record<string, unknown>) => {
    const code = args.code as string;
    if (code === "TOP") {
      topCalls.push(args);
      return {
        state: topState,
        data:
          topPayload === null
            ? undefined
            : {
                code: "TOP",
                instrument: null,
                data: topPayload,
                metadata: topMetadata,
                fetched_at: "2026-11-08T12:00:00Z",
                sources: ["awareness:news"],
                warnings: [],
                elapsed_ms: null,
              },
        error: topState === "error" ? new Error("boom") : undefined,
        refetch: () => {},
      };
    }
    return { state: "idle", data: undefined, error: undefined, refetch: () => {} };
  },
}));

vi.mock("@/lib/market-data", () => ({
  useLiveQuotes: () => ({}),
}));

/** A live-shape TOP row: the fields mapping.news_row produces. */
function row(overrides: Record<string, unknown> = {}) {
  return {
    id: "a1",
    title: "Chipmaker beats estimates on AI demand",
    url: "https://www.cnbc.com/a1",
    link: "https://www.cnbc.com/a1",
    source: "CNBC",
    publisher: "CNBC",
    publisher_id: "cnbc",
    publisher_tier: 2,
    published_at: "2026-11-08T11:00:00Z",
    sentiment: "positive",
    sentiment_score: 0.7,
    quality_label: "premium",
    story_id: "s1",
    ...overrides,
  };
}

const livePayload = {
  status: "ok",
  rows: [
    row(),
    row({
      id: "a2",
      title: "Regulator opens probe into rate benchmark",
      url: "https://www.reuters.com/a2",
      publisher: "Reuters",
      publisher_tier: 1,
      sentiment: "negative",
    }),
    row({
      id: "a3",
      title: "Quiet session for metals",
      url: "https://blog.example.org/a3",
      publisher: "Example Blog",
      publisher_tier: 4,
      sentiment: null,
    }),
  ],
  count: 3,
  next_cursor: null,
  filters: { hours: 48 },
  hidden_note: null,
  meta: {
    providers: [],
    generated_at: "2026-11-08T12:00:00Z",
    notes: [],
    feed_health: null,
  },
};

beforeEach(() => {
  topState = "ok";
  topPayload = livePayload;
  topMetadata = { data_mode: "live_official", live: true };
  topCalls.length = 0;
  localStorage.clear();
  useAppStore.setState({
    sidecarStatus: "healthy",
    sidecarPort: 8765,
    engineRoot: null,
    functionIndex: [{ code: "TOP", name: "Top News", category: "news", description: "" }],
  });
  useSentimentStore.setState({
    gauge: null,
    unavailableReason: null,
    loading: false,
    error: null,
    lastUpdated: null,
    _inflight: null,
    refresh: vi.fn(),
  });
});

afterEach(() => {
  cleanup();
});

function newsflow(): HTMLElement {
  const el = document.querySelector<HTMLElement>(".terminal-newsflow");
  if (!el) throw new Error("newsflow region missing");
  return el;
}

describe("Newsflow reads the Awareness TOP rows", () => {
  it("renders each row with its publisher, tier and sentiment tone", () => {
    render(<Welcome />);
    const list = within(newsflow());
    expect(list.getByText("Chipmaker beats estimates on AI demand")).toBeTruthy();
    expect(list.getByText("Regulator opens probe into rate benchmark")).toBeTruthy();
    expect(list.getByText("CNBC")).toBeTruthy();
    expect(list.getByText("Reuters")).toBeTruthy();
    expect(list.getByLabelText("Tier 2")).toBeTruthy();
    expect(list.getByLabelText("Tier 1")).toBeTruthy();
    expect(list.getByLabelText("Tier 4")).toBeTruthy();

    const dots = newsflow().querySelectorAll(".terminal-newsflow__dot");
    expect(dots[0]!.className).toMatch(/--positive/);
    expect(dots[1]!.className).toMatch(/--negative/);
    expect(dots[2]!.className).toMatch(/--neutral/);
  });

  it("opens http(s) links only, with the row url as the href", () => {
    render(<Welcome />);
    const links = [
      ...newsflow().querySelectorAll<HTMLAnchorElement>("a.terminal-newsflow__item"),
    ];
    expect(links.map((a) => a.getAttribute("href"))).toEqual([
      "https://www.cnbc.com/a1",
      "https://www.reuters.com/a2",
      "https://blog.example.org/a3",
    ]);
    expect(links.every((a) => a.target === "_blank" && a.rel.includes("noopener"))).toBe(
      true,
    );
  });

  it("does not render a javascript: or relative url as a link", () => {
    topPayload = {
      status: "ok",
      rows: [
        row({ id: "x1", title: "Injected", url: "javascript:alert(1)", publisher: "Evil" }),
      ],
    };
    render(<Welcome />);
    expect(newsflow().querySelector("a.terminal-newsflow__item")).toBeNull();
    expect(within(newsflow()).getByRole("button", { name: /Injected/ })).toBeTruthy();
  });

  it("header reads N headlines · Awareness with no cached note on a live answer", () => {
    render(<Welcome />);
    expect(screen.getByText("3 headlines · Awareness")).toBeTruthy();
    expect(screen.queryByText("cached")).toBeNull();
    expect(screen.queryByText(/live RSS/)).toBeNull();
  });

  it("shows a small cached note when the envelope is a cached snapshot", () => {
    topMetadata = {
      data_mode: "cached_snapshot",
      live: false,
      provider_errors: ["news.feeds: down"],
    };
    render(<Welcome />);
    expect(screen.getByText("cached")).toBeTruthy();
    expect(screen.getByText(/3 headlines · Awareness/)).toBeTruthy();
    // The rows still render: a cached answer keeps its data.
    expect(within(newsflow()).getByText("CNBC")).toBeTruthy();
  });

  it("empty answer shows the honest empty state, not a fabricated list", () => {
    topPayload = {
      status: "empty",
      rows: [],
      count: 0,
      next_cursor: null,
      filters: {},
      hidden_note: null,
    };
    render(<Welcome />);
    expect(
      within(newsflow()).getByText(/No Awareness headlines in the last 48 hours/),
    ).toBeTruthy();
    expect(newsflow().querySelectorAll(".terminal-newsflow__listitem").length).toBe(0);
    const header = document.querySelector(".terminal-panel--news .terminal-panel__header")!;
    expect(header.textContent).toBe("NewsflowAwareness");
  });

  it("provider_unavailable names the Awareness news service and never shows rows", () => {
    topPayload = {
      status: "provider_unavailable",
      reason: "awareness service is not running at http://127.0.0.1:8086",
      rows: [],
    };
    render(<Welcome />);
    const message = within(newsflow()).getByText(/Awareness news service unavailable/);
    expect(message.getAttribute("title")).toMatch(/awareness service is not running/);
    expect(newsflow().querySelectorAll(".terminal-newsflow__listitem").length).toBe(0);
  });

  it("a failed TOP call also names the Awareness news service", () => {
    topState = "error";
    topPayload = null;
    render(<Welcome />);
    expect(within(newsflow()).getByText(/Awareness news service unavailable/)).toBeTruthy();
  });

  it("keeps the TOP params the dispatcher aligns the prewarm to", () => {
    render(<Welcome />);
    const call = topCalls.find((c) => c.code === "TOP");
    expect(call).toBeTruthy();
    const params = call!.params as Record<string, unknown>;
    expect(params.hours).toBe(48);
    expect(params.limit).toBe(24);
    expect(Object.keys(params).sort()).toEqual(["_epoch", "hours", "limit"]);
  });
});
