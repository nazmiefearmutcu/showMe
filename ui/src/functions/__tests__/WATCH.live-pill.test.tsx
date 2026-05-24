/**
 * A12 — WATCH per-row "live" pill painted for rows with no price data.
 *
 * Before the fix `transportState === "live"` alone drove the pill, so a row
 * whose socket reported live but whose snapshot hadn't returned glowed
 * green while the cell itself read `—`. The header KPI said "LIVE · 1",
 * footer "ws · 1/7 live", but 6 of 7 row pills still painted green.
 *
 * Now `live` requires BOTH `transportState === "live"` AND `price != null`.
 */
import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { WATCHPane } from "../WATCH";
import * as marketData from "@/lib/market-data";
import * as watchlist from "@/lib/watchlist";
import * as store from "@/lib/store";
import type { QuoteView } from "@/lib/market-data";

vi.mock("@/lib/sidecar", () => ({
  sidecarFetch: vi.fn(async () => ({ data: { ohlcv: [] } })),
}));

vi.mock("@/lib/tauri", () => ({
  isInTauri: () => false,
  invoke: vi.fn(),
}));

function makeView(overrides: Partial<QuoteView> = {}): QuoteView {
  return {
    symbol: "AAPL",
    snapshot: null,
    lastTick: null,
    price: null,
    changePct: null,
    source: null,
    sourceKind: "none",
    fetchedAt: null,
    freshnessMs: null,
    stale: false,
    loading: false,
    refreshing: false,
    error: null,
    transportState: "idle",
    lastTickAt: null,
    refetch: vi.fn(),
    ...overrides,
  };
}

beforeEach(() => {
  vi.spyOn(watchlist, "loadWatchlist").mockResolvedValue([
    { symbol: "AAPL" },
    { symbol: "MSFT" },
  ]);
  vi.spyOn(store, "useAppStore").mockImplementation(((selector: (s: {
    sidecarStatus: string;
    functionIndex: unknown[];
  }) => unknown) => selector({ sidecarStatus: "healthy", functionIndex: [] })) as never);
});

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

function streamPillLabels(container: HTMLElement): string[] {
  // The per-row Stream cell wraps the pill in a `.showme-watch__stream`
  // span, which lets us isolate row pills from header/KPI chrome.
  return Array.from(
    container.querySelectorAll(".showme-watch__stream .ds-pill__label"),
  ).map((el) => el.textContent?.trim() ?? "");
}

function headerPillLabels(container: HTMLElement): string[] {
  return Array.from(
    container.querySelectorAll(".ds-pane-header .ds-pill__label"),
  ).map((el) => el.textContent?.trim() ?? "");
}

describe("WATCH live pill — A12", () => {
  it("paints 'live' ONLY when transportState=live AND price != null", async () => {
    vi.spyOn(marketData, "useLiveQuotes").mockReturnValue({
      AAPL: makeView({
        symbol: "AAPL",
        transportState: "live",
        price: 200,
        snapshot: { symbol: "AAPL" } as never,
      }),
      MSFT: makeView({
        symbol: "MSFT",
        // Transport reports live but the snapshot hasn't landed → must NOT
        // paint a live pill on this row.
        transportState: "live",
        price: null,
      }),
    });

    const { container } = render(<WATCHPane code="WATCH" symbol={undefined} />);
    await screen.findByText("AAPL");

    const labels = streamPillLabels(container);
    // Exactly one row should read "live" — AAPL.
    expect(labels.filter((l) => l === "live").length).toBe(1);
    // MSFT's row pill must NOT be live (will be "idle" — transport says
    // "live" but our guard demands price, and we fall through to
    // view?.transportState ?? "idle" if price is null).
    expect(labels.length).toBe(2);
  });

  it("falls through to 'snapshot' when price exists but transport != live", async () => {
    vi.spyOn(marketData, "useLiveQuotes").mockReturnValue({
      AAPL: makeView({
        symbol: "AAPL",
        transportState: "idle",
        price: 200,
        snapshot: { symbol: "AAPL" } as never,
      }),
      MSFT: makeView({
        symbol: "MSFT",
        transportState: "idle",
        price: 105,
        snapshot: { symbol: "MSFT" } as never,
      }),
    });

    const { container } = render(<WATCHPane code="WATCH" symbol={undefined} />);
    await screen.findByText("AAPL");

    const labels = streamPillLabels(container);
    expect(labels).not.toContain("live");
    expect(labels.filter((l) => l === "snapshot").length).toBe(2);
  });

  it("header LIVE count and per-row pills agree", async () => {
    vi.spyOn(marketData, "useLiveQuotes").mockReturnValue({
      AAPL: makeView({
        symbol: "AAPL",
        transportState: "live",
        price: 200,
        snapshot: { symbol: "AAPL" } as never,
      }),
      // 'live' transport but no price → must NOT bump the LIVE counter.
      MSFT: makeView({ symbol: "MSFT", transportState: "live", price: null }),
    });

    const { container } = render(<WATCHPane code="WATCH" symbol={undefined} />);
    await screen.findByText("AAPL");

    const header = headerPillLabels(container);
    expect(header).toContain("LIVE · 1");
    // Per-row: exactly one live pill.
    const rowLabels = streamPillLabels(container);
    expect(rowLabels.filter((l) => l === "live").length).toBe(1);
  });
});
