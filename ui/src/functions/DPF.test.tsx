/**
 * DPF pane — a11y + honesty + display-contract tests.
 *
 * DPF reports FINRA-reported weekly off-exchange (ATS) share volume plus an
 * estimated dark-pool percent of the REAL consolidated weekly volume. The
 * backend is already honesty-strong (dark_pool_pct is 0–100, clamped, left
 * null when the real denominator is unavailable). These tests pin the
 * FRONTEND honesty + a11y upgrade:
 *
 *  - A1: loading / error branches sit in a SCOPED role=status live region;
 *        the steady-state KPI+table branch stays OUTSIDE any aria-live so the
 *        ~poll refetch never re-announces the whole grid;
 *  - A2: the RefreshButton reports aria-busy while loading/refreshing;
 *  - A3: each row's source_mode pill renders a HUMAN label + an honest
 *        aria-label (live FINRA / stale snapshot / illustrative model), with
 *        the data_warning surfaced via title;
 *  - A4: the header status pill, DataGrid, and KPI ribbon all carry an
 *        accessible name;
 *  - D1: metadata.provider_errors surface in an announced (role=alert) region;
 *  - D2: shared formatters — 38.2 → "38.20%" (NO double-convert), null → "—",
 *        12.4M volume → compact "12.40M";
 *  - D3: avg dark % skips null weeks (no NaN); a prevAts=0 case never yields
 *        Infinity in the ATS delta/trend.
 *
 * `useFunction` is mocked via mutable shared state so each test drives the
 * pane into a specific branch without the real sidecar transport.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, render, screen } from "@testing-library/react";
import { DPFPane } from "./DPF";

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

/* ── fixtures ──────────────────────────────────────────────────────── */

// Live FINRA weeks. Latest dark_pool_pct = 38.2 → must render "38.20%".
// ats_share_volume 12,400,000 → compact "12.40M".
const liveWeekly = [
  {
    weekStartDate: "2026-06-01",
    ats_share_volume: 12_400_000,
    ats_trade_count: 41_000,
    estimated_total_volume: 32_460_000,
    dark_pool_pct: 38.2,
    source_mode: "finra_ats_weekly",
  },
  {
    weekStartDate: "2026-05-25",
    ats_share_volume: 10_000_000,
    ats_trade_count: 38_000,
    estimated_total_volume: 28_000_000,
    dark_pool_pct: 35.71,
    source_mode: "finra_ats_weekly",
  },
];

function livePayload(extra: Record<string, unknown> = {}) {
  return {
    data: {
      data: {
        status: "ok",
        weekly: liveWeekly,
        rows: liveWeekly,
        ...extra,
      },
      sources: ["finra", "yfinance"],
      elapsed_ms: 11,
      metadata: {},
    },
  };
}

// Stale FINRA snapshot: provider_unavailable + data_warning + provider_errors.
const staleReason =
  "FINRA latest week 2024-01-01 is stale for a current market cockpit.";
const staleWeekly = [
  {
    weekStartDate: "2024-01-01",
    ats_share_volume: 9_000_000,
    ats_trade_count: 30_000,
    estimated_total_volume: 25_000_000,
    dark_pool_pct: 36.0,
    source_mode: "finra_ats_weekly_stale",
    data_warning: staleReason,
  },
];

function stalePayload() {
  return {
    data: {
      data: {
        status: "provider_unavailable",
        weekly: staleWeekly,
        rows: staleWeekly,
      },
      sources: ["finra", "yfinance"],
      elapsed_ms: 9,
      metadata: {
        provider_errors: [staleReason],
      },
    },
  };
}

// Illustrative labelled shape model — NOT live data; dark_pool_pct fabricated
// shape, real denominator unavailable (estimated_total_volume null).
const modelWeekly = [
  {
    weekStartDate: "2026-06-01",
    ats_share_volume: 8_000_000,
    ats_trade_count: null,
    estimated_total_volume: null,
    dark_pool_pct: null,
    source_mode: "labelled_current_shape_model",
    data_warning: "Illustrative shape — not live FINRA data.",
  },
];

