/**
 * TSAR pane — linked-symbol sync (UI-2).
 *
 * The pane is linked to a symbol through the `symbol` prop. Changing the link
 * must re-sync the symbol input, drop the analysis computed for the previous
 * symbol, and run any new analysis on the new symbol. A result computed for
 * AAPL must never be displayed under an MSFT label.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { TSARPane } from "./TSAR";

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

function analysisPayload() {
  return {
    data: {
      status: "ok",
      data_mode: "live_official",
      summary: {
        dominant_tone: "positive",
        net_score: 0.42,
        management_score: 0.5,
        analyst_score: -0.2,
        utterance_count: 1,
        model_set: ["finbert"],
        source: "archive",
      },
      speaker_rollups: [],
      utterances: [
        {
          position: 1,
          section: "prepared_remarks",
          speaker: "CEO",
          role: "management",
          utterance: "Archived remark.",
          sentiment: "positive",
          score: 0.6,
          model: "finbert",
        },
      ],
      rows: [],
      methodology: "…",
      next_actions: [],
    },
    sources: ["transcripts_archive", "finbert"],
    warnings: [],
    elapsed_ms: 5,
  };
}

beforeEach(() => {
  localStorage.clear();
  runFunctionMock.mockReset();
  runFunctionMock.mockResolvedValue(analysisPayload());
});
afterEach(() => {
  cleanup();
});

describe("TSAR pane — linked symbol sync (UI-2)", () => {
  it("re-syncs the symbol input and drops the stale analysis when the link changes", async () => {
    const { rerender } = render(<TSARPane code="TSAR" symbol="AAPL" />);
    fireEvent.click(screen.getByRole("button", { name: "Analyze" }));
    expect(await screen.findByText("+0.42")).toBeInTheDocument();
    expect(screen.getByText(/^AAPL · /)).toBeInTheDocument();

    rerender(<TSARPane code="TSAR" symbol="MSFT" />);

    const input = screen.getByPlaceholderText(
      "Symbol (optional archive lookup)",
    ) as HTMLInputElement;
    expect(input.value).toBe("MSFT");
    expect(screen.queryByText("+0.42")).not.toBeInTheDocument();
    expect(screen.queryByText(/^AAPL · /)).not.toBeInTheDocument();
  });

  it("runs the next analysis on the newly linked symbol", async () => {
    const { rerender } = render(<TSARPane code="TSAR" symbol="AAPL" />);
    fireEvent.click(screen.getByRole("button", { name: "Analyze" }));
    await waitFor(() => expect(runFunctionMock).toHaveBeenCalledTimes(1));

    rerender(<TSARPane code="TSAR" symbol="MSFT" />);
    fireEvent.click(screen.getByRole("button", { name: "Analyze" }));
    await waitFor(() => expect(runFunctionMock).toHaveBeenCalledTimes(2));
    const [, optsArg] = runFunctionMock.mock.calls[1] as [
      string,
      { params: Record<string, unknown> },
    ];
    expect(optsArg.params).toEqual({ symbol: "MSFT" });
  });
});
