/**
 * B1b — ALRT route-bound seeding (campaign 2026-09-11 double).
 *
 * `PaneChrome`'s "set alert" action navigates to `#/symbol/<sym>/ALRT`.
 * This pane used to ignore the route symbol entirely (deferral note in
 * lane-B1.md); these specs pin the wired behaviour:
 *
 *  - the route symbol prefills the Symbol field (normalized);
 *  - the Threshold seeds FROM THE LIVE QUOTE (the same multiplexed
 *    `useLiveQuote` source the pane chrome header uses) — once;
 *  - no quote → blank threshold + an honest hint (loading vs unavailable),
 *    never a fabricated price;
 *  - a manual edit is never clobbered by a later quote tick;
 *  - submitting the seeded form creates a real alert row;
 *  - unbound panes (`#/fn/ALRT`) mount no seed bridge at all.
 */
import { render, screen, act, fireEvent } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("@/lib/quotes", () => ({
  fetchQuote: vi.fn(),
}));
vi.mock("@/lib/tauri", () => ({
  invoke: vi.fn(async () => undefined),
  isInTauri: vi.fn(() => false),
}));
vi.mock("@/lib/toast", () => ({
  toast: { info: vi.fn(), success: vi.fn(), warn: vi.fn(), error: vi.fn() },
}));
vi.mock("@/lib/confirm", () => ({ confirmAction: vi.fn(async () => true) }));
// Keep the real module (normalizeSymbol etc.) — only the live hook is driven.
vi.mock("@/lib/market-data", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/lib/market-data")>();
  return { ...actual, useLiveQuote: vi.fn() };
});

import { ALRTPane } from "./ALRT";
import { useLiveQuote, type QuoteView } from "@/lib/market-data";
import { clearAlerts, loadAlerts } from "@/lib/alerts";

const mockedUseLiveQuote = vi.mocked(useLiveQuote);

function quoteView(overrides: Partial<QuoteView> = {}): QuoteView {
  return {
    symbol: "MSFT",
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
    refetch: () => undefined,
    ...overrides,
  };
}

async function flush() {
  await act(async () => {
    for (let i = 0; i < 6; i++) await Promise.resolve();
  });
}

async function mount(symbol?: string) {
  let utils!: ReturnType<typeof render>;
  await act(async () => {
    utils = render(<ALRTPane code="ALRT" symbol={symbol} />);
  });
  await flush();
  return utils;
}

function symbolInput(): HTMLInputElement {
  return screen.getByLabelText(/symbol/i) as HTMLInputElement;
}

function thresholdInput(): HTMLInputElement {
  return screen.getByLabelText(/threshold/i) as HTMLInputElement;
}

beforeEach(async () => {
  await clearAlerts();
  mockedUseLiveQuote.mockReset();
});

afterEach(() => {
  vi.clearAllMocks();
});