function modelPayload() {
  return {
    data: {
      data: {
        status: "ok",
        weekly: modelWeekly,
        rows: modelWeekly,
      },
      sources: ["dark_pool_model"],
      elapsed_ms: 5,
      metadata: {
        provider_errors: ["Anonymous FINRA endpoint unavailable."],
      },
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

describe("DPF pane — A1 scoped live region", () => {
  it("wraps the loading branch in an aria-busy role=status region (no grid)", () => {
    setMockFn({ state: "loading", data: undefined });
    const { container } = render(<DPFPane code="DPF" symbol="AAPL" />);
    const busy = container.querySelector('[role="status"][aria-busy="true"]');
    expect(busy).not.toBeNull();
    expect(
      container.querySelector('[aria-label="Haftalık dark pool / ATS hacmi"]'),
    ).toBeNull();
  });

  it("wraps the error branch in a role=status live region", () => {
    setMockFn({ state: "error", data: undefined, error: new Error("boom") });
    const { container } = render(<DPFPane code="DPF" symbol="AAPL" />);
    const status = container.querySelector('[role="status"]');
    expect(status).not.toBeNull();
    expect(status?.textContent ?? "").toMatch(/boom/);
  });

  it("does NOT wrap the steady-state table in a polite live region", () => {
    setMockFn({ state: "ok", ...livePayload() });
    const { container } = render(<DPFPane code="DPF" symbol="AAPL" />);
    const grid = container.querySelector(
      '[aria-label="Haftalık dark pool / ATS hacmi"]',
    );
    expect(grid).not.toBeNull();
    expect(grid?.closest('[role="status"]')).toBeNull();
    // The KPI ribbon must also be outside any live region.
    const kpi = container.querySelector('[aria-label="DPF KPI ribbon"]');
    expect(kpi).not.toBeNull();
    expect(kpi?.closest('[aria-live]')).toBeNull();
  });
});

describe("DPF pane — A2 RefreshButton busy", () => {
  it("flags the RefreshButton aria-busy while refreshing", () => {
    setMockFn({ state: "refreshing", ...livePayload() });
    render(<DPFPane code="DPF" symbol="AAPL" />);
    const refresh = screen.getByRole("button", { name: /refresh/i });
    expect(refresh).toHaveAttribute("aria-busy", "true");
  });

  it("flags the RefreshButton aria-busy while loading", () => {
    setMockFn({ state: "loading", data: undefined });
    render(<DPFPane code="DPF" symbol="AAPL" />);
    const refresh = screen.getByRole("button", { name: /refresh/i });
    expect(refresh).toHaveAttribute("aria-busy", "true");
  });
});

describe("DPF pane — A3 source_mode pill (human label + honest aria)", () => {
  it("a live row → human 'Live' label + aria-label conveying live", () => {
    setMockFn({ state: "ok", ...livePayload() });
    render(<DPFPane code="DPF" symbol="AAPL" />);
    const pills = screen.getAllByLabelText(/canlı FINRA/i);
    expect(pills.length).toBeGreaterThan(0);
    expect(pills[0].textContent ?? "").toMatch(/Live|Canlı/);
    // The raw enum must NOT be shown to the user.
    expect(screen.queryByText("finra_ats_weekly")).toBeNull();
  });

  it("a stale row → aria-label conveys 'out-of-date/stale' + title=data_warning", () => {
    setMockFn({ state: "ok", ...stalePayload() });
    render(<DPFPane code="DPF" symbol="AAPL" />);
    const pill = screen.getByLabelText(/güncel değil|bayat|eski anlık/i);
    expect(pill.textContent ?? "").toMatch(/Stale|Bayat/);
    // The staleness reason is reachable via title.
    expect(pill.getAttribute("title")).toBe(staleReason);
  });

  it("a model row → label/aria make clear it is NOT live (illustrative)", () => {
    setMockFn({ state: "ok", ...modelPayload() });
    render(<DPFPane code="DPF" symbol="AAPL" />);
    const pill = screen.getByLabelText(/canlı değil|örnek|illustrative|model/i);
    expect(pill.textContent ?? "").toMatch(/Model/);
    // Must not be advertised as a live feed.
    expect(pill.getAttribute("aria-label") ?? "").not.toMatch(/canlı FINRA/i);
  });
});

describe("DPF pane — A4 accessible names", () => {
  it("gives the DataGrid an accessible name", () => {
    setMockFn({ state: "ok", ...livePayload() });
    const { container } = render(<DPFPane code="DPF" symbol="AAPL" />);
    expect(
      container.querySelector('[aria-label="Haftalık dark pool / ATS hacmi"]'),
    ).not.toBeNull();
  });

  it("labels the header status pill with a data-mode aria-label", () => {
    setMockFn({ state: "ok", ...livePayload() });
    render(<DPFPane code="DPF" symbol="AAPL" />);
    expect(screen.getByLabelText(/Veri modu:/i)).toBeInTheDocument();
  });

  it("gives the KPI ribbon an accessible name", () => {
    setMockFn({ state: "ok", ...livePayload() });
    const { container } = render(<DPFPane code="DPF" symbol="AAPL" />);
    expect(
      container.querySelector('[aria-label="DPF KPI ribbon"]'),
    ).not.toBeNull();
  });
});

describe("DPF pane — D1 surface provider_errors", () => {
  it("renders provider_errors in an announced role=alert region", () => {
    setMockFn({ state: "ok", ...stalePayload() });
    const { container } = render(<DPFPane code="DPF" symbol="AAPL" />);
    const alert = container.querySelector('[role="alert"]');
    expect(alert).not.toBeNull();
    expect(alert?.textContent ?? "").toMatch(/stale|FINRA/i);
  });

  it("renders nothing alert-y when provider_errors is empty", () => {
    setMockFn({ state: "ok", ...livePayload() });
    const { container } = render(<DPFPane code="DPF" symbol="AAPL" />);
    expect(container.querySelector('[role="alert"]')).toBeNull();
  });
});

describe("DPF pane — D2 shared formatters (no double-convert / null-safe)", () => {
  it("renders dark_pool_pct 38.2 as '38.20%' (NOT 3820% or 0.38%)", () => {
    setMockFn({ state: "ok", ...livePayload() });
    render(<DPFPane code="DPF" symbol="AAPL" />);
    expect(screen.getAllByText("38.20%").length).toBeGreaterThan(0);
    expect(screen.queryByText("3820.00%")).toBeNull();
    expect(screen.queryByText("0.38%")).toBeNull();
  });

  it("renders a 12.4M ATS volume as compact '12.40M'", () => {
    setMockFn({ state: "ok", ...livePayload() });
    render(<DPFPane code="DPF" symbol="AAPL" />);
    expect(screen.getAllByText("12.40M").length).toBeGreaterThan(0);
  });

  it("renders a null dark_pool_pct as the missing sentinel '—' (not 0%/NaN%)", () => {
    setMockFn({ state: "ok", ...modelPayload() });
    render(<DPFPane code="DPF" symbol="AAPL" />);
    // The model row has dark_pool_pct null and estimated_total_volume null.
    expect(screen.queryByText("0.00%")).toBeNull();
    expect(screen.queryByText("NaN%")).toBeNull();
    // At least one "—" present for the null cells.
    expect(screen.getAllByText("—").length).toBeGreaterThan(0);
  });
});

describe("DPF pane — D3 null-safe avg + divide-by-zero guard", () => {
  it("all-null-pct window → avg dark % renders '—' (not NaN)", () => {
    const allNull = [
      {
        weekStartDate: "2026-06-01",
        ats_share_volume: 5_000_000,
        estimated_total_volume: null,
        dark_pool_pct: null,
        source_mode: "finra_ats_weekly",
      },
      {
        weekStartDate: "2026-05-25",
        ats_share_volume: 4_000_000,
        estimated_total_volume: null,
        dark_pool_pct: null,
        source_mode: "finra_ats_weekly",
      },
    ];
    setMockFn({
      state: "ok",
      data: {
        data: { status: "ok", weekly: allNull, rows: allNull },
        sources: ["finra"],
        elapsed_ms: 7,
        metadata: {},
      },
    });
    render(<DPFPane code="DPF" symbol="AAPL" />);
    // Latest dark % card caption is "AVG —"; never "AVG NaN%".
    expect(screen.queryByText(/AVG NaN/i)).toBeNull();
    expect(screen.getByText(/AVG —/)).toBeInTheDocument();
  });

  it("prevAts=0 → no Infinity leaks into the ATS delta tone/trend", () => {
    const zeroPrev = [
      {
        weekStartDate: "2026-06-01",
        ats_share_volume: 5_000_000,
        estimated_total_volume: 10_000_000,
        dark_pool_pct: 50,
        source_mode: "finra_ats_weekly",
      },
      {
        weekStartDate: "2026-05-25",
        ats_share_volume: 0,
        estimated_total_volume: 10_000_000,
        dark_pool_pct: 0,
        source_mode: "finra_ats_weekly",
      },
    ];
    setMockFn({
      state: "ok",
      data: {
        data: { status: "ok", weekly: zeroPrev, rows: zeroPrev },
        sources: ["finra"],
        elapsed_ms: 7,
        metadata: {},
      },
    });
    const { container } = render(<DPFPane code="DPF" symbol="AAPL" />);
    // Infinity must never reach the DOM (would show "Infinity%" / "∞").
    expect(container.textContent ?? "").not.toMatch(/Infinity/);
    expect(container.textContent ?? "").not.toContain("∞");
  });
});
