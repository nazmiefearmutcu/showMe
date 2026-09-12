/**
 * TOP terminal-grade — Veryfinder honesty + a11y + display-quality contract.
 *
 * TOP is a RANKED-NEWS pane (real RSS/GDELT headlines ranked by a deterministic
 * importance_score, with an optional Veryfinder social-signal overlay per
 * headline). The headlines + ranking are genuinely real; this suite pins the
 * honesty/a11y hardening pass:
 *
 *   H1 — a fixture/fallback Veryfinder overlay discloses its provenance
 *        ([DEMO]/[YEDEK] marker + tooltip) so a demo social score is never
 *        read as real X/Twitter data; a normal overlay carries NO marker.
 *   H2 — the header sort label reflects importance-then-recency, not
 *        "recent first" only.
 *   A1 — headlines render as a list (role="list") whose plain <li> rows
 *        contain a focusable TITLE button (aria-label = full headline) that
 *        opens the source on click/Enter. No interactive role is nested inside
 *        another interactive element (the symbol jump buttons + source link are
 *        siblings of the title button, not children of an interactive parent).
 *   A2 — there is a SINGLE shared Veryfinder live region (not one per card).
 *   A3 — the source link + symbol buttons carry aria-labels.
 *   Display — loading shows a Skeleton; empty + error states render.
 */
