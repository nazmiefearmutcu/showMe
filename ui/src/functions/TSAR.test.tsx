/**
 * TSAR pane — analyzer-surface + search-mode tests (F4 macro lane).
 *
 * Pins:
 *  - the Sentiment view is reachable and calls the backend's DEFAULT analyzer
 *    route (no `action`) with pasted text / symbol, rendering summary,
 *    speaker rollups and the utterance ladder;
 *  - `not_configured` degrades honestly with the setup hint;
 *  - the Search view still drives action=search and the Stats button reports
 *    failures instead of swallowing them.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { TSARPane } from "./TSAR";

/* ── runFunction mock ──────────────────────────────────────────────── */

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

/* ── fixtures ──────────────────────────────────────────────────────── */

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
        utterance_count: 2,
        model_set: ["finbert"],
        source: "pasted_text",
      },
      speaker_rollups: [
        { role: "management", speaker: "management", score: 0.5, count: 1, sentiment: "positive" },
        { role: "analyst", speaker: "analyst", score: -0.3, count: 1, sentiment: "negative" },
      ],
      utterances: [
        {
          position: 1,
          section: "prepared_remarks",
          speaker: "CEO",
          role: "management",
          utterance: "We grew revenue 20% year over year.",
          sentiment: "positive",
          score: 0.6,
          model: "finbert",
        },
        {
          position: 2,
          section: "qa",
          speaker: "Analyst",
          role: "analyst",
          utterance: "Margins look weak this quarter.",
          sentiment: "negative",
          score: -0.3,
          model: "finbert",
        },
      ],
      rows: [],
      methodology: "…",
      next_actions: [],
    },
    sources: ["pasted_text", "finbert"],
    warnings: [],
    elapsed_ms: 5,
  };
}

function searchPayload() {
  return {
    data: {
      query: "guidance",
      items: [
        {
          id: 7,
          symbol: "AAPL",
          quarter: "Q2",
          fiscal_year: "2026",
          event_date: "2026-05-01",
          source: "call",
          snippet: "guidance raised",
          sentiment: "positive",
        },
      ],
    },
    sources: ["transcripts_archive"],
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

describe("TSAR pane — sentiment analyzer surface", () => {
  it("defaults to the Sentiment view and does not fire on mount", () => {
    render(<TSARPane code="TSAR" symbol="AAPL" />);
    expect(screen.getByText(/Transcript sentiment analyzer/i)).toBeInTheDocument();
    expect(screen.getByText(/No analysis yet/i)).toBeInTheDocument();
    expect(runFunctionMock).not.toHaveBeenCalled();
  });

  it("calls the default analyzer route with pasted text and renders the payload", async () => {
    runFunctionMock.mockResolvedValue(analysisPayload());
    render(<TSARPane code="TSAR" symbol="AAPL" />);
    fireEvent.change(screen.getByLabelText("Transcript text"), {
      target: { value: "CEO: We grew revenue 20% year over year." },
    });
    fireEvent.click(screen.getByRole("button", { name: "Analyze" }));
    await waitFor(() => expect(runFunctionMock).toHaveBeenCalledTimes(1));
    const [codeArg, optsArg] = runFunctionMock.mock.calls[0] as [
      string,
      { params: Record<string, unknown> },
    ];
    expect(codeArg).toBe("TSAR");
    expect(optsArg.params.action).toBeUndefined();
    expect(optsArg.params.text).toBe("CEO: We grew revenue 20% year over year.");

    expect(await screen.findByText("+0.42")).toBeInTheDocument();
    expect(screen.getByText("We grew revenue 20% year over year.")).toBeInTheDocument();
    expect(screen.getByLabelText("TSAR speaker rollups")).toBeInTheDocument();
    expect(screen.getByLabelText("TSAR utterances")).toBeInTheDocument();
  });

  it("falls back to the symbol lookup when no text is pasted", async () => {
    runFunctionMock.mockResolvedValue(analysisPayload());
    render(<TSARPane code="TSAR" symbol="AAPL" />);
    fireEvent.click(screen.getByRole("button", { name: "Analyze" }));
    await waitFor(() => expect(runFunctionMock).toHaveBeenCalledTimes(1));
    const [, optsArg] = runFunctionMock.mock.calls[0] as [string, { params: Record<string, unknown> }];
    expect(optsArg.params).toEqual({ symbol: "AAPL" });
  });

  it("refuses to call the backend with no text and no symbol", async () => {
    render(<TSARPane code="TSAR" />);
    fireEvent.click(screen.getByRole("button", { name: "Analyze" }));
    expect(await screen.findByText(/Paste transcript text/i)).toBeInTheDocument();
    expect(runFunctionMock).not.toHaveBeenCalled();
  });

  it("degrades honestly when the analyzer is not configured", async () => {
    runFunctionMock.mockResolvedValue({
      data: {
        status: "not_configured",
        data_mode: "not_configured",
        summary: { dominant_tone: "neutral", utterance_count: 0, model_set: ["finbert"] },
        speaker_rollups: [],
        utterances: [],
        next_actions: ["Install/warm Whisper (large-v3) to transcribe the audio before scoring."],
      },
      sources: ["whisper"],
      warnings: ["whisper not configured"],
    });
    render(<TSARPane code="TSAR" symbol="AAPL" />);
    fireEvent.click(screen.getByRole("button", { name: "Analyze" }));
    expect(await screen.findByText(/Analyzer not configured/i)).toBeInTheDocument();
    expect(screen.getByText(/Install\/warm Whisper/i)).toBeInTheDocument();
  });
});

describe("TSAR pane — archive search view", () => {
  it("keeps action=search working from the Search tab", async () => {
    runFunctionMock.mockResolvedValue(searchPayload());
    render(<TSARPane code="TSAR" />);
    fireEvent.click(screen.getByRole("tab", { name: "Search" }));
    fireEvent.change(screen.getByPlaceholderText(/Search transcripts/i), {
      target: { value: "guidance" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Search" }));
    await waitFor(() => expect(runFunctionMock).toHaveBeenCalledTimes(1));
    const [codeArg, optsArg] = runFunctionMock.mock.calls[0] as [
      string,
      { params: Record<string, unknown> },
    ];
    expect(codeArg).toBe("TSAR");
    expect(optsArg.params).toEqual({ action: "search", query: "guidance", limit: 50 });
    expect(await screen.findByText("guidance raised")).toBeInTheDocument();
  });

  it("shows a failure pill when the Stats call rejects", async () => {
    runFunctionMock.mockRejectedValueOnce(new Error("archive down"));
    render(<TSARPane code="TSAR" />);
    fireEvent.click(screen.getByRole("tab", { name: "Search" }));
    fireEvent.click(screen.getByRole("button", { name: "Stats" }));
    expect(await screen.findByText(/stats failed/i)).toBeInTheDocument();
  });
});
