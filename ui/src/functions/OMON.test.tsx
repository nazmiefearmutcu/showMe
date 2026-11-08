/**
 * OMON pane — redesign contract tests (L3, options family).
 *
 * Pins the new DOM/behaviour:
 *  - PaneState covers loading / error / empty (provider_unavailable carries
 *    the backend reason + Retry — no duplicate degraded pill/banner);
 *  - the chain DataGrid renders one row per visible strike with a single
 *    "Showing N of M" coverage note, sortable columns and keyboard cells;
 *  - KPI captions are unique (call/put OI share of chain open interest);
 *  - the IV-smile secondary panel is fed by the real `series[]` (call_iv /
 *    put_iv) and stays absent when the series is empty;
 *  - warnings surface as exactly ONE role=status notice;
 *  - side/expiry selection + params stability across visibility ticks.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { OMONPane } from "./OMON";

/* ── useFunction mock ──────────────────────────────────────────────── */

interface MockFnState {
  state: "idle" | "loading" | "ok" | "error" | "refreshing";
  data?: { data?: unknown; warnings?: string[]; metadata?: Record<string, unknown> } | undefined;
  error?: Error | null;
}

const mockFn: MockFnState = { state: "idle", data: undefined, error: null };

function setMockFn(next: MockFnState) {
  mockFn.state = next.state;
  mockFn.data = next.data;
  mockFn.error = next.error ?? null;
}

let lastParams: Record<string, unknown> | undefined;
const refetchMock = vi.fn();
const mockTick = { current: 0 };

vi.mock("@/lib/useFunction", () => ({
  useFunction: (args: { params?: Record<string, unknown> }) => {
    lastParams = args?.params;
    return {
      state: mockFn.state,
      data: mockFn.data,
      error: mockFn.error,
      refetch: refetchMock,
    };
  },
}));

vi.mock("@/lib/useVisibilityTick", () => ({
  useVisibilityTick: () => mockTick.current,
}));

/* ── fixtures: 2 expiries, 4 strikes around spot 100 ───────────────── */

function row(strike: number) {
  return {
    strike,
    moneyness: strike / 100,
    call_bid: 3.1,
    call_ask: 3.3,
    call_oi: 1200,
    call_volume: 300,
    call_iv: 0.31,
    call_delta: 0.55,
    put_bid: 2.9,
    put_ask: 3.1,
    put_oi: 900,
    put_volume: 210,
    put_iv: 0.33,
    put_delta: -0.45,
  };
}

/** Real payload shape (probe 2026-09-12): series carries call/put IV per strike. */
function okPayload() {
  return {
    data: {
      data: {
        status: "ok",
        underlier: "AAPL",
        expiry: "2026-07-17",
        expiries: ["2026-07-17", "2026-08-21"],
        spot: 100.25,
        rows: [row(95), row(100), row(105), row(110)],
        series: [
          { strike: 95, call_iv: 0.35, put_iv: null },
          { strike: 100, call_iv: 0.31, put_iv: 0.33 },
          { strike: 105, call_iv: 0.3, put_iv: 0.34 },
          { strike: 110, call_iv: 0.29, put_iv: 0.36 },
        ],
        summary: {
          underlier: "AAPL",
          expiry: "2026-07-17",
          spot: 100.25,
          atm_iv: 0.32,
          total_call_oi: 4200,
          total_put_oi: 3600,
          strike_count: 4,
        },
      },
      warnings: [] as string[],
      metadata: { data_mode: "live_yfinance" },
      sources: ["yfinance"],
      elapsed_ms: 176,
    },
  };
}

beforeEach(() => {
  localStorage.clear();
  lastParams = undefined;
  mockTick.current = 0;
  refetchMock.mockClear();
  setMockFn({ state: "idle", data: undefined });
});
afterEach(() => {
  cleanup();
});

