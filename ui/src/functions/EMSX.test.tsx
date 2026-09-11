/**
 * EMSX pane — money-path armament + preview contract tests (campaign F9).
 *
 * EMSX is the canonical live-order ticket; before this lane it had ZERO
 * tests. These pin the safety-critical state machine and the preview
 * fidelity fixes:
 *
 *  - idle: no preview, `runFunction` never fires on mount;
 *  - preview: submit:false + the explicit `paper_mode:true` arm, with the
 *    ticket echoed (side/qty/type/tif/price/leverage);
 *  - the preview summary shows the Price + Leverage rows the backend echoes
 *    (a LIMIT ticket must not hide its limit);
 *  - armament gate: the live button is disabled until the confirm checkbox
 *    is ticked, an unchecked click never sends `submit:true`, and an armed
 *    submit sends `submit:true` + `paper_mode:false`;
 *  - the confirm arm resets when any ticket field changes;
 *  - a live success (`status:"submitted"` + order_id) renders as submitted,
 *    never as "preview".
 *
 * `runFunction` is mocked (no sidecar transport); `useAppStore` is stubbed
 * to a ready sidecar.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { FunctionCallError } from "@/lib/functions";
import { EMSXPane } from "./EMSX";

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
      paper_mode: true,
      broker_available: true,
      symbol: "AAPL",
      asset_class: "EQUITY",
      side: "SELL",
      quantity: 5,
      order_type: "LIMIT",
      time_in_force: "DAY",
      price: 200.5,
      leverage: 3,
      next_actions: [],
      ...overrides,
    },
    sources: ["paper_ticket"],
    elapsed_ms: 3,
    warnings: [],
  };
}

function submittedPayload() {
  return {
    data: {
      status: "submitted",
      broker: "alpaca_broker",
      order_id: "ord-9",
      symbol: "AAPL",
      asset_class: "EQUITY",
      side: "SELL",
      quantity: 5,
      order_type: "LIMIT",
      time_in_force: "DAY",
      price: 200.5,
      leverage: 3,
      next_actions: [],
    },
    sources: ["alpaca_broker"],
    elapsed_ms: 9,
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
  fireEvent.click(screen.getByTitle("SIDE Sell"));
  fireEvent.click(screen.getByTitle("TYPE Limit"));
  fireEvent.change(screen.getByLabelText("Quantity"), {
    target: { value: "5" },
  });
  fireEvent.change(screen.getByLabelText(/^Limit price/), {
    target: { value: "200.5" },
  });
  fireEvent.change(screen.getByLabelText(/^Leverage/), {
    target: { value: "3" },
  });
}

/* ── tests ─────────────────────────────────────────────────────────── */

describe("EMSX pane — idle + preview", () => {
  it("renders no preview and never fires on mount", () => {
    render(<EMSXPane code="EMSX" symbol="AAPL" />);
    expect(screen.getByText(/No preview yet/i)).toBeInTheDocument();
    expect(runFunctionMock).not.toHaveBeenCalled();
  });

  it("previews with submit:false + paper_mode:true and echoes the ticket", async () => {
    runFunctionMock.mockResolvedValue(previewPayload());
    render(<EMSXPane code="EMSX" symbol="AAPL" />);
    fillTicket();
    fireEvent.click(screen.getByTitle(/paper-broker preview/));
    await waitFor(() => expect(runFunctionMock).toHaveBeenCalledTimes(1));
    const [codeArg, optsArg] = runFunctionMock.mock.calls[0] as [
      string,
      {
        symbol: string;
        params: Record<string, unknown>;
      },
    ];
    expect(codeArg).toBe("EMSX");
    expect(optsArg.symbol).toBe("AAPL");
    expect(optsArg.params).toMatchObject({
      side: "SELL",
      quantity: 5,
      type: "LIMIT",
      tif: "GTC",
      submit: false,
      paper_mode: true,
      price: 200.5,
      leverage: 3,
    });
  });

  it("shows the echoed Price + Leverage rows in the preview summary", async () => {
    runFunctionMock.mockResolvedValue(previewPayload());
    render(<EMSXPane code="EMSX" symbol="AAPL" />);
    fillTicket();
    fireEvent.click(screen.getByTitle(/paper-broker preview/));
    await screen.findByText("Price");
    expect(screen.getByText("200.5")).toBeInTheDocument();
    expect(screen.getByText("3×")).toBeInTheDocument();
    expect(screen.getByText("Leverage")).toBeInTheDocument();
  });

  it("surfaces transport errors verbatim", async () => {
    runFunctionMock.mockRejectedValue(
      new FunctionCallError("function call failed", 500, "boom"),
    );
    render(<EMSXPane code="EMSX" symbol="AAPL" />);
    fillTicket();
    fireEvent.click(screen.getByTitle(/paper-broker preview/));
    await screen.findByText(/500: boom/);
  });
});

describe("EMSX pane — live armament gate (money path)", () => {
  it("disables live submit until confirm; unchecked never sends submit:true", async () => {
    runFunctionMock.mockResolvedValue(previewPayload());
    render(<EMSXPane code="EMSX" symbol="AAPL" />);
    fillTicket();
    const submitBtn = screen.getByTitle(/Tick the confirm checkbox/);
    expect(submitBtn).toBeDisabled();
    // A click while disabled must not reach runFunction at all.
    fireEvent.click(submitBtn);
    expect(runFunctionMock).not.toHaveBeenCalled();

    // Tick the explicit confirm gate → armed; the submit call carries the
    // full arm (submit:true AND paper_mode:false).
    fireEvent.click(screen.getByText("I confirm this is a real order"));
    expect(screen.getByText("LIVE ARMED")).toBeInTheDocument();
    fireEvent.click(screen.getByTitle("Submit live order (submit=true)"));
    await waitFor(() => expect(runFunctionMock).toHaveBeenCalledTimes(1));
    const optsArg = runFunctionMock.mock.calls[0][1] as {
      params: Record<string, unknown>;
    };
    expect(optsArg.params.submit).toBe(true);
    expect(optsArg.params.paper_mode).toBe(false);
  });

  it("resets the confirm arm when any ticket field changes", () => {
    render(<EMSXPane code="EMSX" symbol="AAPL" />);
    fillTicket();
    fireEvent.click(screen.getByText("I confirm this is a real order"));
    expect(screen.getByText("LIVE ARMED")).toBeInTheDocument();
    fireEvent.change(screen.getByLabelText("Quantity"), {
      target: { value: "6" },
    });
    expect(screen.queryByText("LIVE ARMED")).toBeNull();
    expect(screen.getByTitle(/Tick the confirm checkbox/)).toBeDisabled();
  });
});

describe("EMSX pane — live success state (F9/H)", () => {
  it("renders a SUBMITTED order (not 'preview') after a successful live submit", async () => {
    runFunctionMock.mockResolvedValue(submittedPayload());
    const { container } = render(<EMSXPane code="EMSX" symbol="AAPL" />);
    fillTicket();
    fireEvent.click(screen.getByText("I confirm this is a real order"));
    fireEvent.click(screen.getByTitle("Submit live order (submit=true)"));
    await screen.findByText(/Order submitted/);
    expect(screen.getAllByText("SUBMITTED").length).toBeGreaterThan(0);
    expect(screen.getByText("ord-9")).toBeInTheDocument();
    expect(container.textContent).toContain("· LIVE");
    expect(container.textContent).not.toContain("· paper");
  });
});