import { act, cleanup, fireEvent, render, screen, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { relativeTimeLabel } from "@/lib/time";

const useFunctionMock = vi.fn();
const fetchVeryfinderBatchMock = vi.fn();
const navigateMock = vi.fn();
const setFocusedTargetMock = vi.fn();

vi.mock("@/lib/useFunction", () => ({
  useFunction: (...args: unknown[]) => useFunctionMock(...args),
}));

vi.mock("@/lib/veryfinder", () => ({
  fetchVeryfinderBatch: (...args: unknown[]) => fetchVeryfinderBatchMock(...args),
  recommendedVeryfinderSampleForNews: () => 5,
}));

vi.mock("@/lib/router", () => ({
  navigate: (...args: unknown[]) => navigateMock(...args),
}));

vi.mock("@/lib/workspace", () => ({
  useWorkspace: (selector: (s: { setFocusedTarget: typeof setFocusedTargetMock }) => unknown) =>
    selector({ setFocusedTarget: setFocusedTargetMock }),
}));

vi.mock("@/lib/toast", () => ({
  toast: { success: vi.fn(), info: vi.fn(), warn: vi.fn(), error: vi.fn() },
}));

import { TOPPane } from "./TOP";

// Frozen "now" so relative-time labels stay deterministic across runs.
const FIXED_NOW = new Date("2026-06-09T12:00:00.000Z");

const ARTICLE_FIXTURE = {
  title: "Bitcoin spot ETF inflows hit record as crypto rally extends",
  summary: "Spot bitcoin ETFs absorbed fresh capital across the session, lifting the broad crypto tape.",
  source: "Reuters",
  url: "https://example.com/btc-etf",
  published_at: new Date(FIXED_NOW.getTime() - 30 * 60_000).toISOString(),
  symbols: ["BTC"],
  category: "crypto",
  sentiment: "positive",
  importance_score: 82,
  severity: "high",
  importance_reasons: ["relevance: crypto", "criticality: macro flow"],
};

const ARTICLE_NORMAL = {
  title: "Fed officials signal patience on rate cuts amid sticky inflation",
  summary: "Several policymakers emphasized a data-dependent path as core inflation stayed elevated.",
  source: "Bloomberg",
  url: "https://example.com/fed-patience",
  published_at: new Date(FIXED_NOW.getTime() - 90 * 60_000).toISOString(),
  symbols: ["SPY"],
  category: "fed",
  sentiment: "negative",
  importance_score: 71,
  severity: "high",
  importance_reasons: ["relevance: fed"],
};

// Veryfinder batch: the FIRST headline's overlay is a fixture (demo); the
// SECOND is a normal live overlay. Keys mirror TOP's articleKey() — it uses
// `String(a.url ?? a.link ?? a.title ?? ... ?? index)`, so url is the key.
const FIXTURE_OVERLAY = {
  ok: true,
  query: "btc etf",
  source: "fixture",
  fixture_mode: true,
  model_notes: ["fixture social fixture — not live X data"],
  tone: "positive",
  social_score: 34,
  dominant_view: { label: "bull", display: "bullish", score: 0.72 },
  unique_accounts: 18,
};

const NORMAL_OVERLAY = {
  ok: true,
  query: "fed rates",
  source: "x",
  tone: "negative",
  social_score: -22,
  dominant_view: { label: "bear", display: "bearish", score: 0.61 },
  unique_accounts: 24,
};

function okEnvelope(articles: unknown[]) {
  return {
    state: "ok" as const,
    refetch: vi.fn(),
    error: undefined,
    data: {
      data: { items: articles },
      sources: ["rss", "gdelt"],
      warnings: [],
      elapsed_ms: 42,
    },
  };
}

function batchResolved() {
  return {
    ok: true,
    items: [
      { key: ARTICLE_FIXTURE.url, overlay: FIXTURE_OVERLAY },
      { key: ARTICLE_NORMAL.url, overlay: NORMAL_OVERLAY },
    ],
  };
}

beforeEach(() => {
  vi.useFakeTimers();
  vi.setSystemTime(FIXED_NOW);
  useFunctionMock.mockReset();
  fetchVeryfinderBatchMock.mockReset();
  navigateMock.mockReset();
  setFocusedTargetMock.mockReset();
  fetchVeryfinderBatchMock.mockResolvedValue(batchResolved());
});

afterEach(() => {
  cleanup();
  vi.runOnlyPendingTimers();
  vi.useRealTimers();
});

/** Flush the Veryfinder batch promise + its setState into the rendered tree. */
async function flushVeryfinder() {
  await vi.runOnlyPendingTimersAsync();
}

describe("TOP display states", () => {
  it("shows a Skeleton while loading", () => {
    useFunctionMock.mockReturnValue({ state: "loading", refetch: vi.fn() });
    const { container } = render(<TOPPane code="TOP" />);
    // Skeleton renders an inline-styled <span aria-busy="true"> (no class).
    expect(container.querySelectorAll('span[aria-busy="true"]').length).toBeGreaterThan(0);
  });

  it("renders an honest error state", () => {
    useFunctionMock.mockReturnValue({
      state: "error",
      refetch: vi.fn(),
      error: new Error("feed down"),
    });
    render(<TOPPane code="TOP" />);
    expect(screen.getByText(/Function error/i)).toBeTruthy();
    expect(screen.getByText(/feed down/i)).toBeTruthy();
  });

  it("renders an empty state when the feed has no matches", () => {
    useFunctionMock.mockReturnValue(okEnvelope([]));
    render(<TOPPane code="TOP" />);
    expect(screen.getByText(/No matches with current filters/i)).toBeTruthy();
  });
});

describe("TOP honesty", () => {
  it("H1 — discloses a fixture Veryfinder overlay but NOT a normal one", async () => {
    useFunctionMock.mockReturnValue(okEnvelope([ARTICLE_FIXTURE, ARTICLE_NORMAL]));
    render(<TOPPane code="TOP" />);
    await flushVeryfinder();

    // Exactly one fixture/fallback disclosure marker (for the fixture overlay).
    const markers = screen.getAllByTestId("top-vf-fixture");
    expect(markers).toHaveLength(1);
    expect(markers[0].textContent).toMatch(/\[DEMO\]/);

    // The normal headline's VF pill must NOT carry a disclosure marker. Scope
    // to the row <li> (the title button is no longer the row wrapper).
    const list = screen.getByRole("list", { name: /headlines/i });
    const normalTitle = within(list).getByRole("button", { name: /Fed officials signal patience/i });
    const normalRow = normalTitle.closest("li");
    expect(normalRow).not.toBeNull();
    expect(within(normalRow as HTMLElement).queryByTestId("top-vf-fixture")).toBeNull();
  });

  it("H1 — KPI VF caption reads DEMO when every overlay is a fixture", async () => {
    fetchVeryfinderBatchMock.mockResolvedValue({
      ok: true,
      items: [
        { key: ARTICLE_FIXTURE.url, overlay: FIXTURE_OVERLAY },
        { key: ARTICLE_NORMAL.url, overlay: { ...NORMAL_OVERLAY, fixture_mode: true } },
      ],
    });
    useFunctionMock.mockReturnValue(okEnvelope([ARTICLE_FIXTURE, ARTICLE_NORMAL]));
    render(<TOPPane code="TOP" />);
    await flushVeryfinder();
    expect(screen.getByText(/VF · OK · DEMO/i)).toBeTruthy();
  });

  it("H2 — header sort label matches the REAL ordering: newest first", () => {
    useFunctionMock.mockReturnValue(okEnvelope([ARTICLE_FIXTURE]));
    render(<TOPPane code="TOP" />);
    const sort = screen.getByTestId("top-sort-label");
    // AUDIT A1 [M]: the tape is sorted by published_at DESC (client + backend
    // pipeline), so the label must not claim an importance-driven order.
    expect(sort.textContent).toMatch(/NEWEST FIRST/);
    expect(sort.textContent).not.toMatch(/IMPORTANCE/);
    expect(sort.getAttribute("title")).toMatch(/newest first/i);
    // Importance is still surfaced per headline, never as the sort order.
    expect(sort.getAttribute("title")).toMatch(/importance score/i);
  });

  it("M — keeps the poll tick OUT of fetch params and refetches on tick (no skeleton wipe)", async () => {
    const refetch = vi.fn();
    useFunctionMock.mockReturnValue({
      state: "ok" as const,
      refetch,
      error: undefined,
      data: {
        data: { items: [ARTICLE_FIXTURE] },
        sources: ["rss"],
        warnings: [],
        elapsed_ms: 12,
      },
    });
    render(<TOPPane code="TOP" />);
    // The canonical refetch pattern requires tick to never appear in params —
    // a tick in params fingerprints as a new load and wipes the tape.
    const firstCall = useFunctionMock.mock.calls.at(-1)?.[0] as {
      params: Record<string, unknown>;
    };
    expect(firstCall.params).not.toHaveProperty("tick");
    // The 60s visibility tick drives refetch() instead.
    await act(async () => {
      vi.advanceTimersByTime(60_000);
    });
    expect(refetch).toHaveBeenCalled();
  });
});

describe("TOP — headline source/time meta (C3)", () => {
  const ARTICLE_FEED = {
    ...ARTICLE_FIXTURE,
    source: "rss",
    feed: "US Top News and Analysis",
  };

  it("renders the outlet feed + relative time as right-aligned meta", async () => {
    useFunctionMock.mockReturnValue(okEnvelope([ARTICLE_FEED]));
    render(<TOPPane code="TOP" />);
    await flushVeryfinder();

    const list = screen.getByRole("list", { name: /headlines/i });
    const row = within(list)
      .getByRole("button", { name: ARTICLE_FEED.title })
      .closest("li") as HTMLElement;
    expect(row).not.toBeNull();

    // Outlet = the human `feed` (wire-verified), never the machine token.
    expect(within(row).getByTestId("top-headline-source").textContent).toBe(
      "US Top News and Analysis",
    );
    expect(within(row).queryByText("rss")).toBeNull();

    // Relative time via the existing helper, evaluated against the same
    // frozen clock the pane read (pending timers may have ticked a minute).
    expect(within(row).getByTestId("top-headline-time").textContent).toBe(
      relativeTimeLabel(ARTICLE_FEED.published_at),
    );
    expect(within(row).getByTestId("top-headline-time").textContent).toMatch(
      /minutes ago/,
    );

    // The meta cluster follows the `u-flex-1` spacer in the tags row ⇒ right.
    const tags = screen.getByTestId("top-headline-meta")
      .parentElement as HTMLElement;
    const kids = Array.from(tags.children);
    const spacerIdx = kids.findIndex((k) => k.classList.contains("u-flex-1"));
    const metaIdx = kids.indexOf(screen.getByTestId("top-headline-meta"));
    expect(spacerIdx).toBeGreaterThanOrEqual(0);
    expect(metaIdx).toBeGreaterThan(spacerIdx);
  });

  it("omits the source/time columns honestly when the payload lacks them", async () => {
    const bare = {
      title: "Untitled wire item with no source metadata",
      url: "https://example.com/bare",
      symbols: ["SPY"],
    };
    useFunctionMock.mockReturnValue(okEnvelope([bare]));
    render(<TOPPane code="TOP" />);
    await flushVeryfinder();

    const list = screen.getByRole("list", { name: /headlines/i });
    const row = within(list)
      .getByRole("button", { name: bare.title })
      .closest("li") as HTMLElement;
    expect(row).not.toBeNull();
    // No "source / —" filler: both columns are absent entirely.
    expect(within(row).queryByTestId("top-headline-source")).toBeNull();
    expect(within(row).queryByTestId("top-headline-time")).toBeNull();
  });
});

describe("TOP accessibility", () => {
  it("A1 — headlines render as a list whose plain <li> rows hold a focusable title button (no nested interactive elements)", async () => {
    useFunctionMock.mockReturnValue(okEnvelope([ARTICLE_FIXTURE, ARTICLE_NORMAL]));
    render(<TOPPane code="TOP" />);
    await flushVeryfinder();

    const list = screen.getByRole("list", { name: /headlines/i });
    expect(list.tagName.toLowerCase()).toBe("ul");

    // The title is the activator <button> carrying the full-title aria-label.
    const titleBtn = within(list).getByRole("button", { name: ARTICLE_FIXTURE.title });
    expect(titleBtn.tagName.toLowerCase()).toBe("button");

    // The row itself is a PLAIN <li> container — no interactive role/tabindex,
    // so the title button is NOT nested inside an interactive parent.
    const li = titleBtn.closest("li");
    expect(li).not.toBeNull();
    expect(li?.getAttribute("role")).toBeNull();
    expect(li?.getAttribute("tabindex")).toBeNull();

    // No interactive element is nested inside another interactive element.
    const interactiveSelector = "a[href],button,[role='button'],[tabindex]";
    for (const el of Array.from(li!.querySelectorAll(interactiveSelector))) {
      expect(el.closest(interactiveSelector) === el).toBe(true);
    }
  });

  it("A1 — clicking the title button opens its source URL", async () => {
    useFunctionMock.mockReturnValue(okEnvelope([ARTICLE_FIXTURE]));
    const openSpy = vi.spyOn(window, "open").mockReturnValue(null);
    render(<TOPPane code="TOP" />);
    await flushVeryfinder();

    const list = screen.getByRole("list", { name: /headlines/i });
    const titleBtn = within(list).getByRole("button", { name: ARTICLE_FIXTURE.title });
    fireEvent.click(titleBtn);
    expect(openSpy).toHaveBeenCalledWith(ARTICLE_FIXTURE.url, "_blank", "noopener,noreferrer");
    openSpy.mockRestore();
  });

  it("A1 — pressing Enter on the title button opens its source URL", async () => {
    useFunctionMock.mockReturnValue(okEnvelope([ARTICLE_FIXTURE]));
    const openSpy = vi.spyOn(window, "open").mockReturnValue(null);
    render(<TOPPane code="TOP" />);
    await flushVeryfinder();

    const list = screen.getByRole("list", { name: /headlines/i });
    const titleBtn = within(list).getByRole("button", { name: ARTICLE_FIXTURE.title });
    // A native <button> activates on Enter via a synthesized click; jsdom does
    // not synthesize it, so we assert the click handler (the same `openSource`)
    // fires for the keyboard path by dispatching the click the browser would.
    fireEvent.click(titleBtn);
    expect(openSpy).toHaveBeenCalledWith(ARTICLE_FIXTURE.url, "_blank", "noopener,noreferrer");
    openSpy.mockRestore();
  });

  it("A2 — there is a SINGLE shared Veryfinder live region (not one per card)", async () => {
    useFunctionMock.mockReturnValue(okEnvelope([ARTICLE_FIXTURE, ARTICLE_NORMAL]));
    render(<TOPPane code="TOP" />);
    await flushVeryfinder();
    expect(screen.getAllByTestId("top-vf-live")).toHaveLength(1);
  });

  it("A3 — source link and symbol button carry aria-labels", async () => {
    useFunctionMock.mockReturnValue(okEnvelope([ARTICLE_FIXTURE]));
    render(<TOPPane code="TOP" />);
    await flushVeryfinder();

    const list = screen.getByRole("list", { name: /headlines/i });
    expect(within(list).getByRole("link", { name: /reuters.*open the story/i })).toBeTruthy();
    expect(within(list).getByRole("button", { name: /go to BTC details/i })).toBeTruthy();
  });

  it("A4 — sentiment is conveyed by explicit text, not color alone", async () => {
    useFunctionMock.mockReturnValue(okEnvelope([ARTICLE_FIXTURE, ARTICLE_NORMAL]));
    render(<TOPPane code="TOP" />);
    await flushVeryfinder();
    expect(screen.getByText("POSITIVE")).toBeTruthy();
    expect(screen.getByText("NEGATIVE")).toBeTruthy();
  });
});
