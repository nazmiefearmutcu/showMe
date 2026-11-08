/**
 * MLSIG#6 — the ML Signals pane exposes the controls its backend reads.
 *
 * Before the fix the pane had no symbol or horizon input, its subtitle called
 * the classifier a "signal ranking", and buildParams sent only live_ml. These
 * tests pin the symbol and horizon inputs (sent as symbol and label_horizon),
 * the honest subtitle, and the MODEL default (live_ml=false).
 */
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

const mockReturn: { current: unknown } = { current: null };
const mockArgs: {
  current: { code?: string; symbol?: string; params?: Record<string, unknown> } | null;
} = { current: null };
vi.mock("@/lib/useFunction", () => ({
  useFunction: (args: unknown) => {
    mockArgs.current = args as (typeof mockArgs)["current"];
    return mockReturn.current;
  },
}));
vi.mock("@/lib/router", () => ({ navigate: vi.fn() }));

import { PortfolioAnalyticsPane } from "./PortfolioAnalytics";

function mockNeedsInput() {
  mockReturn.current = {
    state: "ok",
    data: {
      data: { status: "needs_input", reason: "No live model run was requested." },
      metadata: { live: false },
      sources: [],
      warnings: [],
      elapsed_ms: 5,
    },
    error: undefined,
    refetch: vi.fn(),
  };
}

afterEach(() => {
  cleanup();
  mockReturn.current = null;
  mockArgs.current = null;
});

describe("MLSIG pane controls (MLSIG#6)", () => {
  it("shows a symbol input and sends the typed symbol", () => {
    mockNeedsInput();
    render(<PortfolioAnalyticsPane code="MLSIG" symbol="" />);

    const symbol = screen.getByLabelText("Symbol") as HTMLInputElement;
    fireEvent.change(symbol, { target: { value: "msft" } });

    expect(mockArgs.current?.symbol).toBe("MSFT");
  });

  it("shows a horizon input that defaults to 1 bar and is sent as label_horizon", () => {
    mockNeedsInput();
    render(<PortfolioAnalyticsPane code="MLSIG" symbol="" />);

    const horizon = screen.getByLabelText("Horizon (bars)") as HTMLInputElement;
    expect(horizon.value).toBe("1");
    expect(mockArgs.current?.params?.label_horizon).toBe(1);
  });

  it("sends an edited horizon as label_horizon and strips non-digits", () => {
    mockNeedsInput();
    render(<PortfolioAnalyticsPane code="MLSIG" symbol="" />);

    const horizon = screen.getByLabelText("Horizon (bars)") as HTMLInputElement;
    fireEvent.change(horizon, { target: { value: "5x" } });

    expect(horizon.value).toBe("5");
    expect(mockArgs.current?.params?.label_horizon).toBe(5);
  });

  it("keeps MODEL as live_ml=false by default", () => {
    mockNeedsInput();
    render(<PortfolioAnalyticsPane code="MLSIG" symbol="" />);

    expect(mockArgs.current?.params?.live_ml).toBe(false);
  });

  it("subtitle describes a one-symbol classifier, not a signal ranking", () => {
    mockNeedsInput();
    render(<PortfolioAnalyticsPane code="MLSIG" symbol="" />);

    expect(screen.queryByText(/signal ranking/i)).toBeNull();
    expect(screen.getByText(/Next-day direction classifier/i)).toBeTruthy();
  });
});

function mockOkPayload() {
  mockReturn.current = {
    state: "ok",
    data: {
      data: {
        status: "ok",
        symbol: "AAPL",
        backend: "lstsq_linear_probability",
        source_mode: "live_yfinance",
        signal: "long_bias",
        test_accuracy: 0.5652,
        test_samples: 70,
        scored_samples: 69,
        test_baseline_always_long_accuracy: 0.5217,
        test_accuracy_ci95: [0.4012, 0.7100],
        strategy_sharpe: 0.31,
        summary: {
          test_accuracy: 0.5652,
          test_baseline_always_long_accuracy: 0.5217,
          test_accuracy_ci95: [0.4012, 0.7100],
          scored_samples: 69,
          test_samples: 70,
          strategy_sharpe: 0.31,
          signal: "long_bias",
          backend: "lstsq_linear_probability",
          source_mode: "live_yfinance",
        },
      },
      metadata: { live: true },
      sources: ["yfinance"],
      warnings: [],
      elapsed_ms: 5,
    },
    error: undefined,
    refetch: vi.fn(),
  };
}

describe("MLSIG accuracy context (MLSIG#7)", () => {
  it("shows the always-long baseline beside the accuracy", () => {
    mockOkPayload();
    render(<PortfolioAnalyticsPane code="MLSIG" symbol="AAPL" />);

    expect(screen.getByText(/Always-long baseline 52\.17%/)).toBeTruthy();
  });

  it("shows the 95% interval around the accuracy as percentages", () => {
    mockOkPayload();
    render(<PortfolioAnalyticsPane code="MLSIG" symbol="AAPL" />);

    expect(screen.getByText(/95% CI 40\.12% to 71\.00%/)).toBeTruthy();
  });

  it("shows how many test rows the accuracy is scored over", () => {
    mockOkPayload();
    render(<PortfolioAnalyticsPane code="MLSIG" symbol="AAPL" />);

    expect(screen.getByText(/Scored 69 of 70 test rows/)).toBeTruthy();
  });
});
