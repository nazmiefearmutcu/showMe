/**
 * NI / CN — headline FinBERT fallback + adaptive timeline window.
 *
 * Regression coverage for two live "empty pane" bugs:
 *  1. Bull/Bear signals, the header sentiment badge and the BULL/BEAR KPI were
 *     driven only by the Veryfinder social overlay. When the Veryfinder
 *     runtime is missing (route 503) every signal read 0/— even though every
 *     article already carries live FinBERT stamps (`sentiment`,
 *     `sentiment_score` -1..+1). The pane must fall back to headline FinBERT
 *     and SAY SO — never present headline numbers as social numbers.
 *  2. The timeline hard-dropped every article older than 24h while keeping a
 *     "24H" title, so a feed whose newest row is 25h+ old rendered an empty
 *     axis. The window must adapt (24H → 72H → 7D) or show an honest empty
 *     state.
 */
import { cleanup, render, screen, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const runFunctionMock = vi.fn();
const fetchVeryfinderBatchMock = vi.fn();

vi.mock("@/lib/functions", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/lib/functions")>();
  return {
    ...actual,
    runFunction: (...args: unknown[]) => runFunctionMock(...args),
  };
});

vi.mock("@/lib/store", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/lib/store")>();
  return {
    ...actual,
    useAppStore: ((selector: (s: { sidecarPort: number | null; sidecarStatus: string; functionIndex: unknown[] }) => unknown) =>
      selector({ sidecarPort: 8421, sidecarStatus: "healthy", functionIndex: [] })) as never,
  };
});

vi.mock("@/lib/tauri", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/lib/tauri")>();
  return {
    ...actual,
    isInTauri: () => false,
    invoke: vi.fn(),
  };
});

vi.mock("@/lib/veryfinder", () => ({
  fetchVeryfinderBatch: (...args: unknown[]) => fetchVeryfinderBatchMock(...args),
  recommendedVeryfinderSampleForNews: () => 5,
}));

import { NIPane } from "./NI";

const HOUR_MS = 3_600_000;

function hoursAgo(hours: number): string {
  return new Date(Date.now() - hours * HOUR_MS).toISOString();
}

function article(title: string, ageHours: number, sentiment_score?: number) {
  return {
    title,
    summary: `${title} — summary body.`,
    source: "Nasdaq",
    url: `https://example.com/${encodeURIComponent(title)}`,
    published_at: hoursAgo(ageHours),
    symbols: ["AAPL"],
    importance_score: 55,
    sentiment:
      sentiment_score == null ? undefined : sentiment_score >= 0 ? "positive" : "negative",
    sentiment_score,
  };
}

function mockNews(articles: Array<Record<string, unknown>>) {
  runFunctionMock.mockResolvedValue({
    status: "ok",
    data: { articles },
    sources: ["rss"],
  });
}

beforeEach(() => {
  runFunctionMock.mockReset();
  fetchVeryfinderBatchMock.mockReset();
  // The Veryfinder runtime is missing on this machine → the batch route 503s.
  fetchVeryfinderBatchMock.mockRejectedValue(new Error("veryfinder unavailable"));
});

afterEach(() => cleanup());

