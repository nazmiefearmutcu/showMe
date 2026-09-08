/**
 * GRAB pane — honest draft-only capture-plan tests.
 *
 * The backend GRAB function never auto-sends; it returns a draft-only
 * capture plan. These tests pin:
 *
 *  - the idle state ("No plan yet") and the running skeleton;
 *  - the form submit calls runFunction with the entered target/recipient;
 *  - a resolved plan renders both steps with draft-only honesty and the
 *    standing "nothing is emailed automatically" notice;
 *  - a rejected call renders the error message verbatim;
 *  - the pane never renders a control or state that claims a send happened.
 *
 * `runFunction` is mocked (no sidecar transport); `useAppStore` is stubbed
 * to a ready sidecar.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { FunctionCallError } from "@/lib/functions";
import { GRABPane } from "./GRAB";

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

function draftPayload() {
  return {
    data: {
      status: "draft_only",
      target: "current_pane",
      recipient: "trader@example.com",
      rows: [
        {
          step: "capture",
          target: "current_pane",
          status: "ready",
          output: "local screenshot artifact",
          transmits_data: false,
        },
        {
          step: "email",
          target: "trader@example.com",
          status: "draft_only",
          output: "requires user-confirmed mail integration",
          transmits_data: true,
        },
      ],
      cards: [
        { label: "Capture", value: "local" },
        { label: "Email", value: "draft only" },
      ],
      next_actions: ["Confirm the recipient before sending any screenshot."],
    },
    sources: ["local_capture_plan"],
    elapsed_ms: 3.2,
    warnings: [],
  };
}

beforeEach(() => {
  runFunctionMock.mockReset();
});
afterEach(() => {
  cleanup();
});

describe("GRAB pane — idle + running states", () => {
  it("renders the idle plan state before any submit", () => {
    render(<GRABPane code="GRAB" />);
    expect(screen.getByText(/No plan yet/i)).toBeInTheDocument();
    expect(runFunctionMock).not.toHaveBeenCalled();
  });

  it("shows the draft-only pill from the start", () => {
    render(<GRABPane code="GRAB" />);
    expect(screen.getAllByText(/draft only/i).length).toBeGreaterThan(0);
  });
});

describe("GRAB pane — prepare interaction", () => {
  it("calls runFunction with the entered target and recipient", async () => {
    runFunctionMock.mockResolvedValue(draftPayload());
    render(<GRABPane code="GRAB" />);
    fireEvent.change(screen.getByLabelText("Target"), {
      target: { value: "watchlist_pane" },
    });
    fireEvent.change(screen.getByLabelText(/Recipient/), {
      target: { value: "trader@example.com" },
    });
    fireEvent.click(screen.getByTitle(/Prepare the capture plan/));
    await waitFor(() => {
      expect(runFunctionMock).toHaveBeenCalledTimes(1);
    });
    const [codeArg, optsArg] = runFunctionMock.mock.calls[0] as [
      string,
      { params: { target: string; recipient: string } },
    ];
    expect(codeArg).toBe("GRAB");
    expect(optsArg.params.target).toBe("watchlist_pane");
    expect(optsArg.params.recipient).toBe("trader@example.com");
  });

  it("renders both plan steps with transmit honesty when resolved", async () => {
    runFunctionMock.mockResolvedValue(draftPayload());
    render(<GRABPane code="GRAB" />);
    fireEvent.click(screen.getByTitle(/Prepare the capture plan/));
    await screen.findByText("capture");
    expect(screen.getByText("email")).toBeInTheDocument();
    expect(screen.getByText("would transmit")).toBeInTheDocument();
    expect(screen.getByText("local only")).toBeInTheDocument();
    expect(
      screen.getByText(/Nothing is emailed automatically/i),
    ).toBeInTheDocument();
  });

  it("renders the rejected call error verbatim", async () => {
    runFunctionMock.mockRejectedValue(
      new FunctionCallError("function call failed", 503, "sidecar unavailable"),
    );
    render(<GRABPane code="GRAB" />);
    fireEvent.click(screen.getByTitle(/Prepare the capture plan/));
    await screen.findByText(/503: sidecar unavailable/);
    expect(screen.getByText(/Function error/i)).toBeInTheDocument();
  });

  it("never claims an email was sent", async () => {
    runFunctionMock.mockResolvedValue(draftPayload());
    const { container } = render(<GRABPane code="GRAB" />);
    fireEvent.click(screen.getByTitle(/Prepare the capture plan/));
    await screen.findByText("capture");
    expect(container.textContent).toContain("nothing transmitted");
    expect(container.textContent).not.toContain("sent successfully");
  });
});
