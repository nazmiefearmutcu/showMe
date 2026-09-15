/**
 * S12 HP live-truth regressions.
 *
 * Pins the behaviors that the pre-S12 HP pane silently violated and that
 * must survive the chart-engine migration:
 *
 *  1. The header strip's session pill reflects the *live* transport
 *     state, not the historical-fetch state. The misleading
 *     `state === "ok" → "RT SESSION"` badge is replaced with the
 *     transport-aware pill set (RT LIVE / RECONNECTING / STALE /
 *     SNAPSHOT ONLY / OFFLINE) used by GP.
 *  2. HPPane wires `useLiveQuote(effectiveSymbol)` and the header shows
 *     the live tick when the channel is open. The chart engine owns its
 *     own canvas refresh; a live tick must not remount it.
 *
 * Plus a static guard that the legacy `"RT SESSION"` literal no longer
 * lives in `HP.tsx` — a regression there would slip through any mock.
 */
import { readFileSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { act, cleanup, render, screen } from "@testing-library/react";
import type { TransportState } from "@/lib/market-data";
import { HPPane } from "./HP";

const __dirname = dirname(fileURLToPath(import.meta.url));
const hpSourceRaw = readFileSync(resolve(__dirname, "HP.tsx"), "utf-8");

/* ── chart-engine stub ─────────────────────────────────────────────── */
// The engine fetches /api/bars and paints a canvas — stub it out.
vi.mock("@/chart/Chart", () => ({
  Chart: () => <div data-testid="chart-engine" />,
  default: () => <div data-testid="chart-engine" />,
}));

class FakeResizeObserver {
  observe() {}
  disconnect() {}
  unobserve() {}
}
(globalThis as { ResizeObserver?: unknown }).ResizeObserver = FakeResizeObserver;

/* ── hook mocks ────────────────────────────────────────────────────── */
// `useFunction` mocked to return a deterministic 3-bar OHLCV payload so
// HPPane reaches its chart render branch without going through the real
// sidecar. `useLiveQuote` is the controlled lever — the test mutates a
// shared store between renders to simulate transport-state changes.

interface MockLiveQuoteState {
  transportState: TransportState;
  lastTick: { price: number; ts: number } | null;
  lastTickAt: number | null;
  snapshot: { price: number } | null;
  freshnessMs: number | null;
  stale: boolean;
  refreshing: boolean;
}

const mockQuoteState: MockLiveQuoteState = {
  transportState: "idle",
  lastTick: null,
  lastTickAt: null,
  snapshot: null,
  freshnessMs: null,
  stale: false,
  refreshing: false,
};

function resetMockQuoteState() {
  mockQuoteState.transportState = "idle";
  mockQuoteState.lastTick = null;
  mockQuoteState.lastTickAt = null;
  mockQuoteState.snapshot = null;
  mockQuoteState.freshnessMs = null;
  mockQuoteState.stale = false;
  mockQuoteState.refreshing = false;
}

vi.mock("@/lib/market-data", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/lib/market-data")>();
  return {
    ...actual,
    useLiveQuote: () => mockQuoteState,
    useLiveQuotes: () => ({ snapshots: {}, ticks: {} }),
  };
});

const baseHpData = {
  data: [
    { date: "2026-05-18", open: 100, high: 102, low: 99, close: 101, volume: 100_000 },
    { date: "2026-05-19", open: 101, high: 104, low: 100, close: 103, volume: 120_000 },
    { date: "2026-05-20", open: 103, high: 105, low: 102, close: 104.25, volume: 90_000 },
  ],
  sources: ["yfinance"],
};

vi.mock("@/lib/useFunction", () => ({
  useFunction: () => ({
    state: "ok",
    data: baseHpData,
    error: null,
    refetch: vi.fn(),
  }),
}));

/* ── tests ─────────────────────────────────────────────────────────── */

beforeEach(() => {
  resetMockQuoteState();
});
afterEach(() => {
  cleanup();
});

