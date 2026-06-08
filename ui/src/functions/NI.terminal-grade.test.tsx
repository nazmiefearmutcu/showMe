/**
 * NI terminal-grade audit — data-honesty, a11y, and display-quality pins.
 *
 * These tests guard the news-desk hardening pass:
 *   P1.1  provider-unavailable payloads render an honest status banner,
 *         NOT a fake article card.
 *   P1.2  the fabricated static pipeline log/step arrays are gone.
 *   P1.3  real headlines render immediately even while Veryfinder is still
 *         scoring (the social column must not gate the feed).
 *   P2    feed uses list semantics, rows are keyboard-focusable, and the
 *         symbol / source affordances carry aria-labels.
 *   P3    headline / summary elements carry the line-clamp class.
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

const REAL_ARTICLE = {
  title: "Acme Corp beats earnings, guides higher for next quarter",
  summary: "Revenue rose 12% year over year as cloud demand accelerated across enterprise accounts.",
  source: "Reuters",
  url: "https://example.com/acme-earnings",
  published_at: new Date().toISOString(),
  symbols: ["ACME"],
  importance_score: 80,
  severity: "high",
};

const UNAVAILABLE_ROW = {
  title: "ACME news unavailable",
  summary: "News providers are temporarily unavailable. Sources tried: rss, gdelt.",
  symbol: "ACME",
  source: "showMe",
  published_at: null,
  url: null,
  status: "provider_unavailable",
  importance_score: 0,
  severity: "unavailable",
};

afterEach(() => cleanup());
beforeEach(() => {
  runFunctionMock.mockReset();
  fetchVeryfinderBatchMock.mockReset();
  fetchVeryfinderBatchMock.mockResolvedValue({ ok: true, items: [] });
});

describe("NI data honesty", () => {
  it("P1.1 — renders an honest status banner for provider_unavailable rows, not an article card", async () => {
    runFunctionMock.mockResolvedValue({
      status: "ok",
      data: { articles: [UNAVAILABLE_ROW] },
      sources: ["no_live_source"],
    });
    render(<NIPane code="CN" symbol="ACME" />);
    // Wait for the honest banner body (unique to the unavailable state).
    // The fetch effect runs a real 600ms retry `delay()` before settling, so
    // give the query a longer-than-default timeout to stay deterministic on
    // slow CI runners (default 1000ms can race the 600ms delay).
    const body = await screen.findByText(
      /No live headlines right now/i,
      {},
      { timeout: 3000 },
    );
    // It must live inside a role=status region (announced to AT).
    expect(body.closest('[role="status"]')).not.toBeNull();
    // The synthetic placeholder must NOT be rendered as a normal feed article.
    expect(screen.queryByText(/ACME news unavailable/i)).toBeNull();
    // No headline feed list and no external placeholder "source" link should leak.
    expect(screen.queryByRole("list", { name: /headlines/i })).toBeNull();
    expect(screen.queryByText(/source ↗/i)).toBeNull();
  });

  it("P1.2 — no fabricated static pipeline log lines are present", async () => {
    runFunctionMock.mockImplementation(() => new Promise(() => {})); // never resolves → stays loading
    render(<NIPane code="CN" symbol="ACME" />);
    // The old fake terminal logs used these exact strings.
    expect(screen.queryByText(/news\.fetch: requesting latest headline batch/i)).toBeNull();
    expect(screen.queryByText(/inference\.run: sentiment, action, view, impact/i)).toBeNull();
    expect(screen.queryByText(/live pipeline log/i)).toBeNull();
  });

  it("P1.3 — real headlines render even while Veryfinder is still scoring", async () => {
    runFunctionMock.mockResolvedValue({
      status: "ok",
      data: { articles: [REAL_ARTICLE] },
      sources: ["rss"],
    });
    // Veryfinder never resolves → simulate a slow social-signal service.
    fetchVeryfinderBatchMock.mockImplementation(() => new Promise(() => {}));
    render(<NIPane code="CN" symbol="ACME" />);
    // The headline list must render while social scoring is still in flight.
    const list = await screen.findByRole("list", { name: /headlines/i });
    expect(within(list).getByText(/Acme Corp beats earnings/i)).toBeTruthy();
    // The inline social-scoring indicator should be present (not a blocking screen).
    expect(within(list).getByText(/scoring social signals/i)).toBeTruthy();
  });
});

describe("NI accessibility + display quality", () => {
  beforeEach(() => {
    runFunctionMock.mockResolvedValue({
      status: "ok",
      data: { articles: [REAL_ARTICLE] },
      sources: ["rss"],
    });
  });

  it("P2 — feed uses list semantics with keyboard-focusable rows", async () => {
    render(<NIPane code="CN" symbol="ACME" />);
    // The feed container exposes list semantics...
    const list = await screen.findByRole("list", { name: /headlines/i });
    expect(list.tagName.toLowerCase()).toBe("ul");
    // ...and each headline row is a focusable, keyboard-operable control.
    const rows = within(list).getAllByRole("button", { name: /Acme Corp beats earnings/i });
    expect(rows.length).toBeGreaterThan(0);
    expect(rows[0].getAttribute("tabindex")).toBe("0");
    expect(rows[0].tagName.toLowerCase()).toBe("li");
  });

  it("P2 — symbol button and source link carry aria-labels", async () => {
    render(<NIPane code="CN" symbol="ACME" />);
    const list = await screen.findByRole("list", { name: /headlines/i });
    expect(within(list).getByRole("button", { name: /navigate to acme/i })).toBeTruthy();
    const link = within(list).getByRole("link", {
      name: /open article at reuters .*new tab/i,
    });
    expect(link.getAttribute("rel")).toBe("noopener noreferrer");
    expect(link.getAttribute("target")).toBe("_blank");
  });

  it("P3 — headline carries the line-clamp class", async () => {
    render(<NIPane code="CN" symbol="ACME" />);
    const list = await screen.findByRole("list", { name: /headlines/i });
    const title = within(list).getByText(/Acme Corp beats earnings/i);
    expect(title.className).toMatch(/ni-feed-title/);
    // Full headline text is preserved in the title attribute for hover.
    expect(title.getAttribute("title")).toMatch(/Acme Corp beats earnings/i);
  });
});
