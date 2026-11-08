/**
 * BETA pane — render-contract + honesty tests.
 *
 * Pins:
 *  - loading / error / ok render paths;
 *  - the beta + R² headline cards reflect the SELECTED window and follow
 *    the persisted window control;
 *  - the rolling-beta sparkline renders an inline SVG when history exists
 *    and an honest empty note when it does not;
 *  - a betas-only payload (no rows, the retired seeded baseline shape) is an
 *    honest empty state, never a regression;
 *  - the benchmark control re-issues the call with `benchmark` and the
 *    caption shows the benchmark the payload reports (no hard-coded SPY);
 *  - the rolling-window control re-issues the call with `rolling_window`.
 *
 * `useFunction` is mocked with a mutable shared state + an args recorder.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { BetaPane } from "./BETA";
import { downloadGridCsv } from "@/design-system/grid-csv";

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

// Keep the real CSV builder, but capture the download call so the export
// payload can be asserted (jsdom has no Blob download).
vi.mock("@/design-system/grid-csv", async (importOriginal) => {
  const actual =
    await importOriginal<typeof import("@/design-system/grid-csv")>();
  return { ...actual, downloadGridCsv: vi.fn(() => true) };
});

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

function betasOnlyPayload() {
  // Retired seeded-baseline shape: a `betas` map and no `rows`. The pane must
  // not render it as a regression.
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
  (downloadGridCsv as ReturnType<typeof vi.fn>).mockClear();
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
  it("does not render a betas-only seeded baseline as a regression", () => {
    mockFn.state = "ok";
    mockFn.data = betasOnlyPayload();
    const { container } = render(<BetaPane code="BETA" symbol="AAPL" />);
    expect(screen.getByText("No beta computed")).toBeInTheDocument();
    expect(container.textContent).not.toContain("0.90");
    expect(screen.queryByText(/seeded market-model baseline/i)).toBeNull();
    expect(screen.queryByText("baseline")).toBeNull();
  });

  it("shows an honest empty state when no beta rows exist", () => {
    mockFn.state = "ok";
    mockFn.data = { data: { status: "ok", rows: [], history: [] }, warnings: [] };
    render(<BetaPane code="BETA" symbol="AAPL" />);
    expect(screen.getByText("No beta computed")).toBeInTheDocument();
  });
});

describe("BETA pane — benchmark control", () => {
  it("requests the manifest default benchmark ^GSPC", () => {
    mockFn.state = "ok";
    mockFn.data = okPayload();
    render(<BetaPane code="BETA" symbol="AAPL" />);
    expect(lastCall()?.params?.benchmark).toBe("^GSPC");
  });

  it("re-issues the call with the chosen benchmark and shows it in the caption", () => {
    mockFn.state = "ok";
    const base = okPayload();
    mockFn.data = { ...base, data: { ...base.data, benchmark: "QQQ" } };
    const { container } = render(<BetaPane code="BETA" symbol="AAPL" />);
    fireEvent.click(screen.getByTitle("BENCH QQQ"));
    expect(lastCall()?.params?.benchmark).toBe("QQQ");
    expect(container.textContent).toContain("vs QQQ");
    expect(container.textContent).not.toContain("vs SPY");
  });

  it("never falls back to a hard-coded SPY caption when the payload omits the benchmark", () => {
    mockFn.state = "ok";
    const payload = okPayload();
    delete (payload.data as Record<string, unknown>).benchmark;
    mockFn.data = payload;
    const { container } = render(<BetaPane code="BETA" symbol="AAPL" />);
    expect(container.textContent).toContain("vs ^GSPC");
    expect(container.textContent).not.toContain("vs SPY");
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

describe("BETA pane — grid CSV export", () => {
  it("exports the raw per-window regression table via the CSV button", () => {
    mockFn.state = "ok";
    mockFn.data = okPayload();
    render(<BetaPane code="BETA" symbol="AAPL" />);
    const btn = screen.getByTitle("Download CSV");
    expect(btn).not.toBeDisabled();
    fireEvent.click(btn);
    const mock = downloadGridCsv as ReturnType<typeof vi.fn>;
    expect(mock).toHaveBeenCalledTimes(1);
    const [filename, csv] = mock.mock.calls[0] as [string, string];
    expect(filename).toMatch(/^beta-AAPL-\d{4}-\d{2}-\d{2}\.csv$/);
    // Header row + RAW payload numbers (vols stay fractions, not "24.0%").
    expect(csv).toContain(
      "Window,Window days,Beta,Correlation,Samples,Ann vol target,Ann vol bench",
    );
    expect(csv).toContain("1Y,252,1.07,0.72,252,0.24,0.18");
  });

  it("disables the CSV button when no beta rows exist", () => {
    mockFn.state = "ok";
    mockFn.data = { data: { status: "ok", rows: [], history: [] }, warnings: [] };
    render(<BetaPane code="BETA" symbol="AAPL" />);
    expect(screen.getByTitle("Download CSV")).toBeDisabled();
    expect(downloadGridCsv).not.toHaveBeenCalled();
  });
});
