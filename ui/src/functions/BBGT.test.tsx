/**
 * BBGT pane — multi-asset ticket + honesty tests.
 *
 * BBGT is the multi-asset trade ticket over the EMSX paper-preview
 * contract. These tests pin:
 *
 *  - the idle state ("No preview yet"); no call fires on mount;
 *  - Preview calls runFunction with asset_class routing + submit:false;
 *  - the resolved preview renders the order table + the standing quote
 *    honesty note (reference quotes are NOT executable) + honest
 *    "no broker configured" state;
 *  - a provider_unavailable payload surfaces its reason verbatim;
 *  - live submit is gated behind the explicit confirm checkbox, which
 *    arms submit:true only after the tick;
 *  - the pane never labels a preview as a live fill.
 *
 * `runFunction` is mocked (no sidecar transport); `useAppStore` is stubbed
 * to a ready sidecar.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { FunctionCallError } from "@/lib/functions";
import { BBGTPane } from "./BBGT";

/* ── runFunction / store mocks ─────────────────────────────────────── */

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

/* ── fixtures ──────────────────────────────────────────────────────── */

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
      next_actions: [
        "Review the ticket values.",
        "Use the broker order endpoint or Advanced submit=true only after confirming the trade.",
      ],
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

function fillTicket() {
  fireEvent.click(screen.getByTitle("TYPE Limit"));
  fireEvent.change(screen.getByLabelText("Symbol"), {
    target: { value: "SPY" },
  });
  fireEvent.change(screen.getByLabelText("Quantity"), {
    target: { value: "100" },
  });
  fireEvent.change(screen.getByLabelText(/^Limit price/), {
    target: { value: "612.25" },
  });
}

describe("BBGT pane — idle state", () => {
  it("renders no preview and never fires on mount", () => {
    render(<BBGTPane code="BBGT" />);
    expect(screen.getByText(/No preview yet/i)).toBeInTheDocument();
    expect(runFunctionMock).not.toHaveBeenCalled();
  });
});

describe("BBGT pane — preview interaction", () => {
  it("calls runFunction with asset_class routing and submit:false", async () => {
    runFunctionMock.mockResolvedValue(previewPayload());
    render(<BBGTPane code="BBGT" />);
    fireEvent.click(screen.getByTitle("ASSET FX"));
    fillTicket();
    fireEvent.click(screen.getByTitle(/paper-broker preview/));
    await waitFor(() => expect(runFunctionMock).toHaveBeenCalledTimes(1));
    const [codeArg, optsArg] = runFunctionMock.mock.calls[0] as [
      string,
      {
        symbol: string;
        asset_class: string;
        params: {
          side: string;
          quantity: number;
          type: string;
          tif: string;
          submit: boolean;
          price: number;
          paper_mode: boolean;
        };
      },
    ];
    expect(codeArg).toBe("BBGT");
    expect(optsArg.symbol).toBe("SPY");
    expect(optsArg.asset_class).toBe("FX");
    expect(optsArg.params.submit).toBe(false);
    expect(optsArg.params.paper_mode).toBe(true);
    expect(optsArg.params.quantity).toBe(100);
    expect(optsArg.params.price).toBe(612.25);
  });

  it("renders the order preview + quote honesty when resolved", async () => {
    runFunctionMock.mockResolvedValue(previewPayload());
    const { container } = render(<BBGTPane code="BBGT" />);
    fillTicket();
    fireEvent.click(screen.getByTitle(/paper-broker preview/));
    await screen.findByText(/Order preview/i);
    expect(container.textContent).toContain("612.25");
    expect(container.textContent).toContain("NOT executable prices");
    expect(screen.getByText("paper · no broker configured")).toBeInTheDocument();
  });

  it("surfaces provider_unavailable reasons verbatim", async () => {
    runFunctionMock.mockResolvedValue(
      previewPayload({
        status: "provider_unavailable",
        broker: null,
        reason: "No broker is configured for asset class equity; cannot submit.",
      }),
    );
    render(<BBGTPane code="BBGT" />);
    fillTicket();
    fireEvent.click(screen.getByTitle(/paper-broker preview/));
    await screen.findByText(
      /No broker is configured for asset class equity; cannot submit\./,
    );
  });

  it("renders transport errors verbatim", async () => {
    runFunctionMock.mockRejectedValue(
      new FunctionCallError("function call failed", 500, "boom"),
    );
    render(<BBGTPane code="BBGT" />);
    fillTicket();
    fireEvent.click(screen.getByTitle(/paper-broker preview/));
    await screen.findByText(/500: boom/);
  });
});

describe("BBGT pane — live submit gate", () => {
  it("keeps live submit disabled until the confirm checkbox is ticked", async () => {
    runFunctionMock.mockResolvedValue(previewPayload());
    render(<BBGTPane code="BBGT" />);
    fillTicket();
    const submitBtn = screen.getByTitle(/Tick the confirm checkbox/);
    expect(submitBtn).toBeDisabled();
    fireEvent.click(screen.getByText("I confirm this is a real order"));
    expect(screen.getByText("LIVE ARMED")).toBeInTheDocument();
    expect(submitBtn).not.toBeDisabled();
    fireEvent.click(submitBtn);
    await waitFor(() => expect(runFunctionMock).toHaveBeenCalledTimes(1));
    const optsArg = runFunctionMock.mock.calls[0][1] as {
      params: { submit: boolean; paper_mode: boolean };
    };
    expect(optsArg.params.submit).toBe(true);
    // F9 [C]: the engine ignores submit=true unless paper_mode is explicitly
    // false — the armed button is the only call site that passes it.
    expect(optsArg.params.paper_mode).toBe(false);
  });

  it("never labels a preview as a live fill", async () => {
    runFunctionMock.mockResolvedValue(previewPayload());
    const { container } = render(<BBGTPane code="BBGT" />);
    fillTicket();
    fireEvent.click(screen.getByTitle(/paper-broker preview/));
    await screen.findByText(/Order preview/i);
    expect(container.textContent).toContain("· paper");
    expect(container.textContent).not.toContain("FILLED");
  });

  it("renders a submitted live order with an honest SUBMITTED state (F9/H)", async () => {
    runFunctionMock.mockResolvedValue({
      data: {
        status: "submitted",
        broker: "alpaca_broker",
        order_id: "ord-42",
        symbol: "SPY",
        asset_class: "EQUITY",
        side: "BUY",
        quantity: 100,
        order_type: "LIMIT",
        time_in_force: "DAY",
        price: 612.25,
        leverage: null,
        next_actions: [],
      },
      sources: ["alpaca_broker"],
      elapsed_ms: 7,
      warnings: [],
    });
    const { container } = render(<BBGTPane code="BBGT" />);
    fillTicket();
    fireEvent.click(screen.getByText("I confirm this is a real order"));
    fireEvent.click(screen.getByTitle("Submit live order (submit=true)"));
    await screen.findByText(/Order submitted/);
    // Header + summary + footer now carry the honest lifecycle token.
    expect(screen.getAllByText("SUBMITTED").length).toBeGreaterThan(0);
    expect(screen.getByText("ord-42")).toBeInTheDocument();
    expect(container.textContent).toContain("· LIVE");
    expect(container.textContent).not.toContain("· paper");
  });
});
