/**
 * SCAN scanner pane — terminal-grade upgrades (page-by-page campaign).
 *
 * SCAN is a trading scanner: a natural-language intent runs the backend
 * scanner (`/api/scanner/run`) and returns ranked symbol rows with phase
 * (A/B/C/D) decomposition. These tests pin the accessibility + state-honesty
 * behaviour added in the P1–P4 pass, with the scanner client mocked so the
 * suite is deterministic and never touches the sidecar.
 *
 * Covers:
 *   - renders without throwing (intent composer + Run button present)
 *   - A11y: Run button + each sample-intent quick action carry aria-labels
 *   - sort header click changes sort state (header reflects active sort)
 *   - filter-chip removal calls its onRemove (Phase C chip removed)
 *   - empty-results state shows the honest "no matches" message + a Retry
 *     affordance + a contextual suggestion line
 *   - results row: pressing Enter on the symbol launch affordance navigates
 *     to DES (keyboard parity with double-click)
 */
import {
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
  within,
} from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { SCANPane } from "./SCAN";
import * as scanner from "@/lib/scanner";
import * as router from "@/lib/router";
import type { ScanResult, ScanRow } from "@/lib/scanner";

function makeRow(overrides: Partial<ScanRow> = {}): ScanRow {
  return {
    symbol: "BTCUSDT",
    asset_class: "CRYPTO",
    direction: "LONG",
    confidence: 72,
    score: 1.234,
    timeframes: ["1h", "4h"],
    contributions: [],
    fine: { quote: { last: 65000, change_pct: 2.5 } },
    ...overrides,
  };
}

function makeResult(rows: ScanRow[]): ScanResult {
  return {
    intent: "crypto opportunities high conviction",
    universe_key: "CRYPTO_TOP",
    asset_class: "CRYPTO",
    timeframes: ["1h", "4h"],
    rows,
    phases: [{ name: "A", elapsed_ms: 12, output: {} }],
    elapsed_ms: 42,
    warnings: [],
  };
}

beforeEach(() => {
  vi.spyOn(scanner, "listUniverses").mockResolvedValue([
    { key: "CRYPTO_TOP", asset_class: "CRYPTO", size: 250 },
  ]);
  vi.spyOn(router, "navigate").mockImplementation(() => undefined);
});

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

describe("SCAN pane — render + a11y", () => {
  it("renders the intent composer and a labelled Run button without throwing", () => {
    vi.spyOn(scanner, "runScan").mockResolvedValue(makeResult([makeRow()]));
    render(<SCANPane code="SCAN" />);
    expect(
      screen.getByRole("button", { name: /run scan with current filters/i }),
    ).toBeInTheDocument();
  });

  it("gives every sample-intent quick action an aria-label", () => {
    vi.spyOn(scanner, "runScan").mockResolvedValue(makeResult([makeRow()]));
    render(<SCANPane code="SCAN" />);
    // The four SAMPLE_INTENTS each render a preset quick-action button.
    const presets = screen.getAllByRole("button", {
      name: /load preset intent:/i,
    });
    expect(presets.length).toBeGreaterThanOrEqual(4);
  });
});

describe("SCAN pane — sort headers", () => {
  it("changes the active sort when a sort header is clicked", async () => {
    vi.spyOn(scanner, "runScan").mockResolvedValue(
      makeResult([
        makeRow({ symbol: "BTCUSDT", confidence: 50, score: 2 }),
        makeRow({ symbol: "ETHUSDT", confidence: 90, score: 1 }),
      ]),
    );
    render(<SCANPane code="SCAN" />);
    fireEvent.click(
      screen.getByRole("button", { name: /run scan with current filters/i }),
    );
    await screen.findByText("BTCUSDT");

    // Default sort is "score". Clicking the Conf% header switches sort state.
    // The header button's accessible name comes from its visible text ("Conf %").
    const confHeader = screen.getByRole("button", { name: /conf %/i });
    fireEvent.click(confHeader);
    // Footer + filter chip both mirror the now-active "confidence" sort key.
    await waitFor(() =>
      expect(
        screen.getAllByText(/sort · confidence/i).length,
      ).toBeGreaterThanOrEqual(1),
    );
  });
});

