/**
 * OVME honesty (WC2-G06 T10-OVME): an unedited pane must not price a demo
 * option. Spot, strike, expiry and volatility are sent to the backend only
 * after the user has entered them; until then they are null, so the sidecar
 * answers needs_input instead of pricing the field's prefilled number.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";

const seen = vi.hoisted(() => ({
  params: [] as Array<Record<string, unknown>>,
}));

vi.mock("@/lib/useFunction", () => ({
  useFunction: (args: { params: Record<string, unknown> }) => {
    seen.params.push(args.params);
    return {
      state: "ok",
      data: { data: { status: "ok", curve: [], sensitivity: [], rows: [] } },
      error: null,
      refetch: vi.fn(),
    };
  },
}));

import { OVMEPane } from "./OVME";

function lastParams(): Record<string, unknown> {
  return seen.params[seen.params.length - 1];
}

describe("OVME pane — no demo option priced", () => {
  beforeEach(() => {
    localStorage.clear();
    seen.params.length = 0;
  });
  afterEach(() => {
    cleanup();
  });

  it("does not send prefilled spot, strike, expiry or vol before the user enters them", () => {
    render(<OVMEPane code="OVME" symbol="SPY" />);
    const params = lastParams();
    expect(params.spot).toBeNull();
    expect(params.strike).toBeNull();
    expect(params.years_to_expiry).toBeNull();
    expect(params.vol).toBeNull();
    // Rate and dividend yield are labelled defaults, not option inputs.
    expect(params.rate).toBeCloseTo(0.045, 10);
  });

  it("sends only the field the user has entered", () => {
    render(<OVMEPane code="OVME" symbol="SPY" />);
    fireEvent.change(screen.getByLabelText("Underlying spot price"), {
      target: { value: "112.5" },
    });
    const params = lastParams();
    expect(params.spot).toBe(112.5);
    expect(params.strike).toBeNull();
    expect(params.years_to_expiry).toBeNull();
    expect(params.vol).toBeNull();
  });

  it("sends volatility as a decimal once the user enters it", () => {
    render(<OVMEPane code="OVME" symbol="SPY" />);
    fireEvent.change(screen.getByLabelText("Implied volatility percent"), {
      target: { value: "25" },
    });
    expect(lastParams().vol).toBeCloseTo(0.25, 10);
  });

  it("shows the four option inputs empty until the user enters them", () => {
    localStorage.setItem("showme.ovme.spot", "150");
    render(<OVMEPane code="OVME" symbol="SPY" />);
    for (const label of [
      "Underlying spot price",
      "Option strike price",
      "Years to expiry",
      "Implied volatility percent",
    ]) {
      expect((screen.getByLabelText(label) as HTMLInputElement).value).toBe("");
    }
  });
});
