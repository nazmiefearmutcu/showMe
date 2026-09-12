/**
 * OSA pane — render-contract + interaction tests (options-family redesign
 * 2026-09-12, lane L4).
 *
 * The pane is fully parameter-driven (no market feed): the compact leg
 * editor and strategy presets build the request, the backend returns
 * Black-Scholes premiums (from the entered IV) and a 101-point payoff curve.
 * Tests pin:
 *
 *  - the load states (loading / error / honest bad-payload) via PaneState;
 *  - ok renders 4 KPI cards, the payoff SVG with in-line breakeven markers,
 *    the compact leg editor and the payoff DataGrid (sort/keyboard/CSV);
 *  - honesty: the single "model" pill, em-dash for missing summary values,
 *    and the editor never claims the model solves IV (entered value wins);
 *  - interactions: preset swap, leg edit and add-leg cap persist.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen, within } from "@testing-library/react";
import { OSAPane } from "./OSA";

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

/* ── fixtures ──────────────────────────────────────────────────────── */

function bullCallPayload() {
  const netDebit = 3.59;
  const pvDebit = netDebit;
  const curve = [];
  for (let i = 0; i <= 100; i += 1) {
    const s = 50 + i;
    const payoff = Math.max(s - 100, 0) * 1 + Math.max(s - 110, 0) * -1;
    curve.push({
      spot: s,
      payoff,
      pnl: payoff - pvDebit,
      net_debit: netDebit,
      pv_debit: pvDebit,
    });
  }
  return {
    data: {
      data: {
        status: "ok",
        strategy: "BULL CALL",
        spot: 100,
        rate: 0.045,
        div_yield: 0,
        rows: [
          {
            leg: 1,
            qty: 1,
            type: "CALL",
            strike: 100,
            expiry_years: 0.25,
            vol: 0.25,
            iv_source: "input",
            premium: 5.54,
            initial_value: 5.54,
          },
          {
            leg: 2,
            qty: -1,
            type: "CALL",
            strike: 110,
            expiry_years: 0.25,
            vol: 0.25,
            iv_source: "input",
            premium: 1.95,
            initial_value: -1.95,
          },
        ],
        curve,
        summary: {
          net_debit: netDebit,
          max_gain_visible: 6.41,
          max_loss_visible: -3.59,
          breakeven_count_visible: 1,
        },
      },
      sources: ["black_scholes_formula"],
      elapsed_ms: 14,
    },
  };
}

/* ── harness ───────────────────────────────────────────────────────── */

beforeEach(() => {
  localStorage.clear();
  setMockFn({ state: "idle", data: undefined });
});
afterEach(() => {
  cleanup();
  localStorage.clear();
});

describe("OSA pane — load states", () => {
  it("renders the PaneState skeleton while loading", () => {
    setMockFn({ state: "loading", data: undefined });
    const { container } = render(<OSAPane code="OSA" symbol="SPY" />);
    expect(container.querySelector('[data-testid="pane-state-loading"]')).not.toBeNull();
  });

  it("renders the error state when the fetch errors", () => {
    setMockFn({
      state: "error",
      data: undefined,
      error: new Error("sidecar exploded"),
    });
    render(<OSAPane code="OSA" symbol="SPY" />);
    expect(screen.getByText(/sidecar exploded/i)).toBeInTheDocument();
  });

  it("renders an honest bad-payload state with the backend reason", () => {
    setMockFn({
      state: "ok",
      data: {
        data: {
          status: "calc_error",
          reason: "legs invalid: strike must be > 0",
          curve: [],
          summary: {},
        },
      },
    });
    render(<OSAPane code="OSA" symbol="SPY" />);
    expect(screen.getByText(/Strategy could not be priced/i)).toBeInTheDocument();
    expect(screen.getByText(/legs invalid: strike must be > 0/i)).toBeInTheDocument();
  });
});

