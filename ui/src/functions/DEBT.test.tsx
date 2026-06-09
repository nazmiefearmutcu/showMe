/**
 * DEBT pane — honesty + a11y + display contract tests.
 *
 * DEBT is a macro sovereign-debt board: a horizontal debt-to-GDP ranking by
 * country, a local-currency-share column (a published REFERENCE, not a live
 * series), and a portfolio-weight overlay that is pinned 0 in the baseline.
 * These tests pin the HONESTY-FIRST upgrade:
 *
 *  - the provider/methodology no longer claims FRED (backend seed fix);
 *  - per-row observation `year` is surfaced so the data VINTAGE is distinct
 *    from the fetch timestamp (as_of);
 *  - the local-currency column is labelled a REFERENCE (not a live series);
 *  - when summary.portfolio_linked is false the board is unmistakably macro-only,
 *    and a null portfolio weight renders the missing sentinel ("—") while a real
 *    0 renders "0.00%";
 *  - the percent contract is NOT double-converted (125.67 → "125.7%");
 *  - loading/error/empty sit in a SCOPED role=status live region while the
 *    steady-state table/bars do NOT (the pane polls — no SR spam);
 *  - the bars expose their magnitude to AT (role=img + value in the name);
 *  - the region Tabs and DataGrid carry accessible names and the RefreshButton
 *    reports aria-busy while polling.
 *
 * `useFunction` is mocked via mutable shared state so each test drives the pane
 * into a specific branch without the real sidecar transport.
 */
import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, render, screen } from "@testing-library/react";
import { DEBTPane } from "./DEBT";

/* ── useFunction mock ──────────────────────────────────────────────── */

interface MockFnState {
  state: "idle" | "loading" | "ok" | "error" | "refreshing";
  data?: Record<string, unknown> | undefined;
  error?: Error | null;
}

const mockFn: MockFnState = { state: "idle", data: undefined, error: null };
const refetch = vi.fn();

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
    refetch,
  }),
}));

// Visibility poll is irrelevant to render assertions — return a stable tick.
vi.mock("@/lib/useVisibilityTick", () => ({
  useVisibilityTick: () => 0,
}));

/* ── fixtures ──────────────────────────────────────────────────────── */

const AS_OF = "2026-06-09T11:55:00.000Z";

const rows = [
  {
    country: "JP",
    name: "Japan",
    region: "asia",
    debt_to_gdp: 255.12,
    local_currency_share: 92.0,
    portfolio_weight_pct: 0.0,
    change: 3.4,
    year: "2023",
    history: [240, 245, 250, 255],
  },
  {
    country: "US",
    name: "United States",
    region: "americas",
    debt_to_gdp: 125.67,
    local_currency_share: 99.0,
    portfolio_weight_pct: 0.0,
    change: -1.2,
    year: "2023",
    history: [118, 120, 123, 125],
  },
  {
    country: "DE",
    name: "Germany",
    region: "europe",
    debt_to_gdp: 63.4,
    local_currency_share: 96.0,
    // missing portfolio weight → must render the em-dash sentinel, not 0.00%
    portfolio_weight_pct: null,
    change: -0.8,
    year: "2022",
    history: [70, 68, 65, 63],
  },
];

function okPayload(extra: Record<string, unknown> = {}, summaryExtra: Record<string, unknown> = {}) {
  return {
    data: {
      data: {
        status: "ok",
        rows,
        summary: {
          countries: rows.length,
          avg_debt_to_gdp: 148.06,
          measure: "world_bank_debt_to_gdp",
          portfolio_linked: false,
          ...summaryExtra,
        },
        data_mode: "live_official",
        methodology:
          "DEBT pulls live general-government debt-to-GDP from the World Bank indicator API. " +
          "local_currency_share is a published reference, not a live World Bank series.",
        warnings: [
          "local_currency_share is a published reference, not a live World Bank series.",
        ],
        as_of: AS_OF,
        ...extra,
      },
      sources: ["worldbank"],
      elapsed_ms: 14,
    },
  };
}

/* ── tests ─────────────────────────────────────────────────────────── */

beforeEach(() => {
  localStorage.clear();
  refetch.mockClear();
  setMockFn({ state: "idle", data: undefined });
});
afterEach(() => {
  cleanup();
});

describe("DEBT pane — load states (scoped live region)", () => {
  it("renders the loading placeholder in an aria-busy live region (no grid)", () => {
    setMockFn({ state: "loading", data: undefined });
    const { container } = render(<DEBTPane code="DEBT" />);
    const busy = container.querySelector('[role="status"][aria-busy="true"]');
    expect(busy).not.toBeNull();
    // The country grid is not yet mounted.
    expect(
      container.querySelector('[aria-label="Ülke bazında devlet borcu"]'),
    ).toBeNull();
  });

  it("wraps the error state in a role=status live region", () => {
    setMockFn({ state: "error", data: undefined, error: new Error("boom") });
    const { container } = render(<DEBTPane code="DEBT" />);
    const status = container.querySelector('[role="status"]');
    expect(status).not.toBeNull();
    expect(status?.textContent ?? "").toMatch(/boom/);
  });

  it("does NOT wrap the steady-state table in a polite live region", () => {
    // Regression: the live region must be scoped to loading/error transitions.
    // The grid re-renders on every poll — if it sat inside an aria-live region,
    // screen readers would re-announce the whole board each refresh.
    setMockFn({ state: "ok", ...okPayload() });
    const { container } = render(<DEBTPane code="DEBT" />);
    const grid = container.querySelector(
      '[aria-label="Ülke bazında devlet borcu"]',
    );
    expect(grid).not.toBeNull();
    expect(grid?.closest('[aria-live]')).toBeNull();
    expect(grid?.closest('[role="status"]')).toBeNull();
  });

  it("flags the RefreshButton aria-busy while loading", () => {
    setMockFn({ state: "loading", data: undefined });
    render(<DEBTPane code="DEBT" />);
    const refresh = screen.getByRole("button", { name: /refresh/i });
    expect(refresh).toHaveAttribute("aria-busy", "true");
  });
});

