/**
 * TRAN pane — release view wording (TRAN#1 residual).
 *
 * When the backend answers with document_type "earnings_press_release" (the
 * SEC 8-K EX-99.x default path), no control or label may still say
 * "transcript". These tests pin the release-view labels.
 */
import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, render, screen } from "@testing-library/react";
import { TRANPane } from "./TRAN";

interface MockFnState {
  state: "idle" | "loading" | "ok" | "error" | "refreshing";
  data?: { data?: unknown; sources?: string[]; elapsed_ms?: number };
  error?: Error | null;
}

const mockFn: MockFnState = { state: "idle", data: undefined, error: null };

function setMockFn(next: MockFnState) {
  mockFn.state = next.state;
  mockFn.data = next.data;
  mockFn.error = next.error ?? null;
}

vi.mock("@/lib/useFunction", () => ({
  useFunction: () => ({
    state: mockFn.state,
    data: mockFn.data,
    error: mockFn.error,
    refetch: vi.fn(),
  }),
}));

function releasePayload() {
  return {
    sources: ["sec_edgar"],
    elapsed_ms: 640,
    data: {
      symbol: "AAPL",
      status: "ok",
      document_type: "earnings_press_release",
      event: {
        symbol: "AAPL",
        form: "8-K",
        source: "sec_edgar",
        source_url: "https://www.sec.gov/Archives/edgar/data/320193/x/",
      },
      utterances: [
        {
          section: "document",
          speaker: null,
          role: "",
          utterance: "CUPERTINO, California, Apple today announced financial results.",
          timestamp_seconds: null,
          position: 1,
        },
      ],
    },
  };
}

afterEach(() => {
  cleanup();
});

describe("TRAN pane — release view never says transcript", () => {
  it("uses release wording for the search box and refresh control", () => {
    setMockFn({ state: "ok", data: releasePayload() });
    render(<TRANPane code="TRAN" symbol="AAPL" />);
    expect(screen.getByLabelText("Search release")).toBeInTheDocument();
    expect(screen.queryByLabelText("Search transcript")).toBeNull();
    expect(screen.getByTitle("Refresh release")).toBeInTheDocument();
    expect(screen.queryByTitle("Refresh transcript")).toBeNull();
    expect(screen.queryByPlaceholderText(/transcript/i)).toBeNull();
  });
});
