/**
 * NSE — news search. Nothing is fetched until a query is entered; zero rows at the
 * standard floor is reported by the backend hidden_note and never lowered silently.
 */
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const useFunctionMock = vi.fn();
const tickMock = vi.fn(() => 0);

vi.mock("@/lib/useFunction", () => ({
  useFunction: (...args: unknown[]) => useFunctionMock(...args),
}));
vi.mock("@/lib/useVisibilityTick", () => ({
  useVisibilityTick: () => tickMock(),
}));
vi.mock("@/lib/workspace", () => ({
  useWorkspace: (selector: (s: { setFocusedTarget: () => void }) => unknown) =>
    selector({ setFocusedTarget: () => undefined }),
}));

import { NSEPane } from "./NSE";

const NOW_ISO = new Date().toISOString();
const ROW = {
  id: "q1",
  title: "NVIDIA supply chain update",
  url: "https://news.example/nvda",
  publisher: "CNBC",
  publisher_tier: 2,
  published_at: NOW_ISO,
  summary: "Supply chain notes.",
  symbols: ["NVDA"],
  countries: [],
  topics: [],
  asset_classes: [],
  entities: [],
  sentiment: "neutral",
  sentiment_score: 0,
  importance: 40,
  quality_label: "standard",
  quality_score: 55,
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
      code: "NSE",
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
  useFunctionMock.mockReturnValue(ok({ status: "ok", rows: [] }));
  tickMock.mockReset();
  tickMock.mockReturnValue(0);
  window.localStorage.clear();
});

afterEach(() => {
  cleanup();
});

function search(text: string) {
  fireEvent.change(screen.getByLabelText("Company or keyword"), {
    target: { value: text },
  });
  fireEvent.click(screen.getByRole("button", { name: "Search" }));
}

describe("NSE news search", () => {
  it("does not fetch before a query is entered", () => {
    render(<NSEPane code="NSE" />);
    expect(screen.getByText("Search the news index")).toBeInTheDocument();
    expect(paneCalls().every((p) => p.enabled !== true)).toBe(true);
  });

  it("sends q, window and floor after a search", () => {
    render(<NSEPane code="NSE" />);
    search("NVIDIA");
    const call = paneCalls().at(-1);
    expect(call?.code).toBe("NSE");
    expect(call?.params).toEqual({
      q: "NVIDIA",
      hours: 720,
      min_quality: "standard",
      limit: 50,
    });
    expect(call?.enabled).toBe(true);
  });

  it("renders results with publisher and UTC time", () => {
    useFunctionMock.mockReturnValue(ok({ status: "ok", rows: [ROW] }));
    render(<NSEPane code="NSE" />);
    search("NVIDIA");
    expect(screen.getByText("CNBC")).toBeInTheDocument();
    expect(screen.getByText("NVIDIA supply chain update")).toBeInTheDocument();
    expect(screen.getByText(/UTC/)).toBeInTheDocument();
  });

  it("explains a zero-result floor and offers the relaxer without lowering silently", () => {
    useFunctionMock.mockReturnValue(
      ok({
        status: "empty",
        rows: [],
        hidden_note: "2 low-quality items match; include them to see them.",
        relax: { min_quality: "low" },
      }),
    );
    render(<NSEPane code="NSE" />);
    search("NVIDIA");
    expect(screen.getByText(/2 low-quality items match/)).toBeInTheDocument();
    expect(paneCalls().at(-1)?.params).toMatchObject({ min_quality: "standard" });
    fireEvent.click(screen.getByRole("button", { name: "Show low quality" }));
    expect(paneCalls().at(-1)?.params).toMatchObject({ min_quality: "low" });
  });

  it("shows the awareness-down state with the reason and no rows", () => {
    useFunctionMock.mockReturnValue(
      ok({ status: "provider_unavailable", reason: "awareness down", rows: [] }),
    );
    render(<NSEPane code="NSE" />);
    search("NVIDIA");
    expect(screen.getByRole("alert")).toHaveTextContent("awareness down");
    expect(document.querySelectorAll(".aw-row")).toHaveLength(0);
  });

  it("persists the window and floor choices", () => {
    render(<NSEPane code="NSE" />);
    fireEvent.click(screen.getByRole("button", { name: "7d" }));
    expect(window.localStorage.getItem("aw.nse.hours")).toBe("168");
  });

  it("offers the 60-day window and sends it, never a 90-day window the backend would clamp", () => {
    render(<NSEPane code="NSE" />);
    expect(screen.queryByRole("button", { name: "90d" })).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "60d" }));
    search("NVIDIA");
    expect(paneCalls().at(-1)?.params).toMatchObject({ hours: 1440 });
    expect(window.localStorage.getItem("aw.nse.hours")).toBe("1440");
  });

  it("does not send the pane symbol with a search (the search text is the query)", () => {
    render(<NSEPane code="NSE" symbol="NVDA" />);
    search("NVIDIA");
    expect(paneCalls().at(-1)?.params).not.toHaveProperty("symbol");
  });

  it("does not refetch a second time when a new search follows a refresh tick", () => {
    tickMock.mockReturnValue(1);
    const refetch = vi.fn();
    useFunctionMock.mockReturnValue({ ...ok({ status: "ok", rows: [] }), refetch });
    render(<NSEPane code="NSE" />);
    search("NVIDIA");
    expect(refetch).not.toHaveBeenCalled();
  });

  it("refreshes an active search once per visibility tick", () => {
    const refetch = vi.fn();
    useFunctionMock.mockReturnValue({ ...ok({ status: "ok", rows: [] }), refetch });
    const { rerender } = render(<NSEPane code="NSE" />);
    search("NVIDIA");
    expect(refetch).not.toHaveBeenCalled();
    tickMock.mockReturnValue(1);
    rerender(<NSEPane code="NSE" />);
    expect(refetch).toHaveBeenCalledTimes(1);
  });
});
