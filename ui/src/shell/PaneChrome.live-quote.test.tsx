/**
 * PaneChrome live quote chip (campaign 2026-09-08, Lane B / U2).
 *
 * The header chip subscribes via the existing `useLiveQuote` hook. Honesty
 * contract pinned here:
 *   - price present  → price in display ink + signed directional delta.
 *   - price missing  → NO chip at all (the plain bound symbol stays the
 *     truth — no fake price, no optimistic fill-in).
 *   - changePct null → price without a delta row.
 * The hook itself is module-mocked; its real behaviour is covered by
 * lib/market-data.test.ts and the tape-health integration test.
 */
import { describe, expect, it, vi, beforeEach } from "vitest";
import { cleanup, render, screen } from "@testing-library/react";

import { PaneChrome } from "./PaneChrome";
import { useWorkspace } from "@/lib/workspace";
import { useAppStore } from "@/lib/store";
import { usePaneContractStore } from "@/lib/pane-contract-store";
import type { QuoteView } from "@/lib/market-data";
import { useLiveQuote } from "@/lib/market-data";

vi.mock("@/lib/market-data", () => ({
  useLiveQuote: vi.fn(),
}));

const mockedUseLiveQuote = vi.mocked(useLiveQuote);

function quoteView(overrides: Partial<QuoteView>): QuoteView {
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
    refetch: () => undefined,
    ...overrides,
  };
}

beforeEach(() => {
  cleanup();
  vi.clearAllMocks();
  usePaneContractStore.setState({ byKey: {} });
  useWorkspace.setState({
    tree: { kind: "leaf", id: "L1", code: "GP", symbol: "AAPL" },
    focusedId: "L1",
  } as never);
  useAppStore.setState({
    functionIndex: [
      { code: "GP", name: "Generic Price", category: "charts_tech", description: "test" },
    ],
  } as never);
});

describe("PaneChrome — live quote chip", () => {
  it("renders price + signed delta with transport state when live", () => {
    mockedUseLiveQuote.mockReturnValue(
      quoteView({ price: 101.23, changePct: 1.24, transportState: "live" }),
    );
    render(<PaneChrome leafId="L1" code="GP" symbol="AAPL" />);
    const chip = screen.getByTestId("pane-chrome-quote");
    expect(chip.getAttribute("data-transport")).toBe("live");
    expect(chip.textContent).toContain("101.23");
    const delta = chip.querySelector(".pane-chrome__quote-delta--up");
    expect(delta).not.toBeNull();
    expect(delta?.textContent).toContain("+1.24%");
  });

  it("renders a downward delta for negative change", () => {
    mockedUseLiveQuote.mockReturnValue(
      quoteView({ price: 98.1, changePct: -0.55, transportState: "live" }),
    );
    render(<PaneChrome leafId="L1" code="GP" symbol="AAPL" />);
    const chip = screen.getByTestId("pane-chrome-quote");
    expect(chip.querySelector(".pane-chrome__quote-delta--down")).not.toBeNull();
    expect(chip.textContent).toContain("-0.55%");
  });

  it("no price yet → chip absent entirely (plain symbol remains the truth)", () => {
    mockedUseLiveQuote.mockReturnValue(
      quoteView({ transportState: "reconnecting" }),
    );
    render(<PaneChrome leafId="L1" code="GP" symbol="AAPL" />);
    expect(screen.queryByTestId("pane-chrome-quote")).toBeNull();
    // The bound symbol string is still rendered.
    expect(screen.getByText("AAPL")).toBeTruthy();
  });

  it("price without changePct renders price only, no delta", () => {
    mockedUseLiveQuote.mockReturnValue(
      quoteView({ price: 42, changePct: null, transportState: "live" }),
    );
    render(<PaneChrome leafId="L1" code="GP" symbol="AAPL" />);
    const chip = screen.getByTestId("pane-chrome-quote");
    expect(chip.textContent).toContain("42.00");
    expect(chip.querySelector(".pane-chrome__quote-delta")).toBeNull();
  });

  it("pane without a symbol never mounts a chip (no subscriptions)", () => {
    useWorkspace.setState({
      tree: { kind: "leaf", id: "L1", code: "HOME" },
      focusedId: "L1",
    } as never);
    render(<PaneChrome leafId="L1" code="HOME" />);
    expect(mockedUseLiveQuote).not.toHaveBeenCalled();
    expect(screen.queryByTestId("pane-chrome-quote")).toBeNull();
  });
});
