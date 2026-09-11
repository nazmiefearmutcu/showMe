/**
 * TRDH pane — render-contract + defect-workaround tests.
 *
 * Backend defect: the DEFAULT TRDH board (no `exchanges` param) returns only
 * BINANCE, so the pane always sends an explicit exchange list via a
 * multi-select chip row persisted under `showme.trdh.exchanges`. These
 * tests pin:
 *
 *  - the load states (loading / error / empty / ok);
 *  - an OK payload renders the per-exchange session table with open/closed
 *    tone and the correct countdown leg (closes-in for open venues,
 *    opens-in for closed ones, "continuous" for 24h venues);
 *  - rows sort open-first;
 *  - the chip interaction toggles selection, updates aria-pressed, and
 *    persists the selection.
 *
 * `useFunction` is mocked via a mutable shared state so each test drives
 * the pane into a specific branch without the real sidecar transport.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { TRDHPane } from "./TRDH";

/* ── useFunction mock ──────────────────────────────────────────────── */

interface MockFnState {
  state: "idle" | "loading" | "ok" | "error" | "refreshing";
  data?: {
    data?: unknown;
    metadata?: Record<string, unknown>;
    sources?: string[];
  };
  error?: Error | null;
}

const mockFn: MockFnState = { state: "idle", data: undefined, error: null };
const recordedCalls: Array<{ params?: Record<string, unknown> }> = [];

function setMockFn(next: MockFnState) {
  mockFn.state = next.state;
  mockFn.data = next.data;
  mockFn.error = next.error ?? null;
}

vi.mock("@/lib/useFunction", () => ({
  useFunction: (opts: { params?: Record<string, unknown> }) => {
    recordedCalls.push(opts);
    return {
      state: mockFn.state,
      data: mockFn.data,
      error: mockFn.error,
      refetch: vi.fn(),
    };
  },
}));

/* ── fixtures ──────────────────────────────────────────────────────── */

function boardPayload() {
  return {
    state: "ok" as const,
    data: {
      data: {
        rows: [
          {
            exchange: "NYSE",
            name: "New York Stock Exchange",
            country: "US",
            open_local: "09:30",
            close_local: "16:00",
            timezone: "America/New_York",
            is_open_now: true,
            next_open_utc: "2026-09-08T13:30:00+00:00",
            next_close_utc: "2026-09-07T20:00:00+00:00",
            seconds_until_open: 69743,
            seconds_until_close: 6743,
            hours_until_open: 19.373,
            hours_until_close: 1.873,
            value: 1.873,
          },
          {
            exchange: "BINANCE",
            name: "Binance",
            country: "GLOBAL",
            open_local: "00:00",
            close_local: "23:59",
            timezone: "UTC",
            is_open_now: true,
            next_open_utc: null,
            next_close_utc: null,
            seconds_until_open: 0,
            seconds_until_close: null,
            hours_until_open: 0.0,
            hours_until_close: null,
            value: 0.0,
          },
          {
            exchange: "LSE",
            name: "London Stock Exchange",
            country: "GB",
            open_local: "08:00",
            close_local: "16:30",
            timezone: "Europe/London",
            is_open_now: false,
            next_open_utc: "2026-09-08T07:00:00+00:00",
            next_close_utc: "2026-09-08T15:30:00+00:00",
            seconds_until_open: 46343,
            seconds_until_close: 76943,
            hours_until_open: 12.873,
            hours_until_close: 21.373,
            value: 12.873,
          },
        ],
        surface: [],
        cards: [
          { label: "Open now", value: 2 },
          { label: "Exchanges", value: 3 },
        ],
        source_mode: "exchange_calendar_registry",
      },
      metadata: { now_utc: "2026-09-07T18:07:36.090584+00:00" },
      sources: ["exchange_calendars"],
    },
  };
}

/* ── tests ─────────────────────────────────────────────────────────── */

beforeEach(() => {
  localStorage.removeItem("showme.trdh.exchanges");
  recordedCalls.length = 0;
  setMockFn({ state: "idle", data: undefined });
});
afterEach(() => {
  cleanup();
});

