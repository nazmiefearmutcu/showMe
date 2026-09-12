/**
 * CACT pane — filter interaction + data-honesty tests.
 *
 * The backend CACT merges yfinance dividends/splits with SEC 8-K rows into a
 * sorted timeline; when both providers fail it returns a single
 * provider_unavailable row carrying a reason. These tests pin:
 *
 *  - the load states (loading / provider-unavailable) render honestly;
 *  - an OK mixed payload renders dividend, split and 8-K rows;
 *  - the TYPE chips filter the table (dividend-only view);
 *  - the WINDOW control splits past vs upcoming with an honest empty state.
 *
 * `useFunction` is mocked via a mutable shared state so each test drives
 * the pane into a specific branch without the real sidecar transport.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, render, screen, fireEvent } from "@testing-library/react";
import { CACTPane } from "./CACT";

/* ── useFunction mock ──────────────────────────────────────────────── */

interface MockFnState {
  state: "idle" | "loading" | "ok" | "error" | "refreshing";
  data?: { data?: unknown } | undefined;
  error?: Error | null;
}

const mockFn: MockFnState = { state: "idle", data: undefined, error: null };

function setMockFn(next: MockFnState) {
  mockFn.state = next.state;
  mockFn.data = next.data;
  mockFn.error = next.error ?? null;
}

vi.mock("@/lib/useFunction", () => ({
  useFunction: () => ({
    state: mockFn.state,
    data: mockFn.data,
    error: mockFn.error,
    refetch: vi.fn(),
  }),
}));

// SymbolBar pulls router/symbol-resolver side effects we don't need here.
vi.mock("@/shell/SymbolBar", () => ({
  SymbolBar: () => null,
}));

/* ── fixtures ──────────────────────────────────────────────────────── */

function mixedPayload() {
  return {
    data: {
      data: {
        status: "ok",
        rows: [
          {
            symbol: "AAPL",
            action_type: "dividend",
            event_date: "2026-08-10",
            value: 0.26,
            unit: "cash/share",
            source_mode: "live_yfinance",
          },
          {
            symbol: "AAPL",
            action_type: "split",
            event_date: "2027-01-15",
            value: 4,
            unit: "split ratio",
            source_mode: "live_yfinance",
          },
          {
            symbol: "AAPL",
            action_type: "8-k",
            event_date: "2026-07-31",
            value: "2.02",
            source_mode: "sec_edgar_8k",
            accession: "0000320193-26-000042",
            document: "a8-kq32026.htm",
          },
        ],
        methodology: "CACT normalizes Yahoo dividends/splits plus SEC 8-K rows.",
      },
    },
  };
}

function providerDownPayload() {
  return {
    data: {
      data: {
        status: "provider_unavailable",
        rows: [
          {
            symbol: "AAPL",
            action_type: "provider_unavailable",
            event_date: null,
            value: null,
            source_mode: "corporate_actions_unavailable",
            reason: "No dividend, split, or dated 8-K corporate-action rows were returned.",
          },
        ],
      },
    },
  };
}

/* ── tests ─────────────────────────────────────────────────────────── */

beforeEach(() => {
  localStorage.clear();
  setMockFn({ state: "idle", data: undefined });
});
afterEach(() => {
  cleanup();
  localStorage.clear();
});

describe("CACT pane — load states", () => {
  it("renders a skeleton while loading", () => {
    setMockFn({ state: "loading", data: undefined });
    const { container } = render(<CACTPane code="CACT" symbol="AAPL" />);
    expect(container.querySelector('[aria-busy="true"]')).not.toBeNull();
  });

  it("renders the error state when the fetch errors", () => {
    setMockFn({
      state: "error",
      data: undefined,
      error: new Error("sidecar exploded"),
    });
    render(<CACTPane code="CACT" symbol="AAPL" />);
    expect(screen.getByText(/sidecar exploded/i)).toBeInTheDocument();
  });

  it("renders the honest provider-unavailable state with the backend reason", () => {
    setMockFn({ state: "ok", ...providerDownPayload() });
    render(<CACTPane code="CACT" symbol="AAPL" />);
    expect(screen.getByText(/No corporate actions returned/i)).toBeInTheDocument();
    expect(
      screen.getByText(/No dividend, split, or dated 8-K corporate-action rows/i),
    ).toBeInTheDocument();
  });
});

