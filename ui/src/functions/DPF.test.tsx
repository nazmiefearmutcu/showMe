/**
 * DPF pane — fallback honesty tests.
 *
 * The timeout/provider-unavailable path serves a labelled shape model. These
 * tests pin that:
 *  - fabricated shape rows are NEVER relabelled as stale FINRA data;
 *  - the backend reason/warning is actually surfaced in the body;
 *  - the "Weeks" KPI caption says "LATEST WEEK IN MODEL" for the shape path
 *    instead of an "AS OF" date that would imply reported weeks.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, render, screen } from "@testing-library/react";
import { DPFPane } from "./DPF";

/* ── useFunction mock ──────────────────────────────────────────────── */

interface MockFnState {
  state: "idle" | "loading" | "ok" | "error" | "refreshing";
  data?: { data?: unknown; sources?: string[]; elapsed_ms?: number } | undefined;
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

function shapeModelPayload() {
  return {
    data: {
      sources: ["dark_pool_model"],
      elapsed_ms: 9002,
      data: {
        status: "provider_unavailable",
        reason: "DPF execution timed out: 9.0s",
        weekly: [
          {
            weekStartDate: "2026-09-07",
            ats_share_volume: 12_345_678,
            ats_trade_count: 18_000,
            estimated_total_volume: null,
            dark_pool_pct: null,
            source_mode: "shape_model_timeout",
            data_warning: "DPF execution timed out: 9.0s",
          },
          {
            weekStartDate: "2026-08-31",
            ats_share_volume: 11_900_000,
            ats_trade_count: 17_400,
            estimated_total_volume: null,
            dark_pool_pct: null,
            source_mode: "shape_model_timeout",
            data_warning: "DPF execution timed out: 9.0s",
          },
        ],
      },
    },
  };
}

function reportedFinraPayload() {
  return {
    data: {
      sources: ["finra", "yfinance"],
      elapsed_ms: 421,
      data: {
        status: "ok",
        weekly: [
          {
            weekStartDate: "2026-09-07",
            ats_share_volume: 12_345_678,
            ats_trade_count: 18_000,
            estimated_total_volume: 40_000_000,
            dark_pool_pct: 30.86,
            source_mode: "finra_ats_weekly",
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
});

describe("DPF pane — shape-model fallback honesty", () => {
  it("never labels fabricated shape rows as stale FINRA data", () => {
    setMockFn({ state: "ok", ...shapeModelPayload() });
    render(<DPFPane code="DPF" symbol="AAPL" />);
    expect(screen.queryByText(/finra_ats_weekly_stale/)).toBeNull();
    expect(screen.getAllByText("shape_model_timeout").length).toBeGreaterThan(0);
  });

  it("surfaces the backend timeout reason in a visible warning", () => {
    setMockFn({ state: "ok", ...shapeModelPayload() });
    render(<DPFPane code="DPF" symbol="AAPL" />);
    const warning = screen.getByLabelText("DPF data warning");
    expect(warning).toHaveTextContent(/timed out/i);
  });

  it("captions the model weeks as model weeks, not an AS OF reported date", () => {
    setMockFn({ state: "ok", ...shapeModelPayload() });
    render(<DPFPane code="DPF" symbol="AAPL" />);
    expect(screen.getByText("LATEST WEEK IN MODEL")).toBeInTheDocument();
    expect(screen.queryByText(/^AS OF /)).toBeNull();
  });
});

describe("DPF pane — reported FINRA path", () => {
  it("shows no warning and a real AS OF caption when FINRA rows are ok", () => {
    setMockFn({ state: "ok", ...reportedFinraPayload() });
    render(<DPFPane code="DPF" symbol="AAPL" />);
    expect(screen.queryByLabelText("DPF data warning")).toBeNull();
    expect(screen.getByText(/AS OF 2026-09-07/)).toBeInTheDocument();
    expect(screen.getByText("finra_ats_weekly")).toBeInTheDocument();
  });
});