describe("ALRT route-bound seeding (B1b)", () => {
  it("prefills the symbol field from the route and seeds the threshold from the live quote", async () => {
    mockedUseLiveQuote.mockReturnValue(
      quoteView({ price: 417.11, source: "yahoo", sourceKind: "snapshot" }),
    );
    await mount("msft");

    expect(symbolInput().value).toBe("MSFT");
    expect(thresholdInput().value).toBe("417.11");
    expect(screen.getByText(/seeded from the live MSFT price/i)).toBeTruthy();
    // The seed rides the same multiplexed live channel as the pane chrome.
    expect(mockedUseLiveQuote).toHaveBeenCalledWith("MSFT");
  });

  it("leaves the threshold blank with an honest hint when there is no quote", async () => {
    mockedUseLiveQuote.mockReturnValue(
      quoteView({ error: "provider unavailable" }),
    );
    await mount("MSFT");

    expect(symbolInput().value).toBe("MSFT");
    expect(thresholdInput().value).toBe("");
    expect(screen.getByText(/no live MSFT price/i)).toBeTruthy();
  });

  it("shows a waiting hint while the quote loads (no false 'no quote' claim)", async () => {
    mockedUseLiveQuote.mockReturnValue(quoteView({ loading: true }));
    await mount("MSFT");

    expect(thresholdInput().value).toBe("");
    expect(screen.getByText(/waiting for the live MSFT price/i)).toBeTruthy();
  });

  it("manual edits survive later quote ticks", async () => {
    mockedUseLiveQuote.mockReturnValue(quoteView({ price: 417.11 }));
    const utils = await mount("MSFT");
    expect(thresholdInput().value).toBe("417.11");

    fireEvent.change(thresholdInput(), { target: { value: "500" } });
    expect(thresholdInput().value).toBe("500");

    // A newer quote arrives — the trader's 500 must survive, and the seed
    // hint retires once the input is manually owned.
    mockedUseLiveQuote.mockReturnValue(quoteView({ price: 420.5 }));
    await act(async () => {
      utils.rerender(<ALRTPane code="ALRT" symbol="MSFT" />);
    });
    await flush();

    expect(thresholdInput().value).toBe("500");
    expect(screen.queryByText(/seeded from the live/i)).toBeNull();
  });

  it("submits the seeded form as a real alert row", async () => {
    mockedUseLiveQuote.mockReturnValue(quoteView({ price: 417.11 }));
    await mount("MSFT");

    fireEvent.click(screen.getByTestId("alrt-add-btn"));
    await flush();

    const rows = await loadAlerts();
    expect(rows).toHaveLength(1);
    expect(rows[0].symbol).toBe("MSFT");
    expect(rows[0].threshold).toBeCloseTo(417.11);
    expect(rows[0].direction).toBe("above");
  });

  it("no route symbol → no prefill, no seed, no bridge subscription", async () => {
    mockedUseLiveQuote.mockReturnValue(quoteView({ price: 100 }));
    await mount();

    expect(symbolInput().value).toBe("");
    expect(thresholdInput().value).toBe("");
    expect(mockedUseLiveQuote).not.toHaveBeenCalled();
    expect(screen.queryByText(/seeded from the live/i)).toBeNull();
  });

  it("R1-1: switching MSFT → AAPL reseeds from AAPL, never keeps the MSFT price", async () => {
    // Keyed quote source: the bridge must report the CURRENT symbol's value.
    mockedUseLiveQuote.mockImplementation((sym: string | null | undefined) =>
      quoteView({ symbol: sym ?? "", price: sym === "MSFT" ? 417.11 : 201.5 }),
    );
    const utils = await mount("MSFT");
    expect(thresholdInput().value).toBe("417.11");
    expect(screen.getByText(/seeded from the live MSFT price/i)).toBeTruthy();

    // Workspace reuses the mounted pane across symbol switches (no key), so
    // only the routeSym prop changes.
    await act(async () => {
      utils.rerender(<ALRTPane code="ALRT" symbol="AAPL" />);
    });
    await flush();

    expect(symbolInput().value).toBe("AAPL");
    // The previous closure's MSFT seed must be inert — AAPL's own value wins.
    expect(thresholdInput().value).not.toBe("417.11");
    expect(thresholdInput().value).toBe("201.5");
    expect(screen.getByText(/seeded from the live AAPL price/i)).toBeTruthy();
    expect(screen.queryByText(/seeded from the live MSFT price/i)).toBeNull();
  });

  it("R1-1: switching to a symbol with no quote leaves the threshold blank (MSFT price never sticks)", async () => {
    mockedUseLiveQuote.mockImplementation((sym: string | null | undefined) =>
      sym === "MSFT"
        ? quoteView({ symbol: sym, price: 417.11 })
        : quoteView({ symbol: sym ?? "", error: "provider unavailable" }),
    );
    const utils = await mount("MSFT");
    expect(thresholdInput().value).toBe("417.11");

    await act(async () => {
      utils.rerender(<ALRTPane code="ALRT" symbol="AAPL" />);
    });
    await flush();

    expect(symbolInput().value).toBe("AAPL");
    expect(thresholdInput().value).toBe("");
    expect(screen.getByText(/no live AAPL price/i)).toBeTruthy();
    expect(screen.queryByText(/417\.11/)).toBeNull();
  });
});
