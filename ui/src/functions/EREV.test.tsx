/**
 * EREV pane — provider honesty (F6).
 *
 * The backend used to substitute three hard-coded analyst buckets and return
 * `status:"ok"` with no warning when Finnhub was absent/failed, so the pane
 * lit a green "live" pill over fabricated months in every keyless install.
 * These tests pin the honest contract:
 *  - loading / error states;
 *  - a real provider payload shows the live pill + rows;
 *  - a `provider_unavailable` envelope can never show "live" and surfaces the
 *    reason, warnings and next actions verbatim.
 */
import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

interface MockFnState {
  state: "idle" | "loading" | "ok" | "error" | "refreshing";
  data?:
    | {
        data?: unknown;
        status?: string;
        sources?: string[];
        elapsed_ms?: number;
        metadata?: Record<string, unknown>;
      }
    | undefined;
  error?: Error | null;
}

const mockFn: MockFnState = { state: "idle", data: undefined, error: null };

vi.mock("@/lib/useFunction", () => ({
  useFunction: () => ({
    state: mockFn.state,
    data: mockFn.data,
    error: mockFn.error,
    refetch: vi.fn(),
  }),
}));
vi.mock("@/lib/router", () => ({ navigate: vi.fn() }));

import { EREVPane } from "./EREV";

function liveData() {
  return {
    status: "ok",
    data: {
      status: "ok",
      symbol: "AAPL",
      trend: [
        {
          period: "2026-03",
          score: 5,
          n: 10,
          avg: 0.5,
          strongBuy: 3,
          buy: 2,
          hold: 5,
          sell: 0,
          strongSell: 0,
        },
      ],
      rows: [],
      revisions: [],
      velocity_avg: 0.1,
      data_mode: "live_official",
    },
    sources: ["finnhub"],
    metadata: { live: true, data_mode: "live_official" },
    elapsed_ms: 5,
  };
}

function unavailableData() {
  return {
    status: "provider_unavailable",
    data: {
      status: "provider_unavailable",
      symbol: "AAPL",
      rows: [],
      trend: [],
      revisions: [],
      velocity_avg: null,
      current_score: null,
      reason: "finnhub provider not wired (no API key configured)",
      warnings: [
        "No Finnhub key wired; analyst recommendation buckets unavailable.",
      ],
      next_actions: [
        "Configure a Finnhub API key so analyst recommendation buckets can load.",
      ],
      data_mode: "not_configured",
    },
    sources: [],
    metadata: { live: false, fallback: true, data_mode: "not_configured" },
    elapsed_ms: 3,
  };
}

beforeEach(() => {
  localStorage.clear();
  mockFn.state = "idle";
  mockFn.data = undefined;
  mockFn.error = null;
});

afterEach(() => {
  cleanup();
});

describe("EREV pane — provider honesty", () => {
  it("renders a skeleton while loading", () => {
    mockFn.state = "loading";
    const { container } = render(<EREVPane code="EREV" symbol="AAPL" />);
    expect(container.querySelector('[aria-busy="true"]')).not.toBeNull();
  });

  it("renders the error state with a retry", () => {
    mockFn.state = "error";
    mockFn.error = new Error("sidecar exploded");
    render(<EREVPane code="EREV" symbol="AAPL" />);
    expect(screen.getByText(/sidecar exploded/i)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /retry/i })).toBeInTheDocument();
  });

  it("shows the live pill only for a genuine ok payload", () => {
    mockFn.state = "ok";
    mockFn.data = liveData();
    render(<EREVPane code="EREV" symbol="AAPL" />);
    expect(screen.getByText("live")).toBeInTheDocument();
    // The period appears both as the KPI caption and in the grid.
    expect(screen.getAllByText("2026-03").length).toBeGreaterThanOrEqual(1);
  });

  it("never shows live over a provider_unavailable envelope (fabricated-bucket regression)", () => {
    mockFn.state = "ok";
    mockFn.data = unavailableData();
    render(<EREVPane code="EREV" symbol="AAPL" />);
    expect(screen.queryByText("live")).toBeNull();
    expect(screen.getByText(/provider unavailable/i)).toBeInTheDocument();
    expect(
      screen.getByText(/finnhub provider not wired/i),
    ).toBeInTheDocument();
    expect(
      screen.getByText(/No Finnhub key wired/i),
    ).toBeInTheDocument();
    expect(
      screen.getByText(/Configure a Finnhub API key/i),
    ).toBeInTheDocument();
  });

  it("never shows fabricated bucket rows on the unavailable path", () => {
    mockFn.state = "ok";
    mockFn.data = unavailableData();
    const { container } = render(<EREVPane code="EREV" symbol="AAPL" />);
    expect(container.textContent).not.toMatch(/S\.Buy/);
  });
});