describe("DEBT pane — display / percent contract", () => {
  it("renders debt/GDP already-in-percent, NOT double-converted (125.67 → 125.7%)", () => {
    setMockFn({ state: "ok", ...okPayload() });
    render(<DEBTPane code="DEBT" />);
    // 125.67 → "125.7%" (1dp), never "12567%" (×100) or "1.26%" (÷100).
    expect(screen.getAllByText("125.7%").length).toBeGreaterThan(0);
    expect(screen.queryByText(/12567/)).toBeNull();
    expect(screen.queryByText("1.26%")).toBeNull();
  });
});

describe("DEBT pane — freshness honesty (observation year)", () => {
  it("surfaces the per-row observation year (data vintage)", () => {
    setMockFn({ state: "ok", ...okPayload() });
    render(<DEBTPane code="DEBT" />);
    // The 2023 vintage shows for JP/US, 2022 for DE.
    expect(screen.getAllByText("2023").length).toBeGreaterThan(0);
    expect(screen.getByText("2022")).toBeInTheDocument();
  });
});

describe("DEBT pane — local-currency REFERENCE disclosure", () => {
  it("labels the local-ccy column as a reference (not a live series)", () => {
    setMockFn({ state: "ok", ...okPayload() });
    render(<DEBTPane code="DEBT" />);
    // A "ref"/"referans" disclosure must be visible alongside the local-ccy column.
    expect(screen.getAllByText(/referans/i).length).toBeGreaterThan(0);
  });
});

describe("DEBT pane — portfolio honesty", () => {
  it("portfolio_linked=false → an unmistakable macro-only badge/note", () => {
    setMockFn({ state: "ok", ...okPayload() });
    const { container } = render(<DEBTPane code="DEBT" />);
    const note = container.querySelector('[data-testid="debt-portfolio-note"]');
    expect(note).not.toBeNull();
    expect(note?.textContent ?? "").toMatch(/sadece makro/i);
  });

  it("distinguishes a null portfolio weight (—) from a real 0 (0.00%)", () => {
    setMockFn({ state: "ok", ...okPayload() });
    render(<DEBTPane code="DEBT" />);
    // JP/US have a real 0 → "0.00%"; DE has null → the em-dash sentinel.
    expect(screen.getAllByText("0.00%").length).toBeGreaterThan(0);
    // The DE row's portfolio cell shows the em-dash (not "0.00%").
    const deCell = screen.getByTestId("debt-portfolio-DE");
    expect(deCell.textContent).toBe("—");
  });
});

describe("DEBT pane — a11y (bars, labels)", () => {
  it("exposes each debt bar's magnitude to AT (role=img + value in the name)", () => {
    setMockFn({ state: "ok", ...okPayload() });
    render(<DEBTPane code="DEBT" />);
    // JP at 255.12% must be in an accessible bar name.
    const bar = screen.getByRole("img", { name: /JP.*255/ });
    expect(bar).toBeInTheDocument();
  });

  it("does not duplicate the name in a bar label for a name-only row (no country)", () => {
    // Regression: accName once collapsed country??name into `label` and then
    // re-appended name → "Eurozone Eurozone". A row with name but no country
    // must read its name exactly once.
    setMockFn({
      state: "ok",
      ...okPayload({
        rows: [
          {
            name: "Eurozone",
            debt_to_gdp: 90.0,
            local_currency_share: 100,
            portfolio_weight_pct: 0,
            year: "2023",
          },
        ],
      }),
    });
    render(<DEBTPane code="DEBT" />);
    const bar = screen.getByRole("img", { name: /Eurozone: borç/i });
    expect(bar.getAttribute("aria-label") ?? "").not.toMatch(/Eurozone\s+Eurozone/);
  });

  it("gives the region Tabs and the DataGrid accessible names", () => {
    setMockFn({ state: "ok", ...okPayload() });
    const { container } = render(<DEBTPane code="DEBT" />);
    expect(
      container.querySelector('[role="tablist"][aria-label="Bölge filtresi"]'),
    ).not.toBeNull();
    expect(
      container.querySelector('[aria-label="Ülke bazında devlet borcu"]'),
    ).not.toBeNull();
  });

  it("labels the severity legend dots (not color-only)", () => {
    setMockFn({ state: "ok", ...okPayload() });
    render(<DEBTPane code="DEBT" />);
    const legends = screen.getAllByRole("img", { name: /borç\/GSYİH|< 60|> 100|60/i });
    expect(legends.length).toBeGreaterThan(0);
  });
});

describe("DEBT pane — source guard", () => {
  it("DEBT.tsx contains no dead --text-tertiary token", () => {
    const __dir = dirname(fileURLToPath(import.meta.url));
    const src = readFileSync(join(__dir, "DEBT.tsx"), "utf8");
    expect(src).not.toMatch(/--text-tertiary/);
  });
});
