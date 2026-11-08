/**
 * BBGT pane — pre-trade notional row (WB1-G15 BBGT#4).
 *
 * The backend emits notional = quantity x limit price (or x an indicative
 * last quote, labelled indicative). The ticket must show it with its currency
 * and the basis, and show an honest dash with the reason when it is null.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { BBGTPane } from "./BBGT";

const { runFunctionMock } = vi.hoisted(() => ({
  runFunctionMock: vi.fn(),
}));

vi.mock("@/lib/functions", () => {
  class FakeFunctionCallError extends Error {
    status: number;
    body: string;
    constructor(message: string, status: number, body: string) {
      super(message);
      this.status = status;
      this.body = body;
    }
  }
  return {
    runFunction: runFunctionMock,
    FunctionCallError: FakeFunctionCallError,
  };
});

vi.mock("@/lib/store", () => ({
  useAppStore: (selector: (s: { sidecarPort: number | null }) => unknown) =>
    selector({ sidecarPort: 8795 }),
}));

function previewPayload(overrides: Record<string, unknown> = {}) {
  return {
    data: {
      broker: "paper",
      status: "preview",
      submit: false,
      broker_available: false,
      symbol: "SPY",
      asset_class: "EQUITY",
      side: "BUY",
      quantity: 100,
      order_type: "LIMIT",
      time_in_force: "DAY",
      price: 612.25,
      leverage: null,
      next_actions: ["Review the ticket values."],
      ...overrides,
    },
    sources: ["paper_ticket"],
    elapsed_ms: 4.1,
    warnings: [],
  };
}

beforeEach(() => {
  localStorage.clear();
  runFunctionMock.mockReset();
});
afterEach(() => {
  cleanup();
});

function fillLimitTicket() {
  fireEvent.click(screen.getByTitle("TYPE Limit"));
  fireEvent.change(screen.getByLabelText("Symbol"), { target: { value: "SPY" } });
  fireEvent.change(screen.getByLabelText("Quantity"), { target: { value: "100" } });
  fireEvent.change(screen.getByLabelText(/^Limit price/), { target: { value: "612.25" } });
}

describe("BBGT pane — notional row", () => {
  it("shows the limit-price notional with its currency and basis", async () => {
    runFunctionMock.mockResolvedValue(
      previewPayload({
        notional: 61225,
        notional_currency: "USD",
        notional_basis: "limit_price",
        notional_indicative: false,
        notional_reason: null,
      }),
    );
    const { container } = render(<BBGTPane code="BBGT" />);
    fillLimitTicket();
    fireEvent.click(screen.getByTitle(/paper-broker preview/));
    await screen.findByText(/Order preview/i);
    expect(screen.getByText("Notional")).toBeInTheDocument();
    expect(container.textContent).toContain("61,225 USD");
    expect(container.textContent).not.toContain("· indicative");
  });

  it("labels an indicative quote notional as indicative", async () => {
    runFunctionMock.mockResolvedValue(
      previewPayload({
        order_type: "MARKET",
        price: null,
        notional: 200,
        notional_currency: "USD",
        notional_basis: "indicative_last_quote",
        notional_indicative: true,
      }),
    );
    const { container } = render(<BBGTPane code="BBGT" />);
    fillLimitTicket();
    fireEvent.click(screen.getByTitle(/paper-broker preview/));
    await screen.findByText(/Order preview/i);
    expect(container.textContent).toContain("200 USD");
    expect(container.textContent).toContain("200 USD · indicative");
  });

  it("shows an honest dash with the reason when the notional is null", async () => {
    const reason = "Indicative quote unavailable (RuntimeError); MARKET notional not computed.";
    runFunctionMock.mockResolvedValue(
      previewPayload({
        order_type: "MARKET",
        price: null,
        notional: null,
        notional_currency: "USD",
        notional_basis: "unavailable",
        notional_indicative: null,
        notional_reason: reason,
      }),
    );
    render(<BBGTPane code="BBGT" />);
    fillLimitTicket();
    fireEvent.click(screen.getByTitle(/paper-broker preview/));
    await screen.findByText(/Order preview/i);
    expect(screen.getByTitle(reason)).toHaveTextContent("—");
  });
});