describe("CACT pane — actions table", () => {
  it("renders dividend, split and 8-K rows from the payload", () => {
    setMockFn({ state: "ok", ...mixedPayload() });
    const { container } = render(<CACTPane code="CACT" symbol="AAPL" />);
    expect(container.textContent).toContain("2026-08-10");
    expect(container.textContent).toContain("2027-01-15");
    expect(container.textContent).toContain("0000320193-26-000042");
  });
});

describe("CACT pane — filter interactions", () => {
  it("filters the table to dividends when the DIV chip is active", () => {
    setMockFn({ state: "ok", ...mixedPayload() });
    const { container } = render(<CACTPane code="CACT" symbol="AAPL" />);

    fireEvent.click(screen.getByText("DIV"));

    const table = container.querySelector(
      '[aria-label="CACT corporate actions table"]',
    );
    expect(table?.textContent).toContain("2026-08-10");
    expect(table?.textContent).not.toContain("2027-01-15");
    expect(table?.textContent).not.toContain("0000320193-26-000042");
  });

  it("shows the upcoming window only for future-dated rows", () => {
    setMockFn({ state: "ok", ...mixedPayload() });
    const { container } = render(<CACTPane code="CACT" symbol="AAPL" />);

    // The WINDOW segmented control carries a descriptive aria-label.
    const windowGroup = container.querySelector(
      '[aria-label="Past vs upcoming"]',
    );
    expect(windowGroup).not.toBeNull();
    const upcomingBtn = Array.from(windowGroup!.querySelectorAll("button")).find(
      (b) => b.textContent === "UPCOMING",
    );
    expect(upcomingBtn).toBeDefined();
    fireEvent.click(upcomingBtn!);

    const table = container.querySelector(
      '[aria-label="CACT corporate actions table"]',
    );
    expect(table?.textContent).toContain("2027-01-15");
    expect(table?.textContent).not.toContain("2026-08-10");
  });

  it("states outright when no upcoming actions exist in provider data", () => {
    const pastOnly = mixedPayload();
    (pastOnly.data.data as { rows: Array<{ event_date: string | null }> }).rows =
      (pastOnly.data.data as { rows: Array<{ event_date: string | null }> }).rows.filter(
        (r) => r.event_date !== "2027-01-15",
      );
    setMockFn({ state: "ok", ...pastOnly });
    const { container } = render(<CACTPane code="CACT" symbol="AAPL" />);

    const windowGroup = container.querySelector(
      '[aria-label="Past vs upcoming"]',
    );
    const upcomingBtn = Array.from(windowGroup!.querySelectorAll("button")).find(
      (b) => b.textContent === "UPCOMING",
    );
    fireEvent.click(upcomingBtn!);

    expect(
      screen.getByText(/No upcoming actions in provider data/i),
    ).toBeInTheDocument();
  });
});

describe("CACT pane — actions grid sort + keyboard (lane B4)", () => {
  it("defaults to newest-action-first and enables keyboard grid navigation", () => {
    const payload = mixedPayload();
    // Reverse so only the built-in sorter can put 2027 first.
    const data = payload.data.data as { rows: unknown[] };
    data.rows = [...data.rows].reverse();
    setMockFn({ state: "ok", ...payload });
    const { container } = render(<CACTPane code="CACT" symbol="AAPL" />);

    const grid = screen.getByRole("grid", {
      name: "CACT corporate actions table",
    });
    expect(grid).toBeInTheDocument();
    // Roving keyboard cell: the first cell owns the tab stop.
    expect(
      grid.querySelector('td[data-cell="0-0"]')?.getAttribute("tabindex"),
    ).toBe("0");

    // event_date descending -> 2027-01-15 first, 2026-07-31 last.
    expect(container.querySelector('th[aria-sort="descending"]')).not.toBeNull();
    const rowsBefore = Array.from(container.querySelectorAll("tbody tr"));
    expect(rowsBefore[0]?.textContent).toContain("2027-01-15");
    expect(rowsBefore.at(-1)?.textContent).toContain("2026-07-31");

    // Activating the sort cycles desc -> none: reversed fixture order returns.
    fireEvent.click(container.querySelector('th[aria-sort="descending"]')!);
    const rowsAfter = Array.from(container.querySelectorAll("tbody tr"));
    expect(rowsAfter[0]?.textContent).not.toContain("2027-01-15");
  });
});
