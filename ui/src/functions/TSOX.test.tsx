/**
 * TSOX pane — ticket input honesty (wb1-g10 UI-8).
 *
 * Pins:
 *  - a blank or zero quantity and a blank LIMIT price never reach the
 *    sidecar as 0 (Number('') is 0 and finite): Preview stays disabled;
 *  - a valid ticket sends real numbers and always submit=false;
 *  - the ticket symbol follows the linked symbol prop instead of freezing
 *    at the first render.
 */
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const { runFunctionMock } = vi.hoisted(() => ({
  runFunctionMock: vi.fn(),
}));

vi.mock("@/lib/functions", () => ({
  runFunction: runFunctionMock,
}));

import { TSOXPane } from "./TSOX";

beforeEach(() => {
  runFunctionMock.mockReset();
  runFunctionMock.mockResolvedValue({
    data: { status: "preview", broker: "paper", submit: false },
    sources: [],
    elapsed_ms: 1,
  });
});

afterEach(() => {
  cleanup();
});

function previewButton() {
  return screen.getByRole("button", { name: "Preview ticket" });
}

describe("TSOX pane — ticket input honesty", () => {
  it("blocks preview when the LIMIT price is blank (never sends price 0)", () => {
    render(<TSOXPane code="TSOX" />);
    fireEvent.change(screen.getByLabelText("Limit price"), { target: { value: "" } });
    expect(previewButton()).toBeDisabled();
    fireEvent.click(previewButton());
    expect(runFunctionMock).not.toHaveBeenCalled();
  });

  it("blocks preview for a zero or blank quantity (never sends quantity 0)", () => {
    render(<TSOXPane code="TSOX" />);
    const qty = screen.getByLabelText("Quantity (contracts)");
    fireEvent.change(qty, { target: { value: "0" } });
    expect(previewButton()).toBeDisabled();
    fireEvent.change(qty, { target: { value: "" } });
    expect(previewButton()).toBeDisabled();
    expect(runFunctionMock).not.toHaveBeenCalled();
  });

  it("starts with no invented symbol or limit price (data policy: no placeholder inputs)", () => {
    render(<TSOXPane code="TSOX" />);
    expect(screen.getByLabelText("Symbol / CUSIP")).toHaveValue("");
    expect(screen.getByLabelText("Limit price")).toHaveValue("");
    fireEvent.change(screen.getByLabelText("Quantity (contracts)"), { target: { value: "2" } });
    expect(previewButton()).toBeDisabled();
    expect(runFunctionMock).not.toHaveBeenCalled();
  });

  it("blocks preview when no symbol is linked or entered, even with a price", () => {
    render(<TSOXPane code="TSOX" />);
    fireEvent.change(screen.getByLabelText("Quantity (contracts)"), { target: { value: "2" } });
    fireEvent.change(screen.getByLabelText("Limit price"), { target: { value: "100.0625" } });
    expect(previewButton()).toBeDisabled();
    expect(runFunctionMock).not.toHaveBeenCalled();
  });

  it("sends real numbers and submit=false for a valid ticket", () => {
    render(<TSOXPane code="TSOX" symbol="ZN=F" />);
    fireEvent.change(screen.getByLabelText("Quantity (contracts)"), { target: { value: "2" } });
    fireEvent.change(screen.getByLabelText("Limit price"), { target: { value: "100.0625" } });
    fireEvent.click(previewButton());
    expect(runFunctionMock).toHaveBeenCalledTimes(1);
    const [, body] = runFunctionMock.mock.calls[0] as [string, { symbol: string; params: Record<string, unknown> }];
    expect(body.symbol).toBe("ZN=F");
    expect(body.params).toMatchObject({ quantity: 2, order_type: "LIMIT", submit: false, price: 100.0625 });
  });

  it("market orders need no limit price to preview", () => {
    render(<TSOXPane code="TSOX" symbol="ZN=F" />);
    fireEvent.change(screen.getByLabelText("Quantity (contracts)"), { target: { value: "1" } });
    fireEvent.click(screen.getByRole("button", { name: "MARKET" }));
    fireEvent.change(screen.getByLabelText("Limit price"), { target: { value: "" } });
    expect(previewButton()).toBeEnabled();
  });

  it("follows the linked symbol prop instead of freezing the first value", () => {
    const { rerender } = render(<TSOXPane code="TSOX" symbol="ZB=F" />);
    expect(screen.getByLabelText("Symbol / CUSIP")).toHaveValue("ZB=F");
    rerender(<TSOXPane code="TSOX" symbol="ZN=F" />);
    expect(screen.getByLabelText("Symbol / CUSIP")).toHaveValue("ZN=F");
  });
});
