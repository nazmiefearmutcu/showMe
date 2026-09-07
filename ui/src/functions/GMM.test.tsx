/**
 * GMM pane — data-honesty + render-contract tests.
 *
 * Mirrors the GEX test pattern: `useFunction` is mocked via a mutable
 * shared state so each test drives the pane into a specific branch
 * without the real sidecar transport. Pins:
 *
 *  - the four load states (loading / empty / error / ok) render;
 *  - a provider_unavailable payload renders an honest outage state,
 *    never placeholder macro numbers;
 *  - the ok state renders the stress matrix rows ranked by score;
 *  - missing indicator cells render as em-dash (no fabricated values);
 *  - the universe segmented control accepts an interaction.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { GMMPane } from "./GMM";

/* ── useFunction mock ──────────────────────────────────────────────── */

interface MockFnState {
  state: "idle" | "loading" | "ok" | "error" | "refreshing";
  data?: { data?: unknown; sources?: string[]; elapsed_ms?: number } | undefined;
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

/* ── fixtures ──────────────────────────────────────────────────────── */

function okPayload() {
  return {
    data: {
      sources: ["worldbank"],
      elapsed_ms: 812,
      data: {
        status: "ok",
        source_mode: "worldbank",
        rows: [
          {
            country: "Turkey",
            country_code: "TR",
            gdp_growth: 3.6,
            gdp_growth_year: 2025,
            inflation: 34.9,
            inflation_year: 2025,
            unemployment: 8.5,
            unemployment_year: 2025,
            debt_gdp: 26.6,
            debt_gdp_year: 2024,
            score: 41.1,
          },
          {
            country: "United States",
            country_code: "US",
            gdp_growth: 2.2,
            gdp_growth_year: 2025,
            inflation: 2.9,
            inflation_year: 2024,
            unemployment: 4.2,
            unemployment_year: 2025,
            debt_gdp: 115.8,
            debt_gdp_year: 2024,
            score: 11.3,
          },
          {
            // Sparse row: unemployment + debt never published (nulls).
            country: "Fakeistan",
            country_code: "FK",
            gdp_growth: 1.0,
            gdp_growth_year: 2025,
            inflation: null,
            inflation_year: null,
            unemployment: null,
            unemployment_year: null,
            debt_gdp: null,
            debt_gdp_year: null,
            score: 1.0,
          },
        ],
        cards: [
          { key: "economies", label: "Economies", value: 3 },
          { key: "hottest_inflation", label: "Hottest CPI", value: "Turkey 34.9%" },
          { key: "fastest_growth", label: "Fastest GDP", value: "Turkey 3.6%" },
          { key: "source", label: "Source", value: "World Bank" },
        ],
      },
    },
  };
}

/* ── tests ─────────────────────────────────────────────────────────── */

beforeEach(() => {
  setMockFn({ state: "idle", data: undefined });
});

afterEach(() => {
  cleanup();
});

describe("GMM pane — load states", () => {
  it("renders a skeleton while loading", () => {
    setMockFn({ state: "loading", data: undefined });
    const { container } = render(<GMMPane code="GMM" symbol="SPY" />);
    expect(container.querySelectorAll(".ds-skeleton, [aria-busy='true']").length).toBeGreaterThan(0);
  });

  it("renders the error state when the fetch errors", () => {
    setMockFn({
      state: "error",
      data: undefined,
      error: new Error("sidecar exploded"),
    });
    render(<GMMPane code="GMM" symbol="SPY" />);
    expect(screen.getByText(/sidecar exploded/i)).toBeInTheDocument();
  });

  it("renders the honest outage state for provider_unavailable", () => {
    setMockFn({
      state: "ok",
      data: {
        data: {
          status: "provider_unavailable",
          rows: [],
          reason: "worldbank: connection refused",
          next_actions: ["Retry — the World Bank API occasionally rate-limits."],
        },
      },
    });
    render(<GMMPane code="GMM" symbol="SPY" />);
    expect(screen.getByText(/World Bank unavailable/i)).toBeInTheDocument();
    expect(screen.getByText(/connection refused/i)).toBeInTheDocument();
  });

  it("renders the empty state when there are no rows", () => {
    setMockFn({
      state: "ok",
      data: { data: { status: "ok", rows: [] } },
    });
    render(<GMMPane code="GMM" symbol="SPY" />);
    expect(screen.getByText(/No macro rows/i)).toBeInTheDocument();
  });
});

describe("GMM pane — matrix rendering", () => {
  it("renders one matrix row per economy with the stress score", () => {
    setMockFn({ state: "ok", ...okPayload() });
    const { container } = render(<GMMPane code="GMM" symbol="SPY" />);
    const bodyRows = container.querySelectorAll(".gmm-matrix tbody tr");
    expect(bodyRows.length).toBe(3);
    expect(screen.getByText("Turkey")).toBeInTheDocument();
    expect(screen.getByText("41.1")).toBeInTheDocument();
  });

  it("renders observation years inline on tinted cells", () => {
    setMockFn({ state: "ok", ...okPayload() });
    render(<GMMPane code="GMM" symbol="SPY" />);
    expect(screen.getByText("34.9%")).toBeInTheDocument();
    // Several cells share the 2025 observation year — all must render.
    expect(screen.getAllByText("2025").length).toBeGreaterThanOrEqual(2);
  });

  it("renders missing indicator cells as em-dash, never fabricated numbers", () => {
    setMockFn({ state: "ok", ...okPayload() });
    render(<GMMPane code="GMM" symbol="SPY" />);
    // Fakeistan has no inflation, unemployment, or debt observation.
    expect(
      screen.getAllByLabelText("no World Bank observation").length,
    ).toBe(3);
  });

  it("summarizes hottest CPI and fastest GDP from the payload cards", () => {
    setMockFn({ state: "ok", ...okPayload() });
    render(<GMMPane code="GMM" symbol="SPY" />);
    expect(screen.getByText("Turkey 34.9%")).toBeInTheDocument();
    expect(screen.getByText("Turkey 3.6%")).toBeInTheDocument();
  });
});

describe("GMM pane — universe control", () => {
  it("switches the universe via the segmented control", () => {
    setMockFn({ state: "ok", ...okPayload() });
    render(<GMMPane code="GMM" symbol="SPY" />);
    const g7 = screen.getByTitle("Universe: G7");
    expect(g7).not.toBeDisabled();
    fireEvent.click(g7);
    expect(g7).toBeDisabled();
    expect(screen.getByTitle("Universe: major economies")).not.toBeDisabled();
  });
});
