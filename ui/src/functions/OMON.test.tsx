/**
 * OMON pane — data-honesty + render-contract tests.
 *
 * `useFunction` is mocked via a mutable shared state (same pattern as
 * GEX.test.tsx) plus a params recorder, so tests can pin:
 *
 *  - the four load states (loading / empty / error / ok) render;
 *  - an ok payload renders one row per strike with the side columns;
 *  - the ATM strike (nearest to spot) carries the data-atm highlight;
 *  - the coverage note honestly reports "showing N of M";
 *  - a provider_unavailable payload renders the explicit empty state and
 *    surfaces backend warnings as a degraded pill + inline note;
 *  - switching expiry re-issues the query with the new `expiry` param.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { OMONPane } from "./OMON";

/* ── useFunction mock ──────────────────────────────────────────────── */

interface MockFnState {
  state: "idle" | "loading" | "ok" | "error" | "refreshing";
  data?: { data?: unknown; warnings?: string[] } | undefined;
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

// SymbolBar pulls router/symbol-resolver side effects we don't need here.
vi.mock("@/shell/SymbolBar", () => ({
  SymbolBar: () => null,
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
      warnings: [],
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

describe("OMON pane — load states", () => {
  it("renders a skeleton while loading", () => {
    setMockFn({ state: "loading", data: undefined });
    const { container } = render(<OMONPane code="OMON" symbol="AAPL" />);
    expect(container.querySelector('[aria-busy="true"]')).not.toBeNull();
  });

  it("renders the provider_unavailable empty state with the warning surfaced", () => {
    setMockFn({
      state: "ok",
      data: {
        data: {
          status: "provider_unavailable",
          underlier: "AAPL",
          rows: [],
        },
        warnings: ["Live option chain unavailable: network timeout"],
      },
    });
    render(<OMONPane code="OMON" symbol="AAPL" />);
    // Empty renders the title in both a heading and an aria node.
    expect(
      screen.getAllByText(/Option chain unavailable/i).length,
    ).toBeGreaterThan(0);
    // Honesty: the backend warning text must be visible, plus the degraded pill.
    expect(
      screen.getByText(/Live option chain unavailable/i),
    ).toBeInTheDocument();
    expect(screen.getByText(/degraded/i)).toBeInTheDocument();
  });

  it("renders the error state when the fetch errors", () => {
    setMockFn({
      state: "error",
      data: undefined,
      error: new Error("sidecar exploded"),
    });
    render(<OMONPane code="OMON" symbol="AAPL" />);
    expect(screen.getByText(/sidecar exploded/i)).toBeInTheDocument();
  });

  it("renders one chain row per strike when ok", () => {
    setMockFn({ state: "ok", ...okPayload() });
    const { container } = render(<OMONPane code="OMON" symbol="AAPL" />);
    expect(container.querySelectorAll("tbody tr").length).toBe(4);
    // Honest coverage note.
    expect(screen.getByText(/Showing 4 of 4 strikes/i)).toBeInTheDocument();
    // Live honesty pill (no synthetic/degraded wording for live data).
    expect(screen.getByText(/live chain/i)).toBeInTheDocument();
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

describe("OMON pane — accessibility", () => {
  it("exposes the chain as a keyboard grid with per-cell reachability", () => {
    setMockFn({ state: "ok", ...okPayload() });
    const { container } = render(<OMONPane code="OMON" symbol="AAPL" />);
    // DataGrid upgrades to role=grid when keyboardNavigable is set (arrow-key
    // cell navigation + Ctrl/Cmd+C copy).
    const grid = container.querySelector('[role="grid"]');
    expect(grid).not.toBeNull();
    expect(container.querySelectorAll("tbody tr").length).toBe(4);
    expect(container.querySelectorAll("td[data-cell]").length).toBeGreaterThan(0);
  });

  it("labels the chain table for screen readers", () => {
    setMockFn({ state: "ok", ...okPayload() });
    const { container } = render(<OMONPane code="OMON" symbol="AAPL" />);
    const table = container.querySelector("table");
    expect(table?.getAttribute("aria-label")).toMatch(/chain/i);
  });
});

describe("OMON pane — chain sort + CSV (audit A4 M)", () => {
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
