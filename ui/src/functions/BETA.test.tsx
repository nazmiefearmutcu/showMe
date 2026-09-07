/**
 * BETA pane — render-contract + honesty tests.
 *
 * Pins:
 *  - loading / error / ok render paths;
 *  - the beta + R² headline cards reflect the SELECTED window and follow
 *    the persisted window control;
 *  - the rolling-beta sparkline renders an inline SVG when history exists
 *    and an honest empty note when it does not;
 *  - the backend `computed_market_model` SEEDED baseline renders a prominent
 *    "baseline" warning (never shown as a live regression);
 *  - the rolling-window control re-issues the call with `rolling_window`.
 *
 * `useFunction` is mocked with a mutable shared state + an args recorder.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { BetaPane } from "./BETA";

/* ── mocks ─────────────────────────────────────────────────────────── */

interface MockFnState {
  state: "idle" | "loading" | "ok" | "error" | "refreshing";
  data?: { data?: unknown; warnings?: string[] } | undefined;
  error?: Error | null;
}

const mockFn: MockFnState = { state: "idle", data: undefined, error: null };
const refetchMock = vi.fn();

interface RecordedArgs {
  code: string;
  symbol?: string;
  params?: Record<string, unknown>;
}

const lastArgs: RecordedArgs[] = [];

function lastCall(): RecordedArgs | undefined {
  return lastArgs[lastArgs.length - 1];
}

vi.mock("@/lib/useFunction", () => ({
  useFunction: (args: RecordedArgs) => {
    lastArgs.push(args);
    return {
      state: mockFn.state,
      data: mockFn.data,
      error: mockFn.error,
      refetch: refetchMock,
    };
  },
}));

/* ── fixtures ──────────────────────────────────────────────────────── */

function okPayload() {
  return {
    data: {
      status: "ok",
      benchmark: "SPY",
      rows: [
        {
          window: "1Y",
          window_days: 252,
          beta: 1.07,
          correlation: 0.72,
          samples: 252,
          annualized_volatility_target: 0.24,
          annualized_volatility_bench: 0.18,
        },
        {
          window: "2Y",
          window_days: 504,
          beta: 0.95,
          correlation: 0.66,
          samples: 504,
          annualized_volatility_target: 0.22,
          annualized_volatility_bench: 0.17,
        },
        {
          window: "5Y",
          window_days: 1260,
          beta: 0.68,
          correlation: 0.55,
          samples: 1260,
          annualized_volatility_target: 0.2,
          annualized_volatility_bench: 0.16,
        },
      ],
      history: [
        { date: "2026-08-04", beta: 1.05, rolling_window: 60, samples: 60 },
        { date: "2026-08-18", beta: 1.12, rolling_window: 60, samples: 60 },
        { date: "2026-08-25", beta: 0.98, rolling_window: 60, samples: 60 },
        { date: "2026-09-01", beta: 1.07, rolling_window: 60, samples: 60 },
      ],
    },
    warnings: [],
    sources: ["yfinance"],
    elapsed_ms: 810,
  };
}

function baselinePayload() {
  return {
    data: {
      status: "computed_market_model",
      benchmark: "SPY",
      betas: {
        "1Y": {
          beta: 0.9,
          correlation: 0.62,
          samples: 252,
          annualized_volatility_target: 0.23,
          annualized_volatility_bench: 0.18,
        },
      },
    },
    warnings: [],
    sources: ["beta_market_model"],
    elapsed_ms: 3,
  };
}

beforeEach(() => {
  lastArgs.length = 0;
  refetchMock.mockClear();
  mockFn.state = "idle";
  mockFn.data = undefined;
  mockFn.error = null;
  localStorage.clear();
});
afterEach(() => {
  cleanup();
});

/* ── tests ─────────────────────────────────────────────────────────── */

