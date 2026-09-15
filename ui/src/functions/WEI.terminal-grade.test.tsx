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
const mockTick = { current: 0 };
let lastFnArgs: Record<string, unknown> | undefined;
vi.mock("@/lib/useFunction", () => ({
  useFunction: (args: Record<string, unknown>) => {
    lastFnArgs = args;
    return mockReturn.current;
  },
}));
vi.mock("@/lib/useVisibilityTick", () => ({
  useVisibilityTick: () => mockTick.current,
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
  mockTick.current = 0;
  lastFnArgs = undefined;
  // The region tab is persisted (usePersistentOption → localStorage); clear
  // it so one test's region switch doesn't filter out another test's rows.
  try {
    localStorage.clear();
  } catch {
    /* jsdom may not expose localStorage in every config */
  }
});

function gridSymbols(container: HTMLElement): (string | null | undefined)[] {
  return Array.from(container.querySelectorAll("tbody tr")).map(
    (tr) => within(tr as HTMLElement).queryByRole("button")?.textContent,
  );
}

describe("WEI terminal-grade", () => {
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

  it("default-sorts by Δ vs previous close and cycles on header click", () => {
    mockOk([
      makeRow({ symbol: "^A", name: "A", change_pct: -1.5 }),
      makeRow({ symbol: "^B", name: "B", change_pct: 2.5 }),
      makeRow({ symbol: "^C", name: "C", change_pct: 0.5 }),
    ]);
    const { container } = render(<WEIPane code="WEI" />);
    // Default sort = Δ prev close descending (the board reads leaders first).
    expect(gridSymbols(container).slice(0, 3)).toEqual(["^B", "^C", "^A"]);
    // First header click cycles descending → ascending.
    fireEvent.click(screen.getByRole("columnheader", { name: /Δ prev close %/ }));
    expect(gridSymbols(container).slice(0, 3)).toEqual(["^A", "^C", "^B"]);
  });

  it("derives Δ vs previous close % from last/prev_close when change_pct is absent", () => {
    mockOk([
      makeRow({ symbol: "^D", name: "Derived", change_pct: undefined, change: undefined, last: 102, prev_close: 100 }),
    ]);
    render(<WEIPane code="WEI" />);
    // (102/100 − 1)×100 = +2.00% rendered by the shared DeltaChip (cell +
    // stripped/KPI derivations reuse the same value).
    expect(screen.getAllByText("+2.00%").length).toBeGreaterThan(0);
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

  it("KPI ribbon never paints unlabeled procedural trends (R2-F1)", () => {
    mockOk([
      makeRow({ symbol: "^AAA", change_pct: 0.4 }),
      makeRow({ symbol: "^BBB", change_pct: -0.3 }),
    ]);
    const { container } = render(<WEIPane code="WEI" />);
    const ribbon = container.querySelector('[aria-label="WEI KPI ribbon"]');
    expect(ribbon).toBeTruthy();
    // No row carries history → the ribbon must not draw ANY sparkline.
    expect(ribbon!.querySelectorAll("svg").length).toBe(0);

    mockOk([
      makeRow({ symbol: "^AAA", change_pct: 0.4, history: [1, 2, 3, 4, 5, 6] }),
      makeRow({ symbol: "^BBB", change_pct: -0.3, history: [6, 5, 4, 3, 2, 1] }),
    ]);
    const second = render(<WEIPane code="WEI" />);
    const ribbon2 = second.container.querySelector('[aria-label="WEI KPI ribbon"]');
    expect(ribbon2!.querySelectorAll("svg").length).toBeGreaterThan(0);
    // Every KPI spark is real history — nothing synthetic inside the ribbon.
    expect(ribbon2!.querySelectorAll('[data-synthetic="true"]').length).toBe(0);
  });

  it("renders real data freshness from payload as_of in the header", () => {
    mockOk([makeRow()], { as_of: "2026-06-08T10:11:28.250007+00:00" });
    render(<WEIPane code="WEI" />);
    // 10:11 UTC from the payload, not the client clock. The stamp appears in
    // both the header pill and the KPI caption — assert at least one match.
    expect(screen.getAllByText(/10:11 UTC/).length).toBeGreaterThan(0);
  });
});

describe("WEI visibility poll + honesty (live adoption)", () => {
  it("refetches on a visibility tick and keeps tick out of params", () => {
    mockOk([makeRow()]);
    const refetch = vi.fn();
    (mockReturn.current as { refetch: ReturnType<typeof vi.fn> }).refetch = refetch;
    const { rerender } = render(<WEIPane code="WEI" />);
    expect(refetch).not.toHaveBeenCalled();
    const before = JSON.stringify(lastFnArgs?.params ?? null);
    expect(before).not.toContain("tick");

    mockTick.current = 1;
    rerender(<WEIPane code="WEI" />);
    expect(refetch).toHaveBeenCalledTimes(1);
    // A tick in params would change the fetch key and wipe the pane to a
    // skeleton on every 30s poll (audit A3 WEI M).
    expect(JSON.stringify(lastFnArgs?.params ?? null)).toBe(before);
  });

  it("performance strip never paints a missing change as 0.00%", () => {
    mockOk([
      makeRow({ symbol: "^UP", name: "Up index", change_pct: 1.25 }),
      makeRow({ symbol: "^NA", name: "No data", change_pct: null, changePercent: null }),
    ]);
    const { container } = render(<WEIPane code="WEI" />);
    const strip = container.querySelector(
      '[aria-label="World index performance strip"]',
    ) as HTMLElement;
    expect(strip).not.toBeNull();
    // Tiles display the index symbol WITHOUT the Yahoo caret ("^") because it
    // reads like an up-arrow next to falling values (user report). The raw
    // symbol still rides the aria-label + navigation.
    expect(strip.textContent).toContain("UP");
    expect(strip.textContent).not.toContain("NA");
    expect(strip.textContent).not.toContain("0.00%");
  });

  it("maps live market_state to a healthy tone, not amber warn", () => {
    mockOk([makeRow({ symbol: "^LIVE", market_state: "live" })]);
    const { container } = render(<WEIPane code="WEI" />);
    const row = Array.from(container.querySelectorAll("tbody tr")).find((tr) =>
      tr.textContent?.includes("^LIVE"),
    );
    expect(row).toBeTruthy();
    expect(row?.querySelector(".ds-pill--tone-positive")).not.toBeNull();
    expect(row?.querySelector(".ds-pill--tone-warn")).toBeNull();
  });

  it("renders unresolved indices as explicit no-quote rows, never fake data", () => {
    // The backend now returns the FULL universe every cycle; symbols with
    // no quote carry last=null + market_state="unavailable". The pane must
    // show them as missing (—, warn pill, no sparkline) rather than
    // dropping the row or inventing numbers.
    mockOk([
      makeRow({ symbol: "^UP", name: "Up index", change_pct: 1.25 }),
      makeRow({
        symbol: "^NQ",
        name: "No quote index",
        last: undefined,
        price: undefined,
        change: undefined,
        change_pct: undefined,
        high: undefined,
        low: undefined,
        market_state: "unavailable",
      }),
    ]);
    const { container } = render(<WEIPane code="WEI" />);
    const row = Array.from(container.querySelectorAll("tbody tr")).find((tr) =>
      tr.textContent?.includes("^NQ"),
    );
    expect(row).toBeTruthy();
    expect(row?.textContent).toContain("—");
    expect(row?.querySelector(".ds-pill--tone-warn")).not.toBeNull();
    // No procedural sparkline may masquerade as history for a no-quote row.
    expect(row?.querySelector('[data-synthetic="true"]')).toBeNull();
    expect(row?.querySelector("svg")).toBeNull();
  });

  it("paints the whole global board from one payload (Asia + MEA present)", () => {
    mockOk([
      makeRow({ symbol: "^GSPC", name: "S&P 500", region: "americas" }),
      makeRow({ symbol: "^N225", name: "Nikkei 225", region: "asia", change_pct: -1.2 }),
      makeRow({ symbol: "XU100.IS", name: "BIST 100", region: "mea", change_pct: 0.4 }),
    ]);
    const { container } = render(<WEIPane code="WEI" />);
    const symbols = gridSymbols(container);
    expect(symbols).toEqual(expect.arrayContaining(["^GSPC", "^N225", "XU100.IS"]));
    // Region tabs still gate the board.
    fireEvent.click(screen.getByRole("tab", { name: "Asia" }));
    expect(gridSymbols(container)).toEqual(["^N225"]);
  });
});
