/**
 * B1 (campaign 2026-09-11 double) — systemic symbol affordances in
 * PaneChrome, adopted by every symbol-bound pane:
 *
 *   • "+ watch" toggle backed by the real watchlist store (add / remove,
 *     aria-pressed, and subscription to changes made elsewhere).
 *   • "set alert" navigation hand-off to `#/symbol/<sym>/ALRT`.
 *
 * Both render only when the pane is bound to a symbol; the live-quote
 * chip is mocked away (its own suite covers it) so the DOM here stays
 * deterministic.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen, waitFor, act } from "@testing-library/react";

import { PaneChrome } from "./PaneChrome";
import { useWorkspace } from "@/lib/workspace";
import { useAppStore } from "@/lib/store";
import { usePaneContractStore } from "@/lib/pane-contract-store";
import {
  addSymbol,
  clearWatchlist,
  loadWatchlist,
  removeSymbol,
  resetWatchlistStoreForTests,
} from "@/lib/watchlist";

vi.mock("@/lib/market-data", () => ({
  useLiveQuote: () => ({
    symbol: "DES",
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
  }),
}));

beforeEach(async () => {
  cleanup();
  await clearWatchlist();
  resetWatchlistStoreForTests();
  usePaneContractStore.setState({ byKey: {} });
  useWorkspace.setState({
    tree: { kind: "leaf", id: "L1", code: "DES", symbol: "AAPL" },
    focusedId: "L1",
  } as never);
  useAppStore.setState({
    functionIndex: [
      { code: "DES", name: "Description", category: "equity", description: "test" },
    ],
  } as never);
  window.location.hash = "#/";
});

afterEach(async () => {
  cleanup();
  await clearWatchlist();
  resetWatchlistStoreForTests();
});

describe("PaneChrome — watch toggle (B1)", () => {
  it("adds and removes the bound symbol with aria-pressed + store round-trip", async () => {
    render(<PaneChrome leafId="L1" code="DES" symbol="AAPL" />);
    const btn = screen.getByTestId("pane-chrome-watch");
    await waitFor(() => expect(btn.getAttribute("aria-pressed")).toBe("false"));
    expect(btn.getAttribute("title")).toBe("Add AAPL to watchlist");

    fireEvent.click(btn);
    await waitFor(() => expect(btn.getAttribute("aria-pressed")).toBe("true"));
    expect(btn.getAttribute("title")).toBe("Remove AAPL from watchlist");
    expect((await loadWatchlist()).map((r) => r.symbol)).toEqual(["AAPL"]);

    fireEvent.click(btn);
    await waitFor(() => expect(btn.getAttribute("aria-pressed")).toBe("false"));
    expect(await loadWatchlist()).toEqual([]);
  });

  it("reflects watchlist changes made outside the chrome (subscription)", async () => {
    render(<PaneChrome leafId="L1" code="DES" symbol="AAPL" />);
    const btn = screen.getByTestId("pane-chrome-watch");
    await waitFor(() => expect(btn.getAttribute("aria-pressed")).toBe("false"));

    await act(async () => {
      await addSymbol("aapl");
    });
    await waitFor(() => expect(btn.getAttribute("aria-pressed")).toBe("true"));

    await act(async () => {
      await removeSymbol("AAPL");
    });
    await waitFor(() => expect(btn.getAttribute("aria-pressed")).toBe("false"));
  });
});

describe("PaneChrome — set-alert action (B1)", () => {
  it("navigates to #/symbol/<sym>/ALRT and names the action", async () => {
    render(<PaneChrome leafId="L1" code="DES" symbol="MSFT" />);
    const btn = screen.getByTestId("pane-chrome-alert");
    expect(btn.getAttribute("title")).toBe("Set an alert for MSFT");
    expect(btn.getAttribute("aria-label")).toBe("Set an alert for MSFT");

    fireEvent.click(btn);
    expect(window.location.hash).toBe("#/symbol/MSFT/ALRT");
    // Let the watch store hydration settle (act-safe).
    await waitFor(() =>
      expect(screen.getByTestId("pane-chrome-watch").getAttribute("aria-pressed")).toBe(
        "false",
      ),
    );
  });
});

describe("PaneChrome — symbol affordances without a symbol (B1)", () => {
  it("renders neither watch nor alert affordance when unbound", () => {
    render(<PaneChrome leafId="L1" code="HOME" />);
    expect(screen.queryByTestId("pane-chrome-watch")).toBeNull();
    expect(screen.queryByTestId("pane-chrome-alert")).toBeNull();
  });
});