describe("OMON pane — load states via PaneState", () => {
  it("renders a skeleton while loading", () => {
    setMockFn({ state: "loading", data: undefined });
    const { container } = render(<OMONPane code="OMON" symbol="AAPL" />);
    expect(container.querySelector('[aria-busy="true"]')).not.toBeNull();
  });

  it("provider_unavailable renders the honest empty state with reason + Retry", () => {
    setMockFn({
      state: "ok",
      data: {
        data: {
          status: "provider_unavailable",
          underlier: "AAPL",
          reason: "Live option chain unavailable: network timeout",
          rows: [],
        },
        warnings: ["Live option chain unavailable: network timeout"],
      },
    });
    const { container } = render(<OMONPane code="OMON" symbol="AAPL" />);
    expect(container.querySelector('[data-testid="pane-state-empty"]')).not.toBeNull();
    expect(
      screen.getAllByText(/Option chain unavailable/i).length,
    ).toBeGreaterThan(0);
    // The provider reason is visible verbatim and Retry is offered.
    expect(
      screen.getAllByText(/Live option chain unavailable: network timeout/i).length,
    ).toBeGreaterThan(0);
    expect(screen.getByRole("button", { name: "Retry" })).toBeInTheDocument();
    // One honesty surface only — no second degraded pill/banner.
    expect(screen.queryByText(/^degraded$/i)).toBeNull();
    // FIX R2-#6: the outage string appears ONCE (footer status). The header
    // pill and the footer MODE duplicate are suppressed in this state.
    expect(screen.getAllByText("provider_unavailable").length).toBe(1);
    const footer = container.querySelector(".ds-pane-footer");
    expect(footer?.textContent).toContain("provider_unavailable");
    expect(footer?.textContent).not.toContain("mode");
    // Long provider diagnostics clamp to 2 lines with the full text on title.
    const reason = screen.getByText(/Live option chain unavailable: network timeout/i);
    expect(reason.getAttribute("title")).toBe(
      "Live option chain unavailable: network timeout",
    );
    // Dead controls at 0 rows: SIDE segmented + CSV are disabled.
    expect(screen.getByRole("button", { name: "PUTS" })).toBeDisabled();
    expect(
      screen.getByRole("button", { name: /download 0 strikes as csv/i }),
    ).toBeDisabled();
  });

  it("renders the PaneState error branch when the fetch errors", () => {
    setMockFn({
      state: "error",
      data: undefined,
      error: new Error("sidecar exploded"),
    });
    const { container } = render(<OMONPane code="OMON" symbol="AAPL" />);
    expect(container.querySelector('[data-testid="pane-state-error"]')).not.toBeNull();
    expect(screen.getByText(/sidecar exploded/i)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Retry" })).toBeInTheDocument();
  });

  it("ok payload renders the chain with ONE coverage note and unique OI captions", () => {
    setMockFn({ state: "ok", ...okPayload() });
    const { container } = render(<OMONPane code="OMON" symbol="AAPL" />);
    expect(container.querySelectorAll("tbody tr").length).toBe(4);
    // Coverage stated exactly once (header pill + footer duplicate removed).
    expect(screen.getAllByText(/Showing 4 of 4 strikes/i).length).toBe(1);
    // OI cards carry their own share values, not a repeated "TOTAL CHAIN".
    expect(screen.getByText("53.8% of chain OI")).toBeInTheDocument();
    expect(screen.getByText("46.2% of chain OI")).toBeInTheDocument();
    expect(screen.queryByText(/TOTAL CHAIN/i)).toBeNull();
  });

  it("keeps an empty-string wire cell missing (never coerced to 0.00 / 0.0%)", () => {
    const payload = okPayload();
    const row0 = payload.data.data.rows[0] as unknown as Record<string, unknown>;
    row0.call_bid = "";
    row0.call_iv = "";
    setMockFn({ state: "ok", ...payload });
    const { container } = render(<OMONPane code="OMON" symbol="AAPL" />);
    // Default sort = strike ascending → first row is the strike-95 row.
    const firstRow = container.querySelector("tbody tr")!;
    // Columns: Strike, Bid, Ask, OI, Vol, IV, Delta.
    expect(firstRow.children[1].textContent).toBe("—");
    expect(firstRow.children[5].textContent).toBe("—");
  });
});

describe("OMON pane — smile panel from the real series[]", () => {
  it("draws the IV smile with call and put series", () => {
    setMockFn({ state: "ok", ...okPayload() });
    const { container } = render(<OMONPane code="OMON" symbol="AAPL" />);
    const panel = container.querySelector('[data-testid="omon-iv-smile"]');
    expect(panel).not.toBeNull();
    expect(panel?.querySelectorAll('path[data-series="call"]').length).toBeGreaterThan(0);
    expect(panel?.querySelectorAll('path[data-series="put"]').length).toBeGreaterThan(0);
  });

  it("omits the smile panel when the series carries no usable IV", () => {
    const payload = okPayload();
    (payload.data.data as { series?: unknown }).series = [];
    setMockFn({ state: "ok", ...payload });
    const { container } = render(<OMONPane code="OMON" symbol="AAPL" />);
    expect(container.querySelector('[data-testid="omon-iv-smile"]')).toBeNull();
  });
});

describe("OMON pane — honesty notice", () => {
  it("surfaces backend warnings as exactly one status notice", () => {
    const payload = okPayload();
    payload.data.warnings = ["partial chain: 4 of 29 strikes returned"];
    setMockFn({ state: "ok", ...payload });
    render(<OMONPane code="OMON" symbol="AAPL" />);
    expect(
      screen.getAllByText(/partial chain: 4 of 29 strikes returned/i).length,
    ).toBe(1);
    expect(screen.getAllByRole("status").length).toBe(1);
  });
});

describe("OMON pane — ATM highlight + side toggle", () => {
  it("highlights the strike nearest to spot as ATM", () => {
    setMockFn({ state: "ok", ...okPayload() });
    const { container } = render(<OMONPane code="OMON" symbol="AAPL" />);
    const atmCells = container.querySelectorAll('[data-atm="true"]');
    expect(atmCells.length).toBe(1);
    expect(atmCells[0].textContent).toContain("100");
    expect(container.querySelector('[data-testid="omon-atm-strike"]')).not.toBeNull();
  });

  it("switches to put columns when PUTS is selected", () => {
    setMockFn({ state: "ok", ...okPayload() });
    const { container } = render(<OMONPane code="OMON" symbol="AAPL" />);
    // Delta 0.55 = call side initially.
    expect(container.textContent).toContain("0.55");
    fireEvent.click(screen.getByRole("button", { name: "PUTS" }));
    // Put delta −0.45 now rendered; call delta gone.
    expect(container.textContent).toContain("-0.45");
    expect(container.textContent).not.toContain("0.55");
  });
});

describe("OMON pane — expiry selection", () => {
  it("re-issues the query with the chosen expiry param", () => {
    setMockFn({ state: "ok", ...okPayload() });
    render(<OMONPane code="OMON" symbol="AAPL" />);
    // No preference yet → backend default (no expiry param).
    expect(lastParams?.expiry).toBeUndefined();
    fireEvent.click(screen.getByRole("button", { name: "2026-08-21" }));
    expect(lastParams?.expiry).toBe("2026-08-21");
    // Preference is persisted under the contract key.
    expect(localStorage.getItem("showme.omon.expiry")).toBe("2026-08-21");
  });

  it("restores a persisted expiry that is still listed", () => {
    localStorage.setItem("showme.omon.expiry", "2026-08-21");
    setMockFn({ state: "ok", ...okPayload() });
    render(<OMONPane code="OMON" symbol="AAPL" />);
    expect(lastParams?.expiry).toBe("2026-08-21");
  });
});

describe("OMON pane — sort, CSV, keyboard grid", () => {
  it("reorders the visible strike window when an OI header is clicked", () => {
    const payload = okPayload();
    // Give each strike a distinct OI so the built-in sorter visibly reorders.
    payload.data.data.rows[0].call_oi = 10; // strike 95
    payload.data.data.rows[1].call_oi = 5000; // strike 100
    payload.data.data.rows[2].call_oi = 50; // strike 105
    payload.data.data.rows[3].call_oi = 900; // strike 110
    setMockFn({ state: "ok", ...payload });
    const { container } = render(<OMONPane code="OMON" symbol="AAPL" />);
    const strikes = () =>
      Array.from(container.querySelectorAll("tbody tr td:first-child")).map(
        (td) => td.textContent,
      );
    expect(strikes()[0]).toBe("95");
    fireEvent.click(screen.getByText("OI"));
    // First click on a new column sorts ascending → 10 (strike 95) leads.
    expect(strikes()[0]).toBe("95");
    fireEvent.click(screen.getByText("OI"));
    // Second click flips to descending → 5000 (strike 100) leads.
    expect(strikes()[0]).toBe("100");
  });

  it("offers a CSV export of the visible window", () => {
    setMockFn({ state: "ok", ...okPayload() });
    render(<OMONPane code="OMON" symbol="AAPL" />);
    const csv = screen.getByRole("button", { name: /download 4 strikes as csv/i });
    expect(csv).toBeEnabled();
    expect(csv.textContent).toBe("CSV");
  });

  it("exposes the chain as a keyboard grid with roving cell focus", () => {
    setMockFn({ state: "ok", ...okPayload() });
    const { container } = render(<OMONPane code="OMON" symbol="AAPL" />);
    const grid = container.querySelector('[role="grid"]');
    expect(grid).not.toBeNull();
    expect(container.querySelectorAll("tbody tr").length).toBe(4);
    expect(container.querySelectorAll("td[data-cell]").length).toBe(28);
    // Roving tabindex: exactly one data cell is tabbable.
    expect(
      container.querySelectorAll('td[data-cell][tabindex="0"]').length,
    ).toBe(1);
  });

  it("copies the focused side-aware cell value with Ctrl+C", () => {
    const writeText = vi.fn().mockResolvedValue(undefined);
    Object.defineProperty(navigator, "clipboard", {
      value: { writeText },
      configurable: true,
    });
    try {
      setMockFn({ state: "ok", ...okPayload() });
      const { container } = render(<OMONPane code="OMON" symbol="AAPL" />);
      // Roving focus starts at row 0 / strike column; ArrowRight → Bid.
      fireEvent.keyDown(container.querySelector('[data-cell="0-0"]')!, {
        key: "ArrowRight",
      });
      fireEvent.keyDown(container.querySelector('[data-cell="0-1"]')!, {
        key: "c",
        ctrlKey: true,
      });
      // getCellText wiring: raw-row fallback would copy "" for side columns.
      expect(writeText).toHaveBeenCalledWith("3.1");
    } finally {
      Reflect.deleteProperty(navigator, "clipboard");
    }
  });
});

describe("OMON pane — visibility poll + spot flash (live adoption)", () => {
  it("refetches on a visibility tick but not on mount", () => {
    setMockFn({ state: "ok", ...okPayload() });
    const { rerender } = render(<OMONPane code="OMON" symbol="AAPL" />);
    expect(refetchMock).not.toHaveBeenCalled();

    mockTick.current = 1;
    rerender(<OMONPane code="OMON" symbol="AAPL" />);
    expect(refetchMock).toHaveBeenCalledTimes(1);
  });

  it("keeps the expiry params stable across ticks (no tick key)", () => {
    setMockFn({ state: "ok", ...okPayload() });
    const { rerender } = render(<OMONPane code="OMON" symbol="AAPL" />);
    const before = JSON.stringify(lastParams ?? null);
    expect(before).not.toContain("tick");

    mockTick.current = 3;
    rerender(<OMONPane code="OMON" symbol="AAPL" />);
    expect(JSON.stringify(lastParams ?? null)).toBe(before);
  });

  it("flashes the spot cell when the spot moves", () => {
    vi.useFakeTimers();
    try {
      setMockFn({ state: "ok", ...okPayload() });
      const { rerender } = render(<OMONPane code="OMON" symbol="AAPL" />);
      const cell = screen.getByTestId("flash-value");
      expect(cell.className).not.toMatch(/flash/);

      const payload = okPayload();
      payload.data.data.summary.spot = 101.4;
      (payload.data.data as { spot?: number }).spot = 101.4;
      setMockFn({ state: "ok", ...payload });
      rerender(<OMONPane code="OMON" symbol="AAPL" />);
      expect(screen.getByTestId("flash-value").className).toContain("flash-pos");
    } finally {
      vi.useRealTimers();
    }
  });
});