describe("OSA pane — ok surface", () => {
  it("renders 4 KPIs, the payoff SVG with breakeven markers and the payoff grid", () => {
    setMockFn({ state: "ok", ...bullCallPayload() });
    const { container } = render(<OSAPane code="OSA" symbol="SPY" />);

    // Exactly four KPI cards (no 6-card noise).
    expect(container.querySelectorAll(".stat-card").length).toBe(4);
    // Signed net debit / bounds and the breakeven price caption.
    // Scoped to the KPI strip — the payoff grid legitimately repeats levels.
    const kpis = within(screen.getByRole("region", { name: "Strategy statistics" }));
    expect(kpis.getByText("+3.59")).toBeInTheDocument();
    expect(kpis.getByText("+6.41")).toBeInTheDocument();
    expect(kpis.getByText("-3.59")).toBeInTheDocument();
    expect(kpis.getByText("103.59")).toBeInTheDocument();

    // Primary payoff SVG: breakeven marker on the zero line, no legend chains.
    const chart = container.querySelector('svg[role="img"]');
    expect(chart?.getAttribute("aria-label")).toMatch(/breakeven/i);
    expect(container.querySelectorAll("circle").length).toBeGreaterThan(0);

    // Secondary table is the kit DataGrid, not a raw <table> bypass.
    // (Role query — jsdom's attribute-selector parser chokes on the "&".)
    const grid = screen.getByRole("grid", { name: "Expiry P&L at key prices" });
    const rows = grid.querySelectorAll("tbody tr");
    expect(rows.length).toBe(5); // endpoints + spot + strike + breakeven

    // Exactly one model label (header pill) on the whole surface.
    expect(screen.getAllByText(/^model$/i)).toHaveLength(1);
  });

  it("does not claim the model solves IV per leg (the entered value prices the leg)", () => {
    setMockFn({ state: "ok", ...bullCallPayload() });
    const { container } = render(<OSAPane code="OSA" symbol="SPY" />);
    expect(container.textContent).toMatch(/IV per leg is the entered value/i);
    expect(container.textContent).not.toMatch(/IV solved/i);
  });

  it("renders em-dashes (never fabricated zeros) when the summary is missing", () => {
    const fixture = bullCallPayload();
    (fixture.data.data as Record<string, unknown>).summary = {};
    setMockFn({ state: "ok", ...fixture });
    render(<OSAPane code="OSA" symbol="SPY" />);
    expect(screen.getAllByText("—").length).toBeGreaterThanOrEqual(3);
  });

  it("exposes a CSV export for the payoff grid in the header slot", () => {
    setMockFn({ state: "ok", ...bullCallPayload() });
    render(<OSAPane code="OSA" symbol="SPY" />);
    const csv = screen.getByLabelText(/Download 5 payoff rows as CSV/i);
    expect(csv).toBeInTheDocument();
    // FIX R2-#10 (F4): family-consistent placement — header, not the grid section.
    expect(csv.closest(".ds-pane-header")).not.toBeNull();
  });

  it("renders editable numeric values with en-US dot decimals (no tr-TR commas)", () => {
    setMockFn({ state: "ok", ...bullCallPayload() });
    render(<OSAPane code="OSA" symbol="SPY" />);
    // FIX R2-#3: `type="number"` displayed OS-locale separators ("0,25").
    const expiry = screen.getByLabelText("Leg 1 expiry years") as HTMLInputElement;
    expect(expiry.getAttribute("type")).toBe("text");
    expect(expiry.getAttribute("inputmode")).toBe("decimal");
    expect(expiry.value).toBe("0.25");
    expect(expiry.value).not.toContain(",");
    const rate = screen.getByLabelText("Risk-free rate percent") as HTMLInputElement;
    expect(rate.value).toBe("4.5");
    expect(rate.value).not.toContain(",");
  });

  it("keeps the payoff chart at the trimmed 120px height (below-fold budget)", () => {
    setMockFn({ state: "ok", ...bullCallPayload() });
    const { container } = render(<OSAPane code="OSA" symbol="SPY" />);
    // FIX R2-#9: the chart height was 150px; the primary grid gains a row at
    // the 900px fold with the 120px budget. This pin guards the regression.
    const chart = container.querySelector('svg[role="img"]');
    expect(chart?.getAttribute("height")).toBe("120");
  });
});

describe("OSA pane — interactions", () => {
  it("clicking a strategy preset swaps the legs and persists them", () => {
    setMockFn({ state: "ok", ...bullCallPayload() });
    render(<OSAPane code="OSA" symbol="SPY" />);
    fireEvent.click(screen.getByText("STRADDLE"));
    const stored = JSON.parse(localStorage.getItem("showme.osa.legs") ?? "[]");
    expect(stored).toHaveLength(2);
    expect(stored[0].type).toBe("CALL");
    expect(stored[1].type).toBe("PUT");
    expect(stored[0].strike).toBe(100);
    expect(stored[1].strike).toBe(100);
  });

  it("editing a leg strike persists the strategy", () => {
    setMockFn({ state: "ok", ...bullCallPayload() });
    render(<OSAPane code="OSA" symbol="SPY" />);
    const strike = screen.getByLabelText("Leg 1 strike");
    fireEvent.change(strike, { target: { value: "105" } });
    const stored = JSON.parse(localStorage.getItem("showme.osa.legs") ?? "[]");
    expect(stored[0].strike).toBe(105);
  });

  it("adding a leg appends and persists up to the cap", () => {
    setMockFn({ state: "ok", ...bullCallPayload() });
    render(<OSAPane code="OSA" symbol="SPY" />);
    const add = screen.getByTitle("Add a leg (max 4)");
    fireEvent.click(add);
    fireEvent.click(add);
    const stored = JSON.parse(localStorage.getItem("showme.osa.legs") ?? "[]");
    expect(stored).toHaveLength(4);
    expect(add).toBeDisabled();
  });
});
