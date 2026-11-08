/**
 * NALRT — news alerts. Severity comes from the backend per row (critical >= 85).
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

import { NALRTPane } from "./NALRT";

const NOW_ISO = new Date().toISOString();
const base = {
  publisher: "Reuters",
  publisher_tier: 1,
  published_at: NOW_ISO,
  summary: "",
  symbols: [],
  countries: [],
  topics: [],
  asset_classes: [],
  entities: [],
  sentiment: "negative",
  sentiment_score: -0.6,
  sentiment_confidence: 0.9,
  sentiment_model: "ProsusAI/finbert",
  quality_label: "premium",
  quality_score: 90,
  quality_reasons: [],
  story_id: null,
  story_size: 1,
  is_paywalled: false,
  url: "https://news.example/a",
  link: null,
};
const CRITICAL = {
  ...base,
  id: "x1",
  title: "Central bank emergency action",
  importance: 91,
  severity: "critical",
};
const HIGH = {
  ...base,
  id: "x2",
  title: "Oil spikes on pipeline outage",
  importance: 72,
  severity: "high",
};

function ok(data: Record<string, unknown>) {
  return {
    state: "ok",
    refetch: vi.fn(),
    error: undefined,
    data: {
      code: "NALRT",
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

describe("NALRT alerts", () => {
  it("sends the threshold and window contract params only", () => {
    useFunctionMock.mockReturnValue(ok({ status: "ok", rows: [CRITICAL, HIGH] }));
    render(<NALRTPane code="NALRT" />);
    expect(paneCalls()[0].params).toEqual({ hours: 6, min_importance: 70, limit: 50 });
  });

  it("renders the backend severity per row", () => {
    useFunctionMock.mockReturnValue(ok({ status: "ok", rows: [CRITICAL, HIGH] }));
    render(<NALRTPane code="NALRT" />);
    expect(screen.getByText("CRITICAL")).toBeInTheDocument();
    expect(screen.getByText("HIGH")).toBeInTheDocument();
    expect(screen.getByText(/2 alerts, 1 critical, last 6h/)).toBeInTheDocument();
  });

  it("offers relaxers in the empty state instead of inventing alerts", () => {
    useFunctionMock.mockReturnValue(ok({ status: "empty", rows: [] }));
    render(<NALRTPane code="NALRT" />);
    expect(screen.getByText("No alerts in this window")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Lower to importance 50+" }));
    expect(paneCalls().at(-1)?.params).toMatchObject({ min_importance: 50 });
  });

  it("changing the importance threshold persists it", () => {
    useFunctionMock.mockReturnValue(ok({ status: "ok", rows: [CRITICAL] }));
    render(<NALRTPane code="NALRT" />);
    fireEvent.click(screen.getByRole("button", { name: "85+ critical" }));
    expect(window.localStorage.getItem("aw.nalrt.min")).toBe("85");
    expect(paneCalls().at(-1)?.params).toMatchObject({ min_importance: 85 });
  });

  it("changing the window sends hours", () => {
    useFunctionMock.mockReturnValue(ok({ status: "ok", rows: [CRITICAL] }));
    render(<NALRTPane code="NALRT" />);
    fireEvent.click(screen.getByRole("button", { name: "24h" }));
    expect(paneCalls().at(-1)?.params).toMatchObject({ hours: 24 });
  });

  it("shows the awareness-down state with no rows", () => {
    useFunctionMock.mockReturnValue(
      ok({ status: "provider_unavailable", reason: "awareness down", rows: [] }),
    );
    render(<NALRTPane code="NALRT" />);
    expect(screen.getByRole("alert")).toHaveTextContent("awareness down");
    expect(document.querySelectorAll(".aw-row")).toHaveLength(0);
  });
});
