/**
 * DES transport-pill regression — Agent F a11y close-out.
 *
 * S12 already replaced HP/GP's misleading "RT SESSION" pill with the
 * canonical RT LIVE / RECONNECTING / STALE / SNAPSHOT ONLY / OFFLINE
 * set. DES was the holdover. This file pins three guarantees:
 *
 *  1. The literal "RT SESSION" is gone from DES.tsx.
 *  2. `useLiveQuote(effectiveSymbol)` is imported + invoked so the pill
 *     reflects honest transport state, not the historical-fetch outcome.
 *  3. `<TransportPill state={…}/>` actually renders the right text given
 *     each transport state.
 */
import { readFileSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, render } from "@testing-library/react";
import type { TransportState } from "@/lib/market-data";
import { DESPane } from "./DES";

const __dirname = dirname(fileURLToPath(import.meta.url));
const desSourceRaw = readFileSync(resolve(__dirname, "DES.tsx"), "utf-8");

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

vi.mock("@/lib/useFunction", () => ({
  useFunction: () => ({
    state: "ok",
    data: {
      status: "ok",
      data: {
        longName: "Apple Inc.",
        shortName: "Apple",
        regularMarketPrice: 302.5,
        previousClose: 300.0,
        regularMarketChangePercent: 0.83,
        exchange_name: "NASDAQ",
        sector: "Technology",
        status: "ok",
      },
      sources: ["yfinance"],
      elapsed_ms: 42,
    },
    error: null,
    refetch: vi.fn(),
  }),
}));

beforeEach(() => {
  resetMockQuoteState();
});
afterEach(() => {
  cleanup();
});

describe("DES transport pill (Agent F a11y close-out)", () => {
  it("source no longer contains the legacy 'RT SESSION' literal", () => {
    expect(desSourceRaw).not.toMatch(/RT\s+SESSION/);
  });

  it("source imports useLiveQuote and wires it into DESPane", () => {
    expect(desSourceRaw).toMatch(
      /import\s+\{[^}]*useLiveQuote[^}]*\}\s+from\s+["']@\/lib\/market-data["']/,
    );
    expect(desSourceRaw).toMatch(/useLiveQuote\(effectiveSymbol/);
  });

  it("renders RT LIVE pill when transport is actually live", () => {
    mockQuoteState.transportState = "live";
    mockQuoteState.lastTick = { price: 303.1, ts: Date.now() };
    const { container } = render(<DESPane code="DES" symbol="AAPL" />);
    const pill = container.querySelector('[data-testid="des-transport-pill"]');
    expect(pill).not.toBeNull();
    expect(pill?.getAttribute("data-state")).toBe("live");
    expect(pill?.textContent).toMatch(/RT LIVE/);
  });

  it("renders RECONNECTING when transport is reconnecting", () => {
    mockQuoteState.transportState = "reconnecting";
    const { container } = render(<DESPane code="DES" symbol="AAPL" />);
    const pill = container.querySelector('[data-testid="des-transport-pill"]');
    expect(pill?.getAttribute("data-state")).toBe("reconnecting");
    expect(pill?.textContent).toMatch(/RECONNECTING/);
  });

  it("renders STALE when transport is stale", () => {
    mockQuoteState.transportState = "stale";
    const { container } = render(<DESPane code="DES" symbol="AAPL" />);
    const pill = container.querySelector('[data-testid="des-transport-pill"]');
    expect(pill?.getAttribute("data-state")).toBe("stale");
    expect(pill?.textContent).toMatch(/STALE/);
  });

  it("renders OFFLINE when transport is offline", () => {
    mockQuoteState.transportState = "offline";
    const { container } = render(<DESPane code="DES" symbol="AAPL" />);
    const pill = container.querySelector('[data-testid="des-transport-pill"]');
    expect(pill?.getAttribute("data-state")).toBe("offline");
    expect(pill?.textContent).toMatch(/OFFLINE/);
  });

  it("renders SNAPSHOT ONLY when historical data is present but no live channel", () => {
    // idle transport + payloadStatus=ok + last != null → snapshot path.
    mockQuoteState.transportState = "idle";
    const { container } = render(<DESPane code="DES" symbol="AAPL" />);
    const pill = container.querySelector('[data-testid="des-transport-pill"]');
    expect(pill?.getAttribute("data-state")).toBe("snapshot");
    expect(pill?.textContent).toMatch(/SNAPSHOT ONLY/);
  });
});
