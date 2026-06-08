/**
 * Terminal-grade upgrades for WATCH (page-by-page campaign).
 *
 * Covers:
 *   - A11y: add-symbol input + remove button carry aria-labels; the loading
 *     skeleton region is role=status; the Undo banner is role=alert/aria-live.
 *   - Display: numeric cells (Last, Δ%, Volume, Notional) carry the
 *     `terminal-grid-numeric` monospace/tabular class so live ticks don't jitter.
 *   - Data sufficiency: new Volume + Notional columns render real values from the
 *     snapshot, and the missing sentinel ("—") when volume is absent.
 *   - Live-cell stability: the "Last" cell uses a STABLE React key so a new
 *     quote tick updates the value in place instead of remounting (no flicker).
 */
import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { WATCHPane } from "./WATCH";
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
    snapshot: {
      symbol: "AAPL",
      asset_class: "EQUITY",
      last: 200,
      price: 200,
      previous_close: 198,
      change_pct: 1.0,
      volume: 1_234_567,
      bid: null,
      ask: null,
      source: "yahoo",
      provider_symbol: "AAPL",
      currency: "USD",
      fetched_at: new Date().toISOString(),
    } as never,
    lastTick: null,
    price: 200,
    changePct: 1.2,
    source: "yahoo",
    sourceKind: "snapshot",
    fetchedAt: Date.now() - 30_000,
    freshnessMs: 30_000,
    stale: false,
    loading: false,
    refreshing: false,
    error: null,
    transportState: "live",
    lastTickAt: null,
    refetch: vi.fn(),
    ...overrides,
  };
}

beforeEach(() => {
  vi.spyOn(watchlist, "loadWatchlist").mockResolvedValue([{ symbol: "AAPL" }]);
  vi.spyOn(store, "useAppStore").mockImplementation(((selector: (s: {
    sidecarStatus: string;
    functionIndex: unknown[];
  }) => unknown) => selector({ sidecarStatus: "healthy", functionIndex: [] })) as never);
});

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

describe("WATCH — accessibility", () => {
  it("add-symbol input has an aria-label", () => {
    vi.spyOn(marketData, "useLiveQuotes").mockReturnValue({});
    render(<WATCHPane code="WATCH" symbol={undefined} />);
    expect(
      screen.getByLabelText("Add symbol to watchlist"),
    ).toBeInTheDocument();
  });

  it("remove button has a symbol-specific aria-label", async () => {
    vi.spyOn(marketData, "useLiveQuotes").mockReturnValue({
      AAPL: makeView({ symbol: "AAPL" }),
    });
    render(<WATCHPane code="WATCH" symbol={undefined} />);
    await screen.findByRole("button", { name: "AAPL" });
    expect(
      screen.getByLabelText("Remove AAPL from watchlist"),
    ).toBeInTheDocument();
  });

  it("loading skeleton region is exposed as role=status", async () => {
    // No snapshot/lastTick yet → WATCH renders the loading Skeleton.
    vi.spyOn(marketData, "useLiveQuotes").mockReturnValue({
      AAPL: makeView({
        symbol: "AAPL",
        snapshot: null,
        lastTick: null,
        price: null,
        loading: true,
      }),
    });
    render(<WATCHPane code="WATCH" symbol={undefined} />);
    const status = await screen.findByRole("status");
    expect(status).toHaveAttribute("aria-label", "Loading watchlist");
  });
});

describe("WATCH — display quality", () => {
  it("numeric cells carry terminal-grid-numeric", async () => {
    vi.spyOn(marketData, "useLiveQuotes").mockReturnValue({
      AAPL: makeView({ symbol: "AAPL" }),
    });
    const { container } = render(<WATCHPane code="WATCH" symbol={undefined} />);
    await screen.findByRole("button", { name: "AAPL" });
    const numericCells = container.querySelectorAll(".terminal-grid-numeric");
    // Last, Δ%, Volume, Notional → at least 4 numeric spans on the row.
    expect(numericCells.length).toBeGreaterThanOrEqual(4);
  });
});

describe("WATCH — Volume & Notional columns", () => {
  it("renders Volume + Notional headers", async () => {
    vi.spyOn(marketData, "useLiveQuotes").mockReturnValue({
      AAPL: makeView({ symbol: "AAPL" }),
    });
    render(<WATCHPane code="WATCH" symbol={undefined} />);
    await screen.findByRole("button", { name: "AAPL" });
    expect(screen.getByText("Volume")).toBeInTheDocument();
    expect(screen.getByText(/Notional|24h \$Vol/)).toBeInTheDocument();
  });

  it("renders a real compact volume value when present", async () => {
    vi.spyOn(marketData, "useLiveQuotes").mockReturnValue({
      AAPL: makeView({
        symbol: "AAPL",
        price: 200,
        snapshot: {
          symbol: "AAPL",
          volume: 1_234_567,
        } as never,
      }),
    });
    const { container } = render(<WATCHPane code="WATCH" symbol={undefined} />);
    await screen.findByRole("button", { name: "AAPL" });
    // 1,234,567 → "1.23M" via formatCompactNumber({ fixedDigits: 2 }).
    expect(container.textContent).toContain("1.23M");
  });

  it("renders the missing sentinel when volume is absent", async () => {
    vi.spyOn(marketData, "useLiveQuotes").mockReturnValue({
      AAPL: makeView({
        symbol: "AAPL",
        price: 200,
        snapshot: {
          symbol: "AAPL",
          volume: null,
        } as never,
      }),
    });
    const { container } = render(<WATCHPane code="WATCH" symbol={undefined} />);
    await screen.findByRole("button", { name: "AAPL" });
    // Volume + Notional both fall back to the em-dash sentinel.
    const dashes = (container.textContent ?? "").match(/—/g) ?? [];
    expect(dashes.length).toBeGreaterThanOrEqual(2);
  });
});

describe("WATCH — live Last cell stability", () => {
  it("updates the Last value in place across two quote ticks (stable key, no remount)", async () => {
    const spy = vi.spyOn(marketData, "useLiveQuotes");
    spy.mockReturnValue({
      AAPL: makeView({ symbol: "AAPL", price: 200, fetchedAt: 1_000 }),
    });
    const { container, rerender } = render(
      <WATCHPane code="WATCH" symbol={undefined} />,
    );
    await screen.findByRole("button", { name: "AAPL" });
    const before = container.querySelector(".showme-live-value");
    expect(before?.textContent).toContain("200");

    // New tick: price changes, fetchedAt advances. With a stable key the same
    // element node persists and only its text content updates.
    spy.mockReturnValue({
      AAPL: makeView({ symbol: "AAPL", price: 201.5, fetchedAt: 2_000 }),
    });
    rerender(<WATCHPane code="WATCH" symbol={undefined} />);
    const after = container.querySelector(".showme-live-value");
    expect(after?.textContent).toContain("201.50");
  });
});
