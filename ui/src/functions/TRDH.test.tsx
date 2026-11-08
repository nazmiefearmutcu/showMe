/**
 * TRDH pane — awareness contract tests.
 *
 * Pins: the board sends an explicit MIC list (XNYS, XLON, ...); open venues sort
 * first; countdowns come from next_open_utc / next_close_utc ("continuous" for
 * an open venue with no next close); the chip row toggles and persists MIC
 * codes; provider_unavailable renders AwarenessUnavailable with the reason.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { TRDHPane } from "./TRDH";

interface MockFnState {
  state: "idle" | "loading" | "ok" | "error" | "refreshing";
  data?: { data?: unknown; metadata?: Record<string, unknown>; sources?: string[] };
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

const MIN = 60_000;
const at = (ms: number) => new Date(Date.now() + ms).toISOString();

function venue(overrides: Record<string, unknown>) {
  return {
    mic: "XNYS",
    name: "New York Stock Exchange",
    timezone: "America/New_York",
    today: { open_local: "09:30", close_local: "16:00", early_close: false },
    is_open_now: false,
    next_open_utc: at(12 * 60 * MIN),
    next_close_utc: null,
    sessions: [],
    closures: [],
    ...overrides,
  };
}

const OPEN_VENUE = venue({
  mic: "XNYS",
  is_open_now: true,
  next_close_utc: at(112 * MIN),
  next_open_utc: null,
});
const CLOSED_VENUE = venue({
  mic: "XLON",
  name: "London Stock Exchange",
  timezone: "Europe/London",
  is_open_now: false,
  next_open_utc: at(12 * 60 * MIN + 52 * MIN),
});
const CONTINUOUS_VENUE = venue({
  mic: "XHKG",
  name: "HKEX",
  is_open_now: true,
  next_close_utc: null,
  next_open_utc: null,
});

beforeEach(() => {
  recordedCalls.length = 0;
  setMockFn({ state: "idle" });
  window.localStorage.clear();
});
afterEach(() => cleanup());

describe("TRDH load states", () => {
  it("sends the default MIC list as the exchanges parameter", () => {
    setMockFn({ state: "loading" });
    render(<TRDHPane code="TRDH" />);
    const last = recordedCalls[recordedCalls.length - 1];
    expect(String(last.params?.exchanges)).toBe(
      "XNYS,XNAS,XLON,XETR,XPAR,XTKS,XHKG,XASX,XIST,XSHG",
    );
  });

  it("renders AwarenessUnavailable with the reason and no board", () => {
    setMockFn({
      state: "ok",
      data: {
        data: { status: "provider_unavailable", reason: "calendar down", exchanges: [] },
      },
    });
    render(<TRDHPane code="TRDH" />);
    expect(screen.getByRole("alert").textContent).toContain("calendar down");
    expect(screen.queryByRole("button", { name: /open|closed/i })).toBeNull();
  });

  it("says no sessions were returned for an empty ok payload", () => {
    setMockFn({ state: "ok", data: { data: { status: "empty", exchanges: [] } } });
    render(<TRDHPane code="TRDH" />);
    expect(screen.getByText("No sessions returned")).toBeTruthy();
  });
});

describe("TRDH countdowns and ordering", () => {
  it("shows closes-in for an open venue and opens-in for a closed one", () => {
    setMockFn({
      state: "ok",
      data: { data: { status: "ok", exchanges: [CLOSED_VENUE, OPEN_VENUE] } },
    });
    render(<TRDHPane code="TRDH" />);
    expect(screen.getByText(/closes in 1h 52m/)).toBeTruthy();
    expect(screen.getByText(/opens in 12h 52m/)).toBeTruthy();
  });

  it("marks an open venue with no next close as continuous", () => {
    setMockFn({
      state: "ok",
      data: { data: { status: "ok", exchanges: [CONTINUOUS_VENUE] } },
    });
    render(<TRDHPane code="TRDH" />);
    expect(screen.getByText("continuous (24h)")).toBeTruthy();
  });

  it("sorts open venues before closed ones", () => {
    setMockFn({
      state: "ok",
      data: { data: { status: "ok", exchanges: [CLOSED_VENUE, OPEN_VENUE] } },
    });
    render(<TRDHPane code="TRDH" />);
    const text = document.body.textContent ?? "";
    expect(text.indexOf("XNYS")).toBeGreaterThanOrEqual(0);
    expect(text.indexOf("XNYS")).toBeLessThan(text.indexOf("XLON"));
  });

  it("shows the local session and an early-close flag from today", () => {
    const early = venue({
      mic: "XNAS",
      is_open_now: true,
      next_close_utc: at(60 * MIN),
      today: { open_local: "09:30", close_local: "13:00", early_close: true },
    });
    setMockFn({ state: "ok", data: { data: { status: "ok", exchanges: [early] } } });
    render(<TRDHPane code="TRDH" />);
    expect(screen.getByText(/09:30–13:00 · early close/)).toBeTruthy();
  });
});

describe("TRDH exchange chips", () => {
  it("toggles a MIC chip off, updates the parameter and persists the selection", () => {
    setMockFn({ state: "ok", data: { data: { status: "ok", exchanges: [OPEN_VENUE] } } });
    render(<TRDHPane code="TRDH" />);
    const tse = screen.getByRole("button", { name: "TSE" });
    expect(tse.getAttribute("aria-pressed")).toBe("true");
    fireEvent.click(tse);
    expect(screen.getByRole("button", { name: "TSE" }).getAttribute("aria-pressed")).toBe(
      "false",
    );
    const last = recordedCalls[recordedCalls.length - 1];
    expect(String(last.params?.exchanges)).not.toContain("XTKS");
    expect(window.localStorage.getItem("showme.trdh.exchanges")).not.toContain("XTKS");
  });
});

describe("TRDH lunch-break countdown (F2 I1, backend break-aware boundaries)", () => {
  it("counts an XHKG venue on its lunch break down to the break end, not the next day's open", () => {
    // Backend contract: during a break next_open_utc is the break end (12:00-13:00 HKT in the live feed).
    const lunch = venue({
      mic: "XHKG",
      name: "Hong Kong Stock Exchange",
      timezone: "Asia/Hong_Kong",
      is_open_now: false,
      next_open_utc: at(40 * MIN),
      next_close_utc: at(4 * 60 * MIN),
    });
    setMockFn({ state: "ok", data: { data: { status: "ok", exchanges: [lunch] } } });
    render(<TRDHPane code="TRDH" />);
    expect(screen.getByText(/opens in 40m/)).toBeTruthy();
    expect(screen.queryByText(/opens in 1[0-9]h|opens in [2-9][0-9]h/)).toBeNull();
  });

  it("shows the next close as the lunch-break start before the break", () => {
    const morning = venue({
      mic: "XHKG",
      name: "Hong Kong Stock Exchange",
      timezone: "Asia/Hong_Kong",
      is_open_now: true,
      next_close_utc: at(50 * MIN),
      next_open_utc: null,
    });
    setMockFn({ state: "ok", data: { data: { status: "ok", exchanges: [morning] } } });
    render(<TRDHPane code="TRDH" />);
    expect(screen.getByText(/closes in 50m/)).toBeTruthy();
  });
});