describe("SCAN pane — filter chip removal", () => {
  it("removes the Phase C filter chip via its labelled close button", async () => {
    vi.spyOn(scanner, "runScan").mockResolvedValue(makeResult([makeRow()]));
    render(<SCANPane code="SCAN" />);
    // Phase C is on by default → a removable "PHASE C · FINE" chip exists.
    const removeC = screen.getByRole("button", {
      name: /remove filter phase c · fine/i,
    });
    fireEvent.click(removeC);
    await waitFor(() =>
      expect(
        screen.queryByRole("button", { name: /remove filter phase c · fine/i }),
      ).not.toBeInTheDocument(),
    );
  });
});

describe("SCAN pane — empty results honesty", () => {
  it("shows the honest no-match message, a suggestion, and a Retry action", async () => {
    const runSpy = vi
      .spyOn(scanner, "runScan")
      .mockResolvedValue(makeResult([]));
    render(<SCANPane code="SCAN" />);
    fireEvent.click(
      screen.getByRole("button", { name: /run scan with current filters/i }),
    );
    await screen.findByText(/no matches with current filters/i);
    // Contextual suggestion line.
    expect(
      screen.getByText(/relax/i),
    ).toBeInTheDocument();
    // Retry affordance re-runs the scan (plain "Retry", not "Reset & retry").
    runSpy.mockClear();
    const retry = screen.getByRole("button", { name: /^retry the scan$/i });
    fireEvent.click(retry);
    await waitFor(() => expect(runSpy).toHaveBeenCalled());
  });
});

describe("SCAN pane — reset & retry uses reset filters", () => {
  it("re-runs with the reset universe/phases, not the stale pre-reset closure", async () => {
    const runSpy = vi
      .spyOn(scanner, "runScan")
      .mockResolvedValue(makeResult([]));
    render(<SCANPane code="SCAN" />);
    // Wait for the universe override <select> to be populated, then pick a
    // non-default universe so the reset has something to clear.
    await waitFor(() =>
      expect(
        screen.getByRole("option", { name: /CRYPTO_TOP/i }),
      ).toBeInTheDocument(),
    );
    fireEvent.change(screen.getByDisplayValue("(auto from intent)"), {
      target: { value: "CRYPTO_TOP" },
    });
    // Disable Phase C and Phase D so the reset (which re-enables both) is
    // observable in the re-run's `phases` payload.
    fireEvent.click(screen.getByRole("button", { name: /^C · fine$/i }));
    fireEvent.click(screen.getByRole("button", { name: /^D · risk$/i }));

    // Run with the modified filters → empty result surfaces "Reset & retry".
    fireEvent.click(
      screen.getByRole("button", { name: /run scan with current filters/i }),
    );
    await screen.findByText(/no matches with current filters/i);

    // Sanity: the first run used the modified filters (universe set, no C/D).
    expect(runSpy).toHaveBeenLastCalledWith(
      expect.objectContaining({
        universe: "CRYPTO_TOP",
        phases: ["A", "B"],
      }),
      expect.anything(),
    );

    runSpy.mockClear();
    fireEvent.click(
      screen.getByRole("button", { name: /reset filters and retry the scan/i }),
    );
    // The re-run must use the RESET values: universe cleared (undefined) and
    // Phase C + D back on — proving run() did not read the stale closure.
    await waitFor(() => expect(runSpy).toHaveBeenCalledTimes(1));
    expect(runSpy).toHaveBeenLastCalledWith(
      expect.objectContaining({
        universe: undefined,
        phases: ["A", "B", "C", "D"],
      }),
      expect.anything(),
    );
  });
});

describe("SCAN pane — error retry", () => {
  it("offers a Retry action on scan failure that re-runs the scan", async () => {
    const runSpy = vi
      .spyOn(scanner, "runScan")
      .mockRejectedValueOnce(new Error("boom"));
    render(<SCANPane code="SCAN" />);
    fireEvent.click(
      screen.getByRole("button", { name: /run scan with current filters/i }),
    );
    await screen.findByText(/scan failed/i);
    runSpy.mockResolvedValue(makeResult([makeRow()]));
    const retry = screen.getByRole("button", { name: /retry the scan/i });
    fireEvent.click(retry);
    await waitFor(() => expect(runSpy).toHaveBeenCalledTimes(2));
  });
});

