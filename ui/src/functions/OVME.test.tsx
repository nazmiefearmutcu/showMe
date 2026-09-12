/**
 * OVME pane — render-contract + interaction tests (options-family redesign
 * 2026-09-12, lane L4).
 *
 * Pure Black-Scholes model pane. Tests pin:
 *
 *  - the load states (loading / error / honest invalid-inputs) via PaneState;
 *  - ok renders exactly 4 KPI cards, the value-curve SVG (model value vs
 *    intrinsic) with vega/rho inline, and the sensitivity DataGrid
 *    (sort/keyboard/CSV) with the current-spot row marked;
 *  - honesty: exactly ONE model label (header pill), em-dash for missing
 *    values, backend reason for invalid inputs;
 *  - interactions: CALL/PUT toggle persists and relabels, inputs persist.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { OVMEPane } from "./OVME";

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

function okPayload() {
  const curve = [];
  for (let i = 0; i < 51; i += 1) {
    const s = 75 + i; // 75 .. 125, spot 100 at index 25
    const intrinsic = Math.max(s - 100, 0);
    curve.push({
      spot: s,
      price: intrinsic + 4.5,
      intrinsic,
      time_value: 4.5,
      delta: s >= 100 ? 0.6 : 0.3,
    });
  }
  return {
    data: {
      data: {
        status: "ok",
        spot: 100,
        strike: 100,
        T: 0.25,
        vol: 0.3,
        rate: 0.045,
        div_yield: 0,
        type: "CALL",
        model: "bs",
        price: 4.263,
        delta: 0.4228,
        gamma: 0.026,
        theta: -0.0356,
        vega: 0.1953,
        rho: 0.0951,
        d1: 0.21,
        d2: 0.06,
        curve,
        sensitivity: curve,
        summary: { price: 4.263 },
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

describe("OVME pane — load states", () => {
  it("renders the PaneState skeleton while loading", () => {
    setMockFn({ state: "loading", data: undefined });
    const { container } = render(<OVMEPane code="OVME" symbol="SPY" />);
    expect(container.querySelector('[data-testid="pane-state-loading"]')).not.toBeNull();
  });

  it("renders the error state when the fetch errors", () => {
    setMockFn({
      state: "error",
      data: undefined,
      error: new Error("sidecar exploded"),
    });
    render(<OVMEPane code="OVME" symbol="SPY" />);
    expect(screen.getByText(/sidecar exploded/i)).toBeInTheDocument();
  });

  it("renders an honest invalid-inputs state with the backend reason", () => {
    setMockFn({
      state: "ok",
      data: {
        data: {
          status: "error",
          summary: { error: "invalid_inputs: S and K must be > 0 (got S=-5, K=100)" },
          curve: [],
        },
      },
    });
    render(<OVMEPane code="OVME" symbol="SPY" />);
    expect(screen.getByText(/Model needs valid inputs/i)).toBeInTheDocument();
    expect(screen.getByText(/invalid_inputs/i)).toBeInTheDocument();
  });
});

describe("OVME pane — ok surface", () => {
  it("renders 4 KPIs, the value curve with inline vega/rho and the sensitivity grid", () => {
    setMockFn({ state: "ok", ...okPayload() });
    const { container } = render(<OVMEPane code="OVME" symbol="SPY" />);

    // Exactly four KPI cards (the 6-card row is gone).
    expect(container.querySelectorAll(".stat-card").length).toBe(4);
    expect(screen.getByText("4.263")).toBeInTheDocument();
    expect(screen.getByText("0.4228")).toBeInTheDocument();
    expect(screen.getByText("-0.0356")).toBeInTheDocument();
    // Vega / rho live inline on the curve header, not as oversized cards.
    expect(screen.getByText(/vega 0\.1953/)).toBeInTheDocument();
    expect(screen.getByText(/rho 0\.0951/)).toBeInTheDocument();

    // Value curve SVG present with an aria-label.
    const chart = container.querySelector('svg[role="img"]');
    expect(chart?.getAttribute("aria-label")).toMatch(/value from spot/i);

    // Sensitivity grid: 51 points sampled every 5th = 11 rows, keyboard grid.
    const grid = container.querySelector('table[aria-label="Value sensitivity to spot"]');
    expect(grid).not.toBeNull();
    expect(grid?.getAttribute("role")).toBe("grid");
    const rows = container.querySelectorAll(
      'table[aria-label="Value sensitivity to spot"] tbody tr',
    );
    expect(rows.length).toBe(11);
    // The current-spot row is marked (accent-soft selection tint).
    expect(container.querySelector('span[style*="accent-soft"]')).not.toBeNull();

    // Exactly one model label (header pill) on the whole surface.
    expect(screen.getAllByText(/^model$/i)).toHaveLength(1);
  });

  it("renders em-dashes (never fabricated numbers) for missing model outputs", () => {
    const fixture = okPayload();
    const payload = fixture.data.data as Record<string, unknown>;
    delete payload.price;
    delete payload.delta;
    delete payload.vega;
    setMockFn({ state: "ok", ...fixture });
    render(<OVMEPane code="OVME" symbol="SPY" />);
    expect(screen.getAllByText("—").length).toBeGreaterThanOrEqual(2);
  });

  it("exposes a CSV export for the sensitivity grid in the header slot", () => {
    setMockFn({ state: "ok", ...okPayload() });
    render(<OVMEPane code="OVME" symbol="SPY" />);
    const csv = screen.getByLabelText(/Download 11 sensitivity rows as CSV/i);
    expect(csv).toBeInTheDocument();
    // FIX R2-#10 (F4): family-consistent placement — header, not the grid section.
    expect(csv.closest(".ds-pane-header")).not.toBeNull();
  });

  it("renders editable numeric values with en-US dot decimals (no tr-TR commas)", () => {
    setMockFn({ state: "ok", ...okPayload() });
    render(<OVMEPane code="OVME" symbol="SPY" />);
    // FIX R2-#3: `type="number"` displayed OS-locale separators ("0,25").
    const years = screen.getByLabelText("Years to expiry") as HTMLInputElement;
    expect(years.getAttribute("type")).toBe("text");
    expect(years.getAttribute("inputmode")).toBe("decimal");
    expect(years.value).toBe("0.25");
    expect(years.value).not.toContain(",");
    const rate = screen.getByLabelText("Risk-free rate percent") as HTMLInputElement;
    expect(rate.value).toBe("4.5");
    expect(rate.value).not.toContain(",");
  });

  it("keeps the value curve at the trimmed 120px height (below-fold budget)", () => {
    setMockFn({ state: "ok", ...okPayload() });
    const { container } = render(<OVMEPane code="OVME" symbol="SPY" />);
    // FIX R2-#9: the curve height was 150px; the sensitivity grid gains a row
    // at the 900px fold with the 120px budget. This pin guards the regression.
    const chart = container.querySelector('svg[role="img"]');
    expect(chart?.getAttribute("height")).toBe("120");
  });
});

describe("OVME pane — interactions", () => {
  it("toggling CALL/PUT persists the type and relabels the header", () => {
    setMockFn({ state: "ok", ...okPayload() });
    render(<OVMEPane code="OVME" symbol="SPY" />);
    expect(screen.getByText(/CALL 100 · ATM/)).toBeInTheDocument();
    fireEvent.click(screen.getByText("PUT"));
    expect(localStorage.getItem("showme.ovme.type")).toBe("PUT");
    expect(screen.getByText(/PUT 100 · ATM/)).toBeInTheDocument();
  });

  it("editing the spot input persists it", () => {
    setMockFn({ state: "ok", ...okPayload() });
    render(<OVMEPane code="OVME" symbol="SPY" />);
    const spot = screen.getByLabelText("Underlying spot price");
    fireEvent.change(spot, { target: { value: "112.5" } });
    expect(localStorage.getItem("showme.ovme.spot")).toBe("112.5");
  });
});
