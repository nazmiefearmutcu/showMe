/**
 * XSEN terminal-grade / honesty-first regression tests.
 *
 * Pins the freshness-honesty + a11y upgrade:
 *  - F1: a real "Veri alındı" freshness indicator renders from `fetched_at`
 *    (data-testid=xsen-fetched-at), and the `scrape_seconds` display is
 *    relabeled to "ANALİZ SÜRESİ" (processing duration, NOT freshness).
 *  - F3: per-tweet age renders as a relative-time label, with an honest
 *    "tarih yok" fallback when the date is missing/unparseable (never "now").
 *  - F4: a scoring disclosure (data-testid=xsen-scoring-note) names the local
 *    RoBERTa model — reinforcing the honest AI claim.
 *  - A1: BullishGauge exposes role="meter" with aria-valuenow within [-1, 1].
 *  - A2: the Run button is aria-busy while loading.
 *  - A4/A5: tweet link / sentiment dot / rationale toggle / distribution card
 *    aria-labels are present.
 */
import { act, cleanup, render, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

// Frozen "now" for relative-time assertions (see F1 / F3 describe blocks).
const FROZEN_NOW = new Date("2026-06-09T12:00:00Z");

vi.mock("@/lib/xai", () => ({
  fetchXHealth: vi.fn(),
  analyzeXTopic: vi.fn(),
}));

import { analyzeXTopic, fetchXHealth, type XAnalysisResponse, type XHealth } from "@/lib/xai";
import { XSENPane } from "./XSEN";

const HEALTHY: XHealth = {
  ok: true,
  model_loaded: true,
  scraper: {
    backends: { brave_syndication: true, nitter_pool_size: 0 },
    nitter_mirrors_active: [],
  },
};

function fullResponse(overrides: Partial<XAnalysisResponse> = {}): XAnalysisResponse {
  return {
    query: "AAPL",
    post_count: 6,
    scrape_seconds: 0.5,
    // 4 min before FROZEN_NOW (2026-06-09T12:00:00Z) → "4 dakika önce".
    fetched_at: "2026-06-09T11:56:00.000Z",
    device: "cpu",
    mood: "bullish",
    summary_tr: "özet",
    scores: {
      bullish_score_avg: 0.22,
      bullish_score_engagement_weighted: 0.31,
      confidence: 0.74,
    },
    distributions: {
      sentiment_pct: { positive: 67, neutral: 20, negative: 13 },
      emotion_pct: { joy: 40, anger: 20 },
      topic_pct: { stocks: 80, macro: 20 },
    },
    dominant: { sentiment: "positive", emotion: "joy", topic: "stocks" },
    engagement: { avg_likes: 12.4, avg_retweets: 3.1, total_likes: 74, total_retweets: 18 },
    examples: {
      positive: [
        {
          user: "alice",
          text: "AAPL looks strong into earnings",
          likes: 30,
          retweets: 5,
          url: "https://x.com/alice/status/1",
          score: 0.91,
          emotion: "joy",
          topic: "stocks",
          // 10 min before FROZEN_NOW (2026-06-09T12:00:00Z) → "10 dakika önce".
          date: "2026-06-09T11:50:00.000Z",
        },
        {
          user: "carol",
          text: "no date on this one",
          likes: 4,
          retweets: 0,
          url: "",
          score: 0.55,
          emotion: "optimism",
          topic: "stocks",
          date: "", // missing → honest fallback, NOT "now"
        },
      ],
    },
    ...overrides,
  };
}

async function renderWithData(overrides: Partial<XAnalysisResponse> = {}) {
  vi.mocked(fetchXHealth).mockResolvedValueOnce(HEALTHY);
  vi.mocked(analyzeXTopic).mockResolvedValueOnce(fullResponse(overrides));
  let container!: HTMLElement;
  await act(async () => {
    container = render(<XSENPane code="XSEN" symbol="AAPL" />).container;
  });
  await waitFor(() => expect(analyzeXTopic).toHaveBeenCalled());
  await waitFor(() =>
    expect(container.textContent ?? "").toMatch(/AAPL looks strong/),
  );
  return container;
}

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

describe("XSEN F1 — honest freshness", () => {
  // Freeze the clock so the rendered relative-time output is deterministic
  // (relativeTimeLabel reads Date.now() internally — see ui/src/lib/time.ts).
  beforeEach(() => {
    // shouldAdvanceTime keeps real timer scheduling working (so act/waitFor
    // resolve), while setSystemTime pins Date.now() to the frozen base.
    vi.useFakeTimers({ shouldAdvanceTime: true });
    vi.setSystemTime(FROZEN_NOW);
  });
  afterEach(() => {
    vi.useRealTimers();
  });

  it("renders a 'Veri alındı' freshness indicator from fetched_at", async () => {
    const container = await renderWithData();
    const fresh = container.querySelector('[data-testid="xsen-fetched-at"]');
    expect(fresh).not.toBeNull();
    // fetched_at is exactly 4 min before FROZEN_NOW → exact label.
    expect(fresh!.textContent ?? "").toMatch(/4 dakika önce/);
    expect(fresh!.textContent ?? "").toMatch(/VERİ ALINDI/i);
  });

  it("shows honest '—' for freshness when fetched_at is absent", async () => {
    const container = await renderWithData({ fetched_at: undefined });
    const fresh = container.querySelector('[data-testid="xsen-fetched-at"]');
    expect(fresh).not.toBeNull();
    expect(fresh!.textContent ?? "").toMatch(/—/);
    expect(fresh!.textContent ?? "").not.toMatch(/dakika önce/);
  });

  it("relabels scrape_seconds as analysis duration, not freshness", async () => {
    const container = await renderWithData();
    // The processing-duration field is present and labeled "ANALİZ SÜRESİ".
    expect(container.textContent ?? "").toMatch(/ANALİZ SÜRESİ/);
    // It must NOT be the thing labeled as freshness ("VERİ ALINDI").
    const fresh = container.querySelector('[data-testid="xsen-fetched-at"]');
    expect(fresh!.textContent ?? "").not.toMatch(/ANALİZ SÜRESİ/);
  });
});

describe("XSEN F3 — per-tweet date", () => {
  // Freeze the clock so the per-tweet relative-time output is deterministic
  // (relativeTimeLabel reads Date.now() internally — see ui/src/lib/time.ts).
  beforeEach(() => {
    // shouldAdvanceTime keeps real timer scheduling working (so act/waitFor
    // resolve), while setSystemTime pins Date.now() to the frozen base.
    vi.useFakeTimers({ shouldAdvanceTime: true });
    vi.setSystemTime(FROZEN_NOW);
  });
  afterEach(() => {
    vi.useRealTimers();
  });

  it("renders a relative-time age for tweets with a date", async () => {
    const container = await renderWithData();
    const dates = Array.from(
      container.querySelectorAll('[data-testid="xsen-tweet-date"]'),
    ).map((el) => el.textContent ?? "");
    // First example is exactly 10 min before FROZEN_NOW → exact label.
    expect(dates.some((t) => /10 dakika önce/.test(t))).toBe(true);
  });

  it("shows honest 'tarih yok' (not 'now') for missing dates", async () => {
    const container = await renderWithData();
    const dates = Array.from(
      container.querySelectorAll('[data-testid="xsen-tweet-date"]'),
    ).map((el) => el.textContent ?? "");
    expect(dates.some((t) => /tarih yok/.test(t))).toBe(true);
    // Must not fabricate "az önce" (now) for the dateless post.
    expect(dates.filter((t) => /az önce/.test(t)).length).toBe(0);
  });
});

describe("XSEN F4 — scoring disclosure", () => {
  it("renders a RoBERTa scoring note", async () => {
    const container = await renderWithData();
    const note = container.querySelector('[data-testid="xsen-scoring-note"]');
    expect(note).not.toBeNull();
    expect(note!.textContent ?? "").toMatch(/RoBERTa/);
    expect(note!.textContent ?? "").toMatch(/showme_x_v1/);
  });

  it("labels the per-tweet rationale as RoBERTa classification, not vague AI", async () => {
    const container = await renderWithData();
    // Expand the first tweet's rationale.
    const toggle = container.querySelector<HTMLButtonElement>(
      'button[aria-label="gerekçeyi aç"]',
    );
    expect(toggle).not.toBeNull();
    await act(async () => {
      toggle!.click();
    });
    await waitFor(() =>
      expect(container.textContent ?? "").toMatch(/RoBERTa sınıflandırması/),
    );
    expect(container.textContent ?? "").not.toMatch(/AI rationale/);
  });
});

describe("XSEN A1 — gauge meter", () => {
  it("BullishGauge exposes role=meter with aria-valuenow in [-1, 1]", async () => {
    const container = await renderWithData();
    const meter = container.querySelector('[role="meter"][aria-label="Yükseliş skoru"]');
    expect(meter).not.toBeNull();
    const now = Number(meter!.getAttribute("aria-valuenow"));
    expect(Number.isFinite(now)).toBe(true);
    expect(now).toBeGreaterThanOrEqual(-1);
    expect(now).toBeLessThanOrEqual(1);
    expect(meter!.getAttribute("aria-valuemin")).toBe("-1");
    expect(meter!.getAttribute("aria-valuemax")).toBe("1");
  });
});

describe("XSEN A2 — run button busy state", () => {
  it("marks the Run button aria-busy while loading", async () => {
    // Hold the analyze promise open so the loading state is observable.
    vi.mocked(fetchXHealth).mockResolvedValueOnce(HEALTHY);
    let resolve!: (v: XAnalysisResponse) => void;
    vi.mocked(analyzeXTopic).mockReturnValueOnce(
      new Promise<XAnalysisResponse>((r) => {
        resolve = r;
      }),
    );
    let container!: HTMLElement;
    await act(async () => {
      container = render(<XSENPane code="XSEN" symbol="AAPL" />).container;
    });
    await waitFor(() => expect(analyzeXTopic).toHaveBeenCalled());
    const runBtn = container.querySelector<HTMLButtonElement>(".xsen-run-btn");
    expect(runBtn).not.toBeNull();
    expect(runBtn!.getAttribute("aria-busy")).toBe("true");
    await act(async () => {
      resolve(fullResponse());
    });
  });
});

describe("XSEN A4/A5 — labels", () => {
  it("tweet open link, sentiment dot, toggle and distribution card carry aria-labels", async () => {
    const container = await renderWithData();
    // A4: open link.
    const open = container.querySelector('a[aria-label="@alice gönderisini aç"]');
    expect(open).not.toBeNull();
    // A4: sentiment dot.
    const dot = container.querySelector('.xsen-sent-dot[role="img"]');
    expect(dot).not.toBeNull();
    expect(dot!.getAttribute("aria-label") ?? "").toMatch(/gönderi/);
    // A4: rationale toggle.
    expect(container.querySelector('button[aria-label="gerekçeyi aç"]')).not.toBeNull();
    // A5: distribution card full-breakdown aria-label.
    const distImgs = Array.from(container.querySelectorAll('[role="img"][aria-label*="dağılımı"]'));
    const sentiment = distImgs.find((el) =>
      /Sentiment dağılımı/.test(el.getAttribute("aria-label") ?? ""),
    );
    expect(sentiment).toBeTruthy();
    const label = sentiment!.getAttribute("aria-label") ?? "";
    expect(label).toMatch(/positive 67%/);
    expect(label).toMatch(/neutral 20%/);
    expect(label).toMatch(/negative 13%/);
  });
});

describe("XSEN A6 — load announcement", () => {
  it("announces the load result once via a polite live region", async () => {
    const container = await renderWithData();
    const live = container.querySelector('[role="status"][aria-live="polite"]');
    expect(live).not.toBeNull();
    await waitFor(() =>
      expect(
        Array.from(container.querySelectorAll('[role="status"][aria-live="polite"]'))
          .map((el) => el.textContent ?? "")
          .join(" "),
      ).toMatch(/6 gönderi yüklendi, ruh hali bullish/),
    );
  });
});

describe("XSEN A7 — Since chip selected state", () => {
  it("marks the active Since window aria-pressed=true and the rest false", async () => {
    vi.mocked(fetchXHealth).mockResolvedValueOnce(HEALTHY);
    vi.mocked(analyzeXTopic).mockResolvedValueOnce(fullResponse());
    let container!: HTMLElement;
    await act(async () => {
      container = render(<XSENPane code="XSEN" symbol="AAPL" />).container;
    });
    const group = container.querySelector('[role="group"][aria-label="Since"]');
    expect(group).not.toBeNull();
    const chips = Array.from(group!.querySelectorAll("button"));
    expect(chips.length).toBeGreaterThan(1);
    // Default draftSince is "7d" (label "7d") — see XSEN.tsx.
    const active = chips.find((b) => (b.textContent ?? "").trim() === "7d");
    expect(active).toBeTruthy();
    expect(active!.getAttribute("aria-pressed")).toBe("true");
    for (const chip of chips) {
      if (chip === active) continue;
      expect(chip.getAttribute("aria-pressed")).toBe("false");
    }
  });
});