describe("NI headline FinBERT fallback (Veryfinder unavailable)", () => {
  it("classifies Bull/Bear from FinBERT, labels the source, and fills the KPI + badge", async () => {
    mockNews([
      article("Acme surges on record cloud guidance", 2, 0.91),
      article("Acme faces accounting probe", 3, -0.72),
      article("Acme hires a new chief operating officer", 4, 0.1),
    ]);
    render(<NIPane code="CN" symbol="AAPL" />);

    // The Veryfinder disclosure line stays intact (pinned elsewhere too).
    const note = await screen.findByTestId("ni-social-unavailable");
    expect(note.textContent).toMatch(/Social overlay unavailable/i);
    expect(note.textContent).toMatch(/Catalysts/i);

    // Honesty label: the rail says the source is headline FinBERT.
    const fallback = screen.getByTestId("ni-finbert-fallback");
    expect(fallback.textContent).toMatch(/headline sentiment \(FinBERT\)/i);

    // Section entries quantify each side from the FinBERT stamps.
    expect(await screen.findByText(/1 positive headline\(s\) — FinBERT/)).toBeTruthy();
    expect(screen.getByText(/1 negative headline\(s\) — FinBERT/)).toBeTruthy();

    // The strongest headline titles are the detail rows inside the synthesis
    // card's Bull/Bear sections (they also exist in the feed list and the
    // NOW-READING box, so scope per section).
    const card = screen.getByText("Synthesis").closest(".ds-card") as HTMLElement;
    const bullSection = within(card).getByText("Bull").closest("div") as HTMLElement;
    expect(within(bullSection).getByText("Acme surges on record cloud guidance")).toBeTruthy();
    const bearSection = within(card).getByText("Bear").closest("div") as HTMLElement;
    expect(within(bearSection).getByText("Acme faces accounting probe")).toBeTruthy();
    // Neutral FinBERT headline is not forced into either side.
    expect(within(card).queryByText("Acme hires a new chief operating officer")).toBeNull();

    // BULL/BEAR KPI falls back too, and its caption names the source.
    const kpi = screen.getByText("Bull / Bear").closest(".stat-card") as HTMLElement;
    expect(within(kpi).getByText("1 / 1")).toBeTruthy();
    expect(within(kpi).getByText("headline FinBERT split")).toBeTruthy();

    // Header badge declares headline sentiment, not social.
    const badge = await screen.findByTitle(/Headline sentiment \(FinBERT\)/i);
    expect(badge.getAttribute("aria-label")).toMatch(/Headline sentiment \(FinBERT\)/);
  });

  it("does not fabricate social numbers: FinBERT aggregate replaces the empty state", async () => {
    mockNews([
      article("Strong positive headline", 1, 0.8),
      article("Mild positive headline", 2, 0.4),
    ]);
    render(<NIPane code="CN" symbol="AAPL" />);

    // Badge shows the real FinBERT aggregate (+0.60 average of 0.8 / 0.4).
    const badge = await screen.findByTitle(/Headline sentiment \(FinBERT\)/i);
    expect(badge.getAttribute("aria-label")).toBe("Headline sentiment (FinBERT) +0.60");

    // Sentiment KPI is numeric, not the "—" placeholder.
    const kpi = screen.getByText("Sentiment").closest(".stat-card") as HTMLElement;
    expect(within(kpi).getByText("+0.60")).toBeTruthy();
    expect(within(kpi).queryByText("—")).toBeNull();

    // No social claim and no fabricated 0.00% / empty-sentiment pill.
    expect(screen.queryByTitle(/Aggregate sentiment/)).toBeNull();
    expect(screen.queryByText(/0\.00%/)).toBeNull();
    expect(screen.queryByText(/sentiment · —/)).toBeNull();
  });
});

describe("NI adaptive timeline window", () => {
  it("keeps the 24H window when a headline is fresh", async () => {
    mockNews([article("Fresh headline", 2, 0.9)]);
    render(<NIPane code="CN" symbol="AAPL" />);
    const label = await screen.findByTestId("ni-timeline-window");
    expect(label.textContent).toMatch(/24H sentiment timeline/i);
    expect(screen.queryByTestId("ni-timeline-empty")).toBeNull();
  });

  it("switches to a 72H window when the newest headline is 24-72h old", async () => {
    mockNews([article("Yesterday headline", 30, -0.8)]);
    render(<NIPane code="CN" symbol="AAPL" />);
    const label = await screen.findByTestId("ni-timeline-window");
    expect(label.textContent).toMatch(/72H sentiment timeline/i);
  });

  it("switches to a 7D window when the newest headline is 3-7d old", async () => {
    mockNews([article("Midweek headline", 5 * 24, 0.6)]);
    render(<NIPane code="CN" symbol="AAPL" />);
    const label = await screen.findByTestId("ni-timeline-window");
    expect(label.textContent).toMatch(/7D sentiment timeline/i);
  });

  it("renders the honest empty state when every headline is older than 7 days", async () => {
    mockNews([article("Ancient headline", 10 * 24, 0.6)]);
    render(<NIPane code="CN" symbol="AAPL" />);
    const empty = await screen.findByTestId("ni-timeline-empty");
    expect(empty.textContent).toMatch(/No headlines in the last 7 days/i);
    expect(screen.queryByTestId("ni-timeline-window")).toBeNull();
  });
});
