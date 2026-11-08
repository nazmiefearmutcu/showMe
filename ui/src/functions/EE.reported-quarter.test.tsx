/**
 * EE pane — reported vs upcoming quarter (EE#1).
 *
 * The provider's upcoming quarter (actual null) must not be read as the last
 * reported quarter. Kept in its own file so the pre-existing EE.test.tsx stays
 * untouched.
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

beforeEach(() => {
  mockFn.state = "idle";
  mockFn.data = undefined;
  mockFn.error = null;
});

afterEach(() => {
  cleanup();
});

describe("EE pane — reported vs upcoming quarter (EE#1)", () => {
  function upcomingFirstData() {
    return {
      status: "ok",
      data: {
        status: "ok",
        rows: [
          {
            symbol: "AAPL",
            period: "2099-01-28",
            date: "2099-01-28",
            actual: null,
            estimate: 2.92,
            surprisePercent: null,
            source_mode: "finnhub_earnings",
          },
          {
            symbol: "AAPL",
            period: "2026-09-30",
            date: "2026-09-30",
            actual: 2.1,
            estimate: 1.99,
            surprisePercent: 5.53,
            source_mode: "finnhub_earnings",
          },
        ],
        next_report: { date: "2099-01-28", estimate: 2.92, status: "scheduled" },
      },
      sources: ["finnhub"],
      metadata: { live: true, data_mode: "live_official" },
      elapsed_ms: 8,
    };
  }

  it("takes last actual and estimate from the newest reported quarter", () => {
    mockFn.state = "ok";
    mockFn.data = upcomingFirstData();
    render(<EEPane code="EE" symbol="AAPL" />);
    // "$2.10" appears in the KPI ribbon and the grid; both must be the reported row.
    expect(screen.getAllByText("$2.10").length).toBeGreaterThanOrEqual(1);
    // The KPI cards themselves must read the reported quarter, not the upcoming one.
    const lastActual = screen.getByText("Last actual").closest(".stat-card");
    const lastEstimate = screen.getByText("Last estimate").closest(".stat-card");
    expect(lastActual?.textContent).toContain("$2.10");
    expect(lastEstimate?.textContent).toContain("$1.99");
    expect(lastEstimate?.textContent).not.toContain("$2.92");
  });

  it("shows the next scheduled report date in the footer", () => {
    mockFn.state = "ok";
    mockFn.data = upcomingFirstData();
    const { container } = render(<EEPane code="EE" symbol="AAPL" />);
    expect(container.textContent).toContain("next report");
    expect(container.textContent).toContain("2099-01-28");
  });
});