describe("SCAN pane — keyboard launch DES", () => {
  it("launches DES when Enter is pressed on a symbol launch affordance", async () => {
    vi.spyOn(scanner, "runScan").mockResolvedValue(
      makeResult([makeRow({ symbol: "BTCUSDT" })]),
    );
    render(<SCANPane code="SCAN" />);
    fireEvent.click(
      screen.getByRole("button", { name: /run scan with current filters/i }),
    );
    const symbolBtn = await screen.findByRole("button", {
      name: /open btcusdt in des/i,
    });
    fireEvent.keyDown(symbolBtn, { key: "Enter" });
    expect(router.navigate).toHaveBeenCalledWith("/symbol/BTCUSDT/DES");
  });

  it("launches DES exactly once on double-click of the symbol (no double-fire)", async () => {
    vi.spyOn(scanner, "runScan").mockResolvedValue(
      makeResult([makeRow({ symbol: "ETHUSDT" })]),
    );
    render(<SCANPane code="SCAN" />);
    fireEvent.click(
      screen.getByRole("button", { name: /run scan with current filters/i }),
    );
    const symbolBtn = await screen.findByRole("button", {
      name: /open ethusdt in des/i,
    });
    // Double-clicking the symbol button used to fire jumpToDES twice: once
    // from the button's onDoubleClick and once from the DataGrid row's
    // onRowDoubleClick (the event bubbled). stopPropagation() now stops it.
    fireEvent.doubleClick(symbolBtn);
    expect(router.navigate).toHaveBeenCalledWith("/symbol/ETHUSDT/DES");
    expect(router.navigate).toHaveBeenCalledTimes(1);
  });
});

describe("SCAN pane — data honesty", () => {
  it("renders only real backend rows (no stub/demo fallback rows)", async () => {
    // Backend returns exactly one row → grid shows exactly one symbol cell.
    vi.spyOn(scanner, "runScan").mockResolvedValue(
      makeResult([makeRow({ symbol: "SOLUSDT" })]),
    );
    render(<SCANPane code="SCAN" />);
    fireEvent.click(
      screen.getByRole("button", { name: /run scan with current filters/i }),
    );
    const grid = await screen.findByRole("table");
    expect(within(grid).getByText("SOLUSDT")).toBeInTheDocument();
    // No phantom rows: the only symbol launch affordance is the one we mocked.
    expect(
      screen.getAllByRole("button", { name: /in des$/i }),
    ).toHaveLength(1);
  });

  it("has no synthetic per-row Trend column (procedural data must not pose as real history)", async () => {
    vi.spyOn(scanner, "runScan").mockResolvedValue(
      makeResult([makeRow({ symbol: "SOLUSDT" })]),
    );
    const { container } = render(<SCANPane code="SCAN" />);
    fireEvent.click(
      screen.getByRole("button", { name: /run scan with current filters/i }),
    );
    const grid = await screen.findByRole("table");
    // The "Trend" column header was fed by a deterministic pseudo-random
    // series (not real price history) and has been removed entirely.
    expect(within(grid).queryByText("Trend")).not.toBeInTheDocument();
    expect(
      within(grid).queryByText("~Trend"),
    ).not.toBeInTheDocument();
    expect(
      within(grid).queryByText("Est"),
    ).not.toBeInTheDocument();
    // And there is no unlabeled synthetic per-row sparkline inside the grid:
    // the only allowed in-cell sparkline (Score) renders 4 points, while the
    // removed Trend sparkline drew 22. We simply require any remaining grid
    // sparkline to be explicitly marked if it ever carries procedural data.
    grid
      .querySelectorAll("svg")
      .forEach((svg) => {
        // A grid sparkline that is NOT marked synthetic must be derived from
        // the real per-row score, never the old procedural Trend series.
        expect(svg.getAttribute("data-synthetic")).not.toBe("true");
      });
    // Guard against a regression that re-introduces the column: the header
    // row now carries 8 columns (#, Symbol, Class, Dir, Conf %, Score,
    // Δ today, TFs) — the 9th "Trend" column is gone.
    const headerCells = container.querySelectorAll("thead th");
    expect(headerCells.length).toBe(8);
  });
});
