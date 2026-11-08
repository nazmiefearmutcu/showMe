/**
 * TSOX pane — ticket input honesty (wb1-g10 UI-8) and honest preview state
 * (WB1-G16, TSOX#3 / TSOX#4).
 *
 * Pins:
 *  - a blank or zero quantity and a blank LIMIT price never reach the
 *    sidecar as 0 (Number('') is 0 and finite): Preview stays disabled;
 *  - a valid ticket sends real numbers and always submit=false;
 *  - the ticket symbol follows the linked symbol prop instead of freezing
 *    at the first render;
 *  - an `input_error` preview renders as an input error, never as a valid
 *    preview (the backend sends broker "paper" on these, so the old
 *    `broker === "paper"` check would have shown it as OK);
 *  - bond analytics the backend reports as `not_computed` are labelled as
 *    not computed rather than left silently absent.
 *
 * `runFunction` is mocked; there is no sidecar transport in these tests.
 */
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
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
    expect((screen.getByLabelText("Quantity (contracts)") as HTMLInputElement).value).toBe("");
    expect(previewButton()).toBeDisabled();
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

function payload(data: Record<string, unknown>) {
  return { data, sources: ["paper_ticket"], elapsed_ms: 2, warnings: [] };
}

function previewPayload() {
  return payload({
    broker: "paper",
    status: "preview",
    submit: false,
    symbol: "ZN=F",
    asset_class: "BOND",
    side: "BUY",
    quantity: 1,
    order_type: "LIMIT",
    time_in_force: "GTC",
    price: 100.0625,
    next_actions: [],
    analytics: {
      status: "not_computed",
      reason: "DV01 needs the bond's modified duration, which the ticket does not carry.",
      not_computed: ["dv01"],
    },
  });
}

function inputErrorPayload() {
  return payload({
    status: "input_error",
    reason: "LIMIT tickets need a limit price greater than 0.",
    field: "price",
    broker: "paper",
    submit: false,
    symbol: "ZN=F",
    asset_class: "BOND",
    side: "BUY",
    quantity: 1,
    order_type: "LIMIT",
    time_in_force: "GTC",
    price: null,
    next_actions: ["Correct the price field in the ticket controls and preview again."],
  });
}

describe("TSOX pane — honest preview state", () => {
  it("renders an input_error as an input error, not a valid preview", async () => {
    runFunctionMock.mockResolvedValue(inputErrorPayload());
    render(<TSOXPane code="TSOX" symbol="ZN=F" />);
    fillValidTicket();
    fireEvent.click(screen.getByRole("button", { name: /Preview ticket/i }));
    await waitFor(() => expect(runFunctionMock).toHaveBeenCalledTimes(1));
    expect(await screen.findByText("Input error")).toBeInTheDocument();
    expect(
      screen.getByText("LIMIT tickets need a limit price greater than 0."),
    ).toBeInTheDocument();
    // The KPI strip that presents a ticket as previewed must not render.
    expect(screen.queryByLabelText("Ticket KPIs")).toBeNull();
  });

  it("labels bond analytics the backend reports as not computed", async () => {
    runFunctionMock.mockResolvedValue(previewPayload());
    render(<TSOXPane code="TSOX" symbol="ZN=F" />);
    fillValidTicket();
    fireEvent.click(screen.getByRole("button", { name: /Preview ticket/i }));
    expect(await screen.findByText("Bond analytics not computed")).toBeInTheDocument();
    expect(
      screen.getByText("DV01 needs the bond's modified duration, which the ticket does not carry."),
    ).toBeInTheDocument();
    expect(screen.getByLabelText("Ticket KPIs")).toBeInTheDocument();
  });
});

// The ticket starts blank (no placeholder quantity or price), so Preview needs
// both entered before the honest-state payload can be requested.
function fillValidTicket() {
  fireEvent.change(screen.getByLabelText("Quantity (contracts)"), { target: { value: "1" } });
  fireEvent.change(screen.getByLabelText("Limit price"), { target: { value: "100.0625" } });
}
