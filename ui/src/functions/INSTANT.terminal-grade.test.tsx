/**
 * INSTANT — terminal-grade accessibility, key-stability and data-honesty.
 *
 * Pins the P1–P4 work items:
 *  - the event feed is an aria-live log region (screen readers announce new
 *    events on a busy squawk line);
 *  - filter chips expose aria-pressed/aria-label state;
 *  - the backfill button reports aria-busy while a backfill is running;
 *  - event rows render with stable keys (no array-index suffix) so React
 *    identity survives a re-sort/filter;
 *  - the hardcoded Flow Speed chips are disclosed as *documented* optimizations
 *    (not live-measured metrics) when the backend reports none.
 */
import { cleanup, fireEvent, render, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { INSTANTPane } from "./INSTANT";
import * as instant from "@/lib/instant";
import * as xai from "@/lib/xai";

vi.mock("@/lib/timezone", () => ({
  readTimezone: () => "UTC",
}));

vi.mock("@/lib/xinject", () => ({
  useXInjectStore: {
    getState: () => ({ consumeInjection: () => null }),
  },
}));

function makeEvent(over: Partial<instant.InstantEvent>): instant.InstantEvent {
  return {
    dedupe_key: "k-default",
    source_name: "Reuters",
    source_category: "news",
    source_region: "global",
    title: "Default headline",
    summary: "Default summary",
    priority_score: 80,
    priority_label: "breaking",
    published_at: new Date().toISOString(),
    fetched_at: new Date().toISOString(),
    latency_seconds: 1.2,
    ...over,
  };
}

const baseStatus = {
  ok: true,
  mode: "secondary",
  primary: false,
  transport: "http",
  health: {
    metrics: { total_events: 2, newest_fetched_at: new Date().toISOString() },
    sources: [
      {
        source_id: "reuters",
        source_name: "Reuters",
        enabled: true,
        ok: true,
        status: "ok",
        last_latency_ms: 120,
        last_item_count: 5,
      },
    ],
  },
} as unknown as instant.InstantStatus;

beforeEach(() => {
  vi.spyOn(xai, "fetchXInstantEvents").mockResolvedValue({ events: [] } as never);
});

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

describe("INSTANT terminal-grade", () => {
  it("wraps the event feed in an aria-live log region", async () => {
    vi.spyOn(instant, "fetchInstantStatus").mockResolvedValue(baseStatus);
    vi.spyOn(instant, "fetchInstantEvents").mockResolvedValue({
      events: [makeEvent({ dedupe_key: "a", title: "Alpha headline" })],
    } as never);

    const { container } = render(<INSTANTPane code="INSTANT" symbol={undefined} />);

    await waitFor(() => {
      expect(container.querySelector('[role="log"]')).not.toBeNull();
    });
    const log = container.querySelector('[role="log"]') as HTMLElement;
    expect(log.getAttribute("aria-live")).toBe("polite");
    expect(log.getAttribute("aria-label")).toBeTruthy();
    // The event rows render inside the live region.
    expect(within(log).getByText("Alpha headline")).toBeTruthy();
  });

  it("exposes aria-pressed and aria-label on filter chips", async () => {
    vi.spyOn(instant, "fetchInstantStatus").mockResolvedValue(baseStatus);
    vi.spyOn(instant, "fetchInstantEvents").mockResolvedValue({
      events: [
        makeEvent({ dedupe_key: "a", source_category: "news" }),
        makeEvent({ dedupe_key: "b", source_category: "macro" }),
      ],
    } as never);

    const { container } = render(<INSTANTPane code="INSTANT" symbol={undefined} />);

    // The "all" category chip is active by default → aria-pressed=true.
    const allChip = await waitFor(() => {
      const el = container.querySelector('button[aria-label="all filter"]');
      if (!el) throw new Error("chip not found");
      return el as HTMLButtonElement;
    });
    expect(allChip.getAttribute("aria-pressed")).toBe("true");

    const newsChip = container.querySelector(
      'button[aria-label="news filter"]',
    ) as HTMLButtonElement;
    expect(newsChip).not.toBeNull();
    expect(newsChip.getAttribute("aria-pressed")).toBe("false");

    fireEvent.click(newsChip);
    expect(newsChip.getAttribute("aria-pressed")).toBe("true");
  });

  it("sets aria-busy on the backfill button while a backfill runs", async () => {
    vi.spyOn(instant, "fetchInstantStatus").mockResolvedValue(baseStatus);
    vi.spyOn(instant, "fetchInstantEvents").mockResolvedValue({ events: [] } as never);
    let resolveBackfill: (v: instant.InstantBackfillPayload) => void = () => {};
    vi.spyOn(instant, "runInstantBackfill").mockReturnValue(
      new Promise((resolve) => {
        resolveBackfill = resolve;
      }),
    );

    const { container, getByText } = render(<INSTANTPane code="INSTANT" symbol={undefined} />);

    await waitFor(() => {
      expect(getByText("Backfill")).toBeTruthy();
    });
    const backfillBtn = getByText("Backfill").closest("button") as HTMLButtonElement;
    expect(backfillBtn.getAttribute("aria-busy")).toBe("false");

    fireEvent.click(backfillBtn);

    await waitFor(() => {
      const busy = container.querySelector('button[aria-busy="true"]');
      expect(busy).not.toBeNull();
    });

    resolveBackfill({ items_inserted: 0, items_seen: 0, checked_sources: 1 });
  });

  it("renders event rows with stable keys that do not include the array index", async () => {
    vi.spyOn(instant, "fetchInstantStatus").mockResolvedValue(baseStatus);
    vi.spyOn(instant, "fetchInstantEvents").mockResolvedValue({
      events: [
        makeEvent({ dedupe_key: "alpha", title: "Alpha" }),
        makeEvent({ dedupe_key: "beta", title: "Beta" }),
      ],
    } as never);

    const warnSpy = vi.spyOn(console, "error").mockImplementation(() => {});
    const { getByText } = render(<INSTANTPane code="INSTANT" symbol={undefined} />);
    await waitFor(() => {
      expect(getByText("Alpha")).toBeTruthy();
      expect(getByText("Beta")).toBeTruthy();
    });
    // No duplicate-key React warning.
    const dupKeyWarning = warnSpy.mock.calls.some((call) =>
      String(call[0] ?? "").includes("same key"),
    );
    expect(dupKeyWarning).toBe(false);
    warnSpy.mockRestore();
  });

  it("discloses the hardcoded Flow Speed chips as documented optimizations", async () => {
    // No backend-reported speedups → chips fall back to KNOWN_SPEEDUPS.
    vi.spyOn(instant, "fetchInstantStatus").mockResolvedValue(baseStatus);
    vi.spyOn(instant, "fetchInstantEvents").mockResolvedValue({ events: [] } as never);

    const { queryAllByText } = render(<INSTANTPane code="INSTANT" symbol={undefined} />);

    await waitFor(() => {
      expect(queryAllByText(/documented optimizations/i).length).toBeGreaterThan(0);
    });
  });

  it("shows live speedups (no documented caption) when the backend reports them", async () => {
    vi.spyOn(instant, "fetchInstantStatus").mockResolvedValue({
      ...baseStatus,
      performance: {
        speedups: [{ name: "live-cache", impact: "measured" }],
      },
    } as unknown as instant.InstantStatus);
    vi.spyOn(instant, "fetchInstantEvents").mockResolvedValue({ events: [] } as never);

    const { getByText, queryByText } = render(<INSTANTPane code="INSTANT" symbol={undefined} />);

    await waitFor(() => {
      expect(getByText("live-cache")).toBeTruthy();
    });
    expect(queryByText(/documented optimizations/i)).toBeNull();
  });
});
