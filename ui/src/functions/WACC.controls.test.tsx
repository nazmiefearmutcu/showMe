/**
 * WACC pane — assumption controls (WACC#5).
 *
 * Pins that every assumption the manifest declares is editable in the pane and
 * reaches the function as its manifest name: market_premium (ERP), beta_window,
 * beta, rf, rd and tax_rate_override. Rates are typed in percent and sent as
 * decimals. An empty field sends nothing, so the function resolves that input.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { WACCPane } from "./WACC";

interface RecordedArgs {
  code: string;
  symbol?: string;
  params?: Record<string, unknown>;
}

const lastArgs: RecordedArgs[] = [];

function lastParams(): Record<string, unknown> {
  return lastArgs[lastArgs.length - 1]?.params ?? {};
}

vi.mock("@/lib/useFunction", () => ({
  useFunction: (args: RecordedArgs) => {
    lastArgs.push(args);
    return {
      state: "ok",
      data: { data: { status: "ok", wacc: 0.08, rows: [], surface: [] }, sources: [], warnings: [] },
      error: null,
      refetch: vi.fn(),
    };
  },
}));

beforeEach(() => {
  lastArgs.length = 0;
});

afterEach(() => cleanup());

function percentField(label: string, value: string) {
  const input = screen.getByLabelText(label) as HTMLInputElement;
  fireEvent.change(input, { target: { value } });
  fireEvent.blur(input);
}

describe("WACC assumption controls", () => {
  it("sends no assumption keys until the user sets one", () => {
    render(<WACCPane code="WACC" symbol="AAPL" />);
    const params = lastParams();
    expect(params.market_premium).toBeUndefined();
    expect(params.beta_window).toBeUndefined();
    expect(params.beta).toBeUndefined();
    expect(params.rf).toBeUndefined();
    expect(params.rd).toBeUndefined();
    expect(params.tax_rate_override).toBeUndefined();
  });

  it("sends the ERP as a decimal premium under market_premium", () => {
    render(<WACCPane code="WACC" symbol="AAPL" />);
    percentField("Equity risk premium (ERP) %", "6");
    expect(lastParams().market_premium).toBeCloseTo(0.06, 10);
  });

  it("clamps an out-of-range ERP to the manifest maximum", () => {
    render(<WACCPane code="WACC" symbol="AAPL" />);
    percentField("Equity risk premium (ERP) %", "50");
    expect(lastParams().market_premium).toBeCloseTo(0.12, 10);
  });

  it("clearing the ERP field drops the override", () => {
    render(<WACCPane code="WACC" symbol="AAPL" />);
    percentField("Equity risk premium (ERP) %", "6");
    percentField("Equity risk premium (ERP) %", "");
    expect(lastParams().market_premium).toBeUndefined();
  });

  it("sends the selected beta window under beta_window", () => {
    render(<WACCPane code="WACC" symbol="AAPL" />);
    const select = screen.getByLabelText("Beta window") as HTMLSelectElement;
    fireEvent.change(select, { target: { value: "504d" } });
    expect(lastParams().beta_window).toBe("504d");
  });

  it("sends beta, rf, rd and the tax override under their manifest names", () => {
    render(<WACCPane code="WACC" symbol="AAPL" />);
    percentField("Beta (β)", "1.2");
    expect(lastParams().beta).toBeCloseTo(1.2, 10);
    percentField("Risk-free rate (rf) %", "4.25");
    expect(lastParams().rf).toBeCloseTo(0.0425, 10);
    percentField("Pre-tax cost of debt (Rd) %", "5.5");
    expect(lastParams().rd).toBeCloseTo(0.055, 10);
    percentField("Tax rate override %", "21");
    expect(lastParams().tax_rate_override).toBeCloseTo(0.21, 10);
  });
});
