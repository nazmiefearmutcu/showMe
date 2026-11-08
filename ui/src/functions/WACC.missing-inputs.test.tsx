/**
 * WACC pane — missing-input honesty (UI-11).
 *
 * A missing beta, cost of debt (rd) or tax rate must render as "—", never as
 * a zero that looks like data: "β 0.00", an after-tax cost of debt of
 * "0.00%", or a 0% tax treatment that silently overstates the after-tax cost.
 *
 * `useFunction` is mocked with a mutable shared state, as in WACC.test.tsx.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, render } from "@testing-library/react";
import { WACCPane } from "./WACC";

interface MockFnState {
  state: "idle" | "loading" | "ok" | "error" | "refreshing";
  data?: { data?: unknown; warnings?: string[]; sources?: string[] } | undefined;
  error?: Error | null;
}

const mockFn: MockFnState = { state: "idle", data: undefined, error: null };

vi.mock("@/lib/useFunction", () => ({
  useFunction: () => ({
    state: mockFn.state,
    data: mockFn.data,
    error: mockFn.error,
    refetch: vi.fn(),
  }),
}));

function payloadWith(overrides: Record<string, unknown>) {
  const base: Record<string, unknown> = {
    status: "ok",
    wacc: 0.0842,
    re_capm: 0.096,
    rf: 0.041,
    beta: 1.1,
    erp: 0.05,
    rd: 0.055,
    tax_rate: 0.21,
    equity_weight: 0.8,
    debt_weight: 0.2,
    rows: [{ component: "WACC", value: 0.0842, formula: "(E/V × Re) + (D/V × Rd × (1 − T))" }],
    surface: [],
    methodology: "WACC = (E/V × Re) + (D/V × Rd × (1 − T))",
  };
  for (const [key, value] of Object.entries(overrides)) {
    if (value === undefined) delete base[key];
    else base[key] = value;
  }
  return { data: base, sources: ["fred", "yfinance"], warnings: [], elapsed_ms: 1 };
}

/** Text of the StatCard whose label is `label`, from the label onward. */
function cardText(container: HTMLElement, label: string, span = 80): string {
  const text = container.textContent ?? "";
  const idx = text.indexOf(label);
  expect(idx, `card "${label}" not rendered`).toBeGreaterThanOrEqual(0);
  return text.slice(idx, idx + label.length + span);
}

/** The value rendered directly after a StatCard label (not its caption). */
function cardValue(container: HTMLElement, label: string): string {
  const text = container.textContent ?? "";
  const idx = text.indexOf(label);
  expect(idx, `card "${label}" not rendered`).toBeGreaterThanOrEqual(0);
  // Values are at most "100.00%" / "4.00" wide; read a short window and cut it
  // at the first caption word so the caption's own "Rd 5.50%" is excluded.
  const window = text.slice(idx + label.length, idx + label.length + 12);
  return window.split(/Rd|Re|rf|E\/D|E |D |Tax/)[0];
}

beforeEach(() => {
  mockFn.state = "idle";
  mockFn.data = undefined;
  mockFn.error = null;
});

afterEach(() => {
  cleanup();
});

describe("WACC pane — missing inputs are not shown as zero (UI-11)", () => {
  it("shows an em dash for a missing beta instead of 'β 0.00'", () => {
    mockFn.state = "ok";
    mockFn.data = payloadWith({ beta: undefined });
    const { container } = render(<WACCPane code="WACC" symbol="AAPL" />);
    const text = container.textContent ?? "";
    expect(text).not.toContain("β 0.00");
    expect(cardText(container, "Cost of equity")).toContain("β —");
  });

  it("shows an em dash, not 0.00%, when the cost of debt is missing", () => {
    mockFn.state = "ok";
    mockFn.data = payloadWith({ rd: undefined });
    const { container } = render(<WACCPane code="WACC" symbol="AAPL" />);
    expect(cardValue(container, "Cost of debt (after-tax)")).toBe("—");
  });

  it("shows an em dash, not a 0%-tax figure, when the tax rate is missing", () => {
    mockFn.state = "ok";
    mockFn.data = payloadWith({ tax_rate: undefined });
    const { container } = render(<WACCPane code="WACC" symbol="AAPL" />);
    // rd is 5.50%: with a defaulted 0% tax the pane would show 5.50% here.
    expect(cardValue(container, "Cost of debt (after-tax)")).toBe("—");
  });

  it("still computes the after-tax cost of debt when all inputs are present", () => {
    mockFn.state = "ok";
    mockFn.data = payloadWith({});
    const { container } = render(<WACCPane code="WACC" symbol="AAPL" />);
    // 5.5% * (1 - 0.21) = 4.345% -> "4.35%" with the pane's two-decimal format.
    expect(cardValue(container, "Cost of debt (after-tax)")).toBe("4.35%");
    expect(container.textContent).toContain("β 1.10");
  });
});