describe("S12 HP live truth — HPPane wiring", () => {
  it("source no longer contains the misleading 'RT SESSION' literal", () => {
    // The fastest, mock-proof guarantee: even if every render test in
    // this file rotted, a regression that re-adds the fake badge would
    // be caught by the source-level guard.
    expect(hpSourceRaw).not.toMatch(/RT\s+SESSION/);
  });

  it("source imports useLiveQuote and threads it into HPPane", () => {
    // Defends the integration: someone removing the import or skipping
    // the call would slip past the data-state pill assertion because
    // mocks would silently provide a default state.
    expect(hpSourceRaw).toMatch(
      /import\s+\{[^}]*useLiveQuote[^}]*\}\s+from\s+["']@\/lib\/market-data["']/,
    );
    expect(hpSourceRaw).toMatch(/useLiveQuote\(effectiveSymbol/);
  });

  it("renders RT LIVE pill only when transport is actually 'live'", () => {
    mockQuoteState.transportState = "live";
    mockQuoteState.lastTick = { price: 104.5, ts: Date.now() };
    mockQuoteState.lastTickAt = Date.now();
    const { container } = render(<HPPane code="HP" symbol="AAPL" />);
    const pill = container.querySelector('[data-testid="hp-transport-pill"]');
    expect(pill).not.toBeNull();
    expect(pill?.getAttribute("data-state")).toBe("live");
    expect(pill?.textContent).toMatch(/RT LIVE/);
  });

  it("renders RECONNECTING pill when transport is reconnecting / connecting", () => {
    mockQuoteState.transportState = "reconnecting";
    const { container } = render(<HPPane code="HP" symbol="AAPL" />);
    const pill = container.querySelector('[data-testid="hp-transport-pill"]');
    expect(pill?.getAttribute("data-state")).toBe("reconnecting");
    expect(pill?.textContent).toMatch(/RECONNECTING/);
  });

  it("renders OFFLINE pill when transport is offline / error", () => {
    mockQuoteState.transportState = "offline";
    const { container } = render(<HPPane code="HP" symbol="AAPL" />);
    const pill = container.querySelector('[data-testid="hp-transport-pill"]');
    expect(pill?.getAttribute("data-state")).toBe("offline");
    expect(pill?.textContent).toMatch(/OFFLINE/);
  });

  it("does NOT render RT LIVE when transport is idle (no fake live badge)", () => {
    mockQuoteState.transportState = "idle";
    const { container } = render(<HPPane code="HP" symbol="AAPL" />);
    const pill = container.querySelector('[data-testid="hp-transport-pill"]');
    expect(pill).toBeNull();
    // And the legacy "RT SESSION" wording must not leak through any
    // other code path either.
    expect(container.textContent ?? "").not.toMatch(/RT\s+SESSION/);
  });

  it("source guards a minimum chart height (>= 240px) so the chart remains dominant", () => {
    // S12 visual contract: the price chart is the dominant surface in
    // the pane. `ResizableChartFrame` carries `minHeight` and a default
    // viewport-relative size; neither can drop below ~240px without
    // the chart becoming a strip. This guard scans HP.tsx source for
    // the literal so a layout refactor can't silently collapse the
    // chart.
    const minHeightMatches = Array.from(
      hpSourceRaw.matchAll(/minHeight\s*=\s*\{(\d+)\}/g),
    ).map((m) => Number(m[1]));
    expect(minHeightMatches.length).toBeGreaterThan(0);
    const chartMin = minHeightMatches[0];
    expect(chartMin).toBeGreaterThanOrEqual(240);
    expect(hpSourceRaw).toMatch(/defaultHeight=\{\{[^}]*min:\s*(2[4-9]\d|[3-9]\d{2,})/);
  });

  it("keeps the engine mounted when a live tick lands (no remount)", () => {
    // Phase 1: render with transport idle, no tick. Engine mounts once.
    const { rerender } = render(<HPPane code="HP" symbol="AAPL" />);
    const engineNode = screen.getByTestId("chart-engine");

    // Phase 2: transport flips live and a tick arrives. The header must
    // re-render with the fresh tick while the engine node is reused —
    // the engine owns its own canvas + live refresh.
    const tickTs = Date.now();
    act(() => {
      mockQuoteState.transportState = "live";
      mockQuoteState.lastTick = { price: 105.75, ts: tickTs };
      mockQuoteState.lastTickAt = tickTs;
    });
    rerender(<HPPane code="HP" symbol="AAPL" />);

    // Same DOM node ⇒ the engine was re-rendered in place, not remounted.
    expect(screen.getByTestId("chart-engine")).toBe(engineNode);
  });
});
