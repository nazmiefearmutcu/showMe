/**
 * WACC UI regression — Bug #17.
 *
 * Two contracts pinned:
 *
 *   1. The pane no longer hardcodes "AAPL" as a fallback symbol. It uses
 *      `defaultSymbolForFunction("WACC", ["EQUITY"])` so that the
 *      recent-symbol history wins like every other equity pane.
 *
 *   2. The pane surfaces the new `data_state` + `beta_source` envelope:
 *      live β → green "β 5y" chip; synthetic β fallback → warn "synthetic β"
 *      chip. The chip carries a `data-beta-state` attribute for tests.
 */
import { cleanup, render } from "@testing-library/react";
import { afterEach, describe, expect, it, vi, beforeEach } from "vitest";

const useFunctionMock = vi.fn();
const defaultSymbolMock = vi.fn();

vi.mock("@/lib/useFunction", () => ({
  useFunction: (...args: unknown[]) => useFunctionMock(...args),
}));

vi.mock("@/lib/symbols", () => ({
  defaultSymbolForFunction: (...args: unknown[]) => defaultSymbolMock(...args),
}));

import { WACCPane } from "../WACC";

beforeEach(() => {
  useFunctionMock.mockReset();
  defaultSymbolMock.mockReset();
  defaultSymbolMock.mockReturnValue("MSFT");
});

afterEach(() => cleanup());

function liveResult(overrides: Record<string, unknown> = {}) {
  return {
    state: "ok" as const,
    refetch: vi.fn(),
    error: undefined,
    data: {
      data: {
        status: "ok",
        wacc: 0.0891,
        re_capm: 0.092,
        rf: 0.043,
        beta: 1.20,
        erp: 0.05,
        rd: 0.05,
        tax_rate: 0.21,
        equity_weight: 0.7,
        debt_weight: 0.3,
        rows: [],
        surface: [],
        data_state: "live",
        beta_source: "beta_5y",
        beta_window: "5Y",
        ...overrides,
      },
      sources: ["beta", "fred", "yfinance"],
      warnings: [],
      elapsed_ms: 100,
    },
  };
}

describe("WACC pane", () => {
  it("does not hardcode AAPL — uses defaultSymbolForFunction when no symbol prop", () => {
    useFunctionMock.mockReturnValue(liveResult());
    render(<WACCPane code="WACC" />);
    expect(defaultSymbolMock).toHaveBeenCalledWith("WACC", ["EQUITY"]);
    // First argument to useFunction has resolved symbol from the mock above.
    const call = useFunctionMock.mock.calls[0]?.[0];
    expect(call?.symbol).toBe("MSFT");
  });

  it("honours an explicit symbol prop without touching the default helper", () => {
    useFunctionMock.mockReturnValue(liveResult());
    render(<WACCPane code="WACC" symbol="GOOGL" />);
    expect(defaultSymbolMock).not.toHaveBeenCalled();
    expect(useFunctionMock.mock.calls[0]?.[0]?.symbol).toBe("GOOGL");
  });

  it("renders a live β pill when beta_source is beta_5y", () => {
    useFunctionMock.mockReturnValue(liveResult());
    const { container } = render(<WACCPane code="WACC" symbol="AAPL" />);
    const pill = container.querySelector('[data-testid="wacc-beta-pill"]');
    expect(pill).not.toBeNull();
    expect(pill?.getAttribute("data-beta-state")).toBe("live");
    expect(pill?.textContent).toContain("5y");
  });

  it("renders a synthetic β warning when data_state is synthetic_beta", () => {
    useFunctionMock.mockReturnValue(
      liveResult({
        beta: 1.0,
        data_state: "synthetic_beta",
        beta_source: "synthetic_beta",
        beta_window: null,
      }),
    );
    useFunctionMock.mockReturnValueOnce({
      state: "ok" as const,
      refetch: vi.fn(),
      error: undefined,
      data: {
        data: {
          wacc: 0.0891,
          beta: 1.0,
          data_state: "synthetic_beta",
          beta_source: "synthetic_beta",
          beta_window: null,
        },
        sources: ["synthetic_beta"],
        warnings: ["beta unavailable: WACC is using a synthetic β=1.0"],
        elapsed_ms: 100,
      },
    });
    const { container } = render(<WACCPane code="WACC" symbol="AAPL" />);
    const pill = container.querySelector('[data-testid="wacc-beta-pill"]');
    expect(pill).not.toBeNull();
    expect(pill?.getAttribute("data-beta-state")).toBe("synthetic");
    expect(pill?.textContent?.toLowerCase()).toContain("synthetic");
  });

  it("hides the β chip when user supplied beta directly", () => {
    useFunctionMock.mockReturnValue(
      liveResult({ beta_source: "user_input", beta_window: null, data_state: "live" }),
    );
    const { container } = render(<WACCPane code="WACC" symbol="AAPL" />);
    expect(container.querySelector('[data-testid="wacc-beta-pill"]')).toBeNull();
  });
});
