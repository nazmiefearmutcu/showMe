/**
 * EE pane — placeholder availability honesty (F6).
 *
 * When neither Finnhub nor yfinance answers the backend returns a
 * `provider_unavailable` placeholder row but keeps `data.status:"ok"` with
 * `metadata.fallback=True`. The pane used to compute `isLive = state==="ok"
 * && status==="ok"` and lit a green "live" pill over the placeholder. These
 * tests pin the folded availability contract across the 4 states.
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

import { EEPane } from "./EE";

function liveData() {
  return {
    status: "ok",
    data: {
      status: "ok",
      rows: [
        {
          symbol: "AAPL",
          period: "2026-Q2",
          actual: 1.5,
          estimate: 1.4,
          surprisePercent: 7.1,
          source_mode: "finnhub_earnings",
        },
      ],
    },
    sources: ["finnhub"],
    metadata: { live: true, data_mode: "live_official" },
    elapsed_ms: 8,
  };
}

function placeholderData() {
  return {
    // Shared envelope status derived from metadata.fallback=True.
    status: "provider_unavailable",
    data: {
      status: "ok",
      rows: [
        {
          symbol: "AAPL",
          period: "provider_unavailable",
          actual: null,
          estimate: null,
          surprisePercent: null,
          source_mode: "earnings_calendar_unavailable",
        },
      ],
    },
    sources: ["earnings_calendar_model"],
    metadata: { live: false, fallback: true, data_mode: "modeled" },
    elapsed_ms: 6,
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

describe("EE pane — availability honesty", () => {
  it("renders a skeleton while loading", () => {
    mockFn.state = "loading";
    const { container } = render(<EEPane code="EE" symbol="AAPL" />);
    expect(container.querySelector('[aria-busy="true"]')).not.toBeNull();
  });

  it("renders the error state with a retry", () => {
    mockFn.state = "error";
    mockFn.error = new Error("sidecar exploded");
    render(<EEPane code="EE" symbol="AAPL" />);
    expect(screen.getByText(/sidecar exploded/i)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /retry/i })).toBeInTheDocument();
  });

  it("shows the live pill for a genuine ok payload", () => {
    mockFn.state = "ok";
    mockFn.data = liveData();
    render(<EEPane code="EE" symbol="AAPL" />);
    expect(screen.getByText("live")).toBeInTheDocument();
    // The period appears both as the KPI caption and in the grid.
    expect(screen.getAllByText("2026-Q2").length).toBeGreaterThanOrEqual(1);
  });

  it("shows 'unavailable' (never 'live') over the provider placeholder", () => {
    mockFn.state = "ok";
    mockFn.data = placeholderData();
    render(<EEPane code="EE" symbol="AAPL" />);
    expect(screen.queryByText("live")).toBeNull();
    expect(screen.getByText("unavailable")).toBeInTheDocument();
    expect(screen.getByText(/Provider unavailable/i)).toBeInTheDocument();
  });

  it("does not count the placeholder as an earnings quarter", () => {
    mockFn.state = "ok";
    mockFn.data = placeholderData();
    const { container } = render(<EEPane code="EE" symbol="AAPL" />);
    // The header pill and subtitle report 0 real quarters, not 1.
    expect(container.textContent).toContain("0 quarters");
    expect(container.textContent).toContain("0 q");
  });
});
