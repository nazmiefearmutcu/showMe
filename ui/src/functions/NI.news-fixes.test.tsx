/**
 * NI — the CRYPTO preset is a real backend preset, and a fallback note from the backend is
 * disclosed in the footer when rows are present (not only in the empty state).
 */
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const useFunctionMock = vi.fn();

vi.mock("@/lib/useFunction", () => ({
  useFunction: (...args: unknown[]) => useFunctionMock(...args),
}));
vi.mock("@/lib/useVisibilityTick", () => ({
  useVisibilityTick: () => 0,
}));
vi.mock("@/lib/workspace", () => ({
  useWorkspace: (selector: (s: { setFocusedTarget: () => void }) => unknown) =>
    selector({ setFocusedTarget: () => undefined }),
}));

import { NIPane } from "./NI";

const NOW_ISO = new Date().toISOString();
const ROW = {
  id: "c1",
  title: "Bitcoin ETF flows turn positive",
  url: "https://news.example/btc",
  publisher: "CoinDesk",
  publisher_tier: 3,
  published_at: NOW_ISO,
  summary: "Flows.",
  symbols: ["BTC"],
  countries: [],
  topics: ["crypto_market"],
  asset_classes: ["crypto"],
  entities: [],
  sentiment: "positive",
  sentiment_score: 0.4,
  importance: 50,
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
      code: "NI",
      instrument: null,
      data,
      metadata: {},
      fetched_at: NOW_ISO,
      sources: ["awareness:news"],
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
  useFunctionMock.mockReturnValue(ok({ status: "ok", rows: [ROW] }));
  window.localStorage.clear();
});

afterEach(() => {
  cleanup();
});

describe("NI presets", () => {
  it("offers CRYPTO and sends it as the topic preset", () => {
    render(<NIPane code="NI" />);
    fireEvent.click(screen.getByRole("button", { name: "CRYPTO" }));
    expect(paneCalls().at(-1)?.params).toMatchObject({ topic: "CRYPTO" });
    expect(screen.getByText("CRYPTO preset")).toBeInTheDocument();
  });
});

describe("NI fallback disclosure", () => {
  it("shows the backend hidden_note in the footer when rows are present", () => {
    useFunctionMock.mockReturnValue(
      ok({
        status: "ok",
        rows: [ROW],
        topic: "MACRO",
        hidden_note: "unknown topic 'NOPE'; showing MACRO",
      }),
    );
    render(<NIPane code="NI" />);
    expect(screen.getByRole("note")).toHaveTextContent(
      "unknown topic 'NOPE'; showing MACRO",
    );
    expect(screen.getByText("Bitcoin ETF flows turn positive")).toBeInTheDocument();
  });

  it("shows no note when the backend sends none", () => {
    render(<NIPane code="NI" />);
    expect(screen.queryByRole("note")).toBeNull();
  });
});
