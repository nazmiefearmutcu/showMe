/**
 * EVTS pane — load-state + honesty tests (GEX mock pattern).
 *
 * `useFunction` is mocked via a mutable shared object. Pins:
 *  - loading skeleton and error branches render;
 *  - an ok payload renders the events table with type chips (earnings /
 *    dividend / calendar) and summary cards;
 *  - the `provider_unavailable` payload renders the backend's honest reason
 *    instead of invented events;
 *  - the provider control persists under `showme.evts.provider` and
 *    activates on click.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { EVTSPane } from "./EVTS";

/* ── useFunction mock ──────────────────────────────────────────────── */

interface MockFnState {
  state: "idle" | "loading" | "ok" | "error" | "refreshing";
  data?: { data?: unknown } | undefined;
  error?: Error | null;
}

const mockFn: MockFnState = { state: "idle", data: undefined, error: null };

function setMockFn(next: Partial<MockFnState>) {
  mockFn.state = next.state ?? "idle";
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

/* ── fixtures (shape mirrors a live /api/fn/EVTS probe) ────────────── */

function okPayload() {
  return {
    status: "ok",
    symbol: "AAPL",
    event_count: 3,
    rows: [
      {
        symbol: "AAPL",
        event: "earnings",
        date: "2026-07-30T00:00:00",
        value: 1.2,
        source_section: "earnings",
        "Earnings Date": "2026-07-30",
      },
      {
        symbol: "AAPL",
        event: "dividend",
        date: "2026-05-12",
        value: 0.26,
        source_section: "dividends",
      },
      {
        symbol: "AAPL",
        event: "earnings date",
        date: "2026-04-29",
        value: "2026-04-29",
        source_section: "calendar",
      },
    ],
  };
}

beforeEach(() => {
  localStorage.clear();
  setMockFn({ state: "idle", data: undefined });
});
afterEach(() => {
  cleanup();
});

describe("EVTS pane — load states", () => {
  it("renders a skeleton while loading", () => {
    setMockFn({ state: "loading" });
    const { container } = render(<EVTSPane code="EVTS" symbol="AAPL" />);
    expect(container.querySelector('[aria-busy="true"]')).not.toBeNull();
  });

  it("renders the error state when the fetch errors", () => {
    setMockFn({ state: "error", error: new Error("sidecar exploded") });
    render(<EVTSPane code="EVTS" symbol="AAPL" />);
    expect(screen.getByText(/sidecar exploded/i)).toBeInTheDocument();
  });
});

describe("EVTS pane — events table", () => {
  it("renders dated rows with type chips and summary cards when ok", () => {
    setMockFn({ state: "ok", data: { data: okPayload() } });
    const { container } = render(<EVTSPane code="EVTS" symbol="AAPL" />);
    // Dates render ISO-truncated.
    expect(container.textContent).toContain("2026-07-30");
    expect(container.textContent).toContain("2026-05-12");
    // Type chips per source section ("earnings" appears as chip + event text).
    expect(screen.getAllByText("earnings").length).toBeGreaterThanOrEqual(2);
    expect(screen.getAllByText("dividends").length).toBeGreaterThanOrEqual(1);
    expect(screen.getAllByText("calendar").length).toBeGreaterThanOrEqual(1);
    // Summary cards.
    expect(container.textContent).toContain("YFINANCE");
  });

  it("renders the honest provider_unavailable state with the backend reason", () => {
    setMockFn({
      state: "ok",
      data: {
        data: {
          status: "provider_unavailable",
          rows: [],
          symbol: "AAPL",
          reason: "No dated corporate events were returned for this symbol.",
          next_actions: ["Retry with another equity symbol or a longer provider timeout."],
        },
      },
    });
    render(<EVTSPane code="EVTS" symbol="AAPL" />);
    expect(screen.getByText(/Events provider unavailable/i)).toBeInTheDocument();
    expect(
      screen.getByText(/No dated corporate events were returned for this symbol./i),
    ).toBeInTheDocument();
    // No fabricated event rows.
    expect(screen.queryByText(/2026-07-30/)).toBeNull();
  });
});

describe("EVTS pane — controls", () => {
  it("persists and activates the provider control", () => {
    setMockFn({ state: "ok", data: { data: okPayload() } });
    render(<EVTSPane code="EVTS" symbol="AAPL" />);
    const off = screen.getByRole("button", { name: "off" });
    expect(off).not.toBeDisabled();
    fireEvent.click(off);
    expect(off).toBeDisabled();
    expect(off.className).toContain("fn-segmented__opt--active");
    expect(localStorage.getItem("showme.evts.provider")).toBe("off");
  });
});

describe("EVTS pane — grid upgrade (L7)", () => {
  it("sorts the grid by date from the header", () => {
    setMockFn({ state: "ok", data: { data: okPayload() } });
    const { container } = render(<EVTSPane code="EVTS" symbol="AAPL" />);
    // Default sort is newest-first.
    expect(container.querySelector("tbody tr")?.textContent).toContain("2026-07-30");
    fireEvent.click(screen.getByRole("columnheader", { name: /Date/i }));
    // First click flips the default (descending → none), second lands ascending.
    fireEvent.click(screen.getByRole("columnheader", { name: /Date/i }));
    expect(container.querySelector("tbody tr")?.textContent).toContain("2026-04-29");
  });

  it("filters events by source-section chip", () => {
    setMockFn({ state: "ok", data: { data: okPayload() } });
    const { container } = render(<EVTSPane code="EVTS" symbol="AAPL" />);
    expect(container.querySelectorAll("tbody tr").length).toBe(3);
    fireEvent.click(screen.getByTitle("Filter event type dividends"));
    expect(container.querySelectorAll("tbody tr").length).toBe(1);
    expect(container.textContent).toContain("2026-05-12");
    expect(container.textContent).not.toContain("2026-07-30");
    fireEvent.click(screen.getByTitle("Filter event type ALL"));
    expect(container.querySelectorAll("tbody tr").length).toBe(3);
  });

  it("offers a CSV export button that honors the current filter", () => {
    setMockFn({ state: "ok", data: { data: okPayload() } });
    render(<EVTSPane code="EVTS" symbol="AAPL" />);
    const csv = screen.getByTitle("Download CSV");
    expect(csv).not.toBeDisabled();
    // jsdom has no Blob download path — the helper must degrade silently.
    fireEvent.click(csv);
    fireEvent.click(screen.getByTitle("Filter event type dividends"));
    expect(screen.getByLabelText(/Download 1 events as CSV/i)).not.toBeDisabled();
  });
});
