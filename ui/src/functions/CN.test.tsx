/**
 * CN (company news) and NI (news index) share NIPane. CN is symbol-bound and sends the
 * symbol as the instrument; NI sends a topic preset. Both are news only: no market rows.
 */
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const useFunctionMock = vi.fn();

vi.mock("@/lib/useFunction", () => ({
  useFunction: (...args: unknown[]) => useFunctionMock(...args),
}));
vi.mock("@/lib/workspace", () => ({
  useWorkspace: (selector: (s: { setFocusedTarget: () => void }) => unknown) =>
    selector({ setFocusedTarget: () => undefined }),
}));

import { NIPane } from "./NI";

const NOW_ISO = new Date().toISOString();
const ROW = {
  id: "c1",
  title: "Apple supplier reports record quarter",
  url: "https://news.example/aapl",
  publisher: "Reuters",
  publisher_tier: 1,
  published_at: NOW_ISO,
  summary: "Supplier results beat.",
  symbols: ["AAPL"],
  countries: [],
  topics: ["earnings"],
  asset_classes: ["equity"],
  entities: [],
  sentiment: "positive",
  sentiment_score: 0.4,
  sentiment_confidence: 0.8,
  sentiment_model: "ProsusAI/finbert",
  importance: 55,
  quality_label: "standard",
  quality_score: 60,
  quality_reasons: [],
  story_id: null,
  story_size: 1,
  is_paywalled: false,
};

function ok(data: Record<string, unknown>) {
  return {
    state: "ok",
    refetch: vi.fn(),
    error: undefined,
    data: {
      code: "CN",
      instrument: null,
      data,
      metadata: {},
      fetched_at: NOW_ISO,
      sources: [],
      warnings: [],
      elapsed_ms: 1,
    },
  };
}

function paneCalls() {
  return useFunctionMock.mock.calls
    .map((c) => c[0])
    .filter((a) => a.params && !("story_id" in a.params));
}

beforeEach(() => {
  useFunctionMock.mockReset();
  window.localStorage.clear();
});

afterEach(() => {
  cleanup();
});

describe("CN company news", () => {
  it("asks for an input symbol instead of guessing one", () => {
    render(<NIPane code="CN" />);
    expect(screen.getByText("Pick a symbol")).toBeInTheDocument();
    expect(useFunctionMock).not.toHaveBeenCalled();
  });

  it("sends the bound symbol as instrument and only contract params", () => {
    useFunctionMock.mockReturnValue(ok({ status: "ok", rows: [ROW] }));
    render(<NIPane code="CN" symbol="AAPL" />);
    const call = paneCalls()[0];
    expect(call).toMatchObject({ code: "CN", symbol: "AAPL" });
    expect(call.params).toEqual({ hours: 168, limit: 50 });
    expect(screen.getByText("Company news — AAPL")).toBeInTheDocument();
    expect(screen.getByText("Apple supplier reports record quarter")).toBeInTheDocument();
  });

  it("shows the awareness-down state for CN", () => {
    useFunctionMock.mockReturnValue(
      ok({ status: "provider_unavailable", reason: "awareness not reachable", rows: [] }),
    );
    render(<NIPane code="CN" symbol="AAPL" />);
    expect(screen.getByRole("alert")).toHaveTextContent("awareness not reachable");
    expect(document.querySelectorAll(".aw-row")).toHaveLength(0);
  });

  it("shows the empty state with the symbol in the body", () => {
    useFunctionMock.mockReturnValue(ok({ status: "empty", rows: [] }));
    render(<NIPane code="CN" symbol="AAPL" />);
    expect(screen.getByTestId("pane-state-empty")).toHaveTextContent(
      "No stories for AAPL in the last 168h.",
    );
  });

  it("persists the window under the CN-specific key", () => {
    useFunctionMock.mockReturnValue(ok({ status: "ok", rows: [ROW] }));
    render(<NIPane code="CN" symbol="AAPL" />);
    fireEvent.click(screen.getByRole("button", { name: "30d" }));
    expect(window.localStorage.getItem("aw.cn.hours")).toBe("720");
    expect(window.localStorage.getItem("aw.ni.hours")).toBeNull();
  });
});

describe("NI news index", () => {
  it("sends the topic preset and window, not a symbol", () => {
    useFunctionMock.mockReturnValue(ok({ status: "ok", rows: [ROW] }));
    render(<NIPane code="NI" />);
    const call = paneCalls()[0];
    expect(call.code).toBe("NI");
    expect(call.symbol).toBeUndefined();
    expect(call.params).toEqual({ topic: "MACRO", hours: 48, limit: 50 });
  });

  it("switching the topic preset re-issues the query with the new topic", () => {
    useFunctionMock.mockReturnValue(ok({ status: "ok", rows: [ROW] }));
    render(<NIPane code="NI" />);
    fireEvent.click(screen.getByRole("button", { name: "OIL" }));
    expect(paneCalls().at(-1)?.params).toMatchObject({ topic: "OIL" });
  });
});