describe("TRDH pane — poll pattern (countdown refresh)", () => {
  it("polls via visibility tick without putting tick into the fetch params", () => {
    setMockFn(boardPayload());
    render(<TRDHPane code="TRDH" />);
    expect(recordedCalls.length).toBeGreaterThan(0);
    for (const call of recordedCalls) {
      // The tick is the refetch trigger, never a param — a tick-keyed fetch
      // would wipe to the skeleton every poll.
      expect(call.params ?? {}).not.toHaveProperty("tick");
      expect(call.params).toEqual({ exchanges: expect.any(String) });
    }
  });
});

describe("TRDH pane — load states", () => {
  it("renders a skeleton while loading", () => {
    setMockFn({ state: "loading", data: undefined });
    const { container } = render(<TRDHPane code="TRDH" />);
    expect(container.querySelector("[aria-busy='true']")).not.toBeNull();
  });

  it("renders the error state when the fetch errors", () => {
    setMockFn({ state: "error", data: undefined, error: new Error("sidecar exploded") });
    render(<TRDHPane code="TRDH" />);
    expect(screen.getByText(/sidecar exploded/i)).toBeInTheDocument();
  });

  it("renders an empty prompt when the payload has no rows", () => {
    setMockFn({ state: "ok", data: { data: { rows: [] } } });
    render(<TRDHPane code="TRDH" />);
    expect(screen.getByText(/No sessions returned/i)).toBeInTheDocument();
  });

  it("renders the board summary + session rows when ok", () => {
    setMockFn(boardPayload());
    const { container } = render(<TRDHPane code="TRDH" />);
    expect(screen.getByText(/Open now/i)).toBeInTheDocument();
    expect(screen.getByText("New York Stock Exchange · US")).toBeInTheDocument();
    expect(screen.getByText("London Stock Exchange · GB")).toBeInTheDocument();
    expect(container.querySelectorAll("table tbody tr").length).toBe(3);
  });
});

describe("TRDH pane — countdown honesty", () => {
  it("renders closes-in for open venues with a next close", () => {
    setMockFn(boardPayload());
    render(<TRDHPane code="TRDH" />);
    expect(screen.getByText(/closes in 1h 52m/i)).toBeInTheDocument();
  });

  it("renders opens-in for closed venues", () => {
    setMockFn(boardPayload());
    render(<TRDHPane code="TRDH" />);
    expect(screen.getByText(/opens in 12h 52m/i)).toBeInTheDocument();
  });

  it("renders continuous for a 24h venue with no next close", () => {
    setMockFn(boardPayload());
    render(<TRDHPane code="TRDH" />);
    expect(screen.getByText(/continuous \(24h\)/i)).toBeInTheDocument();
  });

  it("sorts open venues before closed ones", () => {
    setMockFn(boardPayload());
    const { container } = render(<TRDHPane code="TRDH" />);
    const firstRow = container.querySelector("table tbody tr");
    expect(firstRow?.textContent).toContain("BINANCE");
    const lastRow = Array.from(container.querySelectorAll("table tbody tr")).at(-1);
    expect(lastRow?.textContent).toContain("LSE");
  });
});

describe("TRDH pane — exchange chip interaction", () => {
  it("toggles a venue chip, updates aria-pressed, and persists the selection", () => {
    setMockFn(boardPayload());
    render(<TRDHPane code="TRDH" />);
    const tyoChip = screen.getByRole("button", { name: "TYO" });
    expect(tyoChip.getAttribute("aria-pressed")).toBe("true");
    fireEvent.click(tyoChip);
    expect(tyoChip.getAttribute("aria-pressed")).toBe("false");
    expect(localStorage.getItem("showme.trdh.exchanges")).not.toContain("TYO");
    // Re-adding restores the full default board.
    fireEvent.click(tyoChip);
    expect(tyoChip.getAttribute("aria-pressed")).toBe("true");
    expect(localStorage.getItem("showme.trdh.exchanges")).toContain("TYO");
  });
});
