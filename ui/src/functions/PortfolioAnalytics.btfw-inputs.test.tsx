/**
 * WC3-G01 BTFW#3: the walk-forward pane exposes its strategy, history,
 * train share and walk steps, and sends only what the user typed (plus the
 * declared manifest names the backend reads).
 */
import { cleanup, fireEvent, render } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

const hookCalls: Array<{ params?: Record<string, unknown> }> = [];
vi.mock("@/lib/useFunction", () => ({
  useFunction: (args: { params?: Record<string, unknown> }) => {
    hookCalls.push({ params: args.params });
    return { state: "idle", data: undefined, error: undefined, refetch: vi.fn() };
  },
}));
vi.mock("@/lib/router", () => ({ navigate: vi.fn() }));

import { PortfolioAnalyticsPane } from "./PortfolioAnalytics";

afterEach(() => {
  cleanup();
  hookCalls.length = 0;
});

function lastParams(): Record<string, unknown> {
  const last = hookCalls[hookCalls.length - 1];
  return last?.params ?? {};
}

describe("PORTX BTFW inputs (BTFW#3)", () => {
  it("shows the strategy, history, train share and walk step controls with handler defaults", () => {
    const { container } = render(<PortfolioAnalyticsPane code="BTFW" symbol="AAPL" />);
    const strategy = container.querySelector<HTMLSelectElement>("#portx-btfw-strategy");
    const history = container.querySelector<HTMLSelectElement>("#portx-btfw-window");
    const train = container.querySelector<HTMLInputElement>("#portx-btfw-train-pct");
    const steps = container.querySelector<HTMLInputElement>("#portx-btfw-walk-steps");
    expect(strategy?.value).toBe("sma_crossover");
    expect(history?.value).toBe("3Y");
    expect(train?.value).toBe("0.7");
    expect(steps?.value).toBe("5");
    expect(container.textContent).toContain("Train share (fraction)");
  });

  it("sends the typed strategy, history, train share and walk steps", () => {
    const { container } = render(<PortfolioAnalyticsPane code="BTFW" symbol="AAPL" />);
    fireEvent.change(container.querySelector("#portx-btfw-strategy")!, { target: { value: "rsi_meanrev" } });
    fireEvent.change(container.querySelector("#portx-btfw-window")!, { target: { value: "1Y" } });
    fireEvent.change(container.querySelector("#portx-btfw-train-pct")!, { target: { value: "0.6" } });
    fireEvent.change(container.querySelector("#portx-btfw-walk-steps")!, { target: { value: "8" } });
    const params = lastParams();
    expect(params.strategy_id).toBe("rsi_meanrev");
    expect(params.window_length).toBe("1Y");
    expect(params.train_pct).toBe(0.6);
    expect(params.walk_steps).toBe(8);
    expect(params.live).toBe(false);
  });

  it("sends a typed invalid value as text so the backend names it, never a silent default", () => {
    const { container } = render(<PortfolioAnalyticsPane code="BTFW" symbol="AAPL" />);
    fireEvent.change(container.querySelector("#portx-btfw-walk-steps")!, { target: { value: "many" } });
    expect(lastParams().walk_steps).toBe("many");
  });

  it("omits a blank walk step count so the handler default applies", () => {
    const { container } = render(<PortfolioAnalyticsPane code="BTFW" symbol="AAPL" />);
    fireEvent.change(container.querySelector("#portx-btfw-walk-steps")!, { target: { value: "" } });
    expect("walk_steps" in lastParams()).toBe(false);
  });
});
