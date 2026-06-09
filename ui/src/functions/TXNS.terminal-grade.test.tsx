/**
 * TXNS terminal-grade quality pins — honesty + a11y + display close-out.
 *
 * Covers the page-by-page upgrade contracts:
 *   H1 — provenance disclosure renders (imported into local portfolio.db,
 *        not live broker fills / not bot trades) and surfaces the db source.
 *   H2 — each row's `source` shows in the grid.
 *   H3 — the `mode` cell carries the clarifying title / accessible label and
 *        never implies live trading.
 *   B-UI — "Son güncelleme" shows when generated_at is present.
 *   D1/D2 — numbers come from format.ts (a price rendered adaptively, not a
 *        bespoke truncation).
 *   A1 — DataGrid gets the ariaLabel "İşlem defteri".
 *   A2 — error state is an announced role=status region.
 *   A3 — clicking a sortable header fires onSort and toggles aria-sort,
 *        reordering rows.
 *   A5 — empty state distinguishes an empty portfolio.db from a filter miss.
 */
import { cleanup, fireEvent, render, screen, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { StateRead, StateTrade } from "@/lib/state";

// listTrades is the only network seam — mock it so the suite is deterministic.
const listTradesMock = vi.fn();
vi.mock("@/lib/state", () => ({
  listTrades: (...args: unknown[]) => listTradesMock(...args),
}));

// router.navigate has a real side effect (history push); stub it.
vi.mock("@/lib/router", () => ({ navigate: vi.fn() }));

import { TXNSPane } from "./TXNS";

const SAMPLE: StateTrade[] = [
  {
    id: 1,
    trade_id: "t1",
    symbol: "AAPL",
    side: "LONG",
    quantity: 10,
    entry_price: 180.5,
    exit_price: 195.25,
    realized_pnl: 147.5,
    opened_at: "2026-04-01T10:00:00Z",
    closed_at: "2026-04-15T16:00:00Z",
    mode: "read_only",
    source: "showme_import",
  },
  {
    id: 2,
    trade_id: "t2",
    symbol: "MSFT",
    side: "SHORT",
    quantity: 5,
    entry_price: 410,
    exit_price: 400,
    realized_pnl: -50,
    opened_at: "2026-05-01T10:00:00Z",
    closed_at: "2026-05-10T16:00:00Z",
    mode: "writable",
    source: "showme_import",
  },
];

function trades(rows: StateTrade[], over: Partial<StateRead<StateTrade>> = {}) {
  return {
    rows,
    total: rows.length,
    source: "/Users/x/.showme/portfolio.db",
    generated_at: "2026-06-09T12:34:00Z",
    ...over,
  } satisfies StateRead<StateTrade>;
}

/** Resolve listTrades with the given payload and wait for the grid to paint. */
async function renderWith(payload: StateRead<StateTrade>) {
  listTradesMock.mockResolvedValue(payload);
  const utils = render(<TXNSPane code="TXNS" symbol="" />);
  await screen.findByLabelText("İşlem defteri");
  return utils;
}

beforeEach(() => {
  listTradesMock.mockReset();
});

afterEach(() => {
  cleanup();
});

describe("TXNS terminal-grade", () => {
  it("H1: renders an honest import-provenance disclosure with the db source", async () => {
    await renderWith(trades(SAMPLE));
    const note = screen.getByTestId("txns-provenance");
    expect(note).toBeInTheDocument();
    const text = note.textContent ?? "";
    expect(text).toMatch(/portfolio\.db/);
    expect(text).toMatch(/içe aktarıl/i); // "imported"
    expect(text).toMatch(/değildir/i); // "...is NOT (live/bot)"
    // The db source path the API returned is surfaced.
    expect(text).toContain("/Users/x/.showme/portfolio.db");
  });

  it("H2: surfaces each row's source", async () => {
    await renderWith(trades(SAMPLE));
    const cells = screen.getAllByTestId("txns-source-cell");
    expect(cells.length).toBe(2);
    expect(cells[0].textContent).toBe("showme_import");
  });

  it("H3: mode cell clarifies writable != live trading", async () => {
    await renderWith(trades(SAMPLE));
    const modeCells = screen.getAllByTestId("txns-mode-cell");
    // The clarifying tooltip + accessible label spell out that it is a DB
    // record flag, NOT a live trade.
    expect(modeCells[0]).toHaveAttribute(
      "title",
      expect.stringContaining("canlı işlem anlamına gelmez"),
    );
    expect(modeCells[1].getAttribute("aria-label")).toMatch(/writable/);
    expect(modeCells[1].getAttribute("aria-label")).toMatch(
      /canlı işlem anlamına gelmez/,
    );
  });

  it("B-UI: shows a 'Son güncelleme' freshness indicator when generated_at is present", async () => {
    await renderWith(trades(SAMPLE));
    const fresh = screen.getByTestId("txns-last-updated");
    expect(fresh.textContent).toMatch(/Son güncelleme:/);
    // A real clock value, not the missing-sentinel em-dash.
    expect(fresh.textContent).not.toMatch(/Son güncelleme:\s*—/);
  });

  it("B-UI: freshness falls back to '—' when generated_at is absent", async () => {
    await renderWith(trades(SAMPLE, { generated_at: undefined }));
    expect(screen.getByTestId("txns-last-updated").textContent).toMatch(
      /Son güncelleme:\s*—/,
    );
  });

  it("D1/D2: prices render via format.ts (adaptive) not bespoke truncation", async () => {
    await renderWith(trades(SAMPLE));
    // formatPrice(180.5) -> "180.50" (>=1 => 2dp), never the raw "180.5".
    expect(screen.getByText("180.50")).toBeInTheDocument();
    expect(screen.getByText("195.25")).toBeInTheDocument();
    // Numeric cells wear the terminal-grid-numeric class (tabular mono).
    expect(
      document.querySelectorAll(".terminal-grid-numeric").length,
    ).toBeGreaterThan(0);
  });

  it("A1: passes ariaLabel to the DataGrid", async () => {
    await renderWith(trades(SAMPLE));
    expect(screen.getByLabelText("İşlem defteri")).toBeInTheDocument();
  });

  it("A1: symbol button has a descriptive aria-label", async () => {
    await renderWith(trades(SAMPLE));
    expect(
      screen.getByRole("button", { name: "AAPL detayları" }),
    ).toBeInTheDocument();
  });

  it("A2: async error renders an announced role=status region", async () => {
    listTradesMock.mockRejectedValue(new Error("sidecar down"));
    render(<TXNSPane code="TXNS" symbol="" />);
    const err = await screen.findByTestId("txns-error");
    expect(err).toHaveAttribute("role", "status");
    expect(err.className).toMatch(/u-text-negative/);
    expect(err.textContent).toMatch(/sidecar down/);
  });

  it("A3: clicking a sortable header fires onSort, sets aria-sort, and reorders rows", async () => {
    await renderWith(trades(SAMPLE));
    const grid = screen.getByLabelText("İşlem defteri");
    const symbolsNow = () =>
      Array.from(grid.querySelectorAll("tbody .u-symbol-link")).map(
        (el) => el.textContent,
      );

    // Default sort is closed_at descending: MSFT (May) before AAPL (April).
    expect(symbolsNow()).toEqual(["MSFT", "AAPL"]);

    // Click the Realized header → descending P&L → AAPL (+147.5) first.
    const realizedHeader = within(grid).getByText("Realized");
    fireEvent.click(realizedHeader);
    const realizedTh = realizedHeader.closest("th");
    expect(realizedTh).toHaveAttribute("aria-sort", "descending");
    expect(symbolsNow()).toEqual(["AAPL", "MSFT"]);

    // Click again → ascending P&L → MSFT (-50) first.
    fireEvent.click(realizedHeader);
    expect(realizedTh).toHaveAttribute("aria-sort", "ascending");
    expect(symbolsNow()).toEqual(["MSFT", "AAPL"]);
  });

  it("A5: empty portfolio.db reads differently from a filtered-out result", async () => {
    // Empty db: 0 total rows. The grid never renders, so wait on the message.
    listTradesMock.mockResolvedValue(trades([], { total: 0 }));
    const { unmount } = render(<TXNSPane code="TXNS" symbol="" />);
    expect(await screen.findByText(/portfolio\.db boş/i)).toBeInTheDocument();
    unmount();

    // Rows exist but the current filter matched none.
    listTradesMock.mockResolvedValue(trades([], { total: 7 }));
    render(<TXNSPane code="TXNS" symbol="" />);
    expect(
      await screen.findByText(/Filtreyle eşleşen yok/i),
    ).toBeInTheDocument();
    expect(screen.getByText(/7 kayıt var/)).toBeInTheDocument();
  });
});
