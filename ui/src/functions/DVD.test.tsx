/**
 * DVD pane — awareness contract tests.
 *
 * Pins: no fabricated template rows; provider_unavailable renders the backend
 * reason; an empty payload says "No dividends returned"; declared (upcoming)
 * and historical rows render in their own sections; summary values render.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, render, screen } from "@testing-library/react";
import { DVDPane } from "./DVD";

interface MockFnState {
  state: "idle" | "loading" | "ok" | "error" | "refreshing";
  data?: Record<string, unknown> | undefined;
  error?: Error | null;
}

const mockFn: MockFnState = { state: "idle", data: undefined, error: null };
const calls: unknown[] = [];

vi.mock("@/lib/useFunction", () => ({
  useFunction: (args: unknown) => {
    calls.push(args);
    return {
      state: mockFn.state,
      data: mockFn.data,
      error: mockFn.error,
      refetch: vi.fn(),
    };
  },
}));

function setMockFn(next: MockFnState) {
  mockFn.state = next.state;
  mockFn.data = next.data;
  mockFn.error = next.error ?? null;
}

beforeEach(() => {
  calls.length = 0;
  setMockFn({ state: "idle" });
});
afterEach(() => cleanup());

describe("DVDPane", () => {
  it("sends only the history parameter (no live/model toggle)", () => {
    setMockFn({ state: "loading" });
    render(<DVDPane code="DVD" symbol="AAPL" />);
    const args = calls[0] as { params: Record<string, unknown> };
    expect(args.params).toEqual({ history: true });
  });

  it("renders the backend reason when awareness is unavailable and no rows", () => {
    setMockFn({
      state: "ok",
      data: {
        data: {
          status: "provider_unavailable",
          reason: "awareness down",
          upcoming: [],
          history: [],
        },
      },
    });
    render(<DVDPane code="DVD" symbol="AAPL" />);
    expect(screen.getByRole("alert").textContent).toContain("awareness down");
    expect(screen.queryByLabelText("Dividend history")).toBeNull();
  });

  it("says no dividends were returned rather than inventing a schedule", () => {
    setMockFn({
      state: "ok",
      data: { data: { status: "empty", upcoming: [], history: [] } },
    });
    render(<DVDPane code="DVD" symbol="AAPL" />);
    expect(screen.getByText("No dividends returned")).toBeTruthy();
    expect(screen.queryByText(/0\.24|0\.23/)).toBeNull();
  });

  it("renders upcoming and historical sections with the summary", () => {
    setMockFn({
      state: "ok",
      data: {
        data: {
          status: "ok",
          upcoming: [
            { ex_date: "2026-12-05", amount: 0.26, sources: [{ provider: "awareness" }] },
          ],
          history: [
            { ex_date: "2026-08-08", amount: 0.25, source: "yfinance" },
            { ex_date: "2026-05-09", amount: 0.24, source: "yfinance" },
          ],
          summary: {
            annual_amount: 1.04,
            last_amount: 0.25,
            last_ex_date: "2026-08-08",
            frequency_guess: "quarterly",
          },
        },
      },
    });
    render(<DVDPane code="DVD" symbol="AAPL" />);
    expect(screen.getByLabelText("Upcoming dividends")).toBeTruthy();
    expect(screen.getByLabelText("Dividend history")).toBeTruthy();
    expect(screen.getByText("quarterly")).toBeTruthy();
    expect(screen.getAllByText("$1.04").length).toBeGreaterThan(0);
  });
});
