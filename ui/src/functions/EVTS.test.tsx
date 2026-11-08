/**
 * EVTS pane — awareness contract tests.
 *
 * Pins: provider_unavailable shows AwarenessUnavailable with the backend reason
 * and no rows; empty windows say so; upcoming events precede recent events;
 * the type filter narrows rows; no provider/reference toggle is rendered.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { EVTSPane } from "./EVTS";

interface MockFnState {
  state: "idle" | "loading" | "ok" | "error" | "refreshing";
  data?: Record<string, unknown> | undefined;
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

function setMockFn(next: MockFnState) {
  mockFn.state = next.state;
  mockFn.data = next.data;
  mockFn.error = next.error ?? null;
}

const future = (days: number) =>
  new Date(Date.now() + days * 86_400_000).toISOString().slice(0, 10);
const past = (days: number) =>
  new Date(Date.now() - days * 86_400_000).toISOString().slice(0, 10);

beforeEach(() => setMockFn({ state: "idle" }));
afterEach(() => cleanup());

describe("EVTSPane", () => {
  it("renders AwarenessUnavailable with the reason and no event rows", () => {
    setMockFn({
      state: "ok",
      data: {
        data: { status: "provider_unavailable", reason: "awareness timeout", rows: [] },
        sources: ["no_live_source"],
      },
    });
    render(<EVTSPane code="EVTS" symbol="NVDA" />);
    const alert = screen.getByRole("alert");
    expect(alert.textContent).toContain("awareness timeout");
    expect(screen.queryByRole("table")).toBeNull();
  });

  it("says so when the window holds no events and invents none", () => {
    setMockFn({ state: "ok", data: { data: { status: "empty", rows: [] } } });
    render(<EVTSPane code="EVTS" symbol="NVDA" />);
    expect(screen.getByText("No corporate events in this window")).toBeTruthy();
  });

  it("lists upcoming events before recent events, each sorted", () => {
    setMockFn({
      state: "ok",
      data: {
        data: {
          status: "ok",
          rows: [
            {
              date: past(40),
              type: "earnings",
              event: "Q2 earnings",
              status: "reported",
              sources: [{ provider: "awareness" }],
            },
            {
              date: future(60),
              type: "dividend",
              event: "Ex-dividend",
              status: "scheduled",
              sources: [],
            },
            {
              date: future(10),
              type: "earnings",
              event: "Q3 earnings",
              status: "scheduled",
              sources: [],
            },
          ],
        },
      },
    });
    render(<EVTSPane code="EVTS" symbol="NVDA" />);
    const text = document.body.textContent ?? "";
    expect(text.indexOf("Q3 earnings")).toBeGreaterThanOrEqual(0);
    expect(text.indexOf("Q3 earnings")).toBeLessThan(text.indexOf("Ex-dividend"));
    expect(text.indexOf("Ex-dividend")).toBeLessThan(text.indexOf("Q2 earnings"));
  });

  it("narrows rows with the type filter", () => {
    setMockFn({
      state: "ok",
      data: {
        data: {
          status: "ok",
          rows: [
            {
              date: future(5),
              type: "earnings",
              event: "Q3 earnings",
              status: "scheduled",
            },
            {
              date: future(9),
              type: "split",
              event: "10-for-1 split",
              status: "scheduled",
            },
          ],
        },
      },
    });
    render(<EVTSPane code="EVTS" symbol="NVDA" />);
    expect(screen.getByText("10-for-1 split")).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "earnings" }));
    expect(screen.queryByText("10-for-1 split")).toBeNull();
    expect(screen.getByText("Q3 earnings")).toBeTruthy();
  });

  it("does not render a provider or reference toggle", () => {
    setMockFn({ state: "ok", data: { data: { status: "ok", rows: [] } } });
    render(<EVTSPane code="EVTS" symbol="NVDA" />);
    expect(screen.queryByText("yfinance")).toBeNull();
    expect(screen.queryByText(/reference/i)).toBeNull();
  });
});
