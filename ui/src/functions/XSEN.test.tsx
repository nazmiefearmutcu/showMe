/**
 * XSEN regression tests for SHOWME_BUGHUNT 2026-05-24 (theme 5 + 6).
 *
 * Pins the UI fixes:
 *  - Bug #10e: a partial /api/x/health response (no `scraper` key) must not
 *    throw a TypeError; the pane shows "Sentiment model offline" instead.
 *  - Bug #6:  when analyzeXTopic returns {verdict: "insufficient_data"}
 *    the pane renders a "Not enough data for a verdict" empty state, not
 *    a misleading bullish gauge.
 */
import { act, cleanup, render, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

vi.mock("@/lib/xai", () => ({
  fetchXHealth: vi.fn(),
  analyzeXTopic: vi.fn(),
}));

import { analyzeXTopic, fetchXHealth, type XHealth } from "@/lib/xai";
import { XSENPane } from "./XSEN";

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

describe("XSEN Bug #10e — partial health", () => {
  it("does not throw when /api/x/health omits the scraper key", async () => {
    // Backend returns this exact shape when model load times out at 30s.
    const partial: XHealth = {
      ok: false,
      model_loaded: false,
      // scraper, model_dir, load_error all missing
    };
    vi.mocked(fetchXHealth).mockResolvedValueOnce(partial);

    let container: HTMLElement;
    await act(async () => {
      const result = render(<XSENPane code="XSEN" />);
      container = result.container;
    });

    // Mount without TypeError on .scraper.nitter_mirrors_active.length.
    await waitFor(() => {
      expect(fetchXHealth).toHaveBeenCalled();
    });
    expect(container!.firstChild).not.toBeNull();
  });

  it("renders the model-offline empty state when health.ok=false", async () => {
    vi.mocked(fetchXHealth).mockResolvedValueOnce({
      ok: false,
      model_loaded: false,
      load_error: "timed out after 30s",
    });

    let container: HTMLElement;
    await act(async () => {
      const result = render(<XSENPane code="XSEN" />);
      container = result.container;
    });

    await waitFor(() => {
      expect(container!.textContent ?? "").toMatch(/sentiment model offline/i);
    });
    // The detail line surfaces the backend error for ops debugging.
    expect(container!.textContent ?? "").toMatch(/timed out after 30s/);
    // No "Ready to scan X" placeholder while offline.
    expect(container!.textContent ?? "").not.toMatch(/ready to scan x/i);
  });
});

describe("XSEN Bug #6 — insufficient_data verdict", () => {
  it("renders 'Not enough data' instead of confidently bullish on <5 posts", async () => {
    vi.mocked(fetchXHealth).mockResolvedValueOnce({
      ok: true,
      model_loaded: true,
      scraper: {
        backends: { brave_syndication: true, nitter_pool_size: 0 },
        nitter_mirrors_active: [],
      },
    });
    vi.mocked(analyzeXTopic).mockResolvedValueOnce({
      query: "bitcoin",
      post_count: 2,
      verdict: "insufficient_data",
      mood: "insufficient_data",
      warning: "only 2 post(s) scraped — need at least 5 for a reliable verdict",
      scores: {
        bullish_score_avg: 0,
        bullish_score_engagement_weighted: 0,
        confidence: 0,
      },
    });

    let container: HTMLElement;
    let queries: ReturnType<typeof render>;
    await act(async () => {
      queries = render(<XSENPane code="XSEN" symbol="bitcoin" />);
      container = queries.container;
    });

    await waitFor(() => {
      expect(analyzeXTopic).toHaveBeenCalled();
    });
    await waitFor(() => {
      expect(container!.textContent ?? "").toMatch(/not enough data/i);
    });
    expect(container!.textContent ?? "").toMatch(/need at least 5/i);
    // Critical: must NOT render "bullish" verdict in body text. (Header
    // mood pill could legitimately show the literal `insufficient_data`,
    // but no positive verdict word should appear in the result body.)
    const text = container!.textContent ?? "";
    expect(text.match(/\bbullish\b/i)?.length ?? 0).toBe(0);
  });
});