describe("BETA pane — load states", () => {
  it("renders a skeleton while loading", () => {
    mockFn.state = "loading";
    const { container } = render(<BetaPane code="BETA" symbol="AAPL" />);
    expect(container.querySelector('[aria-busy="true"]')).not.toBeNull();
  });

  it("renders the error state when the fetch errors", () => {
    mockFn.state = "error";
    mockFn.error = new Error("sidecar exploded");
    render(<BetaPane code="BETA" symbol="AAPL" />);
    expect(screen.getByText(/sidecar exploded/i)).toBeInTheDocument();
  });

  it("surfaces provider_unavailable with the backend reason verbatim", () => {
    mockFn.state = "ok";
    mockFn.data = {
      data: {
        status: "provider_unavailable",
        reason: "yfinance adapter not configured; BETA cannot compute live regression.",
        rows: [],
      },
      warnings: [],
    };
    render(<BetaPane code="BETA" symbol="AAPL" />);
    expect(screen.getByText(/yfinance adapter not configured/i)).toBeInTheDocument();
  });
});

describe("BETA pane — ok payload", () => {
  it("renders beta and R-squared headline cards for the selected window", () => {
    mockFn.state = "ok";
    mockFn.data = okPayload();
    const { container } = render(<BetaPane code="BETA" symbol="AAPL" />);
    // 1Y headline beta.
    expect(container.textContent).toContain("1.07");
    // R² = 0.72² = 0.518 (rounded to 3 decimals).
    expect(container.textContent).toContain("0.518");
    // All three window rows in the table (text also appears on the window
    // segmented control, hence getAllByText).
    expect(screen.getAllByText("2Y").length).toBeGreaterThan(0);
    expect(screen.getAllByText("5Y").length).toBeGreaterThan(0);
  });

  it("switches the headline when the persisted window control changes", () => {
    mockFn.state = "ok";
    mockFn.data = okPayload();
    const { container } = render(<BetaPane code="BETA" symbol="AAPL" />);
    fireEvent.click(screen.getByTitle("WINDOW 2Y"));
    expect(container.textContent).toContain("0.95");
    expect(container.textContent).toContain("0.436"); // 0.66² = 0.4356
  });

  it("renders the rolling-beta sparkline as an inline SVG", () => {
    mockFn.state = "ok";
    mockFn.data = okPayload();
    render(<BetaPane code="BETA" symbol="AAPL" />);
    const spark = screen.getByRole("img", { name: /rolling beta history sparkline/i });
    expect(spark.tagName.toLowerCase()).toBe("svg");
    expect(screen.getByText(/4 points · window 60d/i)).toBeInTheDocument();
  });
});

describe("BETA pane — honesty", () => {
  it("labels the seeded market-model baseline and still renders its beta", () => {
    mockFn.state = "ok";
    mockFn.data = baselinePayload();
    const { container } = render(<BetaPane code="BETA" symbol="AAPL" />);
    expect(screen.getByText(/seeded market-model baseline/i)).toBeInTheDocument();
    // "baseline" appears on both the header status pill and the note pill.
    expect(screen.getAllByText("baseline").length).toBeGreaterThanOrEqual(2);
    // The baseline's 1Y beta still renders (from the betas map fallback).
    expect(container.textContent).toContain("0.90");
    // Baselines carry no rolling history — the sparkline says so honestly.
    expect(screen.getByText(/no rolling beta history returned/i)).toBeInTheDocument();
  });

  it("shows an honest empty state when no beta rows exist", () => {
    mockFn.state = "ok";
    mockFn.data = { data: { status: "ok", rows: [], history: [] }, warnings: [] };
    render(<BetaPane code="BETA" symbol="AAPL" />);
    expect(screen.getByText("No beta computed")).toBeInTheDocument();
  });
});

describe("BETA pane — persisted controls", () => {
  it("re-issues the call with the committed rolling window", () => {
    mockFn.state = "ok";
    mockFn.data = okPayload();
    render(<BetaPane code="BETA" symbol="AAPL" />);
    fireEvent.click(screen.getByTitle("ROLLING 90d"));
    expect(lastCall()?.params?.rolling_window).toBe(90);
    expect(lastCall()?.symbol).toBe("AAPL");
  });
});
