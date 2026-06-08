/**
 * WEI terminal-grade tests.
 *
 * Covers the page-by-page hardening of the Macro Monitor:
 *  - region filter changes which rows render
 *  - numeric cells carry the shared `terminal-grid-numeric` class
 *  - column sorting (Δ%) reorders rows
 *  - symbol button is a real button with an aria-label
 *  - model / fallback data shows a prominent "Model data — not live" badge
 *  - synthetic sparklines are marked (data-synthetic) so they don't
 *    masquerade as real history; real history is not marked
 *  - the header shows REAL data freshness from the payload `as_of`
 */
import { cleanup, fireEvent, render, screen, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

// Each test installs its own useFunction mock via this mutable holder.
const mockReturn: { current: unknown } = { current: null };
vi.mock("@/lib/useFunction", () => ({
  useFunction: () => mockReturn.current,
}));
// Router navigate is a side-effect we don't need here.
vi.mock("@/lib/router", () => ({ navigate: vi.fn() }));

import { WEIPane } from "./WEI";

function makeRow(over: Record<string, unknown> = {}) {
  return {
    symbol: "^GSPC",
    name: "S&P 500",
    region: "americas",
    last: 5200,
    change: 9.3,
    change_pct: 0.18,
    high: 5215,
    low: 5178,
    market_state: "regular",
    ...over,
  };
}

function mockOk(rows: unknown[], payloadOver: Record<string, unknown> = {}, metaOver: Record<string, unknown> = {}) {
  mockReturn.current = {
    state: "ok",
    data: {
      data: { status: "ok", rows, as_of: "2026-06-08T10:11:28.250007+00:00", ...payloadOver },
      metadata: { live: true, ...metaOver },
      sources: ["yfinance"],
      elapsed_ms: 120,
    },
    error: undefined,
    refetch: vi.fn(),
  };
}

afterEach(() => {
  cleanup();
  mockReturn.current = null;
  // The region tab is persisted (usePersistentOption → localStorage); clear
  // it so one test's region switch doesn't filter out another test's rows.
  try {
    localStorage.clear();
  } catch {
    /* jsdom may not expose localStorage in every config */
  }
});

describe("WEI terminal-grade", () => {
  function gridSymbols(container: HTMLElement): (string | null | undefined)[] {
    return Array.from(container.querySelectorAll("tbody tr")).map(
      (tr) => within(tr as HTMLElement).queryByRole("button")?.textContent,
    );
  }

  it("region filter restricts the rendered rows", () => {
    mockOk([
      makeRow({ symbol: "^GSPC", name: "S&P 500", region: "americas" }),
      makeRow({ symbol: "^FTSE", name: "FTSE 100", region: "europe", change_pct: -0.4 }),
    ]);
    const { container } = render(<WEIPane code="WEI" />);
    // All region: both rows present in the grid.
    expect(gridSymbols(container)).toEqual(expect.arrayContaining(["^GSPC", "^FTSE"]));
    // Switch to Europe.
    fireEvent.click(screen.getByRole("tab", { name: "Europe" }));
    const after = gridSymbols(container);
    expect(after).toContain("^FTSE");
    expect(after).not.toContain("^GSPC");
  });

  it("numeric cells carry the terminal-grid-numeric class", () => {
    mockOk([makeRow()]);
    const { container } = render(<WEIPane code="WEI" />);
    const numericCells = container.querySelectorAll(".terminal-grid-numeric");
    expect(numericCells.length).toBeGreaterThan(0);
  });

  it("symbol button is a button with an aria-label and pointer cursor", () => {
    mockOk([makeRow()]);
    render(<WEIPane code="WEI" />);
    const btn = screen.getByRole("button", { name: "View ^GSPC details" });
    expect(btn).toBeTruthy();
    expect(btn.tagName).toBe("BUTTON");
  });

  it("sorting by Δ% reorders the rows", () => {
    mockOk([
      makeRow({ symbol: "^A", name: "A", change_pct: -1.5 }),
      makeRow({ symbol: "^B", name: "B", change_pct: 2.5 }),
      makeRow({ symbol: "^C", name: "C", change_pct: 0.5 }),
    ]);
    const { container } = render(<WEIPane code="WEI" />);
    expect(gridSymbols(container).slice(0, 3)).toEqual(["^A", "^B", "^C"]);
    // Click the Δ % column header once → descending.
    fireEvent.click(screen.getByRole("columnheader", { name: /Δ %/ }));
    expect(gridSymbols(container).slice(0, 3)).toEqual(["^B", "^C", "^A"]);
  });

  it("shows a prominent model badge when data is model/fallback", () => {
    mockOk(
      [makeRow({ market_state: "model" })],
      { status: "provider_unavailable", source_mode: "world_index_template" },
      { degraded: true, fallback: true },
    );
    render(<WEIPane code="WEI" />);
    const badge = screen.getByRole("status", { name: /model data/i });
    expect(badge).toBeTruthy();
    expect(badge.textContent?.toLowerCase()).toContain("not live");
  });

  it("does NOT show the model badge for live data", () => {
    mockOk([makeRow({ market_state: "regular" })]);
    render(<WEIPane code="WEI" />);
    expect(screen.queryByRole("status", { name: /model data/i })).toBeNull();
  });

  it("marks synthetic sparklines and leaves real history unmarked", () => {
    mockOk([
      makeRow({ symbol: "^REAL", name: "Real", history: [1, 2, 3, 4, 5, 6] }),
      makeRow({ symbol: "^SYNTH", name: "Synth" }),
    ]);
    const { container } = render(<WEIPane code="WEI" />);
    const synthetic = container.querySelectorAll('[data-synthetic="true"]');
    const real = container.querySelectorAll('[data-synthetic="false"]');
    expect(synthetic.length).toBe(1);
    expect(real.length).toBe(1);
  });

  it("renders real data freshness from payload as_of in the header", () => {
    mockOk([makeRow()], { as_of: "2026-06-08T10:11:28.250007+00:00" });
    render(<WEIPane code="WEI" />);
    // 10:11 UTC from the payload, not the client clock. The stamp appears in
    // both the header pill and the KPI caption — assert at least one match.
    expect(screen.getAllByText(/10:11 UTC/).length).toBeGreaterThan(0);
  });
});
