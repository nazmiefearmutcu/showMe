/**
 * IVOL pane — lane L2 tests (options-family redesign, 2026-09-12).
 *
 * Pins the P0 wire fix (commission MASTER-VERDICT.md:212): the pane must read
 * the REAL `vol`/`vol_pct` surface fields — the old pane keyed on `iv` (never
 * emitted) and rendered an empty heatmap + spread arms of em-dashes. These
 * tests use wire-shaped fixtures (`vol`, not `iv`) so a regression back to the
 * dead field fails here.
 *
 * Honesty pins kept from F15: live (`live_*`) never shows the reference notice;
 * a reference payload labels itself exactly once (pill + notice, no footer
 * mode echo, no skew-mode label). Poll pin kept: the visibility tick is a
 * refetch trigger, never a fetch param.
 */
import { cleanup, fireEvent, render, screen, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

interface MockFnState {
  state: "idle" | "loading" | "ok" | "error" | "refreshing";
  data?: {
    data?: unknown;
    sources?: string[];
    elapsed_ms?: number;
    warnings?: string[];
    status?: string;
  };
  error?: Error | null;
}

const mockFn: MockFnState = { state: "idle", data: undefined, error: null };
const recordedCalls: Array<{ params?: Record<string, unknown>; symbol?: string }> = [];

vi.mock("@/lib/useFunction", () => ({
  useFunction: (opts: { params?: Record<string, unknown>; symbol?: string }) => {
    recordedCalls.push(opts);
    return {
      state: mockFn.state,
      data: mockFn.data,
      error: mockFn.error,
      refetch: vi.fn(),
    };
  },
}));

import { IVOLPane } from "./IVOL";

const EXPIRY = "2026-06-19";
const NEXT_EXPIRY = "2026-09-18";

/** Wire-shaped live fixture — surface cells carry `vol`, never `iv`. */
function livePayload() {
  return {
    data: {
      status: "ok",
      symbol: "AAPL",
      spot: 190,
      source_mode: "live_yfinance",
      surface: [
        { expiry: EXPIRY, strike: 180, moneyness: 0.95, vol: 0.35, vol_pct: 35, option_type: "CALL" },
        { expiry: EXPIRY, strike: 190, moneyness: 1.0, vol: 0.31, option_type: "CALL" },
        { expiry: EXPIRY, strike: 190, moneyness: 1.0, vol: 0.33, option_type: "PUT" },
        { expiry: EXPIRY, strike: 200, moneyness: 1.05, vol: 0.36, option_type: "CALL" },
        { expiry: EXPIRY, strike: 200, moneyness: 1.05, vol: 0.34, option_type: "PUT" },
      ],
      series: [
        { t: EXPIRY, v: 0.31 },
        { t: NEXT_EXPIRY, v: 0.33 },
      ],
      summary: {
        contracts: 5,
        expiries: 1,
        calls: 3,
        puts: 2,
        source_mode: "live_yfinance",
        atm_iv_front: 0.31,
        atm_iv_back: 0.33,
        skew: 0.04,
        term_slope: 0.02,
      },
    },
    status: "ok",
    sources: ["yfinance"],
    elapsed_ms: 12,
  };
}

/** Live probe shape (options-redesign/raw/ivol-payload.json): reference with reason. */
function referencePayload() {
  return {
    data: {
      status: "reference",
      symbol: "AAPL",
      spot: 332.27,
      data_state: "live_quote",
      reason: "yfinance options expiries empty",
      surface: [
        { expiry: "30d", strike: 265.82, moneyness: 0.8, vol: 0.37, option_type: "CALL" },
        { expiry: "30d", strike: 299.04, moneyness: 0.9, vol: 0.345, option_type: "CALL" },
        { expiry: "30d", strike: 332.27, moneyness: 1.0, vol: 0.32, option_type: "CALL" },
        { expiry: "30d", strike: 299.04, moneyness: 0.9, vol: 0.375, option_type: "PUT" },
      ],
      series: [
        { t: "30d", v: 0.32 },
        { t: "60d", v: 0.335 },
        { t: "90d", v: 0.35 },
      ],
      summary: {
        contracts: 4,
        expiries: 1,
        source_mode: "reference",
        atm_iv_front: 0.32,
        atm_iv_back: 0.35,
        skew: 0,
        term_slope: 0.03,
      },
    },
    status: "provider_unavailable",
    sources: ["black_scholes_reference_formula"],
    elapsed_ms: 3,
  };
}

/**
 * 30 rows across 3 expiries (the old pane mapped every row → a tab, producing
 * 30 duplicate React keys / duplicate "30d" tabs).
 */
function dedupePayload() {
  const surface: Array<Record<string, unknown>> = [];
  for (const expiry of ["30d", "60d", "90d"]) {
    for (const m of [0.9, 1.0, 1.1]) {
      surface.push({ expiry, strike: 100 * m, moneyness: m, vol: 0.3, option_type: "CALL" });
      surface.push({ expiry, strike: 100 * m, moneyness: m, vol: 0.32, option_type: "PUT" });
    }
  }
  return {
    data: {
      status: "reference",
      symbol: "AAPL",
      spot: 100,
      source_mode: "reference",
      surface,
      series: [
        { t: "30d", v: 0.3 },
        { t: "60d", v: 0.31 },
        { t: "90d", v: 0.32 },
      ],
      summary: {
        contracts: 30,
        expiries: 3,
        source_mode: "reference",
        atm_iv_front: 0.3,
        atm_iv_back: 0.32,
        skew: 0.01,
        term_slope: 0.02,
      },
    },
    status: "ok",
    sources: ["black_scholes_reference_formula"],
    elapsed_ms: 4,
  };
}

/**
 * Exact live-probe payload (showme-review/.../options-redesign/raw/ivol-payload.json,
 * 2026-09-12, AAPL): 30 surface cells carrying `vol`, 3 expiries, 5 K/S buckets,
 * envelope status provider_unavailable + data_state live_quote.
 */
function probePayload() {
  return {
    data: {
      status: "reference",
      symbol: "AAPL",
      spot: 332.27,
      data_state: "live_quote",
      reason: "yfinance options expiries empty",
      source_mode: "reference",
      surface: [
        { expiry: "30d", strike: 265.82, moneyness: 0.800012, vol: 0.37, option_type: "CALL" },
        { expiry: "30d", strike: 299.04, moneyness: 0.899991, vol: 0.345, option_type: "CALL" },
        { expiry: "30d", strike: 332.27, moneyness: 1.0, vol: 0.32, option_type: "CALL" },
        { expiry: "30d", strike: 365.5, moneyness: 1.100009, vol: 0.345, option_type: "CALL" },
        { expiry: "30d", strike: 398.72, moneyness: 1.199988, vol: 0.37, option_type: "CALL" },
        { expiry: "60d", strike: 265.82, moneyness: 0.800012, vol: 0.385, option_type: "CALL" },
        { expiry: "60d", strike: 299.04, moneyness: 0.899991, vol: 0.36, option_type: "CALL" },
        { expiry: "60d", strike: 332.27, moneyness: 1.0, vol: 0.335, option_type: "CALL" },
        { expiry: "60d", strike: 365.5, moneyness: 1.100009, vol: 0.36, option_type: "CALL" },
        { expiry: "60d", strike: 398.72, moneyness: 1.199988, vol: 0.385, option_type: "CALL" },
        { expiry: "90d", strike: 265.82, moneyness: 0.800012, vol: 0.4, option_type: "CALL" },
        { expiry: "90d", strike: 299.04, moneyness: 0.899991, vol: 0.375, option_type: "CALL" },
        { expiry: "90d", strike: 332.27, moneyness: 1.0, vol: 0.35, option_type: "CALL" },
        { expiry: "90d", strike: 365.5, moneyness: 1.100009, vol: 0.375, option_type: "CALL" },
        { expiry: "90d", strike: 398.72, moneyness: 1.199988, vol: 0.4, option_type: "CALL" },
        { expiry: "30d", strike: 265.82, moneyness: 0.800012, vol: 0.4, option_type: "PUT" },
        { expiry: "30d", strike: 299.04, moneyness: 0.899991, vol: 0.375, option_type: "PUT" },
        { expiry: "30d", strike: 332.27, moneyness: 1.0, vol: 0.35, option_type: "PUT" },
        { expiry: "30d", strike: 365.5, moneyness: 1.100009, vol: 0.375, option_type: "PUT" },
        { expiry: "30d", strike: 398.72, moneyness: 1.199988, vol: 0.4, option_type: "PUT" },
        { expiry: "60d", strike: 265.82, moneyness: 0.800012, vol: 0.418, option_type: "PUT" },
        { expiry: "60d", strike: 299.04, moneyness: 0.899991, vol: 0.393, option_type: "PUT" },
        { expiry: "60d", strike: 332.27, moneyness: 1.0, vol: 0.368, option_type: "PUT" },
        { expiry: "60d", strike: 365.5, moneyness: 1.100009, vol: 0.393, option_type: "PUT" },
        { expiry: "60d", strike: 398.72, moneyness: 1.199988, vol: 0.418, option_type: "PUT" },
        { expiry: "90d", strike: 265.82, moneyness: 0.800012, vol: 0.436, option_type: "PUT" },
        { expiry: "90d", strike: 299.04, moneyness: 0.899991, vol: 0.411, option_type: "PUT" },
        { expiry: "90d", strike: 332.27, moneyness: 1.0, vol: 0.386, option_type: "PUT" },
        { expiry: "90d", strike: 365.5, moneyness: 1.100009, vol: 0.411, option_type: "PUT" },
        { expiry: "90d", strike: 398.72, moneyness: 1.199988, vol: 0.436, option_type: "PUT" },
      ],
      series: [
        { t: "30d", v: 0.32 },
        { t: "60d", v: 0.335 },
        { t: "90d", v: 0.35 },
      ],
      summary: {
        contracts: 30,
        expiries: 3,
        source_mode: "reference",
        atm_iv_front: 0.32,
        atm_iv_back: 0.35,
        skew: 0,
        term_slope: 0.03,
      },
    },
    status: "provider_unavailable",
    sources: ["black_scholes_reference_formula"],
    elapsed_ms: 2265,
  };
}

beforeEach(() => {
  localStorage.clear();
  mockFn.state = "idle";
  mockFn.data = undefined;
  mockFn.error = null;
  recordedCalls.length = 0;
});

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

describe("IVOL pane — poll pattern", () => {
  it("polls without putting the visibility tick into the fetch params", () => {
    mockFn.state = "ok";
    mockFn.data = livePayload();
    render(<IVOLPane code="IVOL" symbol="AAPL" />);
    expect(recordedCalls.length).toBeGreaterThan(0);
    for (const call of recordedCalls) {
      expect(call.params ?? {}).not.toHaveProperty("tick");
      expect(call.params).toEqual({ underlying: "AAPL" });
    }
  });
});

describe("IVOL pane — live vs reference honesty", () => {
  it("shows the live pill and NO reference notice for a live_yfinance surface", () => {
    mockFn.state = "ok";
    mockFn.data = livePayload();
    render(<IVOLPane code="IVOL" symbol="AAPL" />);
    expect(screen.getByLabelText("surface mode live")).toBeInTheDocument();
    expect(screen.queryByTestId("ivol-reference-notice")).toBeNull();
  });

  it("renders exactly ONE reference notice + pill and carries the provider reason", () => {
    mockFn.state = "ok";
    mockFn.data = referencePayload();
    render(<IVOLPane code="IVOL" symbol="AAPL" />);
    expect(screen.getByLabelText("surface mode reference")).toBeInTheDocument();
    const notices = screen.getAllByTestId("ivol-reference-notice");
    expect(notices).toHaveLength(1);
    expect(notices[0].textContent).toMatch(/not a live OPRA\/CBOE chain/i);
    expect(notices[0].textContent).toMatch(/Provider: yfinance options expiries empty/i);
    // The old triple-labeling surfaces are gone: no skew-mode label, no footer mode.
    expect(screen.queryByTestId("ivol-skew-mode")).toBeNull();
    expect(screen.queryByText("mode")).toBeNull();
  });

  it("renders real KPI values from the live summary (never a permanent em-dash)", () => {
    mockFn.state = "ok";
    mockFn.data = livePayload();
    render(<IVOLPane code="IVOL" symbol="AAPL" />);
    const kpi = screen.getByLabelText("IVOL KPI ribbon");
    expect(within(kpi).getByText("ATM IV (front)")).toBeInTheDocument();
    expect(within(kpi).getByText("ATM IV (back)")).toBeInTheDocument();
    expect(within(kpi).getByText("31.00%")).toBeInTheDocument();
    expect(within(kpi).getByText("33.00%")).toBeInTheDocument();
    expect(within(kpi).getByText("4.00%")).toBeInTheDocument();
    expect(within(kpi).getByText("+2.00%")).toBeInTheDocument();
  });

  it("never claims live when the envelope reports provider_unavailable", () => {
    mockFn.state = "ok";
    mockFn.data = referencePayload();
    render(<IVOLPane code="IVOL" symbol="AAPL" />);
    expect(screen.queryByLabelText("surface mode live")).toBeNull();
    expect(screen.queryByText("live")).toBeNull();
  });
});

describe("IVOL pane — P0 wire fix: heatmap reads the REAL `vol` field", () => {
  it("renders heat cells from `vol` values (old pane keyed on `iv` → empty grid)", () => {
    mockFn.state = "ok";
    mockFn.data = livePayload();
    render(<IVOLPane code="IVOL" symbol="AAPL" />);
    const grid = screen.getByRole("grid", {
      name: /IV surface heatmap/,
    });
    // 3 moneyness buckets, every one a real cell — no dead column.
    expect(within(grid).getAllByRole("gridcell")).toHaveLength(3);
    // K/S 1.00 merges call 31% + put 33% → real avg 32.00%.
    expect(
      within(grid).getByRole("button", { name: /K\/S 100% · IV 32\.00%/ }),
    ).toBeInTheDocument();
    expect(
      within(grid).getByRole("button", { name: /K\/S 95% · IV 35\.00%/ }),
    ).toBeInTheDocument();
  });

  it("renders the full live-probe payload (30 cells · 3 expiries · 5 buckets)", () => {
    mockFn.state = "ok";
    mockFn.data = probePayload();
    render(<IVOLPane code="IVOL" symbol="AAPL" />);
    const grid = screen.getByRole("grid", { name: /IV surface heatmap/ });
    // 3 expiries × 5 moneyness buckets — every cell real, none dead.
    expect(within(grid).getAllByRole("gridcell")).toHaveLength(15);
    // 30d ATM merged cell: call 32% + put 35% → 33.50%.
    expect(
      within(grid).getByRole("button", { name: /30d · K\/S 100% · IV 33\.50%/ }),
    ).toBeInTheDocument();
    // The smile lists all 5 real strikes of the active expiry.
    const smile = screen.getByLabelText("IV smile — call vs put by strike");
    expect(within(smile).getByText("265.82")).toBeInTheDocument();
    expect(within(smile).getByText("398.72")).toBeInTheDocument();
    // Expiry count is deduped (30 surface rows → 3 expiries).
    expect(screen.getByText(/3 exp · poll 60s/)).toBeInTheDocument();
    // Envelope provider_unavailable stays visible; surface is labeled reference.
    const footer = document.querySelector(".ds-pane-footer") as HTMLElement;
    expect(within(footer).getByText("provider_unavailable")).toBeInTheDocument();
    expect(screen.getAllByTestId("ivol-reference-notice")).toHaveLength(1);
  });

  it("falls back to calls_grid/puts_grid `iv` mirrors only when surface is absent", () => {
    mockFn.state = "ok";
    mockFn.data = {
      data: {
        status: "reference",
        symbol: "AAPL",
        spot: 100,
        source_mode: "reference",
        calls_grid: [
          { expiry: "30d", strike: 90, iv: 0.35, volume: 0 },
          { expiry: "30d", strike: 100, iv: 0.31, volume: 0 },
        ],
        puts_grid: [{ expiry: "30d", strike: 100, iv: 0.33, volume: 0 }],
        summary: { contracts: 3, expiries: 1, source_mode: "reference" },
      },
      status: "ok",
      sources: ["black_scholes_reference_formula"],
    };
    render(<IVOLPane code="IVOL" symbol="AAPL" />);
    expect(
      screen.getByRole("button", { name: /K\/S 100% · IV 32\.00%/ }),
    ).toBeInTheDocument();
    const smile = screen.getByLabelText("IV smile — call vs put by strike");
    expect(within(smile).getByText("31.00%")).toBeInTheDocument();
    expect(within(smile).getByText("33.00%")).toBeInTheDocument();
  });

  it("labels the heat metric as the call+put average with % units (R2-#10/F13)", () => {
    mockFn.state = "ok";
    mockFn.data = probePayload();
    render(<IVOLPane code="IVOL" symbol="AAPL" />);
    // The section header names the merge so 33.5 cannot be read as the
    // single-side front ATM (32.00).
    expect(
      screen.getByText(/IV surface · K\/S buckets · cell = call\+put avg \(%\)/),
    ).toBeInTheDocument();
    // The visible cell label carries the unit.
    const cell = screen.getByRole("button", {
      name: /30d · K\/S 100% · IV 33\.50%/,
    });
    expect(cell.textContent).toBe("33.5%");
  });

  it("treats an `iv`-only surface as empty (regression pin for the dead field)", () => {
    mockFn.state = "ok";
    mockFn.data = {
      data: {
        status: "reference",
        symbol: "AAPL",
        spot: 190,
        surface: [
          { expiry: "30d", strike: 180, moneyness: 0.95, iv: 0.35, option_type: "CALL" },
        ],
        summary: { contracts: 1, expiries: 1, source_mode: "reference" },
      },
      status: "ok",
      sources: ["black_scholes_reference_formula"],
    };
    render(<IVOLPane code="IVOL" symbol="AAPL" />);
    expect(screen.getByTestId("pane-state-empty")).toBeInTheDocument();
    expect(
      screen.queryByRole("grid", { name: /IV surface heatmap/ }),
    ).toBeNull();
  });
});

describe("IVOL pane — smile table from real rows", () => {
  it("derives call/put IV by strike and the put−call spread from surface `vol`", () => {
    mockFn.state = "ok";
    mockFn.data = livePayload();
    render(<IVOLPane code="IVOL" symbol="AAPL" />);
    const smile = screen.getByLabelText("IV smile — call vs put by strike");
    expect(within(smile).getByText("Call IV")).toBeInTheDocument();
    expect(within(smile).getByText("Put IV")).toBeInTheDocument();
    expect(within(smile).getByText("190.00")).toBeInTheDocument();
    expect(within(smile).getByText("31.00%")).toBeInTheDocument();
    expect(within(smile).getByText("33.00%")).toBeInTheDocument();
    // Put − Call = +2 at strike 190, −2 at strike 200.
    expect(within(smile).getByLabelText(/change \+2/)).toBeInTheDocument();
    expect(within(smile).getByLabelText(/change -2/)).toBeInTheDocument();
  });

  it("exports the smile through the header CSV control", () => {
    mockFn.state = "ok";
    mockFn.data = livePayload();
    render(<IVOLPane code="IVOL" symbol="AAPL" />);
    expect(
      screen.getByRole("button", { name: "Download 3 smile rows as CSV" }),
    ).toBeEnabled();
  });

  it("does not render an empty smile section when a side has no usable strike", () => {
    mockFn.state = "ok";
    mockFn.data = {
      data: {
        status: "ok",
        symbol: "AAPL",
        spot: 190,
        source_mode: "live_yfinance",
        surface: [
          { expiry: EXPIRY, moneyness: 0.95, vol: 0.3 },
          { expiry: EXPIRY, moneyness: 1.05, vol: 0.4 },
        ],
        summary: { contracts: 2, expiries: 1, source_mode: "live_yfinance" },
      },
      status: "ok",
      sources: ["yfinance"],
    };
    render(<IVOLPane code="IVOL" symbol="AAPL" />);
    expect(
      screen.queryByLabelText("IV smile — call vs put by strike"),
    ).toBeNull();
  });
});

describe("IVOL pane — expiry dedupe", () => {
  it("renders one tab per unique expiry and emits no duplicate-key warning", () => {
    const errorSpy = vi.spyOn(console, "error").mockImplementation(() => {});
    mockFn.state = "ok";
    mockFn.data = dedupePayload();
    render(<IVOLPane code="IVOL" symbol="AAPL" />);
    expect(screen.getAllByRole("tab")).toHaveLength(3);
    expect(screen.getByText(/3 exp · poll 60s/)).toBeInTheDocument();
    const keyWarnings = errorSpy.mock.calls.filter((call) =>
      /same key|unique "key"/i.test(String(call[0])),
    );
    expect(keyWarnings).toHaveLength(0);
  });
});

describe("IVOL pane — keyboard navigation on the primary grid", () => {
  it("moves focus with arrow/End keys across heat cells (roving tabindex)", () => {
    mockFn.state = "ok";
    mockFn.data = livePayload();
    render(<IVOLPane code="IVOL" symbol="AAPL" />);
    const first = screen.getByRole("button", { name: /K\/S 95% · IV 35\.00%/ });
    first.focus();
    expect(first.tabIndex).toBe(0);
    fireEvent.keyDown(first, { key: "ArrowRight" });
    const second = screen.getByRole("button", { name: /K\/S 100% · IV 32\.00%/ });
    expect(document.activeElement).toBe(second);
    expect(second.tabIndex).toBe(0);
    expect(first.tabIndex).toBe(-1);
    fireEvent.keyDown(second, { key: "End" });
    expect(document.activeElement).toBe(
      screen.getByRole("button", { name: /K\/S 105% · IV 35\.00%/ }),
    );
  });
});

describe("IVOL pane — footer provenance", () => {
  it("keeps provider/status/cells/elapsed once and no mode echo", () => {
    mockFn.state = "ok";
    mockFn.data = livePayload();
    render(<IVOLPane code="IVOL" symbol="AAPL" />);
    const footer = document.querySelector(".ds-pane-footer") as HTMLElement;
    expect(footer).toBeTruthy();
    expect(within(footer).getByText("provider")).toBeInTheDocument();
    expect(within(footer).getByText("yfinance")).toBeInTheDocument();
    expect(within(footer).getByText("status")).toBeInTheDocument();
    expect(within(footer).getByText("ok")).toBeInTheDocument();
    expect(within(footer).getByText("cells")).toBeInTheDocument();
    expect(within(footer).getByText("5")).toBeInTheDocument();
    expect(within(footer).getByText("12 ms")).toBeInTheDocument();
    expect(within(footer).queryByText("mode")).toBeNull();
  });
});
