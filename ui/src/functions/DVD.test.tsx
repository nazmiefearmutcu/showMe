/**
 * DVD pane — Model mode honesty (F6).
 *
 * The backend Model branch used to return a bare template dict with no
 * `rows`, so the toggle rendered "No corporate actions" (dead mode). These
 * tests pin the labelled reference-row contract: model rows render with the
 * "modeled" pill, a visible notice and no "live" claim; the live path and the
 * provider-outage path keep their own states.
 */
import { cleanup, render, screen, within } from "@testing-library/react";
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

import { DVDPane } from "./DVD";

function liveData() {
  return {
    status: "ok",
    data: {
      status: "ok",
      rows: [
        {
          symbol: "AAPL",
          action_type: "dividend",
          date: "2026-08-08",
          amount: 0.25,
          source_mode: "live_yfinance_dividends",
        },
      ],
    },
    sources: ["yfinance"],
    metadata: {},
    elapsed_ms: 9,
  };
}

function modelData() {
  return {
    status: "ok",
    data: {
      status: "modeled",
      rows: [
        {
          symbol: "AAPL",
          action_type: "dividend",
          date: "2026-09-11",
          amount: 0.24,
          source_mode: "model",
          reason: "modelled_latest",
        },
        {
          symbol: "AAPL",
          action_type: "dividend",
          date: "2026-09-11",
          amount: 0.23,
          source_mode: "model",
          reason: "modelled_prior",
        },
      ],
    },
    sources: ["dividend_calendar_model"],
    metadata: { live: false, data_mode: "modeled" },
    elapsed_ms: 4,
  };
}

function outageData() {
  return {
    status: "ok",
    data: {
      status: "provider_unavailable",
      rows: [
        {
          symbol: "AAPL",
          action_type: "provider_unavailable",
          date: null,
          amount: null,
          source_mode: "yfinance_events_empty",
          reason: "Yahoo events returned no dividend or split rows.",
        },
      ],
    },
    sources: ["yfinance"],
    metadata: {},
    elapsed_ms: 7,
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

describe("DVD pane — Model mode honesty", () => {
  it("renders a skeleton while loading", () => {
    mockFn.state = "loading";
    const { container } = render(<DVDPane code="DVD" symbol="AAPL" />);
    expect(container.querySelector('[aria-busy="true"]')).not.toBeNull();
  });

  it("renders the error state with a retry", () => {
    mockFn.state = "error";
    mockFn.error = new Error("sidecar exploded");
    render(<DVDPane code="DVD" symbol="AAPL" />);
    expect(screen.getByText(/sidecar exploded/i)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /retry/i })).toBeInTheDocument();
  });

  it("shows the live pill for a genuine provider payload", () => {
    mockFn.state = "ok";
    mockFn.data = liveData();
    const { container } = render(<DVDPane code="DVD" symbol="AAPL" />);
    const header = container.querySelector(".ds-pane-header") as HTMLElement;
    expect(within(header).getByText("live")).toBeInTheDocument();
    expect(screen.getByText("live_yfinance_dividends")).toBeInTheDocument();
  });

  it("renders labelled model rows instead of the dead 'No corporate actions' state", () => {
    mockFn.state = "ok";
    mockFn.data = modelData();
    const { container } = render(<DVDPane code="DVD" symbol="AAPL" />);
    const header = container.querySelector(".ds-pane-header") as HTMLElement;
    expect(screen.queryByText(/No corporate actions/i)).toBeNull();
    // The header status pill must read "modeled", never "live" (both the
    // status pill and the LoadStatePill can carry the label).
    expect(within(header).queryByText("live")).toBeNull();
    expect(within(header).getAllByText("modeled").length).toBeGreaterThanOrEqual(1);
    expect(screen.getByTestId("dvd-model-notice")).toBeInTheDocument();
    // Both reference rows render in the grid with the model source pill.
    expect(screen.getAllByText("dividend").length).toBeGreaterThanOrEqual(2);
    expect(screen.getAllByText("model").length).toBeGreaterThanOrEqual(2);
  });

  it("keeps the provider-outage empty state", () => {
    mockFn.state = "ok";
    mockFn.data = outageData();
    const { container } = render(<DVDPane code="DVD" symbol="AAPL" />);
    const header = container.querySelector(".ds-pane-header") as HTMLElement;
    expect(within(header).queryByText("live")).toBeNull();
    expect(screen.getByText(/Provider unavailable/i)).toBeInTheDocument();
  });

  it("computes YoY against the dated ~1y-prior dividend, not the 5th row", () => {
    mockFn.state = "ok";
    mockFn.data = {
      status: "ok",
      data: {
        status: "ok",
        rows: [
          { symbol: "AAPL", action_type: "dividend", date: "2026-08-08", amount: 0.3, source_mode: "live_yfinance_dividends" },
          { symbol: "AAPL", action_type: "dividend", date: "2025-08-08", amount: 0.25, source_mode: "live_yfinance_dividends" },
        ],
      },
      sources: ["yfinance"],
      metadata: {},
      elapsed_ms: 5,
    };
    render(<DVDPane code="DVD" symbol="AAPL" />);
    // The YoY stat card + the row's Δ-vs-prev chip both show +20.00%.
    expect(screen.getAllByText("+20.00%").length).toBeGreaterThanOrEqual(2);
    expect(screen.getByText("LATEST VS 1Y PRIOR")).toBeInTheDocument();
    // The caption is date-sliced like the grid cells (caption + grid cell).
    expect(screen.getAllByText("2026-08-08").length).toBeGreaterThanOrEqual(1);
  });

  it("renders '—' for YoY when there is no genuine ~1y-prior comparison", () => {
    mockFn.state = "ok";
    mockFn.data = {
      status: "ok",
      data: {
        status: "ok",
        rows: [
          { symbol: "AAPL", action_type: "dividend", date: "2026-08-01", amount: 0.3, source_mode: "live_yfinance_dividends" },
          { symbol: "AAPL", action_type: "dividend", date: "2026-07-01", amount: 0.29, source_mode: "live_yfinance_dividends" },
          { symbol: "AAPL", action_type: "dividend", date: "2026-06-01", amount: 0.28, source_mode: "live_yfinance_dividends" },
          { symbol: "AAPL", action_type: "dividend", date: "2026-05-01", amount: 0.27, source_mode: "live_yfinance_dividends" },
          { symbol: "AAPL", action_type: "dividend", date: "2026-04-01", amount: 0.26, source_mode: "live_yfinance_dividends" },
        ],
      },
      sources: ["yfinance"],
      metadata: {},
      elapsed_ms: 5,
    };
    render(<DVDPane code="DVD" symbol="AAPL" />);
    const yoyCard = screen.getByText("YoY Δ").closest(".stat-card");
    expect(yoyCard?.textContent).toContain("—");
    expect(yoyCard?.textContent).not.toMatch(/\d+\.\d+%/);
  });
});
